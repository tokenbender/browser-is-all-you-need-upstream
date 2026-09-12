#!/usr/bin/env python3
"""Run positive and negative controls for every generalized verifier.

The check creates a tiny C++ task, candidate responses, and compiler logs in
a temporary directory. Each verifier is exercised through its public CLI,
including JSON output and receipt generation, so a clean checkout needs no
committed benchmark fixture bundle.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


VERIFIER_DIR = Path(__file__).resolve().parents[1]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def create_inputs(root):
    fixture = root / "fixture"
    candidates = root / "candidates"
    responses = root / "responses"
    logs = root / "logs"

    header = """#pragma once
namespace demo {
int add(int left, int right);
int multiply(int left, int right);
}
"""
    good_source = """#include "arithmetic.h"
namespace demo {
int add(int left, int right) { return left + right; }
int multiply(int left, int right) { return left * right; }
}
"""
    write(fixture / ".meta" / "example.h", header)
    write(fixture / ".meta" / "example.cpp", good_source)
    write(fixture / "arithmetic_test.cpp", """#include "arithmetic.h"
#include <utility>
std::pair<int, int> run_tests() {
    int passed = 0;
    constexpr int total = 4;
    passed += demo::add(2, 3) == 5;
    passed += demo::add(-2, 2) == 0;
    passed += demo::multiply(2, 3) == 6;
    passed += demo::multiply(-2, 3) == -6;
    return {passed, total};
}
""")
    write(fixture / "test" / "tests-main.cpp", """#include <iostream>
#include <utility>
std::pair<int, int> run_tests();
int main() {
    const auto [passed, total] = run_tests();
    if (passed == total) {
        std::cout << "All tests passed (" << total
                  << " assertions in 1 test case)\\n";
        return 0;
    }
    std::cout << "----------------------------------------\\n"
              << "arithmetic semantics\\n"
              << "----------------------------------------\\n"
              << "assertions: " << total << " | " << passed
              << " passed | " << total - passed << " failed\\n";
    return 1;
}
""")

    write(candidates / "good.h", header)
    write(candidates / "good.cpp", good_source)
    write(candidates / "foreign.h", """#pragma once
namespace foreign { int add(int, int); int multiply(int, int); }
""")
    write(candidates / "foreign.cpp", """#include "foreign.h"
namespace foreign {
int add(int left, int right) { return left + right; }
int multiply(int left, int right) { return left * right; }
}
""")
    write(candidates / "link_fail.h", header)
    write(candidates / "link_fail.cpp", """#include "arithmetic.h"
namespace demo { int add(int left, int right) { return left + right; } }
""")
    write(candidates / "semantic_fail.h", header)
    write(candidates / "semantic_fail.cpp", """#include "arithmetic.h"
namespace demo {
int add(int left, int right) { return left + right; }
int multiply(int left, int right) { return left + right; }
}
""")
    write(candidates / "unsafe.h", header)
    write(candidates / "unsafe.cpp", """#include "arithmetic.h"
namespace demo {
int add(int left, int right) { return left + right; }
int multiply(int left, int right) {
    int* values = new int[1];
    values[0] = left * right;
    volatile int result = values[1];
    delete[] values;
    return result;
}
}
""")

    complete = """arithmetic.h
```cpp
#pragma once
namespace demo { int add(int, int); int multiply(int, int); }
```

arithmetic.cpp
```cpp
#include "arithmetic.h"
namespace demo {
int add(int left, int right) { return left + right; }
int multiply(int left, int right) { return left * right; }
}
```
"""
    write(responses / "complete.txt", complete)
    write(responses / "truncated.txt", complete.rsplit("```", 1)[0])
    write(responses / "forbidden.txt", """notes.md
```markdown
This file is outside the editable candidate boundary.
```
""")
    write(logs / "clean.txt", "")
    write(
        logs / "unused_parameter.txt",
        "candidate.cpp:3:19: error: unused parameter 'value' "
        "[-Werror=unused-parameter]\n",
    )
    return {
        "fixture": fixture,
        "good_h": candidates / "good.h",
        "good_cpp": candidates / "good.cpp",
        "foreign_h": candidates / "foreign.h",
        "foreign_cpp": candidates / "foreign.cpp",
        "link_h": candidates / "link_fail.h",
        "link_cpp": candidates / "link_fail.cpp",
        "semantic_h": candidates / "semantic_fail.h",
        "semantic_cpp": candidates / "semantic_fail.cpp",
        "unsafe_h": candidates / "unsafe.h",
        "unsafe_cpp": candidates / "unsafe.cpp",
        "complete": responses / "complete.txt",
        "truncated": responses / "truncated.txt",
        "forbidden": responses / "forbidden.txt",
        "clean_log": logs / "clean.txt",
        "warning_log": logs / "unused_parameter.txt",
    }


def cases(inputs):
    fixture = str(inputs["fixture"])
    return [
        ("G01 positive", "01_structural_api_gate.py", 0, '"passed": true', [
            "--test", f"{fixture}/arithmetic_test.cpp", "--header",
            str(inputs["good_h"]), "--source", str(inputs["good_cpp"])]),
        ("G01 missing API", "01_structural_api_gate.py", 1, '"passed": false', [
            "--test", f"{fixture}/arithmetic_test.cpp", "--header",
            str(inputs["foreign_h"]), "--source", str(inputs["foreign_cpp"])]),
        ("G02 clean build", "03_two_stage_build_verifier.py", 0,
         '"status": "PASS"', ["--fixture-dir", fixture, "--header",
                              str(inputs["good_h"]), "--source",
                              str(inputs["good_cpp"])]),
        ("G02 linker attribution", "03_two_stage_build_verifier.py", 1,
         '"status": "LE"', ["--fixture-dir", fixture, "--header",
                            str(inputs["link_h"]), "--source",
                            str(inputs["link_cpp"])]),
        ("G03 reference parity", "04_differential_semantic_verifier.py", 0,
         '"verdict": "PASS"', ["--fixture-dir", fixture, "--header",
                               str(inputs["good_h"]), "--source",
                               str(inputs["good_cpp"])]),
        ("G03 semantic regression", "04_differential_semantic_verifier.py", 1,
         '"score": 0.5', ["--fixture-dir", fixture, "--header",
                          str(inputs["semantic_h"]), "--source",
                          str(inputs["semantic_cpp"])]),
        ("G04 complete response", "05_response_integrity_verifier.py", 0,
         '"verdict": "OK"', ["--response", str(inputs["complete"])]),
        ("G04 truncated response", "05_response_integrity_verifier.py", 1,
         '"verdict": "TRUNCATED"', ["--response", str(inputs["truncated"])]),
        ("G05 editable boundary", "06_candidate_boundary_verifier.py", 0,
         '"status": "OK"', ["--response", str(inputs["complete"]),
                            "--editable", "arithmetic.h", "--editable",
                            "arithmetic.cpp"]),
        ("G05 forbidden file", "06_candidate_boundary_verifier.py", 1,
         '"kind": "FORBIDDEN_FILE"', ["--response", str(inputs["forbidden"]),
                                      "--editable", "arithmetic.h",
                                      "--editable", "arithmetic.cpp"]),
        ("G06 clean diagnostics", "07_warning_hygiene_classifier.py", 0,
         '"verdict": "PASS"', ["--stderr", str(inputs["clean_log"])]),
        ("G06 compiler error", "07_warning_hygiene_classifier.py", 1,
         '"class": "unused-parameter"', ["--stderr",
                                         str(inputs["warning_log"])]),
        ("G07 sanitizer clean", "08_safety_sanitizer_verifier.py", 0,
         '"verdict": "CLEAN"', ["--fixture-dir", fixture, "--header",
                                str(inputs["good_h"]), "--source",
                                str(inputs["good_cpp"]), "--timeout-seconds", "10"]),
        ("G07 sanitizer finding", "08_safety_sanitizer_verifier.py", 1,
         '"verdict": "SANITIZER_HIT"', ["--fixture-dir", fixture, "--header",
                                        str(inputs["unsafe_h"]), "--source",
                                        str(inputs["unsafe_cpp"]),
                                        "--timeout-seconds", "10"]),
    ]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_case(root, name, verifier, expected_exit, expected_text, argv):
    receipt_dir = root / "receipts" / name.replace(" ", "_").lower()
    command = [sys.executable, str(VERIFIER_DIR / verifier), *argv,
               "--json", "--receipt", str(receipt_dir)]
    completed = subprocess.run(
        command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=60,
    )
    receipt_path = receipt_dir / f"{Path(verifier).stem}_kernel_receipt.json"
    failures = []
    if completed.returncode != expected_exit:
        failures.append(f"exit {completed.returncode}, expected {expected_exit}")
    if expected_text not in completed.stdout:
        failures.append(f"stdout missing {expected_text!r}")
    if not receipt_path.is_file():
        failures.append("receipt was not written")
    else:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected_status = "pass" if expected_exit == 0 else "fail"
        if receipt.get("status") != expected_status:
            failures.append(
                f"receipt status {receipt.get('status')!r}, expected {expected_status!r}")
        if receipt.get("verifier_source_sha256") != sha256(VERIFIER_DIR / verifier):
            failures.append("receipt does not bind the verifier source")
    return failures, completed


def execute(root):
    inputs = create_inputs(root)
    failed = 0
    all_cases = cases(inputs)
    for name, verifier, expected_exit, expected_text, argv in all_cases:
        failures, completed = run_case(
            root, name, verifier, expected_exit, expected_text, argv)
        if failures:
            failed += 1
            print(f"FAIL {name}: {'; '.join(failures)}")
            if completed.stdout:
                print(completed.stdout.rstrip())
            if completed.stderr:
                print(completed.stderr.rstrip(), file=sys.stderr)
        else:
            print(f"PASS {name}")
    print(f"\n{len(all_cases) - failed}/{len(all_cases)} controls passed")
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Self-contained positive/negative controls for G01-G07")
    parser.add_argument(
        "--work-dir", type=Path,
        help="keep generated inputs and receipts in this directory")
    args = parser.parse_args(argv)

    if args.work_dir:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        return execute(args.work_dir.resolve())
    with tempfile.TemporaryDirectory(prefix="generalized-verifiers-") as tmp:
        return execute(Path(tmp))


if __name__ == "__main__":
    sys.exit(main())
