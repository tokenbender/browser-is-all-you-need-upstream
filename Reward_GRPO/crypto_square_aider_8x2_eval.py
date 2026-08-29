#!/usr/bin/env python3


from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


IMAGE = (
    "us-central1-docker.pkg.dev/lifeandhalf-24122025/w8-biayn/"
    "glm47-full-v5-unadmitted-grpo"
    "@sha256:5df1c41efb6062a292ac68a49d68ad955d9f8209c182d3fc2f7e8c634ca076a2"
)
MODEL_REVISION = "7dd20894a642a0aa287e9827cb1a1f7f91386b67"
AIDER_COMMIT = "5dc9490bb35f9729ef2c95d00a19ccd30c26339c"
POLYGLOT_COMMIT = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
SOURCE_RUN_ID = os.environ.get(
    "EVAL_SOURCE_RUN_ID",
    "crypto-square-midbreak-grpo20-retry1-20260821T100345Z",
)
SOURCE_CHECKPOINT = os.environ.get("EVAL_SOURCE_CHECKPOINT", "iter_0000019")
ADAPTER_SHA256 = os.environ.get(
    "EVAL_EXPECTED_ADAPTER_SHA256",
    "d190c8bab4928177aa38bde524286b3446ec2d3a110d526cd3461d31d1750073",
)
ADAPTER_CONFIG_SHA256 = os.environ.get(
    "EVAL_EXPECTED_ADAPTER_CONFIG_SHA256",
    "0bd6d85f88fc42fefa52627b3c261f1ad58bb2c9519332ae8034dd5dffe2498e",
)
TRAINING_DATA_MANIFEST_SHA256 = os.environ.get(
    "EVAL_EXPECTED_TRAINING_MANIFEST_SHA256",
    "40304fca1144dbe9ae5588af96a170a181fb6c1088662dcd58564344f073a990",
)
OFFICIAL_TASK_TREE_SHA256 = "0886d9d65844cf61ded7ec3a80775e53a9737eac9bedb0619002f4b2fe4ab7de"
EXPECTED_SOURCE_TENSORS = 9_741
EXPECTED_LAYER_47_TENSORS = 207
EXPECTED_SERVING_TENSORS = 9_534

TRIALS = 8
TRIES = 2
THREADS = 8
TEMPERATURE = 0.7
TOP_P = 1.0
MAX_TOKENS = 32_768
CONTEXT_WINDOW = 65_536
THINKING_ENABLED = True
LORA_NAME = "crypto-square-eval"
SERVED_MODEL_NAME = "glm-4.7-flash-crypto-square"
API_KEY = "local-eval"

HOME = Path.home()
ASSETS = HOME / "eval-assets"
MODEL_HOST_PATH = ASSETS / "model" / "GLM-4.7-Flash"
ADAPTER_HOST_DIR = ASSETS / "adapter"
TRAINING_MANIFEST = ASSETS / "training" / "manifest.json"
AIDER_DIR = Path("/aider")
BUNDLE_DIR = Path(__file__).resolve().parent
RUN_ID = os.environ.get(
    "EVAL_RUN_ID",
    "crypto-square-final-aider-8x2-"
    + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
)
WORKSPACE = Path(os.environ.get("EVAL_WORKSPACE", str(HOME / "crypto-square-eval")))
RUN_DIR = WORKSPACE / RUN_ID
DURABLE_ROOT = os.environ.get(
    "EVAL_DURABLE_ROOT",
    "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/evaluations/"
    "crypto-square-aider-8x2",
)
DOCKER: list[str] = []
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


def log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat()}] {message}", flush=True)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def task_tree_sha256(exercise: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in exercise.rglob("*") if item.is_file()):
        relative = path.relative_to(exercise.parent).as_posix().encode()
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def relative_file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_path(path)
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    log(f"$ {' '.join(str(value) for value in command)[:500]}")
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    result = subprocess.run(command, **kwargs)
    if result.returncode != 0:
        stdout = (result.stdout or "")[-6000:]
        stderr = (result.stderr or "")[-6000:]
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)[:300]}\n"
            f"stdout tail:\n{stdout}\nstderr tail:\n{stderr}"
        )
    return result


def resolve_docker() -> list[str]:
    for candidate in (["docker"], ["sudo", "-n", "docker"]):
        probe = subprocess.run(
            [*candidate, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return list(candidate)
    raise RuntimeError("no working Docker invocation found")


def http_post(port: int, path: str, payload: dict[str, object]) -> tuple[int, str]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def wait_for_server(container: str, port: int, timeout: int = 2400) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = subprocess.run(
            [*DOCKER, "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", container],
            capture_output=True,
            text=True,
        )
        if state.returncode == 0 and state.stdout.split()[0] != "running":
            tail = subprocess.run(
                [*DOCKER, "logs", "--tail", "200", container],
                capture_output=True,
                text=True,
            )
            raise RuntimeError(f"SGLang exited during startup:\n{tail.stdout[-12000:]}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(10)
    raise TimeoutError(f"SGLang did not become healthy within {timeout} seconds")


def load_adapter(port: int, serving_path: str) -> dict[str, object]:
    payload = {"lora_name": LORA_NAME, "lora_path": serving_path}
    for endpoint in ("/load_lora_adapter", "/v1/load_lora_adapter"):
        status, body = http_post(port, endpoint, payload)
        if status == 200:
            return {"endpoint": endpoint, "status": status, "body": body[:2000]}
        if status != 404:
            raise RuntimeError(f"adapter load failed: {status} {body[:2000]}")
    raise RuntimeError("SGLang exposes no LoRA loading endpoint")


def probe_completion(port: int, with_lora: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": SERVED_MODEL_NAME,
        "messages": [{"role": "user", "content": "Return only the integer 42."}],
        "temperature": 0.0,
        "max_tokens": 64,
        "logprobs": True,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    if with_lora:
        payload["lora_path"] = LORA_NAME
    status, body = http_post(port, "/v1/chat/completions", payload)
    if status != 200:
        raise RuntimeError(f"activation probe failed: {status} {body[:2000]}")
    choice = json.loads(body)["choices"][0]
    logprobs = [
        round(item["logprob"], 6)
        for item in (choice.get("logprobs") or {}).get("content") or []
    ]
    return {"content": choice["message"]["content"], "logprobs": logprobs}


def verify_lora_activation(port: int) -> dict[str, object]:
    with_lora = probe_completion(port, True)
    without_lora = probe_completion(port, False)
    if with_lora == without_lora:
        raise RuntimeError("LoRA activation probe did not diverge from the base model")
    return {"status": "diverged", "with_lora": with_lora, "without_lora": without_lora}


def preflight_host() -> None:
    gpu_result = run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]
    )
    gpus = [line.strip() for line in gpu_result.stdout.splitlines() if line.strip()]
    if len(gpus) != 8 or any("H100" not in gpu for gpu in gpus):
        raise RuntimeError(f"expected 8 H100 GPUs, got {gpus}")
    if not (MODEL_HOST_PATH / "config.json").is_file():
        raise RuntimeError(f"model mount missing: {MODEL_HOST_PATH}")
    revision = MODEL_HOST_PATH / "MODEL_REVISION"
    if revision.is_file() and revision.read_text().strip() != MODEL_REVISION:
        raise RuntimeError("model revision does not match the pinned evaluation contract")


def verify_source_adapter() -> None:
    expected = {
        ADAPTER_HOST_DIR / "adapter_model.bin": ADAPTER_SHA256,
        ADAPTER_HOST_DIR / "adapter_config.json": ADAPTER_CONFIG_SHA256,
        TRAINING_MANIFEST: TRAINING_DATA_MANIFEST_SHA256,
    }
    for path, digest in expected.items():
        if not path.is_file() or sha256_path(path) != digest:
            raise RuntimeError(f"source artifact identity mismatch: {path}")
    config = json.loads((ADAPTER_HOST_DIR / "adapter_config.json").read_text())
    if int(config["r"]) != 16 or int(config["lora_alpha"]) != 32:
        raise RuntimeError("adapter rank/alpha mismatch")


def build_serving_adapter() -> dict[str, object]:
    source = RUN_DIR / "adapter-source"
    serving = RUN_DIR / "adapter-serving"
    shutil.copytree(ADAPTER_HOST_DIR, source)
    conversion = (
        "import json, os, shutil, torch\n"
        "src='/workspace-run/adapter-source'; dst='/workspace-run/adapter-serving'\n"
        "state=torch.load(src+'/adapter_model.bin',map_location='cpu',weights_only=True,mmap=True)\n"
        "removed=[k for k in state if '.layers.47.' in k]\n"
        "kept={k:v for k,v in state.items() if '.layers.47.' not in k}\n"
        "os.mkdir(dst); torch.save(kept,dst+'/adapter_model.bin')\n"
        "shutil.copy2(src+'/adapter_config.json',dst+'/adapter_config.json')\n"
        "print(json.dumps({'source':len(state),'removed':len(removed),'serving':len(kept)}))\n"
    )
    result = run(
        [
            *DOCKER,
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "HOME=/tmp",
            "-v",
            f"{RUN_DIR}:/workspace-run",
            IMAGE,
            "python3",
            "-c",
            conversion,
        ]
    )
    counts = json.loads(result.stdout.strip().splitlines()[-1])
    expected = {
        "source": EXPECTED_SOURCE_TENSORS,
        "removed": EXPECTED_LAYER_47_TENSORS,
        "serving": EXPECTED_SERVING_TENSORS,
    }
    if counts != expected:
        raise RuntimeError(f"unexpected serving conversion tensor counts: {counts}")
    receipt = {
        **counts,
        "source_adapter_sha256": ADAPTER_SHA256,
        "serving_adapter_sha256": sha256_path(serving / "adapter_model.bin"),
        "serving_adapter_config_sha256": sha256_path(serving / "adapter_config.json"),
    }
    (serving / "conversion_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return receipt


def stage_aider() -> None:
    aider_head = run(["git", "-C", str(AIDER_DIR), "rev-parse", "HEAD"]).stdout.strip()
    polyglot = AIDER_DIR / "tmp.benchmarks/polyglot-benchmark"
    polyglot_head = run(["git", "-C", str(polyglot), "rev-parse", "HEAD"]).stdout.strip()
    if aider_head != AIDER_COMMIT or polyglot_head != POLYGLOT_COMMIT:
        raise RuntimeError(f"pinned checkout mismatch: aider={aider_head}, polyglot={polyglot_head}")
    python = shutil.which("python3.12") or sys.executable
    run([python, "-m", "venv", str(RUN_DIR / "aider-venv")])
    run([str(RUN_DIR / "aider-venv/bin/pip"), "install", "--upgrade", "pip"])
    run([str(RUN_DIR / "aider-venv/bin/pip"), "install", "--no-cache-dir", "-e", f"{AIDER_DIR}[dev]"])


def create_trial_corpus() -> tuple[Path, list[str], dict[str, str]]:
    source = (
        AIDER_DIR
        / "tmp.benchmarks/polyglot-benchmark/cpp/exercises/practice/crypto-square"
    )
    if task_tree_sha256(source) != OFFICIAL_TASK_TREE_SHA256:
        raise RuntimeError("official Crypto Square task bytes do not match the pinned contract")
    source_hashes = relative_file_hashes(source)
    root = RUN_DIR / "crypto-square-8x2"
    practice = root / "cpp/exercises/practice"
    practice.mkdir(parents=True)
    names = []
    for trial in range(1, TRIALS + 1):
        name = f"crypto-square-trial-{trial:02d}"
        destination = practice / name
        shutil.copytree(source, destination)
        if relative_file_hashes(destination) != source_hashes:
            raise RuntimeError(f"trial copy differs from canonical task: {name}")
        cmake_path = destination / "CMakeLists.txt"
        cmake_text = cmake_path.read_text(encoding="utf-8")
        derived_line = 'string(REPLACE "-" "_" file ' + chr(36) + '{exercise})'
        if cmake_text.count(derived_line) != 1:
            raise RuntimeError(f"unexpected canonical CMake contract: {name}")
        cmake_path.write_text(
            cmake_text.replace(
                derived_line,
                'set(file crypto_square) # Preserve canonical source/test stems in trial clones',
            ),
            encoding="utf-8",
        )
        names.append(name)
    return root, names, source_hashes


def server_command(port: int) -> list[str]:
    return [
        *DOCKER,
        "run",
        "-d",
        "--name",
        f"sglang-{RUN_ID}",
        "--gpus",
        "all",
        "--network",
        "host",
        "--ipc",
        "host",
        "-e",
        "CUDA_VISIBLE_DEVICES=0,1,2,3",
        "-v",
        f"{RUN_DIR}:/workspace-run",
        "-v",
        f"{MODEL_HOST_PATH}:/workspace-model:ro",
        IMAGE,
        "python3",
        "-m",
        "sglang.launch_server",
        "--model-path",
        "/workspace-model",
        "--tp-size",
        "4",
        "--tool-call-parser",
        "glm47",
        "--reasoning-parser",
        "glm45",
        "--mem-fraction-static",
        "0.8",
        "--max-running-requests",
        "16",
        "--served-model-name",
        SERVED_MODEL_NAME,
        "--api-key",
        API_KEY,
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--enable-lora",
        "--max-lora-rank",
        "32",
        "--lora-backend",
        "triton",
        "--lora-target-modules",
        "q_a_proj",
        "kv_a_proj_with_mqa",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
        "--experts-shared-outer-loras",
        "--lora-use-virtual-experts",
    ]


def benchmark_command(corpus: Path) -> list[str]:
    return [
        str(RUN_DIR / "aider-venv/bin/python"),
        str(AIDER_DIR / "benchmark/benchmark.py"),
        RUN_ID,
        "--model",
        f"openai/{SERVED_MODEL_NAME}",
        "--edit-format",
        "whole",
        "--languages",
        "cpp",
        "--tries",
        str(TRIES),
        "--threads",
        str(THREADS),
        "--exercises-dir",
        str(corpus),
        "--read-model-settings",
        str(RUN_DIR / "model-settings.yml"),
        "--num-ctx",
        str(CONTEXT_WINDOW),
    ]


def validate_results(output_dir: Path, expected_names: list[str]) -> dict[str, object]:
    paths = sorted(output_dir.rglob(".aider.results.json"))
    if len(paths) != TRIALS:
        raise RuntimeError(f"expected {TRIALS} terminal results, found {len(paths)}")
    rows: list[dict[str, object]] = []
    for path in paths:
        payload = json.loads(path.read_text())
        outcomes = payload.get("tests_outcomes")
        if (
            not isinstance(outcomes, list)
            or not 1 <= len(outcomes) <= TRIES
            or any(not isinstance(value, bool) for value in outcomes)
            or (len(outcomes) < TRIES and not outcomes[-1])
            or (len(outcomes) == 2 and outcomes[0])
        ):
            raise RuntimeError(f"malformed two-turn result: {path}")
        rows.append({"path": path, "payload": payload})
    observed = sorted(Path(str(row["payload"]["testcase"])).name for row in rows)
    if observed != sorted(expected_names):
        raise RuntimeError(f"trial identities mismatch: {observed}")
    pass_at_1 = sum(bool(row["payload"]["tests_outcomes"][0]) for row in rows)
    final = sum(any(row["payload"]["tests_outcomes"]) for row in rows)
    return {
        "terminal_trials": TRIALS,
        "maximum_turns_per_trial": TRIES,
        "terminal_attempts": sum(len(row["payload"]["tests_outcomes"]) for row in rows),
        "pass_at_1": pass_at_1,
        "mef_pass_by_turn_2": final,
        "repair_only_passes": final - pass_at_1,
        "well_formed_trials": sum(
            int(row["payload"].get("num_malformed_responses", 0)) == 0 for row in rows
        ),
        "malformed_responses": sum(
            int(row["payload"].get("num_malformed_responses", 0)) for row in rows
        ),
        "error_outputs": sum(int(row["payload"].get("num_error_outputs", 0)) for row in rows),
        "context_exhaustions": sum(
            int(row["payload"].get("num_exhausted_context_windows", 0)) for row in rows
        ),
        "test_timeouts": sum(int(row["payload"].get("test_timeouts", 0)) for row in rows),
        "trials": [
            {
                "trial": Path(str(row["payload"]["testcase"])).name,
                "tests_outcomes": row["payload"]["tests_outcomes"],
                "result_sha256": sha256_path(row["path"]),
            }
            for row in rows
        ],
    }


def evaluate(conversion_receipt: dict[str, object]) -> dict[str, object]:
    corpus, trial_names, source_hashes = create_trial_corpus()
    shutil.copy2(
        BUNDLE_DIR / "crypto_square_aider_8x2_model_settings.yml",
        RUN_DIR / "model-settings.yml",
    )
    port = 18000
    container = f"sglang-{RUN_ID}"
    command = server_command(port)
    run(command)
    started = datetime.now(timezone.utc)
    adapter_load: dict[str, object] | None = None
    activation: dict[str, object] | None = None
    try:
        wait_for_server(container, port)
        adapter_load = load_adapter(port, "/workspace-run/adapter-serving")
        activation = verify_lora_activation(port)
        benchmark = benchmark_command(corpus)
        env = dict(
            os.environ,
            OPENAI_API_BASE=f"http://127.0.0.1:{port}/v1",
            OPENAI_API_KEY=API_KEY,
            AIDER_DOCKER="1",
        )
        log_path = RUN_DIR / "benchmark.log"
        with log_path.open("w", encoding="utf-8") as handle:
            subprocess.run(
                benchmark,
                cwd=AIDER_DIR,
                env=env,
                check=True,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
    finally:
        server_log = subprocess.run(
            [*DOCKER, "logs", container], capture_output=True, text=True
        )
        (RUN_DIR / "sglang.log").write_text(server_log.stdout + server_log.stderr)
        subprocess.run([*DOCKER, "rm", "-f", container], capture_output=True)

    candidates = sorted((AIDER_DIR / "tmp.benchmarks").glob(f"*--{RUN_ID}"))
    if not candidates:
        raise RuntimeError("Aider produced no benchmark output")
    output = candidates[-1]
    validation = validate_results(output, trial_names)
    shutil.copytree(output, RUN_DIR / "benchmark-results")
    return {
        "schema_version": 1,
        "kind": "crypto-square-aider-8x2-evaluation",
        "status": "complete",
        "run_id": RUN_ID,
        "source_run_id": SOURCE_RUN_ID,
        "source_checkpoint": SOURCE_CHECKPOINT,
        "adapter_sha256": ADAPTER_SHA256,
        "adapter_config_sha256": ADAPTER_CONFIG_SHA256,
        "training_data_manifest_sha256": TRAINING_DATA_MANIFEST_SHA256,
        "official_task_tree_sha256": OFFICIAL_TASK_TREE_SHA256,
        "official_task_file_hashes": source_hashes,
        "aider_commit": AIDER_COMMIT,
        "polyglot_commit": POLYGLOT_COMMIT,
        "image": IMAGE,
        "thinking_enabled": THINKING_ENABLED,
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "max_tokens": MAX_TOKENS,
        "context_window": CONTEXT_WINDOW,
        "trials": TRIALS,
        "tries": TRIES,
        "lora_activation": activation,
        "adapter_load": adapter_load,
        "serving_conversion": conversion_receipt,
        "server_command": command,
        "benchmark_command": benchmark,
        "started_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation": validation,
    }


def sync_durable() -> None:
    run(
        [
            "gcloud",
            "storage",
            "rsync",
            "--recursive",
            str(RUN_DIR),
            f"{DURABLE_ROOT}/{RUN_ID}/",
        ]
    )


def main() -> None:
    global DOCKER
    if not RUN_ID_PATTERN.fullmatch(RUN_ID):
        raise ValueError("EVAL_RUN_ID contains unsupported characters")
    if RUN_DIR.exists():
        raise RuntimeError(f"refusing to reuse evaluation directory: {RUN_DIR}")
    RUN_DIR.mkdir(parents=True)
    DOCKER = resolve_docker()
    failure: dict[str, object] | None = None
    try:
        preflight_host()
        verify_source_adapter()
        conversion = build_serving_adapter()
        stage_aider()
        receipt = evaluate(conversion)
        (RUN_DIR / "run_receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
        result = receipt["validation"]
        log(
            f"RESULT pass@1={result['pass_at_1']}/{TRIALS} "
            f"MEF={result['mef_pass_by_turn_2']}/{TRIALS}"
        )
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "kind": "crypto-square-aider-8x2-evaluation",
            "status": "failed",
            "run_id": RUN_ID,
            "error": repr(exc),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        (RUN_DIR / "run_receipt.json").write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n"
        )
        raise
    finally:
        try:
            sync_durable()
        except Exception as sync_error:
            log(f"durable sync failed: {sync_error!r}")


if __name__ == "__main__":
    main()
