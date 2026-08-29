from __future__ import annotations

import gzip
import hashlib
import importlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "Reward_GRPO/global_verifiers_set2"
sys.path.insert(0, str(PACKAGE))
sandbox = importlib.import_module("sandbox")
g04 = importlib.import_module("g04_functional")
g02 = importlib.import_module("g02_build")
g05 = importlib.import_module("g05_safety")
g07 = importlib.import_module("g07_portability")


def _result(
    command: list[str] | tuple[str, ...],
    *,
    returncode: int | None = 0,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
    launch_error: str | None = None,
    launch_error_kind: str | None = None,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
) -> Any:
    return sandbox.CommandResult(
        tuple(command), returncode, stdout, stderr, 0.01, timed_out,
        launch_error, stdout_truncated, stderr_truncated, launch_error_kind,
    )


def _functional_manifest() -> dict[str, Any]:
    return {
        "build": {
            "compiler": "primary++",
            "standard": "c++20",
            "flags": ["-Wall"],
            "sources": ["candidate.cpp"],
            "include_dirs": ["include/build"],
            "libraries": ["build-default"],
            "link_args": ["-Wl,--build-default"],
        },
        "functional": {
            "test_sources": ["tests/main.cpp", "tests/cases.cpp"],
            "include_dirs": ["include/functional"],
            "defines": ["GV2_FUNCTIONAL=1"],
            "compile_flags": ["-Wconversion"],
            "libraries": ["functional-support"],
            "link_args": ["-pthread"],
            "run_args": ["--fixture", "fixtures/input.txt"],
            "runtime_assets": ["fixtures/input.txt"],
            "env": {"GV2_FIXTURE": "fixtures/input.txt"},
            "result_regex": (
                r"(?m)^tests_passed=(?P<passed>[0-9]+)/(?P<total>[0-9]+)$"
            ),
            "result_stream": "stderr",
            "expected_total": 2,
        },
        "portability": {"compilers": ["first++", "second++"]},
    }


def _make_functional_workspace(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    manifest = _functional_manifest()
    for name in [
        "candidate.cpp",
        "tests/main.cpp",
        "tests/cases.cpp",
        "fixtures/input.txt",
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name + "\n", encoding="utf-8")
    return tmp_path, manifest


def test_run_host_retains_only_the_bounded_prefix_of_each_stream(tmp_path: Path) -> None:
    script = (
        "import os;"
        "os.write(1, b'o' * 4096);"
        "os.write(2, b'e' * 4096)"
    )
    result = sandbox.run_host(
        [sys.executable, "-c", script],
        tmp_path,
        sandbox.Limits(timeout_s=5, output_bytes=127),
    )

    assert result.returncode == 0
    assert result.stdout == "o" * 127
    assert result.stderr == "e" * 127
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


def test_docker_timeout_uses_deterministic_name_then_kill_and_force_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run_host(
        command: list[str], cwd: Path, limits: Any, env: Any = None
    ) -> Any:
        del cwd, limits, env
        calls.append(list(command))
        if len(calls) == 1:
            return _result(command, returncode=None, timed_out=True, stdout="partial")
        return _result(command)

    monkeypatch.setattr(sandbox, "run_host", fake_run_host)
    limits = sandbox.Limits(timeout_s=17, output_bytes=100)
    result = sandbox.run_docker(
        ["trusted-compiler", "--version"], tmp_path, "image@sha256:" + "a" * 64, limits
    )

    assert result.timed_out is True
    run_command = calls[0]
    name = run_command[run_command.index("--name") + 1]
    assert name == sandbox._container_name(
        tmp_path.resolve(), "image@sha256:" + "a" * 64,
        ["trusted-compiler", "--version"], limits, None, (),
    )
    assert calls[1] == ["docker", "kill", name]
    assert calls[2] == ["docker", "rm", "--force", name]
    assert len(calls) == 3


def test_docker_binary_and_oci_workload_absence_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def docker_missing(command: list[str], *_: Any, **__: Any) -> Any:
        return _result(
            command,
            returncode=None,
            launch_error="FileNotFoundError: docker",
            launch_error_kind="HOST_EXECUTABLE_MISSING",
        )

    monkeypatch.setattr(sandbox, "run_host", docker_missing)
    missing_docker = sandbox.run_docker(
        ["g++", "--version"], tmp_path, "image@sha256:" + "b" * 64,
        sandbox.Limits(),
    )

    def oci_missing(command: list[str], *_: Any, **__: Any) -> Any:
        return _result(
            command,
            returncode=127,
            stderr=(
                'docker: failed to create task for container: '
                'exec: "g++": executable file not found in $PATH'
            ),
        )

    monkeypatch.setattr(sandbox, "run_host", oci_missing)
    missing_compiler = sandbox.run_docker(
        ["g++", "--version"], tmp_path, "image@sha256:" + "b" * 64,
        sandbox.Limits(),
    )

    assert missing_docker.launch_error_kind == "DOCKER_EXECUTABLE_MISSING"
    assert missing_compiler.launch_error_kind == "OCI_EXECUTABLE_MISSING"
    assert missing_docker.launch_error != missing_compiler.launch_error


@pytest.mark.parametrize(
    ("command_result", "expected"),
    [
        (_result(["g++"], returncode=1, stderr="candidate.cpp: error: bad syntax"),
         ("FAIL", "COMPILE_FAIL")),
        (_result(["g++"], returncode=127, stderr="g++: command not found"),
         ("INVALID", "COMPILER_UNAVAILABLE")),
        (_result(["docker"], returncode=None, launch_error="docker missing",
                 launch_error_kind="DOCKER_EXECUTABLE_MISSING"),
         ("INVALID", "BUILD_EXECUTOR_UNAVAILABLE")),
        (_result(["g++"], returncode=None, timed_out=True),
         ("INVALID", "VERIFIER_TIMEOUT")),
    ],
)
def test_g02_separates_candidate_compile_failure_from_trusted_infrastructure(
    tmp_path: Path, command_result: Any, expected: tuple[str, str]
) -> None:
    manifest = {
        "build": {
            "compiler": "g++",
            "standard": "c++17",
            "flags": [],
            "sources": ["candidate.cpp"],
            "include_dirs": ["."],
        }
    }

    def execute(*_: Any, **__: Any) -> Any:
        return command_result

    receipt, _ = g02.verify(
        tmp_path, tmp_path / "artifacts", manifest, execute, sandbox.Limits()
    )
    assert (receipt.status, receipt.reason) == expected


def test_g05_reuses_plural_functional_build_runtime_and_result_contract(
    tmp_path: Path,
) -> None:
    workspace, manifest = _make_functional_workspace(tmp_path)
    calls: list[tuple[list[str], Path, dict[str, str] | None]] = []

    def execute(
        command: list[str], cwd: Path, limits: Any, env: dict[str, str] | None
    ) -> Any:
        del limits
        calls.append((list(command), cwd, env))
        if "-o" in command:
            binary = cwd / command[command.index("-o") + 1]
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("fake binary\n", encoding="utf-8")
            return _result(command)
        assert (cwd / "fixtures/input.txt").read_text() == "fixtures/input.txt\n"
        return _result(command, stderr="tests_passed=2/2\n")

    receipt = g05.verify(workspace, manifest, execute, sandbox.Limits())

    assert (receipt.status, receipt.reason) == ("PASS", "SAFETY_PASS")
    compile_command, _, _ = calls[0]
    assert compile_command[0:2] == ["primary++", "-std=c++20"]
    for argument in [
        "-Wall", "-Wconversion", "-Iinclude/functional",
        "-DGV2_FUNCTIONAL=1", "candidate.cpp", "tests/main.cpp",
        "tests/cases.cpp", "-lfunctional-support", "-pthread",
    ]:
        assert argument in compile_command
    assert "-lbuild-default" not in compile_command
    run_command, run_cwd, run_env = calls[1]
    assert run_command == [
        "./safety_tests", "--fixture", "fixtures/input.txt",
    ]
    assert run_cwd.name == "safety_runtime"
    assert run_env is not None
    assert run_env["GV2_FIXTURE"] == "fixtures/input.txt"
    assert "halt_on_error=1" in run_env["ASAN_OPTIONS"]
    assert receipt.facts["tests_passed"] == receipt.facts["tests_total"] == 2


def test_g05_compiler_rc127_is_invalid_but_candidate_runtime_timeout_is_fail(
    tmp_path: Path,
) -> None:
    workspace, manifest = _make_functional_workspace(tmp_path)

    def missing_compiler(command: list[str], *_: Any, **__: Any) -> Any:
        return _result(command, returncode=127, stderr="primary++: command not found")

    unavailable = g05.verify(
        workspace, manifest, missing_compiler, sandbox.Limits()
    )
    assert (unavailable.status, unavailable.reason) == (
        "INVALID", "SANITIZER_TOOLCHAIN_UNAVAILABLE",
    )

    def timeout_at_runtime(
        command: list[str], cwd: Path, *_: Any, **__: Any
    ) -> Any:
        if "-o" in command:
            binary = cwd / command[command.index("-o") + 1]
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("fake binary\n", encoding="utf-8")
            return _result(command)
        return _result(command, returncode=None, timed_out=True)

    timed_out = g05.verify(
        workspace, manifest, timeout_at_runtime, sandbox.Limits()
    )
    assert (timed_out.status, timed_out.reason) == ("FAIL", "SANITIZER_TIMEOUT")


def test_g07_reuses_plural_functional_build_runtime_and_result_contract(
    tmp_path: Path,
) -> None:
    workspace, manifest = _make_functional_workspace(tmp_path)
    calls: list[tuple[list[str], Path, dict[str, str] | None]] = []

    def execute(
        command: list[str], cwd: Path, limits: Any, env: dict[str, str] | None
    ) -> Any:
        del limits
        calls.append((list(command), cwd, env))
        if "-o" in command:
            binary = cwd / command[command.index("-o") + 1]
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("fake binary\n", encoding="utf-8")
            return _result(command)
        assert (cwd / "fixtures/input.txt").is_file()
        return _result(command, stderr="tests_passed=2/2\n")

    receipt = g07.verify(workspace, manifest, execute, sandbox.Limits())

    assert (receipt.status, receipt.reason) == ("PASS", "PORTABILITY_PASS")
    assert len(calls) == 4
    for compile_command, _, _ in calls[::2]:
        for argument in [
            "-Wall", "-Wconversion", "-Iinclude/functional",
            "-DGV2_FUNCTIONAL=1", "tests/main.cpp", "tests/cases.cpp",
            "-lfunctional-support", "-pthread",
        ]:
            assert argument in compile_command
        assert "-lbuild-default" not in compile_command
    for run_command, run_cwd, run_env in calls[1::2]:
        assert run_command == [
            "./portability_tests", "--fixture", "fixtures/input.txt",
        ]
        assert run_cwd.name.startswith("portability_runtime_")
        assert run_env == {"GV2_FIXTURE": "fixtures/input.txt"}
    assert all(item["tests_total"] == 2 for item in receipt.facts["runs"])


def test_g07_compiler_rc127_is_invalid_but_candidate_runtime_rc127_is_fail(
    tmp_path: Path,
) -> None:
    workspace, manifest = _make_functional_workspace(tmp_path)

    def missing_compiler(command: list[str], *_: Any, **__: Any) -> Any:
        return _result(command, returncode=127, stderr="first++: command not found")

    unavailable = g07.verify(
        workspace, manifest, missing_compiler, sandbox.Limits()
    )
    assert (unavailable.status, unavailable.reason) == (
        "INVALID", "PORTABILITY_TOOLCHAIN_UNAVAILABLE",
    )

    def candidate_exit_127(
        command: list[str], cwd: Path, *_: Any, **__: Any
    ) -> Any:
        if "-o" in command:
            binary = cwd / command[command.index("-o") + 1]
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("fake binary\n", encoding="utf-8")
            return _result(command)
        return _result(command, returncode=127)

    candidate_failure = g07.verify(
        workspace, manifest, candidate_exit_127, sandbox.Limits()
    )
    assert (candidate_failure.status, candidate_failure.reason) == (
        "FAIL", "PORTABILITY_FUNCTIONAL_FAIL",
    )


def _make_external_oracle_workspace(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, Any], list[dict[str, str]]]:
    workspace = tmp_path / "candidate"
    trusted = tmp_path / "trusted"
    workspace.mkdir()
    trusted.mkdir()
    (workspace / ".gv2").mkdir()
    (workspace / "candidate.cpp").write_text(
        "int candidate_value() { return 1; }\n", encoding="utf-8"
    )
    (workspace / "public_probe.cpp").write_text(
        "int main() { return 0; }\n", encoding="utf-8"
    )
    cases = [
        {"id": "visible-request-0", "request": "request-alpha", "expected": "SECRET-A"},
        {"id": "visible-request-1", "request": "request-beta", "expected": "SECRET-B"},
    ]
    oracle = json.dumps(
        {"schema_version": 1, "cases": cases}, sort_keys=True
    ).encode()
    oracle_payload = gzip.compress(oracle)
    (trusted / "official_cases.json.gz").write_bytes(oracle_payload)
    manifest = {
        "protected_files": {
            "public_probe.cpp": hashlib.sha256(
                (workspace / "public_probe.cpp").read_bytes()
            ).hexdigest(),
            "official_cases.json.gz": hashlib.sha256(oracle_payload).hexdigest(),
        },
        "build": {
            "compiler": "primary++",
            "standard": "c++20",
            "flags": ["-Wall"],
            "sources": ["candidate.cpp"],
            "include_dirs": ["."],
            "defines": [],
            "libraries": [],
            "link_args": [],
        },
        "functional": {
            "mode": "external_oracle_v1",
            "bridge_sources": ["public_probe.cpp"],
            "bridge_source_encoding": "plain",
            "bridge_compile_flags": ["-Wexternal-bridge"],
            "include_dirs": ["."],
            "defines": ["GV2_EXTERNAL_PROBE=1"],
            "libraries": [],
            "link_args": [],
            "runtime_assets": [],
            "env": {"PUBLIC_PROBE_ENV": "1"},
            "oracle_cases": "official_cases.json.gz",
            "oracle_cases_encoding": "gzip",
            "expected_total": len(cases),
        },
        "portability": {"compilers": ["first++", "second++"]},
    }
    return workspace, trusted, manifest, cases


def _external_executor(
    workspace: Path,
    trusted: Path,
    cases: list[dict[str, str]],
    calls: list[tuple[list[str], Path, dict[str, str] | None]],
    events: list[str],
) -> Any:
    expected_values = [case["expected"] for case in cases]

    def execute(
        command: list[str], cwd: Path, limits: Any, env: dict[str, str] | None
    ) -> Any:
        del limits
        command_copy = list(command)
        calls.append((command_copy, cwd, env))
        assert cwd.resolve() != trusted.resolve()
        assert not (workspace / "official_cases.json.gz").exists()
        candidate_view = json.dumps(
            {"command": command_copy, "env": env}, sort_keys=True
        )
        assert str(trusted) not in candidate_view
        assert all(expected not in candidate_view for expected in expected_values)

        if "-o" in command_copy:
            output = workspace / command_copy[command_copy.index("-o") + 1]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("fake binary\n", encoding="utf-8")
            if output.name == "candidate_probe":
                events.append("probe_frozen")
            else:
                events.append("candidate_compiled")
            return _result(command_copy)

        events.append("probe_run")
        assert cwd == workspace / ".gv2/external_runtime"
        assert command_copy == [
            "./candidate_probe", *(case["request"] for case in cases),
        ]
        assert sorted(path.name for path in cwd.iterdir()) == ["candidate_probe"]
        stdout = "".join(
            f"{index}\t{case['expected']}\n"
            for index, case in enumerate(cases)
        )
        return _result(command_copy, stdout=stdout)

    return execute


def test_g05_external_oracle_loads_expected_values_only_after_probe_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, trusted, manifest, cases = _make_external_oracle_workspace(tmp_path)
    calls: list[tuple[list[str], Path, dict[str, str] | None]] = []
    events: list[str] = []
    original_load = g04._load_oracle_cases

    def tracked_load(*args: Any, **kwargs: Any) -> Any:
        events.append("oracle_loaded")
        return original_load(*args, **kwargs)

    monkeypatch.setattr(g04, "_load_oracle_cases", tracked_load)
    receipt = g05.verify(
        workspace,
        manifest,
        _external_executor(workspace, trusted, cases, calls, events),
        sandbox.Limits(),
        trusted_assets=trusted,
    )

    assert (receipt.status, receipt.reason) == ("PASS", "SAFETY_PASS")
    assert receipt.facts["authoritative"] is True
    assert receipt.facts["functional"]["trusted_assets_isolated"] is True
    assert receipt.facts["functional"]["oracle"]["asset"] == "official_cases.json.gz"
    assert events == [
        "candidate_compiled", "probe_frozen", "oracle_loaded", "probe_run",
    ]
    candidate_compile, probe_compile = calls[0][0], calls[1][0]
    assert "-fsanitize=address,undefined" in candidate_compile
    assert "-fsanitize=address,undefined" in probe_compile
    assert "-Wexternal-bridge" in probe_compile
    for path in [
        ".gv2/probe_sources", ".gv2/external_runtime", ".gv2/candidate_probe",
    ]:
        assert not (workspace / path).exists()


def test_g07_external_oracle_repeats_authoritative_probe_per_toolchain(
    tmp_path: Path,
) -> None:
    workspace, trusted, manifest, cases = _make_external_oracle_workspace(tmp_path)
    calls: list[tuple[list[str], Path, dict[str, str] | None]] = []
    events: list[str] = []
    receipt = g07.verify(
        workspace,
        manifest,
        _external_executor(workspace, trusted, cases, calls, events),
        sandbox.Limits(),
        trusted_assets=trusted,
    )

    assert (receipt.status, receipt.reason) == ("PASS", "PORTABILITY_PASS")
    assert receipt.facts["authoritative"] is True
    assert len(receipt.facts["runs"]) == 2
    assert all(run["authoritative"] is True for run in receipt.facts["runs"])
    assert events == [
        "candidate_compiled", "probe_frozen", "probe_run",
        "candidate_compiled", "probe_frozen", "probe_run",
    ]
    build_commands = [command for command, _, _ in calls if "-o" in command]
    assert [command[0] for command in build_commands] == [
        "first++", "first++", "second++", "second++",
    ]
    assert all(
        "-Wexternal-bridge" in command
        for command in build_commands
        if command[command.index("-o") + 1] == ".gv2/candidate_probe"
    )
    for path in [
        ".gv2/probe_sources", ".gv2/external_runtime", ".gv2/candidate_probe",
    ]:
        assert not (workspace / path).exists()


@pytest.mark.parametrize(
    ("module", "reason"),
    [
        pytest.param(g05, "EXTERNAL_ORACLE_SAFETY_NOT_READY", id="g05"),
        pytest.param(g07, "EXTERNAL_ORACLE_PORTABILITY_NOT_READY", id="g07"),
    ],
)
def test_external_optional_policies_require_unstaged_separate_trusted_oracle(
    tmp_path: Path, module: Any, reason: str,
) -> None:
    workspace, trusted, manifest, _ = _make_external_oracle_workspace(tmp_path)
    calls: list[list[str]] = []

    def execute(command: list[str], *_: Any, **__: Any) -> Any:
        calls.append(command)
        return _result(command)

    missing_root = module.verify(
        workspace, manifest, execute, sandbox.Limits()
    )
    shutil.copy2(
        trusted / "official_cases.json.gz",
        workspace / "official_cases.json.gz",
    )
    staged_oracle = module.verify(
        workspace, manifest, execute, sandbox.Limits(), trusted_assets=trusted
    )

    assert (missing_root.status, missing_root.reason) == ("INVALID", reason)
    assert (staged_oracle.status, staged_oracle.reason) == ("INVALID", reason)
    assert calls == []


@pytest.mark.parametrize(
    ("module", "reason"),
    [
        pytest.param(g05, "SAFETY_MODE_NOT_READY", id="g05"),
        pytest.param(g07, "PORTABILITY_MODE_NOT_READY", id="g07"),
    ],
)
def test_optional_policies_reject_demoted_fixed_fd_handshake_without_execution(
    tmp_path: Path, module: Any, reason: str,
) -> None:
    workspace, trusted, manifest, _ = _make_external_oracle_workspace(tmp_path)
    manifest["functional"]["mode"] = "opaque_bridge_v1"
    calls: list[list[str]] = []

    def execute(command: list[str], *_: Any, **__: Any) -> Any:
        calls.append(command)
        return _result(command)

    receipt = module.verify(
        workspace, manifest, execute, sandbox.Limits(), trusted_assets=trusted
    )

    assert (receipt.status, receipt.reason) == ("INVALID", reason)
    assert calls == []
