# R6 Hybrid45 formal evaluation

Audit performed: 2026-08-12
Report saved: 2026-08-13
Repository revision recorded by the run: `19c68240991563e4ddbc0171485b1850101e7e2b`
Audited experiment: `unadmitted-r6-v2-four-topic40-20260812T045951Z`
Decision: **experimental, unadmitted, quarantine-only**

## Purpose

This report preserves the detailed evaluation of the current R6 GRPO setup
against both of these reward and diagnostic designs:

- [Weighted45 V1](glm47-aider-weighted45-reward-rubrics.md), with 45 checks in
  nine five-check tiers; and
- [Hybrid45 V2](glm47-aider-hybrid45-context-isolated-rl-loop.md), with causal
  reachability, observation/applicability masks, semantic scoring, strict
  receipts, optimizer projection, and pre-optimizer signal gates.

The evaluation asks four separate questions:

1. Is the reward implementation internally correct?
2. Is the private verifier safe, deterministic, and sufficiently complete?
3. Does the optimizer receive valid and useful task-local signal?
4. Is there enough matched evidence to admit training or promote a checkpoint?

An affirmative answer to an earlier question does not answer a later one.
Local unit tests do not establish optimizer quality, an optimizer run does not
establish benchmark improvement, and benchmark improvement does not by itself
authorize deployment.

## Executive decision

The R6 Hybrid45 system is a credible and operational pilot. Its 45-kernel
receipt arithmetic, causal credit assignment, C++17 verifier, hidden semantic
partitions, sanitizer execution, infrastructure isolation, and quarantine
controls are well justified.

It is not production-ready or promotion-ready. The most important blockers are
enforcement and reproducibility defects rather than a defective Hybrid45
formula:

1. quantitative signal thresholds are enforced only before the first optimizer
   update;
2. duplicate logical tasks appear in every audited optimizer batch;
3. the complete 475-task execution path has not passed;
4. no completed R6 fixed-26 result was located in the evidence set examined for
   this audit;
5. the effective R6 source includes modified and untracked worktree bytes not
   fully identified by the recorded Git commit;
6. trainer-level advantage behavior, especially homogeneous groups, is not
   source-bound and deterministically proved; and
7. several context-isolation properties were verified retrospectively in the
   pilot tensors but are not all fail-closed checks in the batch validator.

The correct formal disposition remains:

| Status surface | Result |
| --- | --- |
| Reward formula implementation | Locally implemented and extensively tested |
| Exact 45-kernel rollout receipts | Replayed successfully for all 960 audited trajectories |
| Reduced optimizer pilot | Completed six updates |
| Full-corpus optimizer path | `not_completed` |
| CHARM training admission | `not_completed` |
| Canonical matched canary | `not_completed` |
| R6 fixed-26 benchmark evidence at audit cutoff | `not_completed` |
| Checkpoint promotion | `not_completed` |
| Deployment certification | `not_completed` |
| Artifact disposition | `QUARANTINE_ONLY` |

## Evidence rules used in the audit

### Evidence classes

Every finding was assigned one of four evidence classes.

| Class | Meaning |
| --- | --- |
| Locally executed | A command or deterministic test was rerun against the active worktree during the audit. |
| Stored execution evidence | A prior GPU run artifact, receipt, manifest, checkpoint marker, log, or tensor dump was inspected and replayed. |
| Historical comparison | A separately versioned earlier result was used only as context, never attributed to R6. |
| Not measured | Existing evidence cannot answer the question; a new instrumented run is required. |

Missing evidence was reported as `not_completed`. A score, clean compilation,
low loss, or earlier-stage PASS was not allowed to override a deterministic
hard failure.

### Evidence cutoff

The fixed-26 conclusion in this report means that no completed, attributable R6
fixed-26 receipt was found in the locations and objects examined at the audit
cutoff. If another document or later session refers to an R6 fixed-26 run, its
raw receipt, exact model and adapter identity, harness revision, task count,
attempt ledger, and artifact digests must be independently reconciled before
this status is changed.

### Reproducibility limitation

The active worktree was already substantially dirty. Relevant R6 profiles,
reward code, launchers, tests, and documents included modified or untracked
files. The run recorded Git revision `19c6824...`, but a revision alone cannot
reconstruct uncommitted bytes. This does not invalidate the archived run
receipts; it does prevent a strong claim that the run is reproducible from the
named commit.

## Analysis method

### 1. Contract review

The audit read the repository authority, Aider scope, CHARM admission rules,
Weighted45 and Hybrid45 specifications, R6 configurations, reward code, Miles
integration, parser, C++ harness, sandbox, dataset construction, launchers, and
relevant tests.

The proposed GRPO recommendations were mapped to the repository's real
contracts. Incompatible external assumptions were not imported silently. In
particular, this repository uses:

- Aider complete whole-file replacements, not SEARCH/REPLACE blocks;
- strict C++17, not a C++20 target contract;
- GCC as canonical executable evidence and Clang as AST/portability evidence;
- fixed versioned reward identity rather than epoch-dependent reward weights;
  and
- the official fixed-26 suite as evaluation-only material.

### 2. Static implementation inspection

The audit traced:

- the 25 static Weighted45 checks;
- the 20 executable checks and their harness evidence;
- Hybrid45 observation and applicability handling;
- tier-score, reachability, semantic, mixed-score, cap, and override arithmetic;
- exact receipt validation at the Miles boundary;
- signal-gate construction and persistence;
- compiler, linker, runtime, sanitizer, hidden-partition, and repeatability
  execution; and
- container isolation and workspace-snapshot behavior.

### 3. Local deterministic tests

The following checks were executed against the active worktree:

| Test | Result |
| --- | ---: |
| `python3 -m compileall -q src tests` | PASS |
| Full `pytest -q` suite | 577 passed, 4 failed |
| Focused reward/R6/harness suite | 226 passed, 2 failed |
| CHARM generation-readiness rule inventory | PASS |
| CHARM skill structural quick validation | PASS |

The focused suite included Weighted45, Hybrid45, AST17, header-only,
TSan/ASLR, Miles bridge, GCP profile, runtime build-stage, unadmitted-run, and
GRPO preservation tests.

### 4. Receipt and tensor replay

The audit retrieved and inspected the six-update pilot's:

- execution receipt and run log;
- six signal receipts;
- six checkpoint publication records;
- representative complete checkpoint marker;
- six raw rollout tensor dumps;
- initial and final development-evaluation tensors; and
- no-update reward controls.

The raw tensors were loaded with the safe `weights_only=True` path. For every
rollout, the audit reconstructed or checked task identity, prompt identity,
receipt shape, kernel values, observed/applicable maps, reward arithmetic,
format outcome, compilation outcome, finish behavior, and group membership.

### 5. Claim review

The final step compared the evidence with the CHARM claim ladder. Reduced-run
success was not allowed to stand in for full-corpus proof, fixed-26 proof,
promotion, or deployment.

## Local test failures

The full suite was not green. Four failures require explicit reconciliation.

| Failure | Finding | Effect |
| --- | --- | --- |
| Legacy fatal-parse expectation | The parser now attempts recovery for one unlabelled single-file fence; the test expects the old fatal-parse result. | Parser, reward reason, and test contract have drifted. |
| Provisioning policy | Test expects `STANDARD`; the effective R6 configuration selects `SPOT`. | Configuration and test are inconsistent. |
| CHARM transition representation | Test expects the former supersession field; implementation uses combined transition revisions. | Repository-wide transition test is stale or behavior is insufficiently migrated. |
| GRPO data guard | Test expects build-data protection in an old runner surface now delegated elsewhere. | Data reuse/overwrite protection must be proved at the current owner boundary. |

These failures do not change the replayed Hybrid45 arithmetic. They do block a
clean-release or frozen-source claim.

## Reward implementation assessment

### Weighted45 V1

Weighted45 evaluates nine tiers with five checks each. Twenty-five checks are
static and twenty require execution. Tier weights total `6.54`, and the V1
formula produces a normalized range of `-0.50` to `+1.00`.

Weighted45 remains valuable as:

- a complete diagnostic vector;
- a versioned historical policy;
- a task/reference proof target; and
- a way to preserve exact pass/fail evidence for every check.

Its main limitation for optimization is causal over-penalization: a candidate
that cannot compile cannot reach runtime or hidden tests, yet a naïve fixed
denominator can charge it repeatedly for consequences of one upstream defect.

### Hybrid45 V2

Hybrid45 retains all 45 identities but makes the optimizer projection causal.
It uses:

- bipolar per-kernel values;
- observed and applicable masks;
- nine normalized tier scores with weights totaling `1.0`;
- a discrete reachability score;
- a five-partition continuous semantic score;
- `R_mix = 0.50*B + 0.20*D + 0.30*C`; and
- hard safety, parse, compile/link, runtime/sanitizer, and full-pass overrides.

This design is justified because it retains full diagnostic evidence while
avoiding repeated optimizer punishment for unreachable stages. Infrastructure
failures are masked and abort the batch rather than becoming negative labels.

### Exact receipt replay

All 960 stored rollout receipts passed the replay checks:

| Check | Result |
| --- | ---: |
| Exact Hybrid45 receipt arithmetic | 960/960 |
| Score equals stored optimizer score | 960/960 |
| Missing or extra kernel identities | 0 |
| Non-finite optimizer rewards | 0 |
| Verifier infrastructure errors | 0 |
| Group size other than eight | 0 |
| Within-group task mismatch | 0 |
| Within-group prompt-hash mismatch | 0 |
| Duplicate response hash inside a group | 0 |

This is strong evidence for reward-record integrity in the reduced pilot. It
does not prove that every required batch-level property is currently enforced
before every optimizer step.

## Six-update pilot results

The pilot contained 20 task/prompt groups per update and eight candidates per
group, for 160 trajectories per update and 960 total trajectories.

### Signal metrics

| Update | Gate applied | Positive groups | Semantic variance | Reward variance | Kernel variance | Homogeneous groups | Exact format | Compile among parsed |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | Yes | 17 | 14 | 18 | 19 | 2 | 70.00% | 99.12% |
| 1 | No | 15 | 10 | 20 | 20 | 0 | 53.13% | 95.40% |
| 2 | No | 18 | 11 | 20 | 20 | 0 | 55.63% | 100.00% |
| 3 | No | 16 | 13 | 20 | 20 | 0 | 65.00% | 97.20% |
| 4 | No | 20 | 13 | 19 | 19 | 1 | 65.63% | 99.08% |
| 5 | No | 17 | 12 | 20 | 20 | 0 | 60.63% | 96.00% |

Every update met the configured numeric minima retrospectively. However, only
update 0 had `signal_requirements_applied=true`. The bridge uses the existence
of a prior signal receipt to disable quantitative enforcement. The later
receipts record metrics but do not fail the update when a metric falls below a
threshold.

The correct statement is therefore:

> All six batches were structurally validated and all six happened to meet the
> configured signal thresholds post-hoc; quantitative thresholds were enforced
> only for the first optimizer update.

It is incorrect to summarize this as six fully enforced gate passes.

### Duplicate logical tasks

Every update contained repeated logical task groups.

| Update | Groups | Unique logical tasks | Duplicate slots |
| ---: | ---: | ---: | ---: |
| 0 | 20 | 18 | 2 |
| 1 | 20 | 16 | 4 |
| 2 | 20 | 16 | 4 |
| 3 | 20 | 18 | 2 |
| 4 | 20 | 17 | 3 |
| 5 | 20 | 16 | 4 |

The configuration disabled the unique-group requirement. This was an active
policy relaxation, not merely a theoretical weakness. Duplicates reduce
effective task diversity, correlate group statistics, and weaken the meaning
of per-update coverage.

### Prompt and context checks

Retrospective replay found:

- exactly eight candidates in every group;
- one task identity and one prompt hash per group;
- no prompt mismatch inside any group;
- prompt lengths between 528 and 837 tokens in training;
- no training prompt above the proposed 2,048-token limit;
- development prompts between 527 and 1,366 tokens; and
- no duplicated response hash inside a group.

These observations support the pilot's context construction. The production
batch validator must still enforce and receipt byte-identical rendered
messages, independent workspace identities, response identities, train/monitor
disjointness, fixed-26 exclusion, private-marker exclusion, and token limits on
every update.

### Reward and length behavior

Raw per-update reward distributions remained finite and non-degenerate except
for three homogeneous groups out of 120. Training response truncation was:

| Update | Truncated samples | Rate |
| ---: | ---: | ---: |
| 0 | 15/160 | 9.38% |
| 1 | 17/160 | 10.63% |
| 2 | 12/160 | 7.50% |
| 3 | 24/160 | 15.00% |
| 4 | 20/160 | 12.50% |
| 5 | 20/160 | 12.50% |
| **Total** | **108/960** | **11.25%** |

This is a material failure mode. It should be diagnosed through finish reason,
location of the final-answer boundary, file completeness, token/repetition
telemetry, and task complexity. A raw reasoning-token penalty should not be
introduced before that diagnosis because it can reward short incomplete
answers.

### Optimizer telemetry

| Update | Raw reward mean | Mean response tokens | Gradient norm | Rollout-KL field | KL-loss field | PPO clip fraction |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | -0.09915 | 4,290 | 0.15551 | 0.17373 | 0.00000 | 0.0 |
| 1 | -0.25546 | 4,037 | 0.15312 | 0.15954 | 0.01379 | 0.0 |
| 2 | -0.08356 | 3,965 | 0.15821 | 0.17686 | 0.01435 | 0.0 |
| 3 | -0.14846 | 5,884 | 0.11672 | 0.16837 | 0.01499 | 0.0 |
| 4 | +0.03129 | 4,708 | 0.15182 | 0.16290 | 0.01400 | 0.0 |
| 5 | -0.18063 | 5,011 | 0.16136 | 0.16919 | 0.01485 | 0.0 |

All observed gradients were finite and well below the configured norm cap of
`1.0`. That supports short-run numerical stability.

It does not justify comparing the logged rollout-KL field directly with a
proposed policy/reference KL target of `0.035` or rollback ceiling of `0.12`.
The exact estimator and reference distribution must be source-bound first.
Similarly, zero PPO clip fraction is an observation, not proof that an imported
5-15% target is appropriate.

The run arguments identify standard GRPO rather than a verified mean-only Dr.
GRPO implementation. Exact homogeneous-group gradient behavior remains
unproved at the pinned trainer-source level. This matters because three
homogeneous groups actually occurred.

## Development evaluation

The task-disjoint development evaluation contained 60 samples before update 0
and 60 after update 5.

| Metric | Initial | Final | Interpretation |
| --- | ---: | ---: | --- |
| Mean Hybrid45 reward | -0.24583 | -0.24167 | +0.00417; too small and under-replicated for an improvement claim |
| Exact-format responses | 40/60 | 46/60 | Improved |
| Compiled parseable responses | 40/40 | 46/46 | Remained strong |
| Responses with positive tests | 20/60 | 25/60 | Improved partial semantics |
| Complete functional passes | 10/60 | 9/60 | Regressed by one |
| Truncated responses | 4/60 | 5/60 | Worsened by one |
| Repetition flags | 1/60 | 4/60 | Worsened |

The evidence is mixed. Formatting and partial semantic reachability improved,
but full correctness did not. One stochastic sample per prompt and one short
training run cannot establish statistical improvement or checkpoint promotion.

## C++ verifier assessment

### Justified surfaces

The verifier provides strong deterministic coverage:

- strict GCC C++17 syntax and compilation;
- `-Wall -Wextra -Werror -pedantic -pthread`;
- public type/API compilation and hidden-grader linkage;
- executable existence and bounded runtime;
- workspace before/after snapshots;
- unpredictable verifier handshake;
- five independently executed hidden partitions;
- ASan, UBSan, and leak detection;
- applicable TSan/concurrency execution;
- repeated execution and result-vector consistency; and
- fail-closed separation of verifier infrastructure faults.

The sandbox uses non-root execution, no network, a read-only root filesystem,
capability removal, no-new-privileges, PID/memory/CPU limits, and a restricted
scratch workspace.

### Remaining verifier gaps

1. The full concurrency/TSan route did not complete successfully for the full
   corpus attempt.
2. Public API check L2 is still primarily regular-expression presence logic;
   it is not the required AST-backed namespace/signature/template/qualifier
   manifest.
3. The five hidden partitions execute independently, but a digest-bound proof
   of disjointness, balance, and complete union coverage is missing.
4. Protected detailed infrastructure logs must be retained without exposing
   private grader details to model-facing feedback.

## Justified current design choices

| Choice | Decision | Reason |
| --- | --- | --- |
| Aider whole-file response format | Keep | It is the repository and benchmark contract. |
| Strict C++17 | Keep | It is the active public target; C++20 would change the task. |
| GCC canonical, Clang supplementary | Keep | Separates executable truth from portability/AST evidence. |
| Forty-five explicit kernels | Keep | Provides dense, attributable diagnostics. |
| Hybrid45 causal observation masks | Keep | Prevents repeated punishment for unreachable downstream stages. |
| Hard safety and runtime caps | Keep | Prevents semantic credit from offsetting unsafe behavior. |
| Infrastructure-abort behavior | Keep | Infrastructure faults must not become policy labels. |
| Five hidden semantic partitions | Keep | Supplies partial semantic signal instead of one all-or-nothing bit. |
| Group size eight | Keep for canary | Produced useful reward and kernel variance within memory limits. |
| Temperature 0.7 and top-p 1.0 | Keep for matched canary | Produced diverse responses without observed group response duplication. |
| Fixed reward identity | Keep | Preserves cross-update and cross-checkpoint comparability. |
| Style and response length as telemetry | Keep | Avoids allowing proxy quality to compensate for correctness. |
| Quarantine-only artifact handling | Keep | Matches the actual evidence level. |

## Required updates

### P0: before any further optimizer run

1. **Apply quantitative signal gates to every update.**
   Remove the prior-receipt shortcut. Every optimizer update must independently
   satisfy all frozen thresholds before weights change.

2. **Enforce unique logical tasks per update.**
   Use logical task lineage and variant identity, not only row IDs. Add a
   deterministic sampler test and a fail-closed batch check.

3. **Restore one authoritative exact-format threshold.**
   The Hybrid45 design specifies `0.50`; R6 uses `0.35`. All successful pilot
   updates exceeded `0.53`, so existing evidence supports restoring `0.50`.

4. **Freeze exact source bytes.**
   Commit or package the effective profiles, reward module, bridge, harness,
   parser, launchers, dataset manifest, trainer source, and tests. Record a
   deterministic aggregate digest in the execution receipt.

5. **Reconcile all four failing tests.**
   Decide explicitly which behavior is authoritative and update code,
   migrations, configurations, and tests together.

6. **Keep the next run quarantined.**
   Repairing these defects does not retroactively admit the existing pilot.

### P1: before training admission

1. Add per-batch prompt/message, workspace, response, split-membership,
   fixed-26 exclusion, private-marker, and token-limit receipts.
2. Replace regex-only public-API evidence with an AST-backed exact API manifest.
3. Prove hidden-partition disjointness, balance, determinism, and union coverage.
4. Digest-bind the exact trainer advantage implementation.
5. Add a deterministic homogeneous-group zero-gradient test.
6. Persist per-group reward mean, reward variance, advantage variance, maximum
   absolute advantage, and non-finite counters.
7. Complete a verifier-only no-update replay over all 475 selected tasks.
8. Repair the concurrent/TSan infrastructure path and rerun it independently.
9. Reduce truncation without increasing memory beyond the measured safe
   envelope.
10. Run the canonical matched canary with repeated trials and checkpoint-level
    compile, hidden-test, validation-loss, and training-loss records.

### P2: separate optimizer experiments

The following must not be folded silently into Hybrid45 V2:

- mean-only Dr. GRPO versus the currently pinned advantage estimator;
- a dynamic KL controller and rollback policy;
- hard likelihood-ratio bounds;
- changed PPO epoch/minibatch structure;
- a different learning-rate schedule;
- entropy or repetition stop boundaries; and
- latent/attention diagnostics.

Each changes a different causal variable and needs a new versioned experiment,
matched control, exact telemetry definition, and rollback rule.

## Disposition of the proposed recommendations

| Proposed recommendation | Disposition | Explanation |
| --- | --- | --- |
| SEARCH/REPLACE integrity gate | Reject | The target format is complete whole-file replacement. |
| C++20/Clang canonical compilation | Reject | Strict GCC C++17 is canonical; Clang is supplementary. |
| Group size `G=8` | Keep for canary | It gave adequate signal diversity and fit memory. |
| Mean-only/Dr. GRPO | Separate canary candidate | Requires trainer digest and homogeneous-group proof. |
| Homogeneous-group neutralization | Require | Constant-reward groups contain no relative preference signal. |
| Dynamic reward weights by phase | Reject for V2 | This changes reward identity during the run. |
| Format must pass in all eight samples | Monitor/stop target | A malformed candidate is a model outcome; aggregate gates govern optimizer admission. |
| ASan/UBSan/leak/TSan checks | Keep | They are executable correctness and safety evidence. |
| Clang-format or modularity bonus | Telemetry only | Style must not offset semantic failure. |
| Reasoning-token penalty | Reject from reward | It may reward premature incomplete responses. |
| Entropy floor `0.85` | Do not adopt | Definition and baseline are uncalibrated. |
| Hidden-state cosine floor `0.82` | Research only | Layer, pooling, reference, and task dependence are uncalibrated. |
| PPO clipping fraction 5-15% | Do not adopt as gate | No project evidence establishes this range. |
| KL target `0.035` and rollback `0.12` | Separate experiment | Current logged KL fields do not yet have equivalent semantics. |
| Increase peak LR to `2e-6` | Reject for current profile | A fourfold increase is unsupported by six updates. |
| Mine official fixed-26 traces into training | Prohibited | The suite is evaluation-only and isolated from model-facing data. |

## Diagnostics requiring a new instrumented run

The following were not recoverable from current artifacts:

- full-vocabulary per-token entropy and calibrated perplexity trajectories;
- exact policy/reference KL under a named estimator;
- likelihood-ratio distributions and hard-bound saturation;
- layer-specific hidden-state cosine drift;
- attention concentration or sink-token behavior;
- PCA/UMAP latent-space geometry;
- statistically meaningful multi-seed training effects;
- complete full-corpus concurrency/TSan behavior; and
- an attributable R6 fixed-26 pass@1/pass@2 result at the audit cutoff.

These remain `not_completed`. They must not be inferred from a scalar reward,
gradient norm, or local unit-test pass.

## Next-run acceptance checklist

Before launching another optimizer update, require one immutable bundle proving:

- [ ] exact committed or packaged source aggregate;
- [ ] model, adapter, tokenizer, template, image, task-manifest, and policy
      digests;
- [ ] no-update positive, compile-failure, parse-failure, no-op, safety, and
      infrastructure controls;
- [ ] all 475 task environments preflight without infrastructure error;
- [ ] exact group count and eight candidates per group;
- [ ] unique logical task per group slot;
- [ ] byte-identical initial messages inside each group;
- [ ] isolated candidate workspaces and response identities;
- [ ] zero train/monitor/fixed-26/private overlap;
- [ ] zero prompt truncation and a frozen response-truncation policy;
- [ ] complete exact 45-kernel receipts;
- [ ] finite reward, advantage, ratio, KL, loss, and gradient telemetry;
- [ ] signal thresholds applied on this update, irrespective of earlier
      receipts;
- [ ] homogeneous groups recorded and proved to contribute zero gradient;
- [ ] failed infrastructure aborts before optimization;
- [ ] checkpoint artifact publication is atomic and manifest-verified; and
- [ ] output remains explicitly unadmitted and quarantined unless the separate
      admission stage passes.

## Final formal finding

The current reward/verifier architecture is moving in the correct direction.
The central Hybrid45 mathematics does not need to be replaced by the proposed
four-tier dynamic reward. The immediate requirement is to make the stated
controls genuinely enforceable, immutable, and independently reproducible.

Until every-update signal gates, unique sampling, full-corpus infrastructure,
source binding, trainer advantage proof, matched canary evidence, and external
evaluation are complete, R6 remains:

```text
experimental
unadmitted
quarantine-only
not promoted
not deployment-certified
```
