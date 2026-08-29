






from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

from glm47_posttraining.aider_polyglot.dataset import (
    SOURCE_MANIFEST_KIND,
    build_aider_polyglot_datasets,
)
from glm47_posttraining.aider_polyglot.harness import run_sandbox_preflight
from glm47_posttraining.aider_polyglot.schema import AiderShadowRubric
from glm47_posttraining.integrations.miles_aider_polyglot import (
    neutralize_infrastructure_scores,
)
from glm47_posttraining.integrations.miles_aider_polyglot import (
    reward_func as aider_reward_func,
)
from glm47_posttraining.integrations.miles_aider_polyglot import (
    run_response_contract_preflight,
)


CURRICULUM_NAME = "phone-number-v1"
DATASET_KIND = "aider-polyglot-cpp-shadow-grpo"
POLYGLOT_COMMIT = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
VERIFICATION_GATE = "phone-number-strange-12-independent-kernel-gcc13-v1"
EDITABLE_FILES = ["phone_number.h", "phone_number.cpp"]
HIDDEN_TEST = "phone_number_hidden_test.cpp"
POLICY_IDS = ["PH-E01", "PH-E02", "PH-E03", "PH-E04"]
KERNEL_IDS = (
    "PH-E01-A",
    "PH-E01-B",
    "PH-E01-C",
    "PH-E02-A",
    "PH-E02-B",
    "PH-E02-C",
    "PH-E03-A",
    "PH-E03-B",
    "PH-E03-C",
    "PH-E04-A",
    "PH-E04-B",
    "PH-E04-C",
)
KERNEL_COUNT = len(KERNEL_IDS)
KERNEL_RECEIPT_RE = re.compile(
    r"GLM47_PHONE_KERNELS_V1:([01]{12})\nGLM47_AIDER_PASS_[0-9a-f]{32}"
)


INSTRUCTIONS = r"""# Phone Number

Clean North American Numbering Plan telephone numbers. Ignore only ordinary
formatting characters: spaces, parentheses, plus, hyphen, and period. Reject
letters, other punctuation, an incorrect number of digits, an eleven-digit
number whose country code is not 1, and numbers whose area or exchange code
starts with 0 or 1. Invalid input throws `std::domain_error`.

The public C++17 interface is exact:

```cpp
namespace phone_number {
class phone_number {
public:
    phone_number(const std::string& text);
    std::string area_code() const;
    std::string number() const;
    explicit operator std::string() const;
};
}
```

`number()` returns the cleaned ten digits, `area_code()` returns the first
three digits, and the explicit string conversion returns `(NXX) NXX-XXXX`.
Only `phone_number.h` and `phone_number.cpp` are editable. The build uses
C++17 with `-Wall -Wextra -Wpedantic -Werror`. Do not modify or attempt to
inspect the hidden verifier.
"""


EXACT_HEADER = r"""#pragma once

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
"""


EMPTY_HEADER = r"""#pragma once

namespace phone_number {
}
"""


EMPTY_SOURCE = r"""#include "phone_number.h"

namespace phone_number {
}
"""


BASE_SOURCE = r"""#include "phone_number.h"

#include <cctype>
#include <stdexcept>

namespace {

bool allowed_separator(char value) {
    return value == ' ' || value == '(' || value == ')' || value == '+' ||
           value == '-' || value == '.';
}

std::string clean_number(const std::string& text) {
    std::string digits;
    for (const char value : text) {
        const auto byte = static_cast<unsigned char>(value);
        if (std::isdigit(byte)) {
            digits.push_back(value);
            continue;
        }
        if (!allowed_separator(value)) {
            throw std::domain_error("invalid phone-number character");
        }
    }

    if (digits.size() == 11) {
        if (digits.front() != '1') {
            throw std::domain_error("invalid country code");
        }
        digits.erase(digits.begin());
    }
    if (digits.size() != 10) {
        throw std::domain_error("invalid phone-number length");
    }
    if (digits[0] < '2' || digits[3] < '2') {
        throw std::domain_error("invalid NANP prefix");
    }
    return digits;
}

}  // namespace

namespace phone_number {

phone_number::phone_number(const std::string& text)
    : digits_(clean_number(text)) {}

std::string phone_number::area_code() const { return digits_.substr(0, 3); }

std::string phone_number::number() const { return digits_; }

phone_number::operator std::string() const {
    return "(" + digits_.substr(0, 3) + ") " + digits_.substr(3, 3) +
           "-" + digits_.substr(6, 4);
}

}  // namespace phone_number
"""


def _replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError("Phone Number fixture mutation target is not unique")
    return source.replace(old, new, 1)


BAD_PREFIX_SOURCE = _replace_once(
    BASE_SOURCE,
    """    if (digits[0] < '2' || digits[3] < '2') {
        throw std::domain_error(\"invalid NANP prefix\");
    }
""",
    "",
)


BAD_CHARACTER_SOURCE = _replace_once(
    BASE_SOURCE,
    """        if (!allowed_separator(value)) {
            throw std::domain_error(\"invalid phone-number character\");
        }
""",
    """        static_cast<void>(allowed_separator(value));
""",
)


BAD_LENGTH_SOURCE = _replace_once(
    BASE_SOURCE,
    """    if (digits.size() == 11) {
        if (digits.front() != '1') {
            throw std::domain_error(\"invalid country code\");
        }
        digits.erase(digits.begin());
    }
    if (digits.size() != 10) {
        throw std::domain_error(\"invalid phone-number length\");
    }
""",
    """    if (digits.size() < 10) {
        throw std::domain_error(\"invalid phone-number length\");
    }
    if (digits.size() > 10) {
        digits = digits.substr(digits.size() - 10);
    }
""",
)


BAD_COUNTRY_SOURCE = _replace_once(
    BASE_SOURCE,
    """        if (digits.front() != '1') {
            throw std::domain_error(\"invalid country code\");
        }
        digits.erase(digits.begin());
""",
    """        digits.erase(digits.begin());
""",
)


BAD_FORMAT_SOURCE = _replace_once(
    BASE_SOURCE,
    """    return \"(\" + digits_.substr(0, 3) + \") \" + digits_.substr(3, 3) +
           \"-\" + digits_.substr(6, 4);
""",
    """    return digits_;
""",
)


COLLIDING_HEADER = r"""#pragma once

#include <string>

namespace phone_number {

class phone_number {
public:
    phone_number(const std::string& text);
    std::string area_code() const;
    std::string number() const;
    explicit operator std::string() const;

private:
    std::string number;
};

}  // namespace phone_number
"""


HIDDEN_TEST_SOURCE = r"""#include "phone_number.h"

#include <array>
#include <iostream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

using Phone = phone_number::phone_number;

static_assert(std::is_constructible_v<Phone, const std::string&>);
static_assert(std::is_same_v<decltype(std::declval<const Phone&>().area_code()),
                             std::string>);
static_assert(std::is_same_v<decltype(std::declval<const Phone&>().number()),
                             std::string>);
static_assert(std::is_same_v<
              decltype(static_cast<std::string>(std::declval<const Phone&>())),
              std::string>);
static_assert(!std::is_convertible_v<const Phone&, std::string>);

template <typename Function>
bool guarded(Function&& function) {
    try {
        return static_cast<bool>(function());
    } catch (...) {
        return false;
    }
}

bool accepts(const std::string& text, const std::string& digits) {
    const Phone value(text);
    return value.number() == digits && value.area_code() == digits.substr(0, 3) &&
           static_cast<std::string>(value) ==
               "(" + digits.substr(0, 3) + ") " + digits.substr(3, 3) +
                   "-" + digits.substr(6, 4);
}

bool rejects(const std::string& text) {
    try {
        const Phone value(text);
        static_cast<void>(value);
    } catch (const std::domain_error&) {
        return true;
    } catch (...) {
        return false;
    }
    return false;
}

bool rejects_all(const std::initializer_list<const char*>& values) {
    for (const char* value : values) {
        if (!rejects(value)) return false;
    }
    return true;
}

int main() {
    std::array<bool, 12> kernels{};

    kernels[0] = guarded([] { return accepts("2234567890", "2234567890"); });
    kernels[1] = guarded([] {
        const Phone value("2234567890");
        return value.area_code() == "223" && value.number() == "2234567890";
    });
    kernels[2] = guarded([] {
        return accepts("1 (223) 456-7890", "2234567890");
    });

    kernels[3] = guarded([] {
        return accepts("+1 (223) 456-7890", "2234567890") &&
               accepts("223.456.7890", "2234567890");
    });
    kernels[4] = guarded([] {
        return rejects_all({"123456789", "22234567890", "223-abc-7890",
                            "223-@:!-7890"});
    });
    kernels[5] = guarded([] {
        return rejects_all({"0234567890", "1234567890", "2230567890",
                            "2231567890", "10234567890", "12230567890"});
    });

    kernels[6] = guarded([] {
        return accepts("223 456   7890", "2234567890") &&
               accepts("+1-999-999-9999", "9999999999");
    });
    kernels[7] = guarded([] {
        return static_cast<std::string>(Phone("2234567890")) ==
               "(223) 456-7890";
    });
    kernels[8] = guarded([] {
        return rejects_all({"", "321234567890", "22234567890",
                            "22345678900", "223@:!4567890"});
    });

    kernels[9] = guarded([] {
        const Phone value("2234567890");
        return value.number() == "2234567890" && value.area_code() == "223" &&
               static_cast<std::string>(value) == "(223) 456-7890";
    });
    kernels[10] = guarded([] {
        return accepts("223.456.7890", "2234567890") &&
               accepts("+1 (223) 456-7890", "2234567890") &&
               accepts("223 456   7890", "2234567890");
    });
    kernels[11] = guarded([] {
        return rejects_all({"123456789", "22234567890", "321234567890",
                            "123-abc-7890", "123-@:!-7890", "0234567890",
                            "1234567890", "2230567890", "2231567890",
                            "10234567890", "12230567890"});
    });

    std::cout << "GLM47_PHONE_KERNELS_V1:";
    for (const bool passed : kernels) std::cout << (passed ? '1' : '0');
    std::cout << '\n';
    return 0;
}
"""


EPISODES = (
    ("full-solve", "missing-public-api", EMPTY_HEADER, EMPTY_SOURCE, ""),
    (
        "missing-definitions-repair",
        "declared-members-not-defined",
        EXACT_HEADER,
        EMPTY_SOURCE,
        "The linker reports unresolved Phone Number constructor and observer definitions.",
    ),
    (
        "nanp-prefix-repair",
        "area-and-exchange-prefixes-not-validated",
        EXACT_HEADER,
        BAD_PREFIX_SOURCE,
        "Area and exchange codes beginning with 0 or 1 must throw std::domain_error.",
    ),
    (
        "character-validation-repair",
        "letters-and-forbidden-punctuation-ignored",
        EXACT_HEADER,
        BAD_CHARACTER_SOURCE,
        "Letters and punctuation other than ordinary phone formatting must be rejected.",
    ),
    (
        "length-partition-repair",
        "overlong-input-silently-truncated",
        EXACT_HEADER,
        BAD_LENGTH_SOURCE,
        "Only ten digits, or eleven digits beginning with country code 1, are valid.",
    ),
    (
        "country-code-repair",
        "any-eleven-digit-country-code-accepted",
        EXACT_HEADER,
        BAD_COUNTRY_SOURCE,
        "An eleven-digit number is valid only when its first digit is 1.",
    ),
    (
        "formatting-repair",
        "string-conversion-returns-bare-digits",
        EXACT_HEADER,
        BAD_FORMAT_SOURCE,
        "The explicit string conversion must return the exact `(NXX) NXX-XXXX` format.",
    ),
    (
        "eval-feedback-repair",
        "observed-member-function-name-collision",
        COLLIDING_HEADER,
        EMPTY_SOURCE,
        "Observed evaluation failure: a private data member named `number` collided with the public `number()` member function, so the header did not compile.",
    ),
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_task_root(root: Path) -> Path:
    practice = root / "cpp" / "exercises" / "practice"
    hidden_hash = _sha256_text(HIDDEN_TEST_SOURCE)
    task_ids: list[str] = []
    for episode_kind, signature, header, source, feedback in EPISODES:
        task_id = f"phone-number--{episode_kind}"
        task_ids.append(task_id)
        exercise = practice / task_id
        docs = exercise / ".docs"
        docs.mkdir(parents=True)
        task_instructions = INSTRUCTIONS
        if feedback:
            task_instructions += f"\n\n## Executed failure evidence\n\n{feedback}\n"
        (docs / "instructions.md").write_text(task_instructions, encoding="utf-8")
        (exercise / "phone_number.h").write_text(header, encoding="utf-8")
        (exercise / "phone_number.cpp").write_text(source, encoding="utf-8")
        (exercise / HIDDEN_TEST).write_text(HIDDEN_TEST_SOURCE, encoding="utf-8")
        (exercise / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.16)\nproject(phone_number LANGUAGES CXX)\n",
            encoding="utf-8",
        )
        rubric = AiderShadowRubric(
            task_id=task_id,
            split="train",
            editable_files=EDITABLE_FILES,
            hidden_test_file=HIDDEN_TEST,
            hidden_test_sha256=hidden_hash,
            source_prompt_sha256=_sha256_text(task_instructions),
            reference_answer_packaged=False,
            verification_stage="passed",
            verification_gate=VERIFICATION_GATE,
            family="phone-number",
            category="phone-number-strange",
            lineage_id="fixed26/phone-number",
            episode_kind=episode_kind,
            objective_group="phone-number-strange",
            failure_signature=signature,
            tags=[
                "official-task-training-authorized",
                "whole-file-action",
                "strange-kernel-reward",
                *POLICY_IDS,
            ],
        )
        (exercise / ".rubric.json").write_text(
            rubric.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    manifest = {
        "kind": SOURCE_MANIFEST_KIND,
        "schema_version": 1,
        "source_locator": (
            f"official:Aider-AI/polyglot-benchmark@{POLYGLOT_COMMIT}/phone-number"
        ),
        "counts": {"tasks": len(task_ids), "train": len(task_ids), "validation": 0},
        "task_ids": task_ids,
        "contract": {
            "official_task_id_overlap": ["phone-number"],
            "official_training_authorized": True,
            "reference_answers_packaged": False,
            "shared_hidden_tests_within_lineage": True,
            "verifier_policy_ids": POLICY_IDS,
            "kernel_count": KERNEL_COUNT,
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root


def build_data(args: argparse.Namespace) -> dict[str, Path]:
    if args.curriculum not in (None, CURRICULUM_NAME):
        raise ValueError(f"unsupported curriculum: {args.curriculum}")
    with TemporaryDirectory(prefix="phone-number-strange-tasks-") as temporary:
        task_root = _write_task_root(Path(temporary))
        return build_aider_polyglot_datasets(
            task_root,
            args.out,
            train_limit=args.train_limit,
            monitor_limit=args.eval_limit or len(EPISODES),
            profile=args.profile,
            run_id=args.run_id,
            sort_by_size=args.sort_by_size,
            force=args.force,
        )


def _invalid_kernel_reward(record: dict[str, Any], reason: str) -> dict[str, Any]:
    record["verifier_pack"] = "phone-number-strange-v1"
    record["verifier_policy_ids"] = POLICY_IDS
    record["verification_gate"] = VERIFICATION_GATE
    record["kernel_results"] = [
        {"kernel_id": kernel_id, "kernel": None, "status": "invalid"}
        for kernel_id in KERNEL_IDS
    ]
    record["policy_results"] = [
        {"policy_id": policy_id, "kernel_sum": None, "status": "invalid"}
        for policy_id in POLICY_IDS
    ]
    record["kernel_sum"] = None
    record["kernel_total"] = KERNEL_COUNT
    record["kernel_status"] = "invalid"
    record["kernel_receipt_error"] = reason
    record["infrastructure_error"] = True
    record["reward"] = 0.0
    record["score"] = 0.0
    return record


def _extract_kernel_bits(record: dict[str, Any]) -> str | None:
    logs = record.get("logs")
    if not isinstance(logs, dict):
        return None
    test_log = logs.get("test")
    if not isinstance(test_log, str):
        return None
    matches = KERNEL_RECEIPT_RE.findall(test_log)
    return matches[-1] if matches else None


def _apply_kernel_reward(record: dict[str, Any]) -> dict[str, Any]:
    record["verifier_pack"] = "phone-number-strange-v1"
    record["verifier_policy_ids"] = POLICY_IDS
    record["verification_gate"] = VERIFICATION_GATE
    if record.get("infrastructure_error"):
        return _invalid_kernel_reward(
            record, "underlying sandbox infrastructure error"
        )

    bits = _extract_kernel_bits(record)
    if bits is None:
        if record.get("all_tests_pass"):
            return _invalid_kernel_reward(
                record,
                "hidden verifier passed without an authenticated kernel receipt",
            )
        bits = "0" * KERNEL_COUNT

    kernel_values = [1 if value == "1" else -1 for value in bits]
    passed = sum(value == 1 for value in kernel_values)
    failed = KERNEL_COUNT - passed
    kernel_sum = sum(kernel_values)
    record["kernel_results"] = [
        {
            "kernel_id": kernel_id,
            "kernel": value,
            "status": "pass" if value == 1 else "fail",
        }
        for kernel_id, value in zip(KERNEL_IDS, kernel_values, strict=True)
    ]
    record["kernel_bits"] = bits
    record["policy_results"] = [
        {
            "policy_id": policy_id,
            "kernel_sum": sum(kernel_values[index : index + 3]),
            "status": (
                "pass"
                if all(value == 1 for value in kernel_values[index : index + 3])
                else "fail"
            ),
        }
        for policy_id, index in zip(
            POLICY_IDS, range(0, KERNEL_COUNT, 3), strict=True
        )
    ]
    record["kernel_passed"] = passed
    record["kernel_failed"] = failed
    record["kernel_sum"] = kernel_sum
    record["kernel_total"] = KERNEL_COUNT
    record["kernel_status"] = "pass" if passed == KERNEL_COUNT else "fail"
    record["tests_passed"] = passed
    record["tests_total"] = KERNEL_COUNT
    record["all_tests_pass"] = passed == KERNEL_COUNT
    record["reason"] = "passed" if passed == KERNEL_COUNT else "kernel_tests_failed"
    record["reward"] = kernel_sum / KERNEL_COUNT
    record["score"] = record["reward"]
    return record


async def reward_func(
    args: Any, sample: Any, **kwargs: Any
) -> dict[str, Any] | list[dict[str, Any]]:
    os.environ.setdefault("MILES_CPP_INCLUDE_LOGS", "1")
    result = await aider_reward_func(args, sample, **kwargs)
    if isinstance(result, list):
        records = [_apply_kernel_reward(record) for record in result]
        return neutralize_infrastructure_scores(records)
    return _apply_kernel_reward(result)


def preflight() -> None:
    run_response_contract_preflight()
    run_sandbox_preflight()
    with TemporaryDirectory(prefix="phone-number-strange-preflight-") as temporary:
        root = Path(temporary)
        args = argparse.Namespace(
            curriculum=CURRICULUM_NAME,
            out=root / "data",
            train_limit=None,
            eval_limit=None,
            profile="phone-number-preflight",
            run_id="phone-number-preflight",
            sort_by_size=False,
            force=True,
        )
        paths = build_data(args)
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        if (
            manifest.get("kind") != DATASET_KIND
            or manifest["counts"]["train"] != len(EPISODES)
        ):
            raise RuntimeError("Phone Number dataset preflight produced an invalid manifest")
    synthetic = _apply_kernel_reward(
        {
            "all_tests_pass": True,
            "infrastructure_error": False,
            "logs": {
                "test": (
                    "GLM47_PHONE_KERNELS_V1:101010101010\n"
                    "GLM47_AIDER_PASS_0123456789abcdef0123456789abcdef\n"
                )
            },
        }
    )
    if synthetic["kernel_sum"] != 0 or synthetic["kernel_passed"] != 6:
        raise RuntimeError("independent Phone Number kernel receipt preflight failed")
    print("PHONE_NUMBER_STRANGE_REWARD_READY")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-data")
    build.add_argument("--tasks-dir", required=True)
    build.add_argument("--out", required=True, type=Path)
    build.add_argument("--curriculum", choices=[CURRICULUM_NAME])
    build.add_argument("--train-limit", type=int)
    build.add_argument("--eval-limit", type=int)
    build.add_argument("--eval-splits", default="validation,test")
    build.add_argument("--profile", default="phone-number-strange-grpo")
    build.add_argument("--run-id")
    build.add_argument("--sort-by-size", action="store_true")
    build.add_argument("--filter-train-oracle-full-marks", action="store_true")
    build.add_argument("--oracle-filter-workers", type=int, default=8)
    build.add_argument("--allow-non-gcc-curriculum", action="store_true")
    build.add_argument("--force", action="store_true")
    subparsers.add_parser("preflight")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "preflight":
        preflight()
        return
    if args.filter_train_oracle_full_marks:
        raise ValueError("the Phone Number curriculum is already verifier-bound")
    paths = build_data(args)
    print(
        json.dumps(
            {key: str(value) for key, value in paths.items()},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
