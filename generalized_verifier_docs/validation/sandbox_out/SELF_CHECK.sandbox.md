# SELF-CHECK -- 6 verifiers x 3 controls (positive / fault / tamper)

Generated: 2026-08-28T14:47:55.435640+00:00 by `validation/self_check.py` on `066590d55bdb` (Linux 6.8.0-136-generic, python 3.11.2, stdlib only).

Every verdict below is from a **real execution** on this machine; stdout blocks are pasted verbatim. Each run also wrote a sandbox-compatible kernel receipt via `--receipt` (paths shown per case). Overall result: **ALL CONTROLS BEHAVED AS EXPECTED**.

## Matrix

| Verifier | (a) positive -> PASS/OK | (b) fault -> FAIL class | (c) tamper -> no silent PASS |
|---|---|---|---|
| `01_structural_api_gate.py` | OK (exit 0) | OK (exit 1) | OK (exit 1) |
| `03_two_stage_build_verifier.py` | OK (exit 0) | OK (exit 1) | OK (exit 1) |
| `04_differential_semantic_verifier.py` | OK (exit 0) | OK (exit 1) | OK (exit 1) |
| `05_response_integrity_verifier.py` | OK (exit 0) | OK (exit 1) | OK (exit 1) |
| `06_candidate_boundary_verifier.py` | OK (exit 0) | OK (exit 1) | OK (exit 1) |
| `07_warning_hygiene_classifier.py` | OK (exit 0) | OK (exit 1) | OK (exit 1) |

Legend: `OK` = the verifier produced the expected verdict class for the control; `MISMATCH` = expectation failed (details below).

## Per-case detail

### 01-positive -- `01_structural_api_gate.py` (positive control)

Known-good reference implementation (.meta/example.*) against its official test file.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/01_structural_api_gate.py --test /workspace/Reward_GRPO/multi_env_fixtures/zebra-puzzle/zebra_puzzle_test.cpp --header /workspace/Reward_GRPO/multi_env_fixtures/zebra-puzzle/.meta/example.h --source /workspace/Reward_GRPO/multi_env_fixtures/zebra-puzzle/.meta/example.cpp --receipt /out/receipts/01-positive
```

exit code: 0 (expected 0) -- expectation MET
kernel receipt: `../out/receipts/01-positive/01_structural_api_gate_kernel_receipt.json`

```
--- Structural API Gate ---
Required symbols derived from test: zebra_puzzle::Solution, zebra_puzzle::solve
  OK    zebra_puzzle::Solution
  OK    zebra_puzzle::solve
VERDICT: PASS (2 symbols)
--- stderr ---
receipt: wrote /out/receipts/01-positive/01_structural_api_gate_kernel_receipt.json (status=pass, kernel=1)
```

### 01-fault -- `01_structural_api_gate.py` (fault control)

Recorded failure input (validation/ candidates): candidate whose namespace lacks the symbol the test uses ('solve' is not a member -- recorded compiler error).

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/01_structural_api_gate.py --test /workspace/Reward_GRPO/multi_env_fixtures/zebra-puzzle/zebra_puzzle_test.cpp --header /workspace/generalized_verifier_docs/validation/candidates/zebra-puzzle/zebra_puzzle.h --source /workspace/generalized_verifier_docs/validation/candidates/zebra-puzzle/zebra_puzzle.cpp --receipt /out/receipts/01-fault
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/01-fault/01_structural_api_gate_kernel_receipt.json`

```
--- Structural API Gate ---
Required symbols derived from test: zebra_puzzle::Solution, zebra_puzzle::solve
  OK    zebra_puzzle::Solution
  FAIL  required symbol 'solve' not declared in namespace 'zebra_puzzle'
VERDICT: FAIL (1/2 symbols)
--- stderr ---
receipt: wrote /out/receipts/01-fault/01_structural_api_gate_kernel_receipt.json (status=fail, kernel=-1)
```

### 01-tamper -- `01_structural_api_gate.py` (tamper control)

Cross-task mismatch: official test file of task A with the reference header/source of task B.

Tamper rationale: Sensible behavior: the required symbols derived from task A's test are absent from task B's namespace, so the gate must FAIL with missing-symbol diagnostics. A silent PASS here would mean the gate is not actually binding the test to the candidate.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/01_structural_api_gate.py --test /workspace/Reward_GRPO/multi_env_fixtures/zebra-puzzle/zebra_puzzle_test.cpp --header /workspace/Reward_GRPO/multi_env_fixtures/clock/.meta/example.h --source /workspace/Reward_GRPO/multi_env_fixtures/clock/.meta/example.cpp --receipt /out/receipts/01-tamper
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/01-tamper/01_structural_api_gate_kernel_receipt.json`

```
--- Structural API Gate ---
Required symbols derived from test: zebra_puzzle::Solution, zebra_puzzle::solve
  FAIL  required symbol 'Solution' not declared in namespace 'zebra_puzzle'
  FAIL  required symbol 'solve' not declared in namespace 'zebra_puzzle'
VERDICT: FAIL (2/2 symbols)
--- stderr ---
receipt: wrote /out/receipts/01-tamper/01_structural_api_gate_kernel_receipt.json (status=fail, kernel=-1)
```

### 03-positive -- `03_two_stage_build_verifier.py` (positive control)

Known-good header-only reference implementation against its fixture (real g++ two-stage build).

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/03_two_stage_build_verifier.py --fixture-dir /workspace/Reward_GRPO/multi_env_fixtures/binary-search-tree --header /workspace/Reward_GRPO/multi_env_fixtures/binary-search-tree/.meta/example.h --receipt /out/receipts/03-positive
```

exit code: 0 (expected 0) -- expectation MET
kernel receipt: `../out/receipts/03-positive/03_two_stage_build_verifier_kernel_receipt.json`

```
--- Two-Stage Build Verifier ---
Stage 1: g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -DEXERCISM_RUN_ALL_TESTS -c <candidate>.cpp
Stage 2: g++ <test>.cpp + tests-main.cpp, then link
STATUS: PASS
Feedback: build clean: candidate compiles and links against the official test
--- stderr ---
receipt: wrote /out/receipts/03-positive/03_two_stage_build_verifier_kernel_receipt.json (status=pass, kernel=1)
```

### 03-fault -- `03_two_stage_build_verifier.py` (fault control)

Recorded failure input: template methods declared in the header but defined in the .cpp (recorded 'undefined reference' link failure).

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/03_two_stage_build_verifier.py --fixture-dir /workspace/Reward_GRPO/multi_env_fixtures/linked-list --header /workspace/generalized_verifier_docs/validation/candidates/linked-list/linked_list.h --source /workspace/generalized_verifier_docs/validation/candidates/linked-list/linked_list.cpp --receipt /out/receipts/03-fault
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/03-fault/03_two_stage_build_verifier_kernel_receipt.json`

```
--- Two-Stage Build Verifier ---
Stage 1: g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -DEXERCISM_RUN_ALL_TESTS -c <candidate>.cpp
Stage 2: g++ <test>.cpp + tests-main.cpp, then link
STATUS: LE
Feedback: LINKER ERROR: the test references symbols that have no definition ('undefined reference'). Typical cause: functions or template methods declared in the header but defined in the .cpp file. Move the definitions into the header (or explicitly instantiate templates).
--- compiler output (first lines) ---
/usr/bin/ld: linked_list_test.o: in function `____C_A_T_C_H____T_E_S_T____0()':
linked_list_test.cpp:(.text+0x17): undefined reference to `linked_list::List<int>::List()'
/usr/bin/ld: linked_list_test.cpp:(.text+0x2b): undefined reference to `linked_list::List<int>::push(int)'
/usr/bin/ld: linked_list_test.cpp:(.text+0xa9): undefined reference to `linked_list::List<int>::pop()'
/usr/bin/ld: linked_list_test.o: in function `____C_A_T_C_H____T_E_S_T____2()':
linked_list_test.cpp:(.text+0x19d): undefined reference to `linked_list::List<int>::List()'
/usr/bin/ld: linked_list_test.cpp:(.text+0x1b1): undefined reference to `linked_list::List<int>::push(int)'
/usr/bin/ld: linked_list_test.cpp:(.text+0x1c5): undefined reference to `linked_list::List<int>::push(int)'
/usr/bin/ld: linked_list_test.cpp:(.text+0x252): undefined reference to `linked_list::List<int>::pop()'
/usr/bin/ld: linked_list_test.cpp:(.text+0x366): undefined reference to `linked_list::List<int>::pop()'
--- stderr ---
receipt: wrote /out/receipts/03-fault/03_two_stage_build_verifier_kernel_receipt.json (status=fail, kernel=-1)
```

### 03-tamper -- `03_two_stage_build_verifier.py` (tamper control)

Cross-task mismatch: fixture (official test + harness) of task A with the reference header of task B (header-only candidate).

Tamper rationale: Sensible behavior: task B's header does not declare task A's API, so stage 2 must fail as CE-2 (the official test does not compile against the foreign candidate header). A PASS would mean the build never actually compiled the test against the candidate.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/03_two_stage_build_verifier.py --fixture-dir /workspace/Reward_GRPO/multi_env_fixtures/zebra-puzzle --header /workspace/Reward_GRPO/multi_env_fixtures/clock/.meta/example.h --receipt /out/receipts/03-tamper
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/03-tamper/03_two_stage_build_verifier_kernel_receipt.json`

```
--- Two-Stage Build Verifier ---
Stage 1: g++ -std=c++17 -Wall -Wextra -Wpedantic -Werror -DEXERCISM_RUN_ALL_TESTS -c <candidate>.cpp
Stage 2: g++ <test>.cpp + tests-main.cpp, then link
STATUS: CE-2
Feedback: COMPILE ERROR (stage 2): the official test file does not compile against your header. The declarations in your header do not match the API the test uses (missing/wrong names, private members, wrong template shape).
--- compiler output (first lines) ---
zebra_puzzle_test.cpp: In function 'void ____C_A_T_C_H____T_E_S_T____0()':
zebra_puzzle_test.cpp:9:5: error: 'zebra_puzzle' has not been declared
    9 |     zebra_puzzle::Solution solution = zebra_puzzle::solve();
      |     ^~~~~~~~~~~~
In file included from zebra_puzzle_test.cpp:5:
zebra_puzzle_test.cpp:11:39: error: 'solution' was not declared in this scope
   11 |     SECTION("Drinks water") { REQUIRE(solution.drinksWater == "Norwegian"); }
      |                                       ^~~~~~~~
zebra_puzzle_test.cpp:11:39: error: 'solution' was not declared in this scope
   11 |     SECTION("Drinks water") { REQUIRE(solution.drinksWater == "Norwegian"); }
--- stderr ---
receipt: wrote /out/receipts/03-tamper/03_two_stage_build_verifier_kernel_receipt.json (status=fail, kernel=-1)
```

### 04-positive -- `04_differential_semantic_verifier.py` (positive control)

Reference implementation as candidate: must score 8/8 assertions, score 1.0.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/04_differential_semantic_verifier.py --fixture-dir /workspace/Reward_GRPO/multi_env_fixtures/crypto-square --header /workspace/Reward_GRPO/multi_env_fixtures/crypto-square/.meta/example.h --source /workspace/Reward_GRPO/multi_env_fixtures/crypto-square/.meta/example.cpp --receipt /out/receipts/04-positive
```

exit code: 0 (expected 0) -- expectation MET
kernel receipt: `../out/receipts/04-positive/04_differential_semantic_verifier_kernel_receipt.json`

```
--- Differential Semantic Verifier ---
Positive control (reference): OK run={'passed_assertions': 8, 'total_assertions': 8, 'score': 1.0, 'failed_test_cases': [], 'crashed': False}
Candidate: 8/8 assertions passed (score 1.0)
VERDICT: PASS (score 1.0)
--- stderr ---
receipt: wrote /out/receipts/04-positive/04_differential_semantic_verifier_kernel_receipt.json (status=pass, kernel=1)
```

### 04-fault -- `04_differential_semantic_verifier.py` (fault control)

Recorded failure input: candidate that returns the essentially-normalized input (recorded Catch2 'clu hlt io ' == 'chillout ' failure).

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/04_differential_semantic_verifier.py --fixture-dir /workspace/Reward_GRPO/multi_env_fixtures/crypto-square --header /workspace/generalized_verifier_docs/validation/candidates/crypto-square/crypto_square.h --source /workspace/generalized_verifier_docs/validation/candidates/crypto-square/crypto_square.cpp --receipt /out/receipts/04-fault
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/04-fault/04_differential_semantic_verifier_kernel_receipt.json`

```
--- Differential Semantic Verifier ---
Positive control (reference): OK run={'passed_assertions': 8, 'total_assertions': 8, 'score': 1.0, 'failed_test_cases': [], 'crashed': False}
Candidate: 5/8 assertions passed (score 0.625)
  failing case: 9 character plaintext results in 3 chunks of 3 characters
  failing case: 8 character plaintext results in 3 chunks, the last one with a trailing space
  failing case: 54 character plaintext results in 7 chunks, the last two with trailing spaces
Differential: candidate fails 3/8 assertions that the reference passes -- semantic regression, not a build problem
VERDICT: FAIL (score 0.625)
--- stderr ---
receipt: wrote /out/receipts/04-fault/04_differential_semantic_verifier_kernel_receipt.json (status=fail, kernel=-1)
```

### 04-tamper -- `04_differential_semantic_verifier.py` (tamper control)

Cross-task mismatch: fixture of task A with a recorded candidate of task B.

Tamper rationale: Sensible behavior: task B's candidate does not provide task A's API, so the candidate build fails (BUILD_FAIL / CE-2) and the verdict is FAIL with score 0.0. A PASS would mean the differential never ran against the real test binary.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/04_differential_semantic_verifier.py --fixture-dir /workspace/Reward_GRPO/multi_env_fixtures/kindergarten-garden --header /workspace/generalized_verifier_docs/validation/candidates/zebra-puzzle/zebra_puzzle.h --source /workspace/generalized_verifier_docs/validation/candidates/zebra-puzzle/zebra_puzzle.cpp --receipt /out/receipts/04-tamper
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/04-tamper/04_differential_semantic_verifier_kernel_receipt.json`

```
--- Differential Semantic Verifier ---
Positive control (reference): OK run={'passed_assertions': 17, 'total_assertions': 17, 'score': 1.0, 'failed_test_cases': [], 'crashed': False}
Candidate: BUILD_FAIL (CE-1: COMPILE ERROR (stage 1): your implementation file fails to compile on its own. Fix the syntax/semantic errors in the candidate source shown below.)
VERDICT: FAIL (score 0.0)
--- stderr ---
receipt: wrote /out/receipts/04-tamper/04_differential_semantic_verifier_kernel_receipt.json (status=fail, kernel=-1)
```

### 05-positive -- `05_response_integrity_verifier.py` (positive control)

Recorded clean generation (complete file listings, stream ends at a closing fence).

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/05_response_integrity_verifier.py --response /workspace/generalized_verifier_docs/validation/05/fixtures/good-bank-account-reply.txt --receipt /out/receipts/05-positive
```

exit code: 0 (expected 0) -- expectation MET
kernel receipt: `../out/receipts/05-positive/05_response_integrity_verifier_kernel_receipt.json`

```
--- Response Integrity Verifier ---
VERDICT: OK
Feedback: OK: 2 file listing(s), 2 complete fenced block(s); the stream ends at a clean boundary.
--- stderr ---
receipt: wrote /out/receipts/05-positive/05_response_integrity_verifier_kernel_receipt.json (status=pass, kernel=1)
```

### 05-fault -- `05_response_integrity_verifier.py` (fault control)

Recorded failure input: degenerate CJK-phrase loop running to the end of the generation.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/05_response_integrity_verifier.py --response /workspace/generalized_verifier_docs/validation/05/fixtures/loop-knapsack-cjk-phrase.txt --receipt /out/receipts/05-fault
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/05-fault/05_response_integrity_verifier_kernel_receipt.json`

```
--- Response Integrity Verifier ---
VERDICT: LOOP
Feedback: LOOP: degenerate repetition -- identical-line unit 'wait，我将输出文件。' repeats 1142x and the run reaches the end of the generation; CJK/fullwidth drift in the tail: 58%. This is non-convergence, not a wrong answer: apply anti-loop filtering / overlong masking rather than a plain negative reward, and do not retry identically.
--- stderr ---
receipt: wrote /out/receipts/05-fault/05_response_integrity_verifier_kernel_receipt.json (status=fail, kernel=-1)
```

### 05-tamper -- `05_response_integrity_verifier.py` (tamper control)

Deliberately corrupted input: the known-good generation with its final closing fence removed (generated at runtime by drop_last_fence).

Tamper rationale: Sensible behavior: the deliverable's last fence is never closed, so the verdict must be TRUNCATED (cut mid-block), not OK. A silent PASS would mean truncation detection is dead.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/05_response_integrity_verifier.py --response /tmp/self_check_generated/05_tamper_unclosed_fence.txt --receipt /out/receipts/05-tamper
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/05-tamper/05_response_integrity_verifier_kernel_receipt.json`

```
--- Response Integrity Verifier ---
VERDICT: TRUNCATED
Feedback: TRUNCATED: the deliverable's last code fence is never closed (3 fence lines) -- generation was cut mid-block. Consider a reasoning budget or overlong shaping; a plain negative reward cannot distinguish this from a wrong answer.
--- stderr ---
receipt: wrote /out/receipts/05-tamper/05_response_integrity_verifier_kernel_receipt.json (status=fail, kernel=-1)
```

### 06-positive -- `06_candidate_boundary_verifier.py` (positive control)

Recorded clean PASS response: both editable files listed exactly once, no boundary issues.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/06_candidate_boundary_verifier.py --response /workspace/generalized_verifier_docs/validation/06/cases/clean__space-age__turn1.response.txt --editable space_age.h --editable space_age.cpp --receipt /out/receipts/06-positive
```

exit code: 0 (expected 0) -- expectation MET
kernel receipt: `../out/receipts/06-positive/06_candidate_boundary_verifier_kernel_receipt.json`

```
--- Candidate Boundary Verifier ---
Editable set: space_age.h, space_age.cpp
  file space_age.cpp: LISTED, 933 bytes
  file space_age.h: LISTED, 1001 bytes
  no issues; reconstructed set == listed set
VERDICT: OK
--- stderr ---
receipt: wrote /out/receipts/06-positive/06_candidate_boundary_verifier_kernel_receipt.json (status=pass, kernel=1)
```

### 06-fault -- `06_candidate_boundary_verifier.py` (fault control)

Recorded failure input (GRPO-30 row, reason=forbidden_file, reward -1.0): markdown-glued labels outside the editable set.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/06_candidate_boundary_verifier.py --response /workspace/generalized_verifier_docs/validation/06/cases/meetup__u1_s477.response.txt --editable meetup.h --editable meetup.cpp --receipt /out/receipts/06-fault
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/06-fault/06_candidate_boundary_verifier_kernel_receipt.json`

```
--- Candidate Boundary Verifier ---
Editable set: meetup.h, meetup.cpp
  FATAL        FORBIDDEN_FILE [*Meetup.h*]: response targets non-editable file '*Meetup.h*': this name is outside the editable set ['meetup.cpp', 'meetup.h'], so the whole response is rejected. Did you mean 'meetup.h'? Emit the bare filename 'meetup.h' on the line directly above the fence -- no markdown emphasis, quotes, or case changes.
  FATAL        FORBIDDEN_FILE [*Meetup.cpp*]: response targets non-editable file '*Meetup.cpp*': this name is outside the editable set ['meetup.cpp', 'meetup.h'], so the whole response is rejected. Did you mean 'meetup.cpp'? Emit the bare filename 'meetup.cpp' on the line directly above the fence -- no markdown emphasis, quotes, or case changes.
  WARNING      SKIPPED_LISTING: fence has no usable filename label (found 'Actually, re-reading my code:'); the listing was ignored. Put the bare editable filename on the line directly above each ``` fence.
  WARNING      SKIPPED_LISTING: fence has no usable filename label (found 'Looks solid.'); the listing was ignored. Put the bare editable filename on the line directly above each ``` fence.
  WARNING      SKIPPED_LISTING: fence has no usable filename label (found '实际上，重新阅读我的代码：'); the listing was ignored. Put the bare editable filename on the line directly above each ``` fence.
  WARNING      SKIPPED_LISTING: fence has no usable filename label (found '看起来很可靠。'); the listing was ignored. Put the bare editable filename on the line directly above each ``` fence.
  WARNING      SKIPPED_LISTING: fence has no usable filename label (found '实际上，重新阅读我的代码：'); the listing was ignored. Put the bare editable filename on the line directly above each ``` fence.
  WARNING      SKIPPED_LISTING: fence has no usable filename label (found '看起来很可靠。'); the listing was ignored. Put the bare editable filename on the line directly above each ``` fence.
  MODIFICATION OMITTED_NO_TEMPLATE [meetup.h]: editable file 'meetup.h' was not listed and no template content was supplied, so the reconstructed set is incomplete.
  MODIFICATION OMITTED_NO_TEMPLATE [meetup.cpp]: editable file 'meetup.cpp' was not listed and no template content was supplied, so the reconstructed set is incomplete.
  FATAL        NO_FILES: no fence yielded a complete editable file; every listing was either unlabeled, mislabeled, or cut off before its closing fence.
VERDICT: FAIL
--- stderr ---
receipt: wrote /out/receipts/06-fault/06_candidate_boundary_verifier_kernel_receipt.json (status=fail, kernel=-1)
```

### 06-tamper -- `06_candidate_boundary_verifier.py` (tamper control)

Cross-task mismatch: a recorded clean response for task A checked against the editable set of task B.

Tamper rationale: Sensible behavior: every listed file is outside task B's editable set, so the verdict must be FAIL with FORBIDDEN_FILE issues. A silent PASS would mean the editable-set boundary is not enforced.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/06_candidate_boundary_verifier.py --response /workspace/generalized_verifier_docs/validation/06/cases/clean__space-age__turn1.response.txt --editable zebra_puzzle.h --editable zebra_puzzle.cpp --receipt /out/receipts/06-tamper
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/06-tamper/06_candidate_boundary_verifier_kernel_receipt.json`

```
--- Candidate Boundary Verifier ---
Editable set: zebra_puzzle.h, zebra_puzzle.cpp
  FATAL        FORBIDDEN_FILE [space_age.h]: response targets non-editable file 'space_age.h': this name is outside the editable set ['zebra_puzzle.cpp', 'zebra_puzzle.h'], so the whole response is rejected. Remove this listing (it looks like an illustrative or out-of-scope file); only list files you were told to modify.
  FATAL        FORBIDDEN_FILE [space_age.cpp]: response targets non-editable file 'space_age.cpp': this name is outside the editable set ['zebra_puzzle.cpp', 'zebra_puzzle.h'], so the whole response is rejected. Remove this listing (it looks like an illustrative or out-of-scope file); only list files you were told to modify.
  MODIFICATION OMITTED_NO_TEMPLATE [zebra_puzzle.h]: editable file 'zebra_puzzle.h' was not listed and no template content was supplied, so the reconstructed set is incomplete.
  MODIFICATION OMITTED_NO_TEMPLATE [zebra_puzzle.cpp]: editable file 'zebra_puzzle.cpp' was not listed and no template content was supplied, so the reconstructed set is incomplete.
  FATAL        NO_FILES: no fence yielded a complete editable file; every listing was either unlabeled, mislabeled, or cut off before its closing fence.
VERDICT: FAIL
--- stderr ---
receipt: wrote /out/receipts/06-tamper/06_candidate_boundary_verifier_kernel_receipt.json (status=fail, kernel=-1)
```

### 07-positive -- `07_warning_hygiene_classifier.py` (positive control)

Recorded clean build log (no compiler diagnostics).

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/07_warning_hygiene_classifier.py --stderr /workspace/generalized_verifier_docs/validation/07/cases/clean_robot-name_trial-03.build-log.txt --receipt /out/receipts/07-positive
```

exit code: 0 (expected 0) -- expectation MET
kernel receipt: `../out/receipts/07-positive/07_warning_hygiene_classifier_kernel_receipt.json`

```
--- Warning-Hygiene Classifier ---
no compiler diagnostics found
VERDICT: PASS
--- stderr ---
receipt: wrote /out/receipts/07-positive/07_warning_hygiene_classifier_kernel_receipt.json (status=pass, kernel=1)
```

### 07-fault -- `07_warning_hygiene_classifier.py` (fault control)

Recorded failure input: missing <cstdint> include ('uint32_t' was not declared in this scope).

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/07_warning_hygiene_classifier.py --stderr /workspace/generalized_verifier_docs/validation/07/cases/eval_missing-include-cstdint.stderr.txt --receipt /out/receipts/07-fault
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/07-fault/07_warning_hygiene_classifier_kernel_receipt.json`

```
--- Warning-Hygiene Classifier ---
  ERROR   [missing-include] /aider/spiral-matrix/spiral_matrix.h:8: ‘uint32_t’ was not declared in this scope
          fix: add #include <cstdint> -- 'uint32_t' is declared there
  ERROR   [other] /aider/spiral-matrix/spiral_matrix.h:8: template argument 1 is invalid
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix.h:8: template argument 2 is invalid
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix.h:8: template argument 1 is invalid
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix.h:8: template argument 2 is invalid
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [missing-include] /aider/spiral-matrix/spiral_matrix.h:8: ‘uint32_t’ was not declared in this scope
          fix: add #include <cstdint> -- 'uint32_t' is declared there
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:14: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:14: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:14: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:20: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:20: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:20: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:28: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:28: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:28: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:37: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:37: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:37: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:47: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
          fix: unclassified compiler diagnostic; read the full message and the source line it points at
  ERROR   [other] /aider/spiral-matrix/spiral_matrix_test.cpp:47: ‘spiral_matrix::spiral_matrix’ cannot be used as a function
... (11 more lines)
--- stderr ---
receipt: wrote /out/receipts/07-fault/07_warning_hygiene_classifier_kernel_receipt.json (status=fail, kernel=-1)
```

### 07-tamper -- `07_warning_hygiene_classifier.py` (tamper control)

Deliberately corrupted input: the known-good clean log of one build with a foreign error block from a different failing build appended (generated at runtime by concat).

Tamper rationale: Sensible behavior: the classifier trusts only the diagnostic content, never the filename or origin label, so the injected unused-parameter errors must flip the verdict to FAIL with dominant class unused-parameter. A silent PASS would mean it is not actually parsing the text.

```
$ /usr/bin/python3 /workspace/generalized_verifier_docs/07_warning_hygiene_classifier.py --stderr /tmp/self_check_generated/07_tamper_mixed_log.txt --receipt /out/receipts/07-tamper
```

exit code: 1 (expected 1) -- expectation MET
kernel receipt: `../out/receipts/07-tamper/07_warning_hygiene_classifier_kernel_receipt.json`

```
--- Warning-Hygiene Classifier ---
  ERROR   [unused-parameter] /aider/crypto-square/crypto_square.cpp:8: unused parameter ‘text’ [-Werror=unused-parameter]
          fix: remove the parameter, omit its name in the definition, or mark it [[maybe_unused]]
dominant class: unused-parameter (1 errors, 0 warnings)
VERDICT: FAIL
--- stderr ---
receipt: wrote /out/receipts/07-tamper/07_warning_hygiene_classifier_kernel_receipt.json (status=fail, kernel=-1)
```
