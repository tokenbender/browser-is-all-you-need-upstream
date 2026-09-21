#!/usr/bin/env python3





















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
    pass
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
    pass
    if isinstance(value, str) and value:

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
    pass








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
    pass
    for line in stdout_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("VERDICT:", "STATUS:")):
            return stripped
    return f"verifier exited with status '{status}'"


def run_with_receipt(receipt_dir, impl, args, argv=None):
    pass






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
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 2
        except Exception as exc:
            print(f"receipt_compat: verifier raised {exc!r}",
                  file=stderr_buffer)
            exit_code = 2
    duration = round(time.monotonic() - started, 6)

    stdout_text = stdout_buffer.getvalue()
    stderr_text = stderr_buffer.getvalue()

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
            "stdout_tail": stdout_text[-4000:],
            "stderr_tail": stderr_text[-4000:],
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
