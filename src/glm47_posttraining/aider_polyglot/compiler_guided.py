"""Compiler-guided best-of-N generation for answer-blind Aider C++ tasks."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol, Sequence

from glm47_posttraining.aider_polyglot.harness import (
    DEFAULT_AIDER_DOCKER_IMAGE,
    _combined_logs,
    _run_stage,
    _validate_candidate_source,
    run_shadow_tests,
    shlex_quote,
)
from glm47_posttraining.aider_polyglot.parser import ParsedAiderResponse
from glm47_posttraining.aider_polyglot.reward import (
    ProductionAiderRewardBreakdown,
    compute_production_aider_reward,
)
from glm47_posttraining.aider_polyglot.schema import AiderPolyglotTask, AiderTestResult


GENERIC_PRIVATE_FAILURE = (
    "Private tests failed. Private test names and output are intentionally withheld. "
    "Re-check the stated public contract and repair only the editable production files."
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
ABSOLUTE_PATH_RE = re.compile(r"(?:/[A-Za-z0-9_.+~-]+){2,}")
PRIVATE_LOG_MARKERS = (
    ".grader",
    ".reference",
    "_test.cpp",
    "_test.cc",
    "cmakelists",
    "expected output",
    "private test",
    "hidden test",
)
ACTIONABLE_MARKERS = (
    "error:",
    "fatal error:",
    "undefined reference",
    "multiple definition",
    "warning:",
)


class ChatCompletionClient(Protocol):
    def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float,
        seed: int,
    ) -> str: ...


@dataclass(frozen=True)
class PublicCompileResult:
    passed: bool
    returncode: int
    log_sha256: str
    feedback: str | None


@dataclass(frozen=True)
class CandidateResult:
    candidate_index: int
    turn: int
    seed: int
    response: str
    response_sha256: str
    reward: float
    reason: str
    format_valid: bool
    all_tests_pass: bool
    tests_passed: int
    tests_total: int
    public_compile: PublicCompileResult | None
    repair_feedback: str | None


class OpenAIChatClient:
    """Small OpenAI-compatible client intended for a local SGLang endpoint."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout_s: int = 1800,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float,
        seed: int,
    ) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": list(messages),
                "temperature": temperature,
                "seed": seed,
                "n": 1,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.endpoint}/chat/completions", data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("chat completion response lacks choices[0].message.content") from exc
        if not isinstance(content, str) or not content:
            raise RuntimeError("chat completion returned empty content")
        return content


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sanitize_public_compiler_feedback(
    logs: str, editable_files: Sequence[str], *, max_lines: int = 12
) -> str | None:
    """Return the first public-source diagnostic without private grader details."""

    allowed = set(editable_files)
    cleaned: list[str] = []
    for raw in ANSI_RE.sub("", logs).splitlines():
        lowered = raw.lower()
        if not raw.strip() or any(marker in lowered for marker in PRIVATE_LOG_MARKERS):
            continue
        line = ABSOLUTE_PATH_RE.sub(lambda match: Path(match.group(0)).name, raw).strip()
        if len(line) > 800:
            line = line[:800]
        cleaned.append(line)
    start = next(
        (
            index
            for index, line in enumerate(cleaned)
            if any(marker in line.lower() for marker in ACTIONABLE_MARKERS)
            and (any(name in line for name in allowed) or "glm47_public_headers.cpp" in line)
        ),
        None,
    )
    if start is None:
        return None
    selected: list[str] = []
    for line in cleaned[start : start + max_lines]:
        if any(marker in line.lower() for marker in PRIVATE_LOG_MARKERS):
            continue
        selected.append(line.replace("glm47_public_headers.cpp", "public-header-probe.cpp"))
    if not selected:
        return None
    return (
        "Compilation failed.\n\nFirst actionable public-source diagnostic:\n"
        + "\n".join(selected)
        + "\n\nRepair only the editable production files. Preserve all public APIs and structure."
    )


def run_public_compile(
    exercise_dir: str | Path,
    editable_files: Sequence[str],
    candidate_files: dict[str, str],
    *,
    image: str = DEFAULT_AIDER_DOCKER_IMAGE,
    timeout_s: int = 120,
) -> PublicCompileResult:
    """Compile only public/editable source, never the hidden grader."""

    source = Path(exercise_dir)
    with TemporaryDirectory(prefix=f"aider_public_compile_{source.name}_") as temporary:
        scratch = Path(temporary)
        for name in editable_files:
            contents = candidate_files.get(name, (source / name).read_text(encoding="utf-8"))
            _validate_candidate_source(name, contents)
            (scratch / name).write_text(contents, encoding="utf-8")
        headers = sorted(name for name in editable_files if Path(name).suffix in {".h", ".hpp"})
        sources = sorted(name for name in editable_files if Path(name).suffix in {".cpp", ".cc"})
        probe = "".join(f'#include "{name}"\n' for name in headers) + "int main() { return 0; }\n"
        (scratch / "glm47_public_headers.cpp").write_text(probe, encoding="utf-8")
        units = [*sources, "glm47_public_headers.cpp"]
        command = (
            "timeout "
            + str(timeout_s)
            + "s c++ -std=c++17 -Wall -Wextra -Werror -pedantic -pthread -I. -fsyntax-only "
            + " ".join(shlex_quote(name) for name in units)
        )
        result = _run_stage(scratch, command, image=image, timeout_s=timeout_s + 10)
        logs = _combined_logs(result)
        feedback = None
        if result.returncode != 0:
            feedback = sanitize_public_compiler_feedback(logs, editable_files)
        return PublicCompileResult(
            passed=result.returncode == 0,
            returncode=result.returncode,
            log_sha256=_sha256_text(logs),
            feedback=feedback,
        )


def _score_response(
    task: AiderPolyglotTask,
    exercise_dir: Path,
    response: str,
    *,
    image: str,
) -> tuple[ProductionAiderRewardBreakdown, ParsedAiderResponse | None]:
    def runner(path: Path, files: dict[str, str]) -> AiderTestResult:
        return run_shadow_tests(
            path,
            files,
            image=image,
            expected_test_sha256=task.hidden_test_sha256,
        )

    breakdown = compute_production_aider_reward(
        task, exercise_dir, response, runner=runner
    )
    return breakdown, breakdown.parsed


def _candidate_result(
    *,
    candidate_index: int,
    turn: int,
    seed: int,
    response: str,
    breakdown: ProductionAiderRewardBreakdown,
    public_compile: PublicCompileResult | None,
    repair_feedback: str | None,
) -> CandidateResult:
    harness = breakdown.harness
    return CandidateResult(
        candidate_index=candidate_index,
        turn=turn,
        seed=seed,
        response=response,
        response_sha256=_sha256_text(response),
        reward=breakdown.reward,
        reason=breakdown.reason,
        format_valid=bool(breakdown.parsed and breakdown.parsed.format_valid),
        all_tests_pass=bool(harness and harness.all_tests_pass),
        tests_passed=harness.tests_passed if harness else 0,
        tests_total=harness.tests_total if harness else 0,
        public_compile=public_compile,
        repair_feedback=repair_feedback,
    )


def _repair_feedback(
    task: AiderPolyglotTask,
    exercise_dir: Path,
    parsed: ParsedAiderResponse | None,
    *,
    image: str,
) -> tuple[str, PublicCompileResult | None]:
    if parsed is None:
        return (
            "The response could not be applied as complete editable files. Return only complete "
            "Aider whole-file replacements for the allowed filenames.",
            None,
        )
    public = run_public_compile(
        exercise_dir,
        task.editable_files,
        parsed.files,
        image=image,
    )
    if not public.passed and public.feedback:
        return public.feedback, public
    return GENERIC_PRIVATE_FAILURE, public


def run_best_of_n_with_repair(
    task: AiderPolyglotTask,
    exercise_dir: str | Path,
    client: ChatCompletionClient,
    *,
    candidates: int = 4,
    repair_turns: int = 1,
    seed: int = 1701,
    temperature: float = 0.7,
    repair_temperature: float = 0.2,
    image: str = DEFAULT_AIDER_DOCKER_IMAGE,
) -> tuple[CandidateResult, list[CandidateResult]]:
    """Generate independent candidates, repair failures, and select executable best."""

    if candidates < 1 or repair_turns < 0:
        raise ValueError("candidates must be positive and repair_turns nonnegative")
    root = Path(exercise_dir)
    base_messages = [message.model_dump() for message in task.prompt]
    results: list[CandidateResult] = []
    for candidate_index in range(candidates):
        candidate_seed = seed + candidate_index
        messages = list(base_messages)
        response = client.complete(messages, temperature=temperature, seed=candidate_seed)
        breakdown, parsed = _score_response(task, root, response, image=image)
        initial = _candidate_result(
            candidate_index=candidate_index,
            turn=0,
            seed=candidate_seed,
            response=response,
            breakdown=breakdown,
            public_compile=None,
            repair_feedback=None,
        )
        results.append(initial)
        current = initial
        current_parsed = parsed
        for turn in range(1, repair_turns + 1):
            if current.all_tests_pass:
                break
            feedback, public = _repair_feedback(
                task, root, current_parsed, image=image
            )
            messages.extend(
                [
                    {"role": "assistant", "content": current.response},
                    {"role": "user", "content": feedback},
                ]
            )
            repaired = client.complete(
                messages,
                temperature=repair_temperature,
                seed=candidate_seed + turn * 100_000,
            )
            repaired_breakdown, current_parsed = _score_response(
                task, root, repaired, image=image
            )
            current = _candidate_result(
                candidate_index=candidate_index,
                turn=turn,
                seed=candidate_seed + turn * 100_000,
                response=repaired,
                breakdown=repaired_breakdown,
                public_compile=public,
                repair_feedback=feedback,
            )
            results.append(current)

    selected = max(
        results,
        key=lambda item: (
            item.all_tests_pass,
            item.reward,
            item.tests_passed,
            item.format_valid,
            -item.turn,
            -item.candidate_index,
        ),
    )
    return selected, results


def result_receipt(
    task: AiderPolyglotTask,
    selected: CandidateResult,
    attempts: Sequence[CandidateResult],
) -> dict[str, Any]:
    """Serialize selection evidence without private grader logs or expected values."""

    def record(item: CandidateResult) -> dict[str, Any]:
        public = item.public_compile
        return {
            "candidate_index": item.candidate_index,
            "turn": item.turn,
            "seed": item.seed,
            "response_sha256": item.response_sha256,
            "reward": item.reward,
            "reason": item.reason,
            "format_valid": item.format_valid,
            "all_tests_pass": item.all_tests_pass,
            "tests_passed": item.tests_passed,
            "tests_total": item.tests_total,
            "repair_feedback_sha256": (
                _sha256_text(item.repair_feedback) if item.repair_feedback else None
            ),
            "public_compile": (
                {
                    "passed": public.passed,
                    "returncode": public.returncode,
                    "log_sha256": public.log_sha256,
                    "feedback_sha256": (
                        _sha256_text(public.feedback) if public.feedback else None
                    ),
                }
                if public
                else None
            ),
        }

    return {
        "schema_version": "compiler-guided-best-of-n-receipt-v1",
        "decision": "PASS" if selected.all_tests_pass else "FAIL",
        "task_id": task.task_id,
        "hidden_test_sha256": task.hidden_test_sha256,
        "selected_candidate_index": selected.candidate_index,
        "selected_turn": selected.turn,
        "selected_response_sha256": selected.response_sha256,
        "candidate_count": len({item.candidate_index for item in attempts}),
        "attempt_count": len(attempts),
        "private_test_source_disclosed": False,
        "private_test_output_disclosed": False,
        "attempts": [record(item) for item in attempts],
    }
