"""Task-independent command sandbox with deterministic resource receipts."""

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path, PurePath
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Limits:
    timeout_s: int = 120
    memory_mb: int = 2048
    pids: int = 128
    cpus: float = 2.0
    output_bytes: int = 1_000_000


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool
    launch_error: str | None
    stdout_truncated: bool
    stderr_truncated: bool
    launch_error_kind: str | None = None


class _BoundedCapture:
    """Drain a pipe completely while retaining at most the configured limit."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._data = bytearray()
        self.truncated = False

    def drain(self, stream: object) -> None:
        reader = getattr(stream, "read")
        while True:
            chunk = reader(64 * 1024)
            if not chunk:
                return
            remaining = self._limit - len(self._data)
            if remaining > 0:
                self._data.extend(chunk[:remaining])
            if len(chunk) > max(remaining, 0):
                self.truncated = True

    def text(self) -> str:
        return bytes(self._data).decode("utf-8", "replace")


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            pass


_OCI_EXECUTABLE_MISSING = re.compile(
    r"(?:executable file .*?not found in \$PATH"
    r"|failed to (?:create task|start container process).*?exec:.*?no such file or directory"
    r"|OCI runtime.*?(?:command|executable).*?not found)",
    re.IGNORECASE | re.DOTALL,
)


def executable_missing(result: CommandResult) -> bool:
    """Return whether the requested workload executable was unavailable."""
    if result.launch_error_kind in {
        "HOST_EXECUTABLE_MISSING", "OCI_EXECUTABLE_MISSING",
    }:
        return True
    return bool(_OCI_EXECUTABLE_MISSING.search(f"{result.stderr}\n{result.stdout}"))


def run_host(
    command: Sequence[str], cwd: Path, limits: Limits, env: Mapping[str, str] | None = None
) -> CommandResult:
    """Execute an argument array; intended for tests and already-isolated workers."""
    if not command or not all(isinstance(value, str) and value for value in command):
        raise ValueError("command must be a non-empty argument array")
    if limits.timeout_s <= 0 or limits.output_bytes < 0:
        raise ValueError("timeout_s must be positive and output_bytes non-negative")
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            list(command), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "LANG": "C", **(env or {})},
            start_new_session=True,
        )
    except FileNotFoundError as error:
        return CommandResult(
            tuple(command), None, "", "", time.monotonic() - started, False,
            f"{type(error).__name__}: {error}", False, False,
            "HOST_EXECUTABLE_MISSING",
        )
    except OSError as error:
        return CommandResult(
            tuple(command), None, "", "", time.monotonic() - started, False,
            f"{type(error).__name__}: {error}", False, False, "HOST_LAUNCH_ERROR",
        )

    assert process.stdout is not None and process.stderr is not None
    stdout = _BoundedCapture(limits.output_bytes)
    stderr = _BoundedCapture(limits.output_bytes)
    readers = [
        threading.Thread(target=stdout.drain, args=(process.stdout,), daemon=True),
        threading.Thread(target=stderr.drain, args=(process.stderr,), daemon=True),
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        process.wait(timeout=limits.timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(process)
        process.wait()
    finally:
        for reader in readers:
            reader.join()
        process.stdout.close()
        process.stderr.close()
    return CommandResult(
        tuple(command), None if timed_out else process.returncode,
        stdout.text(), stderr.text(), time.monotonic() - started, timed_out, None,
        stdout.truncated, stderr.truncated,
    )


def _container_name(
    workspace: Path, image: str, command: Sequence[str], limits: Limits,
    env: Mapping[str, str] | None, read_only_paths: Sequence[str],
) -> str:
    identity = hashlib.sha256()
    values = [
        str(workspace), image, *command,
        str(limits.timeout_s), str(limits.memory_mb), str(limits.pids),
        str(limits.cpus), str(limits.output_bytes), *sorted(read_only_paths),
        *(f"{key}={value}" for key, value in sorted((env or {}).items())),
    ]
    for value in values:
        identity.update(value.encode("utf-8"))
        identity.update(b"\0")
    return f"gv2-{identity.hexdigest()[:24]}"


def _cleanup_container(docker: str, name: str, workspace: Path, limits: Limits) -> None:
    cleanup_limits = Limits(
        timeout_s=max(1, min(limits.timeout_s, 10)),
        memory_mb=limits.memory_mb,
        pids=limits.pids,
        cpus=limits.cpus,
        output_bytes=min(limits.output_bytes, 16_384),
    )
    # Always attempt both operations. docker kill may trigger --rm before the
    # explicit removal, in which case the second command harmlessly fails.
    run_host([docker, "kill", name], workspace, cleanup_limits)
    run_host([docker, "rm", "--force", name], workspace, cleanup_limits)


def run_docker(
    command: Sequence[str], workspace: Path, image: str, limits: Limits,
    *, docker: str = "docker", env: Mapping[str, str] | None = None,
    read_only_paths: Sequence[str] = (),
) -> CommandResult:
    """Run a command in a locked-down, networkless container."""
    if not command or not all(isinstance(value, str) and value for value in command):
        raise ValueError("command must be a non-empty argument array")
    if not image or any(character.isspace() for character in image):
        raise ValueError("a safe pinned container image is required")
    workspace = workspace.resolve(strict=True)
    name = _container_name(workspace, image, command, limits, env, read_only_paths)
    args = [
        docker, "run", "--rm", "--name", name, "--network=none", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
        "--read-only",
        f"--memory={limits.memory_mb}m", f"--pids-limit={limits.pids}",
        f"--cpus={limits.cpus}", "--tmpfs=/tmp:rw,exec,nosuid,nodev,size=256m",
        "--mount", f"type=bind,src={workspace},dst=/workspace",
        "--workdir=/workspace",
    ]
    for value in read_only_paths:
        relative = PurePath(value)
        if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
            raise ValueError(f"unsafe read-only mount path: {value}")
        source = (workspace / relative).resolve(strict=True)
        if not source.is_relative_to(workspace):
            raise ValueError(f"read-only mount escapes workspace: {value}")
        args.extend([
            "--mount",
            f"type=bind,src={source},dst=/workspace/{relative.as_posix()},readonly",
        ])
    for key, value in sorted((env or {}).items()):
        args.extend(["--env", f"{key}={value}"])
    args.extend([image, *command])
    result = run_host(args, workspace, limits)
    if result.timed_out:
        _cleanup_container(docker, name, workspace, limits)
    if result.launch_error_kind == "HOST_EXECUTABLE_MISSING":
        return replace(
            result,
            launch_error=f"Docker executable unavailable: {docker}",
            launch_error_kind="DOCKER_EXECUTABLE_MISSING",
        )
    if result.returncode in {125, 126, 127} and executable_missing(result):
        return replace(
            result,
            launch_error=f"OCI executable unavailable: {command[0]}",
            launch_error_kind="OCI_EXECUTABLE_MISSING",
        )
    return result


def result_facts(result: CommandResult) -> dict[str, object]:
    return {
        "command": list(result.command), "returncode": result.returncode,
        "duration_s": round(result.duration_s, 6), "timed_out": result.timed_out,
        "launch_error": result.launch_error,
        "launch_error_kind": result.launch_error_kind,
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        "stdout": result.stdout, "stderr": result.stderr,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
    }
