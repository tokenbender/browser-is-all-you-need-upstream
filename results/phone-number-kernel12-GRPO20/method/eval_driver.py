#!/usr/bin/env python3




















from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
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
    "unadmitted-r8-r87-run21-20260814T030808Z-attempt-20260814T031719Z-d951d40e",
)
SOURCE_CHECKPOINT = os.environ.get("EVAL_SOURCE_CHECKPOINT", "iter_0000005")
ADAPTER_SHA256 = os.environ.get(
    "EVAL_EXPECTED_ADAPTER_SHA256",
    "7fb350de045fb1d476fefcdaeb59a5c69ea7f5e2fe744516b63e146f26d8bfc2",
)
ADAPTER_CONFIG_SHA256 = os.environ.get(
    "EVAL_EXPECTED_ADAPTER_CONFIG_SHA256",
    "0bd6d85f88fc42fefa52627b3c261f1ad58bb2c9519332ae8034dd5dffe2498e",
)
SERVING_SHA256 = os.environ.get(
    "EVAL_EXPECTED_SERVING_SHA256",
    "ba5b531947851c44e5a0587a3585cfc14bccf322ef8ccfb98e0db4af00290eb0",
)
TRAINING_DATA_MANIFEST_SHA256 = os.environ.get(
    "EVAL_EXPECTED_TRAINING_MANIFEST_SHA256",
    "72296f7bae1b4690a613922f3f29b2011e4a8646d356a4e7663cfc5822e7bfd2",
)
TRAINING_GATE_RUN_ID = os.environ.get("EVAL_TRAINING_GATE_RUN_ID", SOURCE_RUN_ID)

EXPECTED_SOURCE_TENSORS = 9_741
EXPECTED_LAYER_47_TENSORS = 207
EXPECTED_SERVING_TENSORS = 9_534

LORA_NAME = "glm-4.7-flash-grpo"
SERVED_MODEL_NAME = "glm-4.7-flash-grpo"
API_KEY = "local-eval"
TRIES = 2
THREADS = 8
TEMPERATURE = 0.7
TOP_P = 1.0
MAX_TOKENS = 32768
THINKING_DISABLED = False

DURABLE_ROOT = os.environ.get(
    "EVAL_DURABLE_ROOT",
    "gs://lifeandhalf-24122025-w8-biayn/runs/glm47/evaluations/aider-fixed26",
)

HOME = Path.home()
ASSETS = HOME / "eval-assets"
MODEL_HOST_PATH = ASSETS / "model" / "GLM-4.7-Flash"
ADAPTER_HOST_DIR = ASSETS / "adapter"
TRAINING_MANIFEST = ASSETS / "training" / "manifest.json"
BUNDLE_DIR = Path(__file__).resolve().parent


AIDER_DIR = Path("/aider")

RUN_ID = os.environ.get(
    "EVAL_RUN_ID",
    "job22-iter5-fixed26-contractv2-thinking-"
    + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
)
WORKSPACE = Path(os.environ.get("EVAL_WORKSPACE", str(HOME / "glm47-eval-workspace")))
RUN_DIR = WORKSPACE / f"eval-{RUN_ID}"


def log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat()}] {message}", flush=True)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


DOCKER: list[str] = []


def resolve_docker() -> list[str]:
    for candidate in (["docker"], ["sudo", "-n", "docker"]):
        probe = subprocess.run(
            [*candidate, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            log(f"docker access via: {' '.join(candidate)} (server {probe.stdout.strip()})")
            return candidate
    raise RuntimeError("no working docker invocation found")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    log(f"$ {' '.join(str(c) for c in cmd)[:400]}")
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        stdout = (result.stdout or "")[-4000:] if result.stdout else ""
        stderr = (result.stderr or "")[-4000:] if result.stderr else ""
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(str(c) for c in cmd)[:200]}\n"
            f"stdout tail:\n{stdout}\nstderr tail:\n{stderr}"
        )
    return result


def http_post(port: int, path: str, payload: dict, timeout: int = 600) -> tuple[int, str]:
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
            raise RuntimeError(
                f"server container {container} exited: {state.stdout.strip()}\n"
                f"log tail:\n{state.stdout}{state.stderr}\n{tail.stdout[-8000:]}"
            )
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=5
            ) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(10)
    raise TimeoutError(f"server on port {port} did not become healthy in {timeout}s")


def load_adapter(port: int, serving_path: str) -> dict[str, object]:
    payload = {"lora_name": LORA_NAME, "lora_path": serving_path}
    for endpoint in ("/load_lora_adapter", "/v1/load_lora_adapter"):
        status, body = http_post(port, endpoint, payload)
        if status == 200:
            return {"endpoint": endpoint, "status": status, "body": body[:2000]}
        if status != 404:
            raise RuntimeError(f"adapter load failed on {endpoint}: {status} {body[:2000]}")
    raise RuntimeError("SGLang exposes no LoRA adapter loading endpoint")


def probe_completion(port: int, lora: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "model": LORA_NAME,
        "messages": [
            {
                "role": "user",
                "content": "Write a C++17 function `int answer()` that returns 42. "
                "Reply with only the code.",
            }
        ],
        "temperature": 0.0,
        "max_tokens": 48,
        "logprobs": True,
    }
    if lora:
        body["lora_path"] = LORA_NAME
    status, text = http_post(port, "/v1/chat/completions", body)
    if status != 200:
        raise RuntimeError(f"probe completion failed: {status} {text[:1000]}")
    payload = json.loads(text)
    choice = payload["choices"][0]
    logprobs = [
        round(entry["logprob"], 6)
        for entry in (choice.get("logprobs") or {}).get("content") or []
    ]
    return {"content": choice["message"]["content"], "logprobs": logprobs}


def verify_lora_activation(port: int) -> dict[str, object]:
    with_lora = probe_completion(port, lora=True)
    without_lora = probe_completion(port, lora=False)
    if (
        with_lora["content"] == without_lora["content"]
        and with_lora["logprobs"] == without_lora["logprobs"]
    ):
        raise RuntimeError(
            "LoRA activation probe failed: greedy completions with and without "
            "lora_path are identical; benchmark traffic would measure base weights"
        )
    return {"status": "diverged", "with_lora": with_lora, "without_lora": without_lora}





def preflight_host() -> None:
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=True,
    )
    gpus = [line.strip() for line in smi.stdout.strip().splitlines()]
    if len(gpus) != 8 or any("H100" not in line for line in gpus):
        raise RuntimeError(f"expected 8x H100, got: {gpus}")
    log(f"host GPUs: {gpus[0]} x{len(gpus)}")
    if not (MODEL_HOST_PATH / "config.json").is_file():
        raise RuntimeError(f"model mount missing: {MODEL_HOST_PATH}")
    revision_file = MODEL_HOST_PATH / "MODEL_REVISION"
    if revision_file.is_file() and revision_file.read_text().strip() != MODEL_REVISION:
        raise RuntimeError("model revision mismatch against the pinned contract")


def verify_source_adapter() -> None:
    model_bin = ADAPTER_HOST_DIR / "adapter_model.bin"
    config = ADAPTER_HOST_DIR / "adapter_config.json"
    for path in (model_bin, config, TRAINING_MANIFEST):
        if not path.is_file():
            raise RuntimeError(f"source artifact mount incomplete: {path}")
    if sha256_path(model_bin) != ADAPTER_SHA256:
        raise RuntimeError("adapter_model.bin does not match the configured source digest")
    if sha256_path(config) != ADAPTER_CONFIG_SHA256:
        raise RuntimeError("adapter_config.json does not match the configured source digest")
    if sha256_path(TRAINING_MANIFEST) != TRAINING_DATA_MANIFEST_SHA256:
        raise RuntimeError("training manifest does not match the configured source digest")
    parsed = json.loads(config.read_text(encoding="utf-8"))
    if int(parsed["r"]) != 16 or int(parsed["lora_alpha"]) != 32:
        raise RuntimeError("adapter LoRA rank/alpha mismatch against the configured contract")
    log("source adapter and training manifest identities verified")


def build_serving_adapter() -> dict[str, object]:

    source = RUN_DIR / "adapter-source"
    serving = RUN_DIR / "adapter-serving"
    if serving.exists():
        raise RuntimeError(f"refusing to reuse serving path: {serving}")
    shutil.copytree(ADAPTER_HOST_DIR, source)
    script = (
        "import json, shutil, torch\n"
        "src = '/workspace-run/adapter-source'\n"
        "dst = '/workspace-run/adapter-serving'\n"
        "state = torch.load(src + '/adapter_model.bin', map_location='cpu',"
        " weights_only=True, mmap=True)\n"
        "removed = [k for k in state if '.layers.47.' in k]\n"
        "kept = {k: v for k, v in state.items() if '.layers.47.' not in k}\n"
        "import os; os.mkdir(dst)\n"
        "torch.save(kept, dst + '/adapter_model.bin')\n"
        "shutil.copy2(src + '/adapter_config.json', dst + '/adapter_config.json')\n"
        "print(json.dumps({'source': len(state), 'removed': len(removed),"
        " 'serving': len(kept)}))\n"
    )
    result = run(
        [
            *DOCKER, "run", "--rm",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-e", "HOME=/tmp",
            "-v", f"{RUN_DIR}:/workspace-run",
            IMAGE, "python3", "-c", script,
        ],
        capture_output=True,
        text=True,
    )
    counts = json.loads(result.stdout.strip().splitlines()[-1])
    expected = {
        "source": EXPECTED_SOURCE_TENSORS,
        "removed": EXPECTED_LAYER_47_TENSORS,
        "serving": EXPECTED_SERVING_TENSORS,
    }
    if counts != expected:
        raise RuntimeError(f"serving conversion tensor counts mismatch: {counts}")
    serving_sha = sha256_path(serving / "adapter_model.bin")
    if serving_sha != SERVING_SHA256:
        raise RuntimeError(
            f"serving adapter digest {serving_sha} != configured {SERVING_SHA256}"
        )
    log("serving adapter reproduces the configured digest exactly")
    receipt = {
        "schema_version": 2,
        "kind": "glm47-serving-adapter-conversion",
        "source_adapter_path": str(source),
        "source_adapter_sha256": ADAPTER_SHA256,
        "source_adapter_config_sha256": ADAPTER_CONFIG_SHA256,
        "source_tensor_count": EXPECTED_SOURCE_TENSORS,
        "removed_layer_47_tensor_count": EXPECTED_LAYER_47_TENSORS,
        "serving_tensor_count": EXPECTED_SERVING_TENSORS,
        "serving_adapter_sha256": serving_sha,
        "serving_adapter_config_sha256": sha256_path(serving / "adapter_config.json"),
        "training_data_manifest_sha256": TRAINING_DATA_MANIFEST_SHA256,
        "training_gate_run_id": TRAINING_GATE_RUN_ID,
        "source_run_id": SOURCE_RUN_ID,
        "source_checkpoint": SOURCE_CHECKPOINT,
    }
    (serving / "conversion_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def stage_aider_tree() -> None:





    target = AIDER_DIR
    if not (target / "benchmark/benchmark.py").is_file():
        raise RuntimeError(f"pinned aider checkout missing: {target}")
    aider_head = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    polyglot_head = subprocess.run(
        ["git", "-C", str(target / "tmp.benchmarks/polyglot-benchmark"), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if aider_head != AIDER_COMMIT or polyglot_head != POLYGLOT_COMMIT:
        raise RuntimeError(
            f"staged tree commit drift: aider={aider_head} polyglot={polyglot_head}"
        )
    venv_python = shutil.which("python3.12") or sys.executable
    run([venv_python, "-m", "venv", str(RUN_DIR / "aider-venv")])
    run([str(RUN_DIR / "aider-venv/bin/pip"), "install", "--upgrade", "pip"])
    run([
        str(RUN_DIR / "aider-venv/bin/pip"), "install", "--no-cache-dir",
        "-e", f"{target}[dev]",
    ])
    log("staged /aider tree matches pinned aider and polyglot commits")


def create_shards() -> dict[int, dict[str, object]]:
    sys.path.insert(0, str(BUNDLE_DIR))
    import aider_fixed26_contract_overlay as overlay

    source = AIDER_DIR / "tmp.benchmarks/polyglot-benchmark/cpp/exercises/practice"
    tasks = sorted(path for path in source.iterdir() if path.is_dir())
    if len(tasks) != 26:
        raise RuntimeError(f"fixed C++ benchmark task count mismatch: {len(tasks)} != 26")
    shards: dict[int, dict[str, object]] = {}
    for shard_index in (0, 1):
        selected = tasks[shard_index * 13 : (shard_index + 1) * 13]
        shard_root = RUN_DIR / "shards" / f"shard-{shard_index}"
        destination = shard_root / "cpp/exercises/practice"
        destination.mkdir(parents=True, exist_ok=False)
        for task in selected:
            shutil.copytree(task, destination / task.name)
        manifest = overlay.apply(destination)
        if int(manifest["tasks"]) != len(selected):
            raise RuntimeError("contract overlay did not cover every shard task")
        audit_manifest = overlay.audit(destination)
        if int(audit_manifest["unexplained_deterministic_requirements"]) != 0:
            raise RuntimeError("contract audit left unexplained deterministic requirements")
        manifest["prompt_test_audit"] = audit_manifest
        manifest["prompt_test_audit_sha256"] = audit_manifest["audit_sha256"]
        shards[shard_index] = {
            "root": str(shard_root),
            "tasks": [task.name for task in selected],
            "overlay": manifest,
        }
        log(
            f"shard {shard_index}: {len(selected)} tasks, overlay "
            f"{manifest['overlay_version']} sha {manifest['overlay_sha256'][:12]}…"
        )
    return shards





def server_command(shard_index: int, port: int) -> list[str]:
    gpus = "0,1,2,3" if shard_index == 0 else "4,5,6,7"
    return [
        *DOCKER, "run", "-d",
        "--name", f"sglang-{RUN_ID}-shard{shard_index}",
        "--gpus", "all",
        "--network", "host",
        "--ipc", "host",
        "-e", f"CUDA_VISIBLE_DEVICES={gpus}",
        "-v", f"{RUN_DIR}:/workspace-run",
        "-v", f"{MODEL_HOST_PATH}:/workspace-model:ro",
        IMAGE,
        "python3", "-m", "sglang.launch_server",
        "--model-path", "/workspace-model",
        "--tp-size", "4",
        "--tool-call-parser", "glm47",
        "--reasoning-parser", "glm45",
        "--mem-fraction-static", "0.8",
        "--max-running-requests", "16",
        "--served-model-name", SERVED_MODEL_NAME,
        "--api-key", API_KEY,
        "--host", "0.0.0.0",
        "--port", str(port),
        "--enable-lora",
        "--max-lora-rank", "32",
        "--lora-backend", "triton",
        "--lora-target-modules", "q_a_proj", "kv_a_proj_with_mqa", "o_proj",
        "gate_proj", "up_proj", "down_proj",
        "--experts-shared-outer-loras",
        "--lora-use-virtual-experts",
    ]


def benchmark_command(shard_index: int, port: int) -> list[str]:
    label = f"{RUN_ID}-shard-{shard_index}"
    return [
        str(RUN_DIR / "aider-venv/bin/python"),
        str(AIDER_DIR / "benchmark/benchmark.py"), label,
        "--model", f"openai/{SERVED_MODEL_NAME}",
        "--edit-format", "whole",
        "--languages", "cpp",
        "--tries", str(TRIES),
        "--threads", str(THREADS),
        "--exercises-dir", str(RUN_DIR / f"shards/shard-{shard_index}"),
        "--read-model-settings", str(RUN_DIR / "model-settings.yml"),
    ]


def evaluate_shard(
    shard_index: int, shard_info: dict[str, object], conversion_receipt: dict[str, object]
) -> dict[str, object]:
    port = 18000 + shard_index
    container = f"sglang-{RUN_ID}-shard{shard_index}"
    started = datetime.now(timezone.utc)
    server_cmd = server_command(shard_index, port)
    adapter_load: dict[str, object] | None = None
    activation_probe: dict[str, object] | None = None
    try:
        run(server_cmd, capture_output=True)
        wait_for_server(container, port)
        log(f"shard {shard_index}: SGLang healthy on :{port}; loading adapter")
        adapter_load = load_adapter(port, "/workspace-run/adapter-serving")
        activation_probe = verify_lora_activation(port)
        log(f"shard {shard_index}: adapter active; starting benchmark")
        bench_cmd = benchmark_command(shard_index, port)
        log_path = RUN_DIR / f"benchmark-shard-{shard_index}.log"
        bench_env = dict(
            os.environ,
            OPENAI_API_BASE=f"http://127.0.0.1:{port}/v1",
            OPENAI_API_KEY=API_KEY,
            AIDER_DOCKER="1",
        )
        with log_path.open("w", encoding="utf-8") as handle:
            subprocess.run(
                bench_cmd,
                check=True,
                stdout=handle,
                stderr=subprocess.STDOUT,
                cwd=AIDER_DIR,
                env=bench_env,
            )
    finally:
        server_log = subprocess.run(
            [*DOCKER, "logs", container], capture_output=True, text=True
        )
        (RUN_DIR / f"sglang-shard-{shard_index}.log").write_text(
            server_log.stdout + server_log.stderr, encoding="utf-8"
        )
        subprocess.run([*DOCKER, "rm", "-f", container], capture_output=True)

    candidates = sorted(
        (AIDER_DIR / "tmp.benchmarks").glob(f"*--{RUN_ID}-shard-{shard_index}")
    )
    if not candidates:
        raise RuntimeError(f"no benchmark output for shard {shard_index}")
    output_dir = candidates[-1]
    stats = subprocess.run(
        [
            str(RUN_DIR / "aider-venv/bin/python"),
            str(AIDER_DIR / "benchmark/benchmark.py"),
            "--stats", str(output_dir),
        ],
        capture_output=True, text=True, check=True, cwd=AIDER_DIR,
    )
    validation = validate_results(output_dir, expected_tasks=13)
    observed = sorted(Path(t).name for t in validation["testcases"])
    if observed != sorted(shard_info["tasks"]):
        raise RuntimeError("shard task identities do not match the fixed partition")

    shard_out = RUN_DIR / "receipts" / f"shard-{shard_index}"
    shutil.copytree(output_dir, shard_out / output_dir.name)
    overlay_manifest = shard_info["overlay"]
    receipt = {
        "status": "complete",
        "run_id": RUN_ID,
        "shard_index": shard_index,
        "selected_tasks": shard_info["tasks"],
        "model_kind": "adapter",
        "model_revision": MODEL_REVISION,
        "adapter_source_sha256": ADAPTER_SHA256,
        "adapter_config_sha256": ADAPTER_CONFIG_SHA256,
        "training_data_manifest_sha256": TRAINING_DATA_MANIFEST_SHA256,
        "training_gate_run_id": TRAINING_GATE_RUN_ID,
        "source_run_id": SOURCE_RUN_ID,
        "source_checkpoint": SOURCE_CHECKPOINT,
        "serving_conversion_receipt": conversion_receipt,
        "aider_commit": AIDER_COMMIT,
        "polyglot_commit": POLYGLOT_COMMIT,
        "tries": TRIES,
        "eval_set_version": overlay_manifest["overlay_version"],
        "contract_overlay_sha256": overlay_manifest["overlay_sha256"],
        "prompt_test_audit_sha256": overlay_manifest["prompt_test_audit_sha256"],
        "contract_overlay": overlay_manifest,
        "gpu_ids": "0-3" if shard_index == 0 else "4-7",
        "gpu_requested": "4x NVIDIA H100 80GB HBM3",
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "max_tokens": MAX_TOKENS,
        "thinking_disabled": THINKING_DISABLED,
        "threads": THREADS,
        "image": IMAGE,
        "started_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "server_command": server_cmd,
        "benchmark_command": bench_cmd,
        "adapter_load": adapter_load,
        "lora_activation_probe": activation_probe,
        "stats_stdout": stats.stdout,
        "validation": validation,
    }
    (shard_out / "shard_receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    return receipt


def validate_results(output_dir: Path, *, expected_tasks: int) -> dict[str, object]:
    result_paths = sorted(output_dir.rglob(".aider.results.json"))
    if len(result_paths) != expected_tasks:
        raise RuntimeError(
            f"benchmark terminal-result count mismatch: {len(result_paths)} != {expected_tasks}"
        )
    rows = []
    for path in result_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        outcomes = payload.get("tests_outcomes")
        if (
            payload.get("model") != f"openai/{SERVED_MODEL_NAME}"
            or payload.get("edit_format") != "whole"
            or not isinstance(payload.get("testcase"), str)
            or not payload["testcase"]
            or not isinstance(outcomes, list)
            or not 1 <= len(outcomes) <= TRIES
            or any(not isinstance(value, bool) for value in outcomes)
            or (len(outcomes) < TRIES and not outcomes[-1])
            or (len(outcomes) > 1 and outcomes[0])
        ):
            raise RuntimeError(f"malformed or incomplete benchmark result: {path}")
        rows.append(payload)
    testcases = [payload["testcase"] for payload in rows]
    if len(testcases) != len(set(testcases)):
        raise RuntimeError("benchmark contains duplicate task identities")
    return {
        "terminal_tasks": len(rows),
        "terminal_attempts": sum(len(p["tests_outcomes"]) for p in rows),
        "maximum_attempts": expected_tasks * TRIES,
        "short_circuited_after_first_pass": sum(
            len(p["tests_outcomes"]) == 1 and p["tests_outcomes"][0] for p in rows
        ),
        "pass_at_1": sum(bool(p["tests_outcomes"][0]) for p in rows),
        "pass_at_k": sum(bool(any(p["tests_outcomes"])) for p in rows),
        "well_formed_tasks": sum(int(p.get("num_malformed_responses", 0)) == 0 for p in rows),
        "malformed_responses": sum(int(p.get("num_malformed_responses", 0)) for p in rows),
        "error_outputs": sum(int(p.get("num_error_outputs", 0)) for p in rows),
        "context_exhaustions": sum(int(p.get("num_exhausted_context_windows", 0)) for p in rows),
        "test_timeouts": sum(int(p.get("test_timeouts", 0)) for p in rows),
        "prompt_tokens": sum(int(p.get("prompt_tokens", 0)) for p in rows),
        "completion_tokens": sum(int(p.get("completion_tokens", 0)) for p in rows),
        "unique_testcases": len(set(testcases)),
        "testcases": sorted(testcases),
        "outcomes": {p["testcase"]: p["tests_outcomes"] for p in rows},
        "result_sha256": {
            p["testcase"]: sha256_path(path)
            for p, path in zip(rows, result_paths)
        },
    }


def merge_receipts(shard_receipts: list[dict[str, object]]) -> dict[str, object]:
    if sorted(r["shard_index"] for r in shard_receipts) != [0, 1]:
        raise RuntimeError("evaluation did not return both shards")
    testcases = [t for r in shard_receipts for t in r["validation"]["testcases"]]
    if len(testcases) != 26 or len(set(testcases)) != 26:
        raise RuntimeError("merged fixed-26 evaluation is incomplete or duplicated")
    summed = (
        "terminal_tasks", "terminal_attempts", "maximum_attempts",
        "short_circuited_after_first_pass", "pass_at_1", "pass_at_k",
        "well_formed_tasks", "malformed_responses", "error_outputs",
        "context_exhaustions", "test_timeouts", "prompt_tokens", "completion_tokens",
    )
    validation = {
        field: sum(int(r["validation"][field]) for r in shard_receipts) for field in summed
    }
    validation["unique_testcases"] = 26
    validation["testcases"] = sorted(testcases)
    validation["outcomes"] = {
        task: outcomes
        for r in shard_receipts
        for task, outcomes in r["validation"]["outcomes"].items()
    }
    receipt = {
        "status": "complete",
        "run_id": RUN_ID,
        "benchmark": "aider-polyglot-cpp-grpo-eval",
        "parallel_topology": "2x TP4 on one GCP a3-highgpu-8g (8x H100)",
        "model_kind": "adapter",
        "model_revision": MODEL_REVISION,
        "adapter_source": SOURCE_RUN_ID
        + f"/checkpoints/grpo_lora_r16/{SOURCE_CHECKPOINT}/adapter",
        "source_run_id": SOURCE_RUN_ID,
        "source_checkpoint": SOURCE_CHECKPOINT,
        "adapter_sha256": ADAPTER_SHA256,
        "adapter_config_sha256": ADAPTER_CONFIG_SHA256,
        "training_data_manifest_sha256": TRAINING_DATA_MANIFEST_SHA256,
        "aider_commit": AIDER_COMMIT,
        "polyglot_commit": POLYGLOT_COMMIT,
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "max_tokens": MAX_TOKENS,
        "thinking_disabled": THINKING_DISABLED,
        "tries": TRIES,
        "eval_set_version": shard_receipts[0]["eval_set_version"],
        "contract_overlay_sha256": shard_receipts[0]["contract_overlay_sha256"],
        "prompt_test_audit_sha256": shard_receipts[0]["prompt_test_audit_sha256"],
        "lora_activation_verified": all(
            r["lora_activation_probe"]["status"] == "diverged" for r in shard_receipts
        ),
        "image": IMAGE,
        "validation": validation,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (RUN_DIR / "run_receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    return receipt


def sync_durable() -> None:
    destination = f"{DURABLE_ROOT}/{RUN_ID}/"
    run(["gcloud", "storage", "rsync", "--recursive", str(RUN_DIR), destination])
    log(f"synced {RUN_DIR} -> {destination}")


def main() -> None:
    global DOCKER
    DOCKER = resolve_docker()
    log(f"run id: {RUN_ID}")
    if RUN_DIR.exists():
        raise RuntimeError(f"refusing to reuse run directory: {RUN_DIR}")
    RUN_DIR.mkdir(parents=True)
    preflight_host()
    verify_source_adapter()
    conversion_receipt = build_serving_adapter()
    stage_aider_tree()
    shards = create_shards()
    shutil.copy2(BUNDLE_DIR / "model-settings.yml", RUN_DIR / "model-settings.yml")

    failed: dict[str, object] | None = None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(evaluate_shard, index, shards[index], conversion_receipt)
                for index in (0, 1)
            ]
            shard_receipts = [future.result() for future in futures]
        merged = merge_receipts(shard_receipts)
        log(
            "RESULT pass@1 "
            f"{merged['validation']['pass_at_1']}/26, pass@2 "
            f"{merged['validation']['pass_at_k']}/26, well-formed "
            f"{merged['validation']['well_formed_tasks']}/26"
        )
    except Exception as exc:
        failed = {"status": "failed", "run_id": RUN_ID, "error": repr(exc)}
        (RUN_DIR / "run_receipt.json").write_text(
            json.dumps(failed, indent=2), encoding="utf-8"
        )
        raise
    finally:
        try:
            sync_durable()
        except Exception as sync_exc:
            log(f"WARNING: durable sync failed: {sync_exc!r}")


if __name__ == "__main__":
    main()
