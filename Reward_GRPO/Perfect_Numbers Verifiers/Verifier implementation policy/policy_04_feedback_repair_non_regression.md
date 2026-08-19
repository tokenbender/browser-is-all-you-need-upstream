# Policy 4 — Feedback Repair and Non-Regression

Policy 4 verifies an authenticated two-turn Perfect Numbers trajectory. It asks whether turn 2 changed the file implicated by turn-1 feedback, removed the named diagnostics, preserved all previously passing official tests, and reached a complete result.

## Kernel table

| Kernel | Verifier function | Question | Exact implementation | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|---|
| E04-A | `verify_e04_a_targeted_edit()` | Did turn 2 modify the mapped source file? | Authenticate both source snapshots and compare changed files with the stable diagnostic-to-file map | A real change touches every required target and no unauthorized file | No change, missing required target, or unauthorized change | Tree hashes, changed-file list, unified diff hash |
| E04-B | `verify_e04_b_diagnostic_elimination()` | Did turn 2 remove every turn-1 diagnostic ID? | Compare authenticated stable diagnostic arrays between evaluation receipts | No turn-1 diagnostic remains | At least one remains | Both receipts, raw log hashes, diagnostic sets |
| E04-C | `verify_e04_c_no_regression()` | Did all previously passing tests remain passing? | Require `turn_1_passed_test_UUIDs` to be a subset of `turn_2_passed_test_UUIDs` | Subset relation holds | A previously passing test regresses | Pinned UUID set and both per-test outcome maps |
| E04-D | `verify_e04_d_full_repair()` | Did turn 1 or turn 2 reach an authenticated 13/13 pass? | Check selected, passed, failed, timeout, build, and terminal fields | Complete 13/13 result | Valid trajectory remains incomplete or failing | Terminal receipt and official-test hash |

## Trajectory bundle contract

The bundle contains `manifest.json`, generated and delivered feedback, two response receipts, two evaluation receipts, raw evaluation logs, two source snapshots, and `turn_2.diff`. The manifest SHA-256-binds every non-manifest regular file. Each evaluation receipt also binds the combined digest of that turn's two authorized source files. The verifier recomputes the source diff and test/diagnostic relations; it does not trust narrative claims.

Required stable diagnostics are `PN-E01-API`, `PN-E02-ONE`, `PN-E03-ZERO-NO-THROW`, `PN-E03-ZERO-WRONG-TYPE`, `PN-E03-NEGATIVE-NO-THROW`, and `PN-E03-NEGATIVE-WRONG-TYPE`.

## E04-A — Targeted edit

`PN-E01-API` maps to `perfect_numbers.h`; Policy 2 and Policy 3 diagnostic IDs map to `perfect_numbers.cpp`. Both candidate files are authorized, but changing an authorized file does not excuse omitting a required target.

## E04-B — Diagnostic elimination

The turn-1 diagnostic set must be nonempty. Turn 2 passes only when its stable diagnostic set is disjoint from the turn-1 set.

## E04-C — No regression

Both receipts must contain outcomes for all 13 pinned test UUIDs whenever the evaluation reached the test stage. A compilation-stage turn may use an empty pass set, but a turn-2 compilation regression after turn-1 test execution fails this kernel.

## E04-D — Full repair

A complete pass requires `selected_tests=13`, `passed_tests=13`, `failed_tests=0`, `timed_out=false`, `build_succeeded=true`, and `evaluation_completed=true`. A turn-1 pass excludes Policy 4 instead of assigning automatic kernel passes.

## Applicability and aggregation

For a genuine two-turn repair, all four kernels are equal. The range is `-4` through `+4`, and Policy 4 passes only at `+4`. If turn 1 already passed, all four kernels are excluded with reason `not_applicable_turn_1_already_passed`. Missing, corrupt, unbound, or inconsistent evidence is `INVALID`.

## Execution

```bash
python3 "Reward_GRPO/Perfect_Numbers Verifiers/verifiers/verifier_04_feedback_repair_non_regression.py" \
  --bundle-dir <perfect-numbers-trajectory-bundle> \
  --output-dir <new-empty-directory>
```
