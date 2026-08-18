"""Build exact-task drill packs for the five remaining fixed26 mid-band tasks.

Measured reward density on Synth-v1 epoch 50 (32 samples/episode, thinking
enabled, temperature 0.7, response ceiling 8192, strict official GCC 13 reward):

    allergies        6 episodes  57.3% pass  6/6 groups mixed  0 infra-invalid
    grade-school     3 episodes  53.1% pass  3/3 groups mixed  0 infra-invalid
    perfect-numbers  5 episodes  50.6% pass  5/5 groups mixed  0 infra-invalid
    sublist          3 episodes  33.3% pass  3/3 groups mixed  0 infra-invalid
    diamond          5 episodes  46.3% pass  5/5 groups mixed  0 infra-invalid

Diamond is accepted with a recorded exception: its truncation rate is 7.5%
(12/160) against the 5% ceiling the other four families clear. The truncation
concentrates in the ``full-solve`` and ``test-feedback-filled-interior``
episodes, where the glyph geometry consumes the thinking budget. Reward density
itself is sound, so the pack is retained as-is rather than narrowed further.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Mapping

from .dataset import DATASET_KIND, build_aider_messages, write_jsonl
from .schema import AiderPolyglotTask


CURRICULUM_NAME = "midband-official-drill-v1"
CURRICULUM_ID = "fixed26-midband-exact-task-rl-v1"
POLYGLOT_COMMIT = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
VERIFICATION_GATE = "fixed26-midband-official-gcc13-v1"
TASKS = ("allergies", "diamond", "grade-school", "perfect-numbers", "sublist")

PASS_RE = re.compile(
    r"All tests passed \(\s*\d+ assertions? in\s*(\d+) test cases?\)", re.I
)
FAIL_RE = re.compile(
    r"test cases:\s*(\d+)\s*\|\s*(\d+) passed\s*\|\s*(\d+) failed", re.I
)


@dataclass(frozen=True)
class TaskSpec:
    task: str
    stem: str
    editable_files: tuple[str, str]
    contract: str


@dataclass(frozen=True)
class Evaluation:
    stage: str
    tests_passed: int
    tests_total: int
    diagnostic: str = ""


@dataclass(frozen=True)
class Episode:
    family: str
    episode_kind: str
    failure_signature: str
    starter: Mapping[str, str]
    target: Mapping[str, str]
    instructions: str
    expected_stage: str


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _replace_once(value: str, old: str, new: str, label: str) -> str:
    if value.count(old) != 1:
        raise ValueError(f"{label}: expected one mutation anchor, found {value.count(old)}")
    return value.replace(old, new, 1)


def _mutate(files: Mapping[str, str], name: str, transform: Callable[[str], str]) -> dict[str, str]:
    result = dict(files)
    result[name] = transform(result[name])
    return result


def _feedback(instructions: str, diagnostic: str) -> str:
    return (
        instructions.rstrip()
        + "\n\n## Executed failure evidence\n\n"
        + "The supplied implementation produced this output under the declared GCC contract:\n\n"
        + "```text\n"
        + diagnostic.rstrip()
        + "\n```\n\nFix the implementation. The hidden tests and build contract are correct.\n"
    )


CONTRACTS = {
    "allergies": """
## C++ interface contract

The test file is not shown to you, so the interface it expects is stated here in
full. Implement exactly these names and signatures; the tests use nothing else.

```cpp
namespace allergies {
class allergy_test {
public:
    allergy_test(unsigned int test_result);
    bool is_allergic_to(std::string const& allergen) const;
    std::unordered_set<std::string> get_allergies() const;
};
}
```

## Build environment

- The exercise is compiled as C++17 with `-Wall -Wextra -Wpedantic -Werror`, so
  any warning fails the build.
- Only `allergies.h` and `allergies.cpp` are editable. `CMakeLists.txt` and the test
  file are fixed and must not be modified.
- The test file includes only `allergies.h`, so every name above must be visible
  from that header.
- You may either declare in `allergies.h` and define in `allergies.cpp`, or define
  everything `inline`/in-class in `allergies.h` and leave `allergies.cpp` unchanged.
  Both are accepted.
""",
    "diamond": """
## C++ interface contract

The test file is not shown to you, so the interface it expects is stated here in
full. Implement exactly these names and signatures; the tests use nothing else.

```cpp
namespace diamond {
std::vector<std::string> rows(char middle_letter);
}
```

Each returned row is a full square line: leading and trailing padding included, so every string has the same length.

## Build environment

- The exercise is compiled as C++17 with `-Wall -Wextra -Wpedantic -Werror`, so
  any warning fails the build.
- Only `diamond.h` and `diamond.cpp` are editable. `CMakeLists.txt` and the test
  file are fixed and must not be modified.
- The test file includes only `diamond.h`, so every name above must be visible
  from that header.
- You may either declare in `diamond.h` and define in `diamond.cpp`, or define
  everything `inline`/in-class in `diamond.h` and leave `diamond.cpp` unchanged.
  Both are accepted.
""",
    "grade-school": """
## C++ interface contract

The test file is not shown to you, so the interface it expects is stated here in
full. Implement exactly these names and signatures; the tests use nothing else.

```cpp
namespace grade_school {
class school {
public:
    const std::map<int, std::vector<std::string>>& roster() const;
    void add(std::string const& name, int grade);
    std::vector<std::string> grade(int grade) const;
};
}
```

Names within a grade are sorted alphabetically, and `roster()` is keyed by grade in ascending order. `grade()` on an unknown grade returns an empty vector.

## Build environment

- The exercise is compiled as C++17 with `-Wall -Wextra -Wpedantic -Werror`, so
  any warning fails the build.
- Only `grade_school.h` and `grade_school.cpp` are editable. `CMakeLists.txt` and the test
  file are fixed and must not be modified.
- The test file includes only `grade_school.h`, so every name above must be visible
  from that header.
- You may either declare in `grade_school.h` and define in `grade_school.cpp`, or define
  everything `inline`/in-class in `grade_school.h` and leave `grade_school.cpp` unchanged.
  Both are accepted.
""",
    "perfect-numbers": """
## C++ interface contract

The test file is not shown to you, so the interface it expects is stated here in
full. Implement exactly these names and signatures; the tests use nothing else.

```cpp
namespace perfect_numbers {
enum class classification { deficient, perfect, abundant };
classification classify(int n);
}
```

`classify` throws `std::domain_error` for zero and for negative input.

## Build environment

- The exercise is compiled as C++17 with `-Wall -Wextra -Wpedantic -Werror`, so
  any warning fails the build.
- Only `perfect_numbers.h` and `perfect_numbers.cpp` are editable. `CMakeLists.txt` and the test
  file are fixed and must not be modified.
- The test file includes only `perfect_numbers.h`, so every name above must be visible
  from that header.
- You may either declare in `perfect_numbers.h` and define in `perfect_numbers.cpp`, or define
  everything `inline`/in-class in `perfect_numbers.h` and leave `perfect_numbers.cpp` unchanged.
  Both are accepted.
""",
    "sublist": """
## C++ interface contract

The test file is not shown to you, so the interface it expects is stated here in
full. Implement exactly these names and signatures; the tests use nothing else.

```cpp
namespace sublist {
enum class List_comparison { equal, sublist, superlist, unequal };
List_comparison sublist(const std::vector<int>& list_one,
                        const std::vector<int>& list_two);
}
```

Note the capital L and underscore in `List_comparison`. The result is stated from the perspective of `list_one` relative to `list_two`: `sublist` means `list_one` is contained in `list_two`.

## Build environment

- The exercise is compiled as C++17 with `-Wall -Wextra -Wpedantic -Werror`, so
  any warning fails the build.
- Only `sublist.h` and `sublist.cpp` are editable. `CMakeLists.txt` and the test
  file are fixed and must not be modified.
- The test file includes only `sublist.h`, so every name above must be visible
  from that header.
- You may either declare in `sublist.h` and define in `sublist.cpp`, or define
  everything `inline`/in-class in `sublist.h` and leave `sublist.cpp` unchanged.
  Both are accepted.
""",
}


SPECS = {
    "allergies": TaskSpec("allergies", "allergies", ("allergies.h", "allergies.cpp"), CONTRACTS["allergies"]),
    "diamond": TaskSpec("diamond", "diamond", ("diamond.h", "diamond.cpp"), CONTRACTS["diamond"]),
    "grade-school": TaskSpec("grade-school", "grade_school", ("grade_school.h", "grade_school.cpp"), CONTRACTS["grade-school"]),
    "perfect-numbers": TaskSpec("perfect-numbers", "perfect_numbers", ("perfect_numbers.h", "perfect_numbers.cpp"), CONTRACTS["perfect-numbers"]),
    "sublist": TaskSpec("sublist", "sublist", ("sublist.h", "sublist.cpp"), CONTRACTS["sublist"]),
}


def _task_root(source: Path, task: str) -> Path:
    candidates = (
        source / task,
        source / "cpp" / "exercises" / "practice" / task,
        source / "exercises" / "practice" / task,
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"cannot resolve pinned Polyglot task {task} below {source}")


def _base_target(task_root: Path, spec: TaskSpec) -> dict[str, str]:
    target = {
        spec.editable_files[0]: (task_root / ".meta" / "example.h").read_text(encoding="utf-8"),
        spec.editable_files[1]: (task_root / ".meta" / "example.cpp").read_text(encoding="utf-8"),
    }
    return {name: body if body.endswith("\n") else body + "\n" for name, body in target.items()}


def _original_starter(task_root: Path, spec: TaskSpec) -> dict[str, str]:
    return {
        name: (task_root / name).read_text(encoding="utf-8")
        for name in spec.editable_files
    }


def _instructions(task_root: Path, spec: TaskSpec) -> str:
    pristine = (task_root / ".docs" / "instructions.md").read_text(encoding="utf-8")
    if "## C++ interface contract" in pristine:
        raise ValueError(f"{spec.task}: pristine prompt already contains the fixed26 overlay")
    return pristine.rstrip() + "\n" + spec.contract.rstrip() + "\n"


def _allergies_episodes(
    task_root: Path, spec: TaskSpec, target: Mapping[str, str], instructions: str
) -> list[Episode]:
    header, source = spec.editable_files
    missing_map = _mutate(
        target,
        header,
        lambda text: _replace_once(text, "#include <map>\n", "", "allergies map include"),
    )
    undeclared_table = _mutate(
        target,
        header,
        lambda text: re.sub(
            r"\nstd::map<std::string, unsigned int> const ALLERGENS \{.*?\n\};\n",
            "\n",
            text,
            count=1,
            flags=re.S,
        ),
    )
    if undeclared_table[header] == target[header]:
        raise ValueError("allergies global table mutation did not apply")
    invalid_static = _mutate(
        target,
        source,
        lambda text: _replace_once(
            text,
            "std::unordered_set<std::string> allergy_test::get_allergies() const",
            "static std::unordered_set<std::string> allergy_test::get_allergies() const",
            "allergies invalid static",
        ),
    )
    wrong_bitmask = _mutate(
        target,
        source,
        lambda text: _replace_once(
            text,
            "return (result & allergen_value) == allergen_value;",
            "return result == allergen_value;",
            "allergies exact-score mutation",
        ),
    )
    diagnostic = (
        "allergies.h: error: ‘map’ in namespace ‘std’ does not name a template type\n"
        "note: ‘std::map’ is defined in header ‘<map>’; did you forget to include it?"
    )
    return [
        Episode(spec.task, "full-solve", "official-full-solve", _original_starter(task_root, spec), target, instructions, "compile"),
        Episode(spec.task, "missing-map-header-repair", "missing-standard-header", missing_map, target, instructions, "compile"),
        Episode(spec.task, "undeclared-allergen-table-repair", "helper-used-without-declaration", undeclared_table, target, instructions, "compile"),
        Episode(spec.task, "invalid-static-member-repair", "invalid-static-member-definition", invalid_static, target, instructions, "compile"),
        Episode(spec.task, "bitmask-membership-repair", "exact-score-instead-of-bitmask", wrong_bitmask, target, instructions, "semantic-counterexample"),
        Episode(spec.task, "compiler-feedback-repair", "feedback-missing-standard-header", missing_map, target, _feedback(instructions, diagnostic), "compile"),
    ]


def _diamond_episodes(
    task_root: Path, spec: TaskSpec, target: Mapping[str, str], instructions: str
) -> list[Episode]:
    header, source = spec.editable_files
    missing_string = _mutate(
        target,
        header,
        lambda text: _replace_once(text, "#include <string>\n", "", "diamond string include"),
    )
    missing_vector = _mutate(
        target,
        header,
        lambda text: _replace_once(text, "#include <vector>\n", "", "diamond vector include"),
    )
    filled = _mutate(
        target,
        source,
        lambda text: _replace_once(
            text,
            "row.append(inner_spacing, ' ');\n                row += c;",
            "row.append(inner_spacing, c);\n                row += c;",
            "diamond hollow interior",
        ),
    )
    unused = _mutate(
        target,
        source,
        lambda text: _replace_once(
            text,
            "std::vector<std::string> diamond;\n",
            "std::vector<std::string> diamond;\n        const char middle = middle_letter;\n",
            "diamond unused middle",
        ),
    )
    compile_feedback = (
        "diamond.h: error: ‘string’ is not a member of ‘std’\n"
        "note: ‘std::string’ is defined in header ‘<string>’; did you forget to include it?"
    )
    vector_feedback = (
        "diamond.h: error: ‘vector’ in namespace ‘std’ does not name a template type\n"
        "note: ‘std::vector’ is defined in header ‘<vector>’; did you forget to include it?"
    )
    unused_feedback = (
        "diamond.cpp: error: unused variable ‘middle’ [-Werror=unused-variable]"
    )
    filled_feedback = (
        "Smallest non-degenerate case: each non-center row must contain two boundary letters with spaces between them; the interior was filled with letters."
    )
    return [
        Episode(spec.task, "compiler-feedback-missing-string", "feedback-missing-string-header", missing_string, target, _feedback(instructions, compile_feedback), "compile"),
        Episode(spec.task, "compiler-feedback-missing-vector", "feedback-missing-vector-header", missing_vector, target, _feedback(instructions, vector_feedback), "compile"),
        Episode(spec.task, "compiler-feedback-unused-middle", "feedback-unused-variable-under-werror", unused, target, _feedback(instructions, unused_feedback), "compile"),
        Episode(spec.task, "full-solve", "official-full-solve", _original_starter(task_root, spec), target, instructions, "compile"),
        Episode(spec.task, "test-feedback-filled-interior", "feedback-filled-interior", filled, target, _feedback(instructions, filled_feedback), "semantic-counterexample"),
    ]


def _grade_school_episodes(
    task_root: Path, spec: TaskSpec, target: Mapping[str, str], instructions: str
) -> list[Episode]:
    source = spec.editable_files[1]
    unsorted = _mutate(
        target,
        source,
        lambda text: _replace_once(
            text,
            "auto it = lower_bound(grade_roster.begin(), grade_roster.end(), name);\n    grade_roster.insert(it, name);",
            "grade_roster.push_back(name);",
            "grade-school ordering",
        ),
    )
    dropout_feedback = (
        "No usable whole-file response or applied edit was received. The unchanged scaffold failed to declare grade_school::school."
    )
    starter = _original_starter(task_root, spec)
    return [
        Episode(spec.task, "full-solve", "official-full-solve", starter, target, instructions, "compile"),
        Episode(spec.task, "sorted-roster-repair", "unsorted-grade-roster", unsorted, target, instructions, "semantic-counterexample"),
        Episode(spec.task, "feedback-whole-file-repair", "feedback-whole-file-response-dropout", starter, target, _feedback(instructions, dropout_feedback), "compile"),
    ]


def _perfect_numbers_episodes(
    task_root: Path, spec: TaskSpec, target: Mapping[str, str], instructions: str
) -> list[Episode]:
    source = spec.editable_files[1]
    int64_target = _mutate(
        target,
        source,
        lambda text: _replace_once(
            _replace_once(text, "#include <cmath>\n", "#include <cmath>\n#include <cstdint>\n", "perfect cstdint target include"),
            "int acc = 1;",
            "std::int64_t acc = 1;",
            "perfect int64 target",
        ),
    )
    missing_cstdint = _mutate(
        int64_target,
        source,
        lambda text: _replace_once(text, "#include <cstdint>\n", "", "perfect cstdint include"),
    )
    value_one = _mutate(
        target,
        source,
        lambda text: _replace_once(
            text,
            "    if (n == 1) {\n        return 0;\n    }\n",
            "",
            "perfect value one",
        ),
    )
    compile_feedback = (
        "perfect_numbers.cpp: error: ‘int64_t’ is not a member of ‘std’\n"
        "note: ‘std::int64_t’ is defined in header ‘<cstdint>’."
    )
    semantic_feedback = "classification of 1 failed: expected deficient, observed perfect."
    return [
        Episode(spec.task, "full-solve", "official-full-solve", _original_starter(task_root, spec), target, instructions, "compile"),
        Episode(spec.task, "missing-cstdint-repair", "missing-standard-header", missing_cstdint, int64_target, instructions, "compile"),
        Episode(spec.task, "value-one-boundary-repair", "value-one-misclassified-perfect", value_one, target, instructions, "semantic-counterexample"),
        Episode(spec.task, "compiler-feedback-repair", "feedback-missing-cstdint", missing_cstdint, int64_target, _feedback(instructions, compile_feedback), "compile"),
        Episode(spec.task, "test-feedback-repair", "feedback-value-one-boundary", value_one, target, _feedback(instructions, semantic_feedback), "semantic-counterexample"),
    ]


def _sublist_episodes(
    task_root: Path, spec: TaskSpec, target: Mapping[str, str], instructions: str
) -> list[Episode]:
    source = spec.editable_files[1]
    inverted = _mutate(
        target,
        source,
        lambda text: _replace_once(
            _replace_once(
                text,
                "list_one.size() < list_two.size() && is_sublist(list_one, list_two)",
                "list_one.size() < list_two.size() && is_sublist(list_two, list_one)",
                "sublist first orientation",
            ),
            "list_one.size() > list_two.size() && is_sublist(list_two, list_one)",
            "list_one.size() > list_two.size() && is_sublist(list_one, list_two)",
            "sublist second orientation",
        ),
    )
    diagnostic = (
        "Containment cases failed: list_one inside list_two was reported unequal, and the reverse relation was misclassified."
    )
    return [
        Episode(spec.task, "full-solve", "official-full-solve", _original_starter(task_root, spec), target, instructions, "compile"),
        Episode(spec.task, "containment-direction-repair", "containment-direction-inversion", inverted, target, instructions, "semantic-counterexample"),
        Episode(spec.task, "test-feedback-repair", "feedback-containment-direction", inverted, target, _feedback(instructions, diagnostic), "semantic-counterexample"),
    ]


EPISODE_BUILDERS = {
    "allergies": _allergies_episodes,
    "diamond": _diamond_episodes,
    "grade-school": _grade_school_episodes,
    "perfect-numbers": _perfect_numbers_episodes,
    "sublist": _sublist_episodes,
}


def _evaluate(task_root: Path, files: Mapping[str, str], *, compiler: str) -> Evaluation:
    with TemporaryDirectory(prefix=f"midband-{task_root.name}-") as temporary:
        work = Path(temporary) / task_root.name
        shutil.copytree(task_root, work)
        for name, body in files.items():
            (work / name).write_text(body, encoding="utf-8")
        configure = subprocess.run(
            [
                "cmake",
                "-S",
                ".",
                "-B",
                "build",
                "-DEXERCISM_RUN_ALL_TESTS=ON",
                "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                f"-DCMAKE_CXX_COMPILER={compiler}",
            ],
            cwd=work,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        configure_log = configure.stdout + configure.stderr
        if configure.returncode != 0:
            return Evaluation("compile", 0, 0, configure_log[-6000:])
        build = subprocess.run(
            ["cmake", "--build", "build", "--parallel", "2"],
            cwd=work,
            text=True,
            capture_output=True,
            check=False,
            timeout=240,
        )
        log = build.stdout + build.stderr
        passed = PASS_RE.search(log)
        if passed:
            total = int(passed.group(1))
            return Evaluation("pass", total, total)
        failed = FAIL_RE.search(log)
        if failed:
            total, passed_count, _failed_count = map(int, failed.groups())
            return Evaluation("semantic-counterexample", passed_count, total, log[-6000:])
        return Evaluation("compile", 0, 0, log[-6000:])


def _imitation_response(episode: Episode, editable_files: tuple[str, str]) -> str:
    changed = [
        name
        for name in editable_files
        if episode.starter[name].rstrip() != episode.target[name].rstrip()
    ]
    if not changed:
        raise ValueError(f"{episode.family}/{episode.episode_kind}: target makes no change")
    explanation = (
        "I’ll replace the incomplete implementation with the verified contract."
        if len(changed) == 2
        else f"I’ll correct {changed[0]} so the implementation satisfies the contract."
    )
    listings = "\n\n".join(
        f"{name}\n```cpp\n{episode.target[name].rstrip()}\n```" for name in changed
    )
    return f"{explanation}\n\n{listings}"


def _source_tree_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for root in sorted(paths):
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root.parent).as_posix().encode()
            data = path.read_bytes()
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    return digest.hexdigest()


def _row(task: AiderPolyglotTask, descriptor: Path, output: Path) -> dict[str, object]:
    task_path = descriptor.relative_to(output).as_posix()
    return {
        "prompt": [message.model_dump() for message in task.prompt],
        "label": task.task_id,
        "task_id": task.task_id,
        "problem_id": task.exercise,
        "split": task.split,
        "metadata": {
            "data_source": DATASET_KIND,
            "task_id": task.task_id,
            "problem_id": task.exercise,
            "split": task.split,
            "harness_kind": task.harness_kind,
            "task_path": task_path,
            "editable_files": task.editable_files,
            "hidden_test_sha256": task.hidden_test_sha256,
            "source_prompt_sha256": task.source_prompt_sha256,
            "verification_gate": task.verification_gate,
            "family": task.family,
            "category": task.category,
            "lineage_id": task.lineage_id,
            "episode_kind": task.episode_kind,
            "objective_group": task.objective_group,
            "failure_signature": task.failure_signature,
            "tags": task.tags,
        },
    }


def build_midband_official_drill(
    source_root: str | Path,
    output_root: str | Path,
    *,
    compiler: str = "g++",
    run_id: str | None = None,
) -> dict[str, Path]:
    """Build and fully verify the five-family official CMake task pack."""

    source = Path(source_root).resolve()
    output = Path(output_root).resolve()
    if output.exists():
        if output.is_symlink():
            raise ValueError(f"refusing to replace symlink: {output}")
        shutil.rmtree(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix=f".{output.name}-preparing-", dir=output.parent) as temporary:
        staging = Path(temporary)
        exercise_roots: list[Path] = []
        train_rows: list[dict[str, object]] = []
        sft_rows: list[dict[str, object]] = []
        receipts: list[dict[str, object]] = []

        for family in TASKS:
            spec = SPECS[family]
            official = _task_root(source, family)
            target = _base_target(official, spec)
            instructions = _instructions(official, spec)
            reference = _evaluate(official, target, compiler=compiler)
            if reference.stage != "pass":
                raise ValueError(f"{family}: pinned reference failed: {reference}")
            episodes = EPISODE_BUILDERS[family](official, spec, target, instructions)

            for episode in episodes:
                observed = _evaluate(official, episode.starter, compiler=compiler)
                if observed.stage != episode.expected_stage:
                    raise ValueError(
                        f"{family}/{episode.episode_kind}: expected {episode.expected_stage}, "
                        f"got {observed.stage}: {observed.diagnostic}"
                    )
                target_result = _evaluate(official, episode.target, compiler=compiler)
                if target_result.stage != "pass":
                    raise ValueError(f"{family}/{episode.episode_kind}: target failed")

                exercise_id = f"{family}--{episode.episode_kind}"
                exercise = staging / "official" / exercise_id
                shutil.copytree(official, exercise)
                shutil.rmtree(exercise / ".meta", ignore_errors=True)
                cmake_path = exercise / "CMakeLists.txt"
                cmake = cmake_path.read_text(encoding="utf-8")
                cmake = _replace_once(
                    cmake,
                    "get_filename_component(exercise ${CMAKE_CURRENT_SOURCE_DIR} NAME)",
                    f'set(exercise "{exercise_id}")',
                    f"{exercise_id} CMake target",
                )
                cmake = _replace_once(
                    cmake,
                    'string(REPLACE "-" "_" file ${exercise})',
                    f'set(file "{spec.stem}")',
                    f"{exercise_id} CMake source stem",
                )
                cmake_path.write_text(cmake, encoding="utf-8")
                (exercise / ".docs" / "instructions.md").write_text(
                    episode.instructions.rstrip() + "\n", encoding="utf-8"
                )
                for name, body in episode.starter.items():
                    (exercise / name).write_text(body, encoding="utf-8")
                exercise_roots.append(exercise)

                test_file = exercise / f"{spec.stem}_test.cpp"
                task = AiderPolyglotTask(
                    task_id=f"aider-official-cpp/{exercise_id}",
                    exercise=exercise_id,
                    split="train",
                    harness_kind="official_cmake",
                    exercise_dir=f"official/{exercise_id}",
                    editable_files=list(spec.editable_files),
                    prompt=build_aider_messages(exercise, list(spec.editable_files)),
                    source_revision=_sha256_path(test_file),
                    family=family,
                    category="official-midband-drill",
                    lineage_id=f"fixed26/{family}",
                    episode_kind=episode.episode_kind,
                    objective_group=f"{family}-drill",
                    failure_signature=episode.failure_signature,
                    tags=[
                        "official-task-training-authorized",
                        "strict-binary-reward",
                        "whole-file-action",
                        episode.episode_kind,
                        episode.failure_signature,
                    ],
                    hidden_test_sha256=_sha256_path(test_file),
                    source_prompt_sha256=_sha256_text(episode.instructions.rstrip() + "\n"),
                    verification_gate=VERIFICATION_GATE,
                )
                descriptor = task.write_json(staging / "tasks" / "train" / f"{exercise_id}.json")
                row = _row(task, descriptor, staging)
                train_rows.append(row)
                response = _imitation_response(episode, spec.editable_files)
                metadata = dict(row["metadata"])
                metadata["subset"] = "verified-imitation"
                metadata["imitation_target_sha256"] = _sha256_text(response)
                sft_rows.append(
                    {
                        "messages": [
                            *(message.model_dump() for message in task.prompt),
                            {"role": "assistant", "content": response},
                        ],
                        "label": row["label"],
                        "task_id": row["task_id"],
                        "problem_id": row["problem_id"],
                        "split": row["split"],
                        "metadata": metadata,
                    }
                )
                receipts.append(
                    {
                        "task_id": task.task_id,
                        "family": family,
                        "episode_kind": episode.episode_kind,
                        "failure_signature": episode.failure_signature,
                        "starter_rejected_as": observed.stage,
                        "starter_tests_passed": observed.tests_passed,
                        "starter_tests_total": observed.tests_total,
                        "starter_sha256": {
                            name: _sha256_text(body) for name, body in sorted(episode.starter.items())
                        },
                        "target_sha256": {
                            name: _sha256_text(body) for name, body in sorted(episode.target.items())
                        },
                        "prompt_sha256": task.source_prompt_sha256,
                        "hidden_test_sha256": task.hidden_test_sha256,
                    }
                )

        train_rows.sort(key=lambda row: (str(row["metadata"]["family"]), str(row["problem_id"])))
        sft_rows.sort(key=lambda row: (str(row["metadata"]["family"]), str(row["problem_id"])))
        write_jsonl(staging / "grpo" / "train.jsonl", train_rows)
        write_jsonl(staging / "sft" / "train.jsonl", sft_rows)
        write_jsonl(staging / "eval" / "train_monitor.jsonl", train_rows)
        write_jsonl(staging / "eval" / "validation.jsonl", train_rows)
        write_jsonl(staging / "verification.jsonl", receipts)

        counts_by_family = {
            family: sum(row["metadata"]["family"] == family for row in train_rows)
            for family in TASKS
        }
        manifest = {
            "kind": DATASET_KIND,
            "schema_version": 5,
            "profile": CURRICULUM_NAME,
            "run_id": run_id,
            "source_root": f"official:Aider-AI/polyglot-benchmark@{POLYGLOT_COMMIT}",
            "source_manifest_kind": "fixed26-midband-official-task-pack",
            "source_tree_sha256": _source_tree_sha256(exercise_roots),
            "split_contract": {
                "train": "five exact official fixed26 task families with verified failure episodes",
                "validation": "training-task monitor only; zero held-out by explicit authorization",
                "monitor": "training-task reward-density monitor",
                "official_26": "explicitly authorized exact-task reliability drill",
                "official_task_id_overlap": list(TASKS),
                "source_reference_answers_packaged": False,
                "reference_answers_packaged": True,
                "imitation_role": "exact authorized task overfit",
            },
            "counts": {
                "available_official": len(train_rows),
                "train": len(train_rows),
                "sft_train": len(sft_rows),
                "validation": 0,
                "monitor": len(train_rows),
            },
            "composition": {
                "families": counts_by_family,
                "categories": {"official-midband-drill": len(train_rows)},
            },
            "contract": {
                "official_training_authorized": True,
                "zero_held_out": True,
                "strict_binary_reward": True,
                "verification_gate": VERIFICATION_GATE,
                "polyglot_commit": POLYGLOT_COMMIT,
                "task_families": list(TASKS),
                "issue": "https://github.com/tokenbender/browser-is-all-you-need/issues/112",
            },
            "verification_receipts": "verification.jsonl",
            "verification_receipts_sha256": _sha256_path(staging / "verification.jsonl"),
            "files": {
                "grpo_train": "grpo/train.jsonl",
                "sft_train": "sft/train.jsonl",
                "validation": "eval/validation.jsonl",
                "train_monitor": "eval/train_monitor.jsonl",
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        shutil.move(str(staging), output)

    return {
        "grpo_train": output / "grpo" / "train.jsonl",
        "sft_train": output / "sft" / "train.jsonl",
        "eval": output / "eval" / "validation.jsonl",
        "manifest": output / "manifest.json",
        "verification": output / "verification.jsonl",
    }
