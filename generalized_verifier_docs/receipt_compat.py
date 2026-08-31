#!/usr/bin/env python3
"""receipt_compat -- wrap any check-layer verifier verdict into the sandbox
runner's kernel-receipt JSON shape.

Each receipt carries one kernel {kernel_id, kernel (1|-1|None), status
(pass|fail|invalid), summary, facts, command, duration_seconds,
stdout_log, stderr_log} and binds the run to its inputs via sha256
(verifier source hash, input file hashes, stdout/stderr hashes, timing,
exit code). Runner exit-code convention: 0 = pass, 1 = fail, 2 = invalid.

Imported by the check-layer verifiers when invoked with --receipt DIR;
each writes <verifier>_kernel_receipt.json into DIR. No task names are
hardcoded -- inputs are discovered generically from the parsed CLI
arguments.

Usage (from a verifier's main)::

    if args.receipt:
        import receipt_compat
        return receipt_compat.run_with_receipt(args.receipt, run, args, argv)
"""

import contextlib
import hashlib
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

SCHEMA_VERSION = 2
RECEIPT_FORMAT = "check-layer-kernel-receipt/1"

# CLI argument names that are outputs, never inputs, when scanning parsed
# arguments for files to bind by hash.
_OUTPUT_ARG_NAMES = {"receipt", "out_dir", "o", "output", "output_dir"}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_path(path):
    value = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            value.update(chunk)
    return value.hexdigest()


def dir_manifest_sha256(path):
    """Hash a directory as a sorted (relpath, file-sha256) manifest."""
    entries = []
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, path)
            if os.path.isfile(full) and not os.path.islink(full):
                entries.append((rel, sha256_path(full)))
    payload = json.dumps(entries, sort_keys=True).encode("utf-8")
    return sha256_bytes(payload), len(entries)


def _candidate_input_values(value):
    """Yield plausible input path strings from one argparse value."""
    if isinstance(value, str) and value:
        # Handle NAME=PATH specs (e.g. a --template NAME=PATH option).
        if "=" in value and not os.path.exists(value):
            _, _, tail = value.partition("=")
            if tail:
                yield tail
        else:
            yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _candidate_input_values(item)


def input_bindings(args, exclude_dir=None):
    """Walk the parsed CLI namespace and hash every existing input path.

    Returns (file_hashes, dir_manifests) where file_hashes maps the argument
    value (as given on the command line) to its sha256, and dir_manifests
    maps directory arguments to {"manifest_sha256", "file_count"}. Values
    that do not resolve to an existing file/directory (flags, counts,
    editable-file *names*) are ignored. Options named in _OUTPUT_ARG_NAMES
    and anything under exclude_dir are skipped.
    """
    file_hashes = {}
    dir_manifests = {}
    exclude = os.path.abspath(exclude_dir) if exclude_dir else None
    for name, value in sorted(vars(args).items()):
        if name in _OUTPUT_ARG_NAMES:
            continue
        for candidate in _candidate_input_values(value):
            if not os.path.exists(candidate):
                continue
            full = os.path.abspath(candidate)
            if exclude and (full == exclude or full.startswith(exclude + os.sep)):
                continue
            if os.path.isfile(candidate):
                file_hashes.setdefault(candidate, sha256_path(candidate))
            elif os.path.isdir(candidate):
                if candidate not in dir_manifests:
                    manifest, count = dir_manifest_sha256(candidate)
                    dir_manifests[candidate] = {
                        "manifest_sha256": manifest, "file_count": count}
    return file_hashes, dir_manifests


def _verifier_name():
    return os.path.splitext(os.path.basename(sys.argv[0]))[0]


def _summarize(status, stdout_text):
    """One-sentence summary: prefer the verifier's own VERDICT/STATUS line."""
    for line in stdout_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("VERDICT:", "STATUS:")):
            return stripped
    return f"verifier exited with status '{status}'"


def run_with_receipt(receipt_dir, impl, args, argv=None):
    """Run impl(args) with stdout/stderr captured, replay stdout, and write
    the kernel receipt into receipt_dir.

    impl is the verifier's own worker (returns 0 pass / 1 fail / 2 invalid).
    Returns impl's exit code, so caller behavior is unchanged apart from the
    extra receipt file.
    """
    argv = list(sys.argv if argv is None else argv)
    command = [sys.executable, *argv]
    os.makedirs(receipt_dir, exist_ok=True)

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    started = time.monotonic()
    with contextlib.redirect_stdout(stdout_buffer), \
            contextlib.redirect_stderr(stderr_buffer):
        try:
            exit_code = impl(args)
        except SystemExit as exc:  # a verifier may sys.exit() internally
            exit_code = exc.code if isinstance(exc.code, int) else 2
        except Exception as exc:  # noqa: BLE001 -- crash => invalid kernel
            print(f"receipt_compat: verifier raised {exc!r}",
                  file=stderr_buffer)
            exit_code = 2
    duration = round(time.monotonic() - started, 6)

    stdout_text = stdout_buffer.getvalue()
    stderr_text = stderr_buffer.getvalue()
    # Replay so `--receipt` never silences the verifier's normal output.
    if stdout_text:
        sys.stdout.write(stdout_text)
    if stderr_text:
        sys.stderr.write(stderr_text)

    status = {0: "pass", 1: "fail"}.get(exit_code, "invalid")
    kernel_value = {"pass": 1, "fail": -1, "invalid": None}[status]

    file_hashes, dir_manifests = input_bindings(args, exclude_dir=receipt_dir)
    verifier_path = os.path.abspath(sys.argv[0])
    verifier_name = _verifier_name()
    policy_id = verifier_name.upper().replace("_", "-")

    kernel = {
        "kernel_id": f"{policy_id}-A",
        "kernel": kernel_value,
        "status": status,
        "summary": _summarize(status, stdout_text),
        "facts": {
            "exit_code": exit_code,
            "stdout_sha256": sha256_bytes(stdout_text.encode("utf-8")),
            "stderr_sha256": sha256_bytes(stderr_text.encode("utf-8")),
            "stdout_bytes": len(stdout_text.encode("utf-8")),
            "stderr_bytes": len(stderr_text.encode("utf-8")),
        },
        "command": command,
        "duration_seconds": duration,
        "stdout_log": None,
        "stderr_log": None,
    }
    numeric = kernel_value if kernel_value in (-1, 1) else None
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_format": RECEIPT_FORMAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy_id": policy_id,
        "verifier": os.path.basename(sys.argv[0]),
        "verifier_source_sha256": sha256_path(verifier_path),
        "status": status,
        "kernel_results": [kernel],
        "kernel_sum": numeric,
        "maximum_kernel_sum": 1,
        "exit_code": exit_code,
        "duration_seconds": duration,
        "command": command,
        "stdout_sha256": kernel["facts"]["stdout_sha256"],
        "stderr_sha256": kernel["facts"]["stderr_sha256"],
        "stdout_bytes": kernel["facts"]["stdout_bytes"],
        "stderr_bytes": kernel["facts"]["stderr_bytes"],
        "input_sha256": file_hashes,
        "input_dir_manifests": dir_manifests,
    }
    if status == "invalid":
        # Match the runner's convention: an invalid receipt carries no
        # numeric kernel sum and its maximum equals the numeric-kernel count.
        receipt["kernel_sum"] = None
        receipt["maximum_kernel_sum"] = 0

    receipt_path = os.path.join(
        receipt_dir, f"{verifier_name}_kernel_receipt.json")
    with open(receipt_path, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"receipt: wrote {receipt_path} (status={status}, "
          f"kernel={kernel_value})", file=sys.stderr)
    return exit_code
