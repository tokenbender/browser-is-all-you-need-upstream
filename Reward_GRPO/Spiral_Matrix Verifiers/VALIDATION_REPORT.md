# Spiral Matrix verifier validation report

## Step 1: Positive and metamorphic controls

The pinned spiral-matrix contract was reconstructed from Polyglot commit 7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f. The known-good reference was installed only in a temporary fixture; protected tests, metadata, Catch2, and build files remained hash-bound.

All fifteen kernels passed the reference. A second behavior-preserving fixture renamed coordinate and direction locals consistently; all fifteen kernels passed again, showing that scoring depends on the public contract and behavior rather than one exact reference spelling.

| Check | Result | Decision |
|---|---:|---|
| Known-good reference | 15/15 kernels passed | Positive control passed |
| Harmless metamorphic rewrite | 15/15 kernels passed | No observed false negative |
| GCC identity | 13.3.0 | Pinned compiler matched |
| Official terminal suite | Compiled, linked, and all selected tests passed | Canonical behavior authenticated |

## Step 2: Fault and evaluator-integrity controls

The controlled semantic mutant started traversal downward instead of to the right. It kept the task API available but was rejected by the semantic and/or official policy, so the pack did not accept this known faulty candidate.

Two evaluator faults were then injected separately. Modifying one byte of the official test and selecting a nonexistent compiler both produced INVALID, never -1, which keeps infrastructure and evidence failures out of candidate reward.

| Check | Result | Decision |
|---|---:|---|
| API-compatible semantic mutant | Killed | Known fault rejected |
| Actual midbreak-RL-v2 failed output | Rejected by the added task-specific policies | Observed eval fault reached a -1 boundary |
| Modified official test | INVALID | Contract tampering detected |
| Missing compiler | INVALID | Infrastructure fault not charged to candidate |
| Surviving controlled mutants | 0/1 | No known false positive |

## Step 3: Repeatability and GRPO readiness

Every policy was rerun from a new empty output directory. The second run again passed 15/15 kernels, and candidate-source digests stayed identical across all policies, proving deterministic decisions and source immutability for this campaign.

Policies 1, 2, 4, and 5 provide granular +1/-1 reward signals. Policy 3 is mandatory for terminal correctness because it authenticates and executes the complete official suite; a candidate cannot be called correct from compile or partial semantic checks alone.

| Check | Result | Decision |
|---|---:|---|
| Repeat run | 15/15 kernels passed | Deterministic decision |
| Candidate-source digest | Stable across 5/5 policies | Source remained immutable |
| Receipt creation | Complete for pass, fail, and INVALID paths | Evidence is machine-readable |
| Terminal rule | Policy 3 requires 3/3 | Full official success is mandatory |

## Final conclusion

The Spiral Matrix package is READY as a verifier layer for the pinned canonical task. It passed reference, harmless-change, mutation, evaluator-fault, repeatability, and immutability controls, and its authenticated official suite blocks known faulty answers from terminal success. Fast API and semantic kernels can provide GRPO sample rewards; live reward-worker wiring and production-scale throughput remain separate integration checks.
