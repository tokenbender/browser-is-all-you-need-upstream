from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from Reward_GRPO import global_verifier_grpo_mediator as mediator
from src.glm47_posttraining.aider_polyglot.dataset import build_aider_messages

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "Reward_GRPO/global_verifiers_set2"
BUNDLE = ROOT / "Reward_GRPO/task_bundles/phone-number-fixed26-v2"
REGISTRY = ROOT / "Reward_GRPO/global_verifier_task_registry.json"
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))
reconstruction = importlib.import_module("candidate_reconstruction")
receipt_module = importlib.import_module("receipt")
sandbox_module = importlib.import_module("sandbox")

PHONE_HEADER = r'''#if !defined(PHONE_NUMBER_H)
#define PHONE_NUMBER_H

#include <string>

namespace phone_number {

class phone_number {
public:
    phone_number(const std::string& text);
    std::string area_code() const;
    std::string number() const;
    explicit operator std::string() const;

private:
    std::string digits_;
};

}  // namespace phone_number

#endif
'''

PHONE_CPP = r'''#include "phone_number.h"

#include <algorithm>
#include <cctype>
#include <stdexcept>

namespace phone_number {

phone_number::phone_number(const std::string& text) {
    std::string digits;
    for (unsigned char value : text) {
        if (std::isdigit(value)) {
            digits.push_back(static_cast<char>(value));
        } else if (std::isalpha(value)) {
            throw std::domain_error("letters are invalid");
        } else if (value != ' ' && value != '-' && value != '.' && value != '(' && value != ')' && value != '+') {
            throw std::domain_error("punctuation is invalid");
        }
    }
    if (digits.size() == 11) {
        if (digits.front() != '1') {
            throw std::domain_error("country code is invalid");
        }
        digits.erase(digits.begin());
    }
    if (digits.size() != 10 || digits[0] < '2' || digits[3] < '2') {
        throw std::domain_error("NANP number is invalid");
    }
    digits_ = digits;
}

std::string phone_number::area_code() const { return digits_.substr(0, 3); }
std::string phone_number::number() const { return digits_; }
phone_number::operator std::string() const { return "(" + digits_.substr(0, 3) + ") " + digits_.substr(3, 3) + "-" + digits_.substr(6, 4); }

}  // namespace phone_number
'''


def binding() -> mediator.BundleBinding:
    return mediator.TaskBundleRegistry(REGISTRY).resolve("phone-number-fixed26-v2")


def candidate(tmp_path: Path, cpp: str = PHONE_CPP, header: str = PHONE_HEADER) -> Path:
    target = tmp_path / "candidate"
    target.mkdir()
    (target / "phone_number.h").write_text(header)
    (target / "phone_number.cpp").write_text(cpp)
    return target


def policy(receipt: dict, identifier: str) -> dict:
    return next(item for item in receipt["policies"] if item["policy"] == identifier)


def evaluate(path: Path) -> dict:
    return mediator.evaluate_candidate(binding(), path, executor="host", invalid_retries=0)


def test_real_phone_reference_passes_without_ast_truncation(tmp_path: Path) -> None:
    value = evaluate(candidate(tmp_path))
    assert value["status"] == "PASS"
    assert policy(value, "G04")["facts"]["tests_passed"] == 18
    command = policy(value, "G03")["facts"]["ast_commands"][0]
    assert command["stdout_truncated"] is False
    assert len(command["stdout"].encode()) < 200_000


def test_real_a2_first_attempt_fails_exactly_four_semantic_cases(tmp_path: Path) -> None:
    flawed = PHONE_CPP.replace(
        "digits.size() != 10 || digits[0] < '2' || digits[3] < '2'",
        "digits.size() != 10 || digits[0] == '0' || digits[3] == '0'",
    )
    value = evaluate(candidate(tmp_path, flawed))
    assert value["status"] == "FAIL"
    g04 = policy(value, "G04")
    assert (g04["reason"], g04["facts"]["tests_passed"], g04["facts"]["tests_total"]) == (
        "SEMANTIC_FAIL", 14, 18,
    )


def test_early_exit_zero_cannot_false_pass_g04(tmp_path: Path) -> None:
    attack = PHONE_CPP.replace(
        '#include <stdexcept>',
        '#include <stdexcept>\n#include <cstdlib>\nnamespace { struct Stop { Stop() { ::_Exit(0); } } stop; }',
    )
    value = evaluate(candidate(tmp_path, attack))
    assert value["status"] == "FAIL"
    g04 = policy(value, "G04")
    assert (g04["status"], g04["reason"]) == ("FAIL", "SEMANTIC_FAIL")
    assert g04["facts"]["tests_passed"] == 0


def test_forged_generic_count_cannot_false_pass_g04(tmp_path: Path) -> None:
    attack = PHONE_CPP.replace(
        '#include <stdexcept>',
        '#include <stdexcept>\n#include <cstdio>\n#include <cstdlib>\n'
        'namespace { struct Stop { Stop() { std::fputs("tests_passed=18/18\\n", stdout); '
        'std::fflush(stdout); ::_Exit(0); } } stop; }',
    )
    value = evaluate(candidate(tmp_path, attack))
    assert value["status"] == "FAIL"
    assert policy(value, "G04")["reason"] == "SEMANTIC_FAIL"


def test_forged_authenticated_marker_plus_exit_cannot_pass(tmp_path: Path) -> None:
    attack = PHONE_CPP.replace(
        '#include <stdexcept>',
        '#include <stdexcept>\n#include <cstdio>\n#include <cstdlib>\n'
        'namespace { struct Stop { Stop() { std::fputs('
        '"GV2_PHONE_FIXED26_V2_RESULT passed=18 total=18\\n", stdout); '
        'std::fflush(stdout); ::_Exit(0); } } stop; }',
    )
    value = evaluate(candidate(tmp_path, attack))
    g04 = policy(value, "G04")
    assert value["status"] == "FAIL"
    assert g04["status"] == "FAIL"
    assert g04["reason"] == "SEMANTIC_FAIL"
    assert g04["facts"]["run"]["returncode"] == 0
    assert g04["facts"]["tests_passed"] == 0
    assert "GV2_PHONE_FIXED26_V2_RESULT" in g04["facts"]["run"]["stdout"]


def test_private_constructor_is_targeted_api_failure(tmp_path: Path) -> None:
    private = PHONE_HEADER.replace(
        "class phone_number {\npublic:\n    phone_number(const std::string& text);",
        "class phone_number {\nprivate:\n    phone_number(const std::string& text);\npublic:",
    )
    value = evaluate(candidate(tmp_path, header=private))
    assert policy(value, "G02")["status"] == "PASS"
    assert (policy(value, "G03")["status"], policy(value, "G03")["reason"]) == (
        "FAIL", "API_FAIL",
    )


def test_wrong_const_is_targeted_api_failure(tmp_path: Path) -> None:
    header = PHONE_HEADER.replace("std::string number() const;", "std::string number();")
    cpp = PHONE_CPP.replace("std::string phone_number::number() const", "std::string phone_number::number()")
    value = evaluate(candidate(tmp_path, cpp, header))
    assert (policy(value, "G03")["status"], policy(value, "G03")["reason"]) == (
        "FAIL", "API_FAIL",
    )


def test_warning_promoted_by_werror_is_classified_separately(tmp_path: Path) -> None:
    cpp = PHONE_CPP.replace(
        "std::string phone_number::number() const { return digits_; }",
        "std::string phone_number::number() const { int unused = 1; return digits_; }",
    )
    value = evaluate(candidate(tmp_path, cpp))
    assert (policy(value, "G02")["status"], policy(value, "G02")["reason"]) == (
        "FAIL", "WARNING_FAIL",
    )


def test_reconstruction_inherits_omitted_file_and_handles_glm_protocol(tmp_path: Path) -> None:
    response = "reasoning</think>src/phone_number.cpp\n```cpp\n" + PHONE_CPP + "```<|user|>"
    value = reconstruction.reconstruct(
        BUNDLE / "starter", tmp_path / "out", ["phone_number.h", "phone_number.cpp"],
        response=response,
    )
    assert value.returned_files == ["phone_number.cpp"]
    assert value.inherited_files == ["phone_number.h"]
    assert value.format_valid is False
    assert (value.root / "phone_number.h").read_bytes() == (BUNDLE / "starter/phone_number.h").read_bytes()


def test_reconstruction_rejects_unauthorized_and_duplicate_files(tmp_path: Path) -> None:
    with pytest.raises(reconstruction.ReconstructionError) as unauthorized:
        reconstruction.reconstruct(
            BUNDLE / "starter", tmp_path / "bad", ["phone_number.h", "phone_number.cpp"],
            response="CMakeLists.txt\n```\nchanged\n```\n",
        )
    assert unauthorized.value.reason == "UNAUTHORIZED_FILE"
    duplicate = "phone_number.h\n```\nA\n```\nphone_number.h\n```\nB\n```\n"
    with pytest.raises(reconstruction.ReconstructionError) as repeated:
        reconstruction.reconstruct(
            BUNDLE / "starter", tmp_path / "dup", ["phone_number.h", "phone_number.cpp"],
            response=duplicate,
        )
    assert repeated.value.reason == "DUPLICATE_FILE"


def test_mediator_prompt_matches_canonical_aider_builder(tmp_path: Path) -> None:
    exercise = tmp_path / "phone-number"
    (exercise / ".docs").mkdir(parents=True)
    shutil.copy2(BUNDLE / "instructions.md", exercise / ".docs/instructions.md")
    for name in ("phone_number.h", "phone_number.cpp"):
        shutil.copy2(BUNDLE / "starter" / name, exercise / name)
    expected = build_aider_messages(exercise, ["phone_number.h", "phone_number.cpp"])
    assert mediator.build_prompt(binding()).messages == expected


def test_receipt_digest_detects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    payload = {"schema_version": 2, "status": "PASS"}
    payload["receipt_sha256"] = receipt_module.receipt_sha256(payload)
    path.write_text(json.dumps(payload))
    assert receipt_module.read_verified(path)["status"] == "PASS"
    payload["status"] = "FAIL"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="digest mismatch"):
        receipt_module.read_verified(path)


def test_invalid_scores_are_group_neutralized_without_changing_audit_reward() -> None:
    records = [
        {"rollout_id": "r", "problem_id": "p", "score": 1.0, "reward": 1.0},
        {"rollout_id": "r", "problem_id": "p", "score": 0.0, "reward": 0.0},
        {"rollout_id": "r", "problem_id": "p", "score": 0.0, "reward": 0.0},
        {"rollout_id": "r", "problem_id": "p", "score": 0.0, "reward": 0.0,
         "infrastructure_error": True},
    ]
    mediator.neutralize_infrastructure_scores(records)
    assert records[-1]["score"] == pytest.approx(1 / 3)
    assert records[-1]["reward"] == 0.0
    assert records[-1]["score_neutralized"] is True


def test_docker_command_uses_nonroot_identity_and_read_only_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected = tmp_path / "asset.txt"
    protected.write_text("fixed")
    captured = {}

    def fake_run(command, cwd, limits, env=None):
        captured["command"] = list(command)
        return sandbox_module.CommandResult(tuple(command), 0, "", "", 0.0,
                                            False, None, False, False)

    monkeypatch.setattr(sandbox_module, "run_host", fake_run)
    sandbox_module.run_docker(
        ["true"], tmp_path,
        "example.invalid/verifier@sha256:" + "1" * 64,
        sandbox_module.Limits(), read_only_paths=["asset.txt"],
    )
    command = captured["command"]
    assert command[command.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    assert mounts[0].endswith("dst=/workspace") and not mounts[0].endswith(",rw")
    assert mounts[1].endswith("dst=/workspace/asset.txt,readonly")
    assert "--network=none" in command and "--cap-drop=ALL" in command


def test_reward_batch_uses_bounded_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_score(item, registry, *, executor, invalid_retries, **retry_metadata):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"score": 1.0, "reward": 1.0, "rollout_id": "r", "problem_id": "p"}

    monkeypatch.setattr(mediator, "_settings", lambda: (object(), "host", 0))
    monkeypatch.setattr(mediator, "score_sample", fake_score)
    monkeypatch.setenv(mediator.WORKERS_ENV, "3")
    values = asyncio.run(mediator.reward_func(None, [{} for _ in range(32)]))
    assert len(values) == 32
    assert 1 < peak <= 3



def test_extra_defaulted_constructor_parameter_is_exact_api_failure(tmp_path: Path) -> None:
    header = PHONE_HEADER.replace(
        "phone_number(const std::string& text);",
        "phone_number(const std::string& text, int ignored = 0);",
    )
    cpp = PHONE_CPP.replace(
        "phone_number::phone_number(const std::string& text) {",
        "phone_number::phone_number(const std::string& text, int ignored) {\n    (void)ignored;",
    )
    value = evaluate(candidate(tmp_path, cpp, header))
    assert policy(value, "G02")["status"] == "PASS"
    g03 = policy(value, "G03")
    assert (g03["status"], g03["reason"]) == ("FAIL", "API_FAIL")
    observed = g03["facts"]["declaration_mismatches"][0]["observed"]
    assert observed[0]["parameter_count"] == 2
    assert observed[0]["default_argument_count"] == 1


def test_conversion_operator_must_remain_explicit(tmp_path: Path) -> None:
    header = PHONE_HEADER.replace(
        "explicit operator std::string() const;", "operator std::string() const;",
    )
    value = evaluate(candidate(tmp_path, PHONE_CPP, header))
    assert (policy(value, "G03")["status"], policy(value, "G03")["reason"]) == (
        "FAIL", "API_FAIL",
    )


def test_plaintext_official_test_is_unavailable_to_candidate_preprocessing(tmp_path: Path) -> None:
    guarded = PHONE_CPP.replace(
        '#include "phone_number.h"',
        '#include "phone_number.h"\n#if __has_include("official_tests.cpp")\n'
        '#error "hidden official test leaked into candidate preprocessing"\n#endif',
    )
    value = evaluate(candidate(tmp_path, guarded))
    assert value["status"] == "PASS"
    g04 = policy(value, "G04")
    assert g04["facts"]["authoritative"] is True
    assert g04["facts"]["oracle"]["asset"] == "official_cases.json.gz"
    assert g04["facts"]["trust_boundary"] == "python-compares-raw-observations-v1"
    assert g04["facts"]["oracle"]["request_count"] == 18
    assert g04["facts"]["oracle"]["aggregate_request_bytes"] < 128 * 1024
    assert not (BUNDLE / "official_tests.cpp").exists()
    assert not (BUNDLE / "official_cases.json").exists()


def test_raw_exit_group_with_exact_marker_cannot_false_pass(tmp_path: Path) -> None:
    attack = PHONE_CPP.replace(
        '#include <stdexcept>',
        '#include <stdexcept>\n#include <cstdio>\n#include <sys/syscall.h>\n#include <unistd.h>\n'
        'namespace { struct Stop { Stop() { std::fputs('
        '"GV2_PHONE_FIXED26_V2_RESULT passed=18 total=18\\n", stdout); '
        'std::fflush(stdout); (void)::syscall(SYS_exit_group, 0); } } stop; }',
    )
    value = evaluate(candidate(tmp_path, attack))
    g04 = policy(value, "G04")
    assert value["status"] == "FAIL"
    assert (g04["status"], g04["reason"]) == ("FAIL", "SEMANTIC_FAIL")
    assert g04["facts"]["tests_passed"] == 0
    assert g04["facts"]["run"]["returncode"] == 0
    assert "passed=18 total=18" in g04["facts"]["run"]["stdout"]


def test_candidate_completion_artifact_forgery_cannot_pass(tmp_path: Path) -> None:
    attack = PHONE_CPP.replace(
        '#include <stdexcept>',
        '#include <stdexcept>\n#include <cstdio>\n#include <fcntl.h>\n'
        '#include <sys/syscall.h>\n#include <unistd.h>\n'
        'namespace { struct Stop { Stop() { '
        'const int fd = ::open("verification_receipt.json", O_CREAT | O_TRUNC | O_WRONLY, 0600); '
        'if (fd >= 0) { static constexpr char forged[] = '
        '"GV2_SUPERVISOR_COMPLETION_V1 handshake=1 child_rc=0 nonce=forged reason=ok\\n"; '
        '(void)::write(fd, forged, sizeof(forged) - 1); (void)::close(fd); } '
        'std::fputs("GV2_PHONE_FIXED26_V2_RESULT passed=18 total=18\\n", stdout); '
        'std::fflush(stdout); (void)::syscall(SYS_exit_group, 0); } } stop; }',
    )
    value = evaluate(candidate(tmp_path, attack))
    g04 = policy(value, "G04")
    assert value["status"] == "FAIL"
    assert (g04["status"], g04["reason"]) == ("FAIL", "SEMANTIC_FAIL")
    assert g04["facts"]["tests_passed"] == 0
    assert g04["facts"]["run"]["returncode"] == 0



def test_full_fixed_fd_handshake_and_marker_spoof_cannot_pass(tmp_path: Path) -> None:
    attack = PHONE_CPP.replace(
        '#include <stdexcept>',
        '#include <stdexcept>\n#include <cstdio>\n#include <string>\n'
        '#include <sys/syscall.h>\n#include <unistd.h>\n'
        'namespace { struct Stop { Stop() { '
        'static constexpr char ready[] = "READY 0\\n"; '
        '(void)::write(198, ready, sizeof(ready) - 1); '
        'char bytes[128] = {}; const ssize_t count = ::read(199, bytes, sizeof(bytes)); '
        'if (count > 0) { const std::string challenge(bytes, static_cast<std::size_t>(count)); '
        'if (challenge.rfind("CHALLENGE ", 0) == 0) { '
        'const std::string done = "DONE " + challenge.substr(10, 64) + " 0\\n"; '
        '(void)::write(198, done.data(), done.size()); } } '
        'std::fputs("GV2_PHONE_FIXED26_V2_RESULT passed=18 total=18\\n", stdout); '
        'std::fflush(stdout); (void)::syscall(SYS_exit_group, 0); } } stop; }',
    )
    value = evaluate(candidate(tmp_path, attack))
    g04 = policy(value, "G04")
    assert value["status"] == "FAIL"
    assert (g04["status"], g04["reason"]) == ("FAIL", "SEMANTIC_FAIL")
    assert g04["facts"]["tests_passed"] == 0
    assert g04["facts"]["trust_boundary"] == "python-compares-raw-observations-v1"



def test_correct_observations_plus_trailing_forged_marker_cannot_get_pass_score(
    tmp_path: Path,
) -> None:
    attack = PHONE_CPP.replace(
        '#include <stdexcept>',
        '#include <stdexcept>\n#include <cstdio>\n'
        'namespace { struct Tail { ~Tail() { '
        'std::fputs("GV2_PHONE_FIXED26_V2_RESULT passed=18 total=18\\n", stdout); '
        '} } tail; }',
    )
    value = evaluate(candidate(tmp_path, attack))
    g04 = policy(value, "G04")
    assert value["status"] == "FAIL"
    assert (g04["status"], g04["reason"]) == ("FAIL", "SEMANTIC_FAIL")
    assert g04["facts"]["tests_passed"] == 18
    assert g04["facts"]["output_cardinality_ok"] is False
    assert g04["facts"]["score"] == pytest.approx(17 / 18)
    assert g04["facts"]["score"] < 1.0
