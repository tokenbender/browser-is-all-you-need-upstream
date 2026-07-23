# Aider C++ SFT defect inventory

Updated: `2026-07-24T00:00:00Z`

## Decision contract

This inventory records defects; it does not claim that they are fixed. A checkpoint is not promotable from training loss alone.

- Corpus floor: **790 unique packaged rows**.
- Current v4 package: **790 rows**.
- Current consumption: **780 rows per epoch**.
- Required consumption: **790 rows per epoch**.
- Replacement rule: Rows rejected as positive supervision must be repaired, replaced, or backfilled with independently verified rows. Quality work must not reduce the unique packaged corpus below 790. Tail-batch remediation must consume all rows or backfill; it must not shrink the corpus to a convenient multiple.
- RL rollout settings are outside this inventory and are unchanged.

## Inventory summary

- 55 recorded defects: 17 dataset, 7 loader, 10 training, 7 behavior, 7 evaluation, 7 observability.
- Severity: 10 critical, 31 high, 14 medium.
- Evidence status: 49 confirmed, 6 risk.

## Dataset and outcome history

| Stage | Unique packaged | Consumed / epoch | Epochs | First-turn | Assisted by attempt 2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| sft-v1 | 321 | 320 | 1 | 1/26 | 5/26 |
| sft-v2 | 1211 | 1184 | 1 | 1/26 | 6/26 |
| sft-v3 | 530 | 520 | 1 | 0/26 | 7/26 |
| sft-v4-1ep | 790 | 780 | 1 | 1/26 | 4/26 |
| sft-v4-3ep | 790 | 780 | 3 | 0/26 | 6/26 |

## Raw-715 audit receipt

| Check | Count |
| --- | ---: |
| Total | 715 |
| Train-ready | 0 |
| Review | 643 |
| Reject | 72 |
| Compile pass / fail | 690 / 25 |
| Contradictory pairs | 40 |
| Gold conflicts | 7 |
| Unresolved lineage | 104 |
| Missing examples | 60 |
| Dense or minified answers | 606 |
| Independent semantic receipts | 0 |

## Defects

### Behavior

#### B001 — critical — confirmed

**Finding.** The observed first-turn frontier is only 1 of 26 tasks.

**Evidence.** [run_registry](../docs/aider_posttraining_runs.json), [v4_1ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/4b888cd8ae024f1e90003b2b45a3c097603d66bb/evals/sft-v4-holistic-790-fixed26-20260723), [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Prioritize first-turn interface fidelity and executable correctness targets.

**Acceptance test.** A promoted checkpoint exceeds 1/26 first-turn passes under the frozen harness.

#### B002 — high — confirmed

**Finding.** Assisted performance varies non-monotonically across SFT versions and epochs.

**Evidence.** [run_registry](../docs/aider_posttraining_runs.json), [v4_1ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/4b888cd8ae024f1e90003b2b45a3c097603d66bb/evals/sft-v4-holistic-790-fixed26-20260723), [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Use task-level regression gates, not aggregate score alone.

**Acceptance test.** Promotion reports recovered, retained, and regressed tasks.

#### B003 — medium — confirmed

**Finding.** Some repair attempts exhaust context or fail to converge after feedback.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Train concise diagnosis-to-patch examples and measure context use.

**Acceptance test.** Repair traces remain within the declared budget and improve executable outcomes.

#### B004 — high — confirmed

**Finding.** Well-formed output is much more common than executable success.

**Evidence.** [run_registry](../docs/aider_posttraining_runs.json), [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Separate formatting supervision from compile, interface, and semantic targets.

**Acceptance test.** Evaluation reports format, compile, interface, test, and semantic stages separately.

#### B005 — critical — confirmed

**Finding.** Sixteen of twenty terminal v4 three-epoch failures are interface or compile-contract failures.

**Evidence.** [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Add verified examples that preserve exact headers, types, symbols, ownership, and template visibility.

**Acceptance test.** Contract-failure count falls on held-out tasks without semantic regression.

#### B006 — high — confirmed

**Finding.** Four terminal v4 three-epoch failures are semantic rather than interface failures.

**Evidence.** [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Add independently verified semantic edge-case coverage.

**Acceptance test.** Bank-account, dnd-character, yacht, and zebra-puzzle failure classes have targeted held-out analogues.

#### B007 — high — confirmed

**Finding.** No completed SFT checkpoint dominates both first-turn and assisted outcomes: v3 leads assisted at 7/26, while v1, v2, and v4 one-epoch share the 1/26 first-turn frontier.

**Evidence.** [run_registry](../docs/aider_posttraining_runs.json), [v3_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/d817c418b29eae23a97a83c70c896b56296b330c/evals/sft-v3-fixed26-20260721), [v4_1ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/4b888cd8ae024f1e90003b2b45a3c097603d66bb/evals/sft-v4-holistic-790-fixed26-20260723), [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Use a predeclared multi-metric promotion rule with retained-task gates.

**Acceptance test.** The selected checkpoint satisfies the rule without hiding a regression in the other metric.

### Dataset

#### D001 — critical — confirmed

**Finding.** The raw-715 audit found zero rows ready for training without review.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Reverify every retained row and record an executable semantic receipt.

**Acceptance test.** Every positive row has a passing row-level receipt and an explicit disposition.

#### D002 — critical — confirmed

**Finding.** Seventy-two raw-715 rows are classified reject.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Remove them from positive supervision only after one-for-one repair, replacement, or backfill.

**Acceptance test.** No rejected row remains positive and the packaged dataset still contains at least 790 unique rows.

#### D003 — high — confirmed

**Finding.** Six hundred forty-three raw-715 rows remain review-only.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Resolve review rows with compile, test, interface, and semantic checks.

**Acceptance test.** No review-only row is silently promoted to positive supervision.

#### D004 — high — confirmed

**Finding.** Twenty-five raw-715 answers fail compilation.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Repair or replace each compile-failing answer.

**Acceptance test.** All positive answers compile in their declared fixture.

#### D005 — critical — confirmed

**Finding.** The audit contains 40 contradictory prompt pairs.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Resolve each pair using executable correctness and provenance.

**Acceptance test.** No normalized prompt maps to incompatible positive targets.

#### D006 — critical — confirmed

**Finding.** Seven rows conflict with Gold targets.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Adjudicate conflicts and retain only the verified target.

**Acceptance test.** Every Gold conflict has a decision, receipt, and superseded-row link.

#### D007 — high — confirmed

**Finding.** One hundred four raw-715 rows have unresolved lineage.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Attach immutable source, transform, and parent identifiers.

**Acceptance test.** Every positive row has reconstructable lineage.

#### D008 — high — confirmed

**Finding.** Sixty raw-715 records lack the example needed to audit the target.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Restore the missing fixture or replace the row.

**Acceptance test.** Each positive row is self-contained enough for deterministic replay.

#### D009 — medium — confirmed

**Finding.** Six hundred six raw-715 answers are dense or minified, weakening edit pedagogy and auditability.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Normalize style without changing semantics, then replay verification.

**Acceptance test.** Style gates flag no unreadable positive target.

#### D010 — critical — confirmed

**Finding.** No raw-715 row has an independent row-level semantic receipt.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Generate immutable compile, test, sanitizer, and contract receipts per row.

**Acceptance test.** Receipt coverage equals positive-row count.

#### D011 — high — confirmed

**Finding.** Raw-715 supplies 81.71% of the 875-row raw-concat mixture that regressed from SFT v2.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Keep raw-715 out of positive mixtures until adjudicated.

**Acceptance test.** Promotion tests show no first-turn or assisted regression versus the declared baseline.

#### D012 — high — confirmed

**Finding.** The v4 package verifies the 260 new rows strongly, but does not independently replay all 530 inherited rows.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_data](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/c0db40db76fb16014103d131335fb15a2c0cfd19/datasets/sft-v4-holistic-790)

**Remediation.** Replay the same strict checks over inherited and new rows.

**Acceptance test.** All 790 rows pass one uniform verification pipeline.

#### D013 — high — risk

**Finding.** Exact fixed-26 overlap is zero, but semantic contamination has not been fully excluded.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Run AST, behavior, and problem-concept similarity audits against fixed-26.

**Acceptance test.** Every near match is adjudicated and held-out claims exclude contaminated rows.

#### D014 — critical — confirmed

**Finding.** Quality filtering can falsely improve audit rates by shrinking the 790-row corpus.

**Evidence.** [inventory_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/38), [v4_data](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/c0db40db76fb16014103d131335fb15a2c0cfd19/datasets/sft-v4-holistic-790)

**Remediation.** Enforce repair, replacement, or backfill for every rejected positive row.

**Acceptance test.** The verified unique packaged corpus remains at least 790 rows after every intervention.

#### D015 — high — confirmed

**Finding.** All 715 raw rows were exposed as usable by the earlier API even though the later audit found zero train-ready rows.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Make the audited disposition authoritative and remove permissive legacy labels.

**Acceptance test.** No consumer can select a row as positive when its current audited disposition is review or reject.

#### D016 — high — risk

**Finding.** Seven hundred five of 715 raw answers share the same curriculum namespace, indicating a highly concentrated generation lineage.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Measure generator, template, and solution-family diversity before treating row count as independent coverage.

**Acceptance test.** The corpus report separates unique behavioral coverage from repeated generator style.

#### D017 — high — confirmed

**Finding.** The 600-row pass1-skills mixture achieved 0/26 first-turn and 2/26 assisted passes, so its added skill rows did not transfer under that run.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Audit the skill labels, target correctness, and mixture weights before reuse.

**Acceptance test.** A matched ablation shows positive first-turn transfer before this mixture is promoted.

### Evaluation

#### E001 — high — confirmed

**Finding.** The repository label pass@2 denotes sequential feedback-assisted repair, not two independent samples.

**Evidence.** [run_registry](../docs/aider_posttraining_runs.json), [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37)

**Remediation.** Rename the metric assisted-pass-by-attempt-2 in new reports while preserving legacy mapping.

**Acceptance test.** No report conflates assisted repair with independent pass@k.

#### E002 — high — risk

**Finding.** Repeated tuning on the fixed 26 tasks risks adaptive benchmark overfitting.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [run_registry](../docs/aider_posttraining_runs.json)

**Remediation.** Use fixed-26 for regression and add an untouched promotion set.

**Acceptance test.** Final promotion is decided on a predeclared untouched split.

#### E003 — medium — confirmed

**Finding.** Aggregate scores lack uncertainty estimates despite sampling at temperature 0.7.

**Evidence.** [run_registry](../docs/aider_posttraining_runs.json)

**Remediation.** Run independent seeds or trials and report intervals.

**Acceptance test.** Promotion evidence includes uncertainty or is explicitly labeled deterministic/single-trial.

#### E004 — high — confirmed

**Finding.** At least one prior evaluation was invalid and had to be excluded because of harness failure.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37)

**Remediation.** Make harness validity a hard precondition with receipts.

**Acceptance test.** Every score has task count, response count, parser, compile, and test integrity checks.

#### E005 — medium — confirmed

**Finding.** SFT v2 produced two malformed responses and only 25 well-formed tasks.

**Evidence.** [run_registry](../docs/aider_posttraining_runs.json)

**Remediation.** Retain malformed-output accounting as a promotion gate.

**Acceptance test.** All 26 tasks have auditable response artifacts and format outcomes.

#### E006 — high — risk

**Finding.** Task transition tables are descriptive but are not yet enforced as regression gates.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Encode retained-win and maximum-regression thresholds.

**Acceptance test.** CI rejects a candidate that violates the predeclared task-level gate.

#### E007 — medium — confirmed

**Finding.** Post-hoc minimal corrections derived from failed responses are useful error analysis but are not independent evidence of model capability.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Store analyst corrections separately and test any resulting data on untouched tasks.

**Acceptance test.** Reports label observed model outputs, assisted attempts, and analyst-authored corrections as distinct artifacts.

### Loader

#### L001 — high — confirmed

**Finding.** SFT v1 consumed 320 of 321 packaged rows.

**Evidence.** [run_registry](../docs/aider_posttraining_runs.json)

**Remediation.** Make tail handling explicit and consume all unique rows.

**Acceptance test.** The epoch receipt accounts for all 321 row identities.

#### L002 — high — confirmed

**Finding.** SFT v2 consumed 1,184 of 1,211 packaged rows.

**Evidence.** [run_registry](../docs/aider_posttraining_runs.json)

**Remediation.** Use a non-dropping final batch or deterministic backfill.

**Acceptance test.** The epoch receipt accounts for all 1,211 row identities.

#### L003 — critical — confirmed

**Finding.** SFT v3 and both v4 schedules drop tail rows; v4 consumes 780 of 790 each epoch.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_1ep_wandb](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v4-holistic-790-lium-20260723T142220Z), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z)

**Remediation.** Consume the final ten rows without reducing the packaged dataset.

**Acceptance test.** Each v4 epoch accounts for 790 distinct row identities.

#### L004 — high — risk

**Finding.** Current receipts do not expose the row identities consumed at each optimizer step.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_1ep_wandb](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v4-holistic-790-lium-20260723T142220Z), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z)

**Remediation.** Log deterministic row IDs and packed-sample membership.

**Acceptance test.** A run can reconstruct row coverage and repetition per epoch.

#### L005 — high — risk

**Finding.** The corpus has no checked-in per-row token-length and truncation report.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_data](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/c0db40db76fb16014103d131335fb15a2c0cfd19/datasets/sft-v4-holistic-790)

**Remediation.** Record raw, rendered, packed, and truncated token counts per row.

**Acceptance test.** The report proves whether every target fits the training window.

#### L006 — medium — confirmed

**Finding.** Training is capped at 4,096 tokens while evaluation permits outputs up to 32,768 tokens.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Measure failure sensitivity to training-window coverage before changing the cap.

**Acceptance test.** A length-stratified evaluation quantifies the train/eval window mismatch.

#### L007 — medium — confirmed

**Finding.** The pass1-skills-600 experiment used a 3,072-token sequence length despite data fitting 4,096.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [data_catalog](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/0f0f69346eaeeb13401e57863efd33cc501e0922)

**Remediation.** Match sequence length when comparing data interventions.

**Acceptance test.** Ablations vary one declared factor and record the effective token cap.

### Observability

#### O001 — high — confirmed

**Finding.** The v4 one-epoch and three-epoch runs live under different W&B entities.

**Evidence.** [v4_1ep_wandb](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v4-holistic-790-lium-20260723T142220Z), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z)

**Remediation.** Use one controlled entity/project and record immutable run URLs.

**Acceptance test.** The project owner can access all promoted run histories.

#### O002 — medium — confirmed

**Finding.** The one-epoch W&B history duplicates steps 0 through 37.

**Evidence.** [v4_1ep_wandb](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v4-holistic-790-lium-20260723T142220Z), [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37)

**Remediation.** Use monotonic step keys and reject duplicate metric steps.

**Acceptance test.** History contains exactly one metric record per declared optimizer step.

#### O003 — medium — confirmed

**Finding.** The three-epoch run produced three local W&B resume directories under one run ID.

**Evidence.** [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z), [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37)

**Remediation.** Record resume lineage and a single canonical history.

**Acceptance test.** Run receipt enumerates sessions and proves lossless history merging.

#### O004 — medium — confirmed

**Finding.** The three-epoch shutdown logged transport or EOF errors despite successful HTTP upload responses.

**Evidence.** [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z), [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37)

**Remediation.** Add an explicit post-run sync and remote artifact verification gate.

**Acceptance test.** The receipt proves remote history and artifact completeness after shutdown.

#### O005 — high — confirmed

**Finding.** W&B contains no validation metrics for the v4 SFT runs.

**Evidence.** [v4_1ep_wandb](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v4-holistic-790-lium-20260723T142220Z), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z)

**Remediation.** Publish validation loss and executable validation tables.

**Acceptance test.** A promoted run has queryable validation metrics and samples.

#### O006 — medium — confirmed

**Finding.** Dataset revision, row manifest, training receipt, checkpoint, W&B run, and evaluation are not uniformly joined by one provenance record.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [run_registry](../docs/aider_posttraining_runs.json)

**Remediation.** Create one immutable run receipt that links every artifact and hash.

**Acceptance test.** A reviewer can traverse dataset to checkpoint to every response without inference.

#### O007 — high — confirmed

**Finding.** The current project account cannot access the W&B entity that owns the three-epoch run.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z)

**Remediation.** Mirror or transfer the run to the controlled project while preserving the original URL and run ID.

**Acceptance test.** The project owner and designated reviewers can query the complete remote history.

### Training

#### T001 — critical — confirmed

**Finding.** No disjoint validation split is reported for SFT training.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_1ep_wandb](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v4-holistic-790-lium-20260723T142220Z), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z)

**Remediation.** Create immutable train, validation, and fixed-26 holdout boundaries.

**Acceptance test.** Training receipts include non-overlapping split manifests.

#### T002 — high — confirmed

**Finding.** W&B reports training loss but no validation loss or executable validation score.

**Evidence.** [v4_1ep_wandb](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v4-holistic-790-lium-20260723T142220Z), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z)

**Remediation.** Log validation loss and first-turn executable metrics at fixed intervals.

**Acceptance test.** Every promoted run has synchronized train and validation curves.

#### T003 — high — confirmed

**Finding.** There is no evidence-based early stopping criterion.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z)

**Remediation.** Predeclare a validation-based checkpoint selection rule.

**Acceptance test.** Checkpoint choice follows the recorded rule rather than final-step convenience.

#### T004 — high — confirmed

**Finding.** Intermediate checkpoints from the three-epoch run were not all evaluated on fixed-26.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z), [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Evaluate each saved epoch or selected interval under one harness.

**Acceptance test.** A checkpoint-by-checkpoint table identifies the actual behavioral frontier.

#### T005 — high — confirmed

**Finding.** Schedule comparisons are not compute- and token-matched.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [run_registry](../docs/aider_posttraining_runs.json)

**Remediation.** Report seen tokens, optimizer updates, effective batches, and wall time.

**Acceptance test.** Comparative claims use matched budgets or state the confound.

#### T006 — high — confirmed

**Finding.** Data interventions have not been isolated from simultaneous schedule and sequence-length changes.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [run_registry](../docs/aider_posttraining_runs.json)

**Remediation.** Run one-factor ablations against a frozen recipe.

**Acceptance test.** Each ablation changes one declared variable.

#### T007 — medium — confirmed

**Finding.** Reported SFT benchmark results are single-seed measurements.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [run_registry](../docs/aider_posttraining_runs.json)

**Remediation.** Repeat promoted recipes with predeclared seeds.

**Acceptance test.** Results include dispersion or an explicit single-seed limitation.

#### T008 — medium — confirmed

**Finding.** V4 performs only 39 optimizer steps per epoch.

**Evidence.** [v4_1ep_wandb](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v4-holistic-790-lium-20260723T142220Z), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z)

**Remediation.** Interpret epoch count jointly with optimizer updates and tokens seen.

**Acceptance test.** Run summaries state all three quantities.

#### T009 — high — confirmed

**Finding.** Falling training loss did not produce a monotonic fixed-26 improvement, so undertraining is not established as the primary cause.

**Evidence.** [v4_1ep_wandb](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v4-holistic-790-lium-20260723T142220Z), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z), [v4_1ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/4b888cd8ae024f1e90003b2b45a3c097603d66bb/evals/sft-v4-holistic-790-fixed26-20260723), [v4_3ep_eval](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/1401f17c84d146b4cfa91bb67a6e625ea8cba2a9/evals/sft-v4-holistic-790-3ep-fixed26-20260723)

**Remediation.** Treat data-target alignment, validation, and checkpoint selection as competing diagnoses.

**Acceptance test.** Any undertraining claim is supported by matched learning curves and held-out improvement.

#### T010 — medium — confirmed

**Finding.** The three-epoch run reports a mean wait ratio of 54.67%, but the waiting source is not attributed in the run receipt.

**Evidence.** [master_issue](https://github.com/tokenbender/browser-is-all-you-need/issues/37), [v4_3ep_wandb](https://wandb.ai/sparmar27feb2003-nit-kurukshetra/glm47-pie-cpp-posttraining/runs/glm47-aider-sft-v4-holistic-790-modal-3ep-20260723T164628Z)

**Remediation.** Break wait time down by data loading, synchronization, checkpointing, and tracking.

**Acceptance test.** The next receipt attributes wait time and reports throughput from the same interval.

## V4 three-epoch terminal failure map

| Task | Failure class |
| --- | --- |
| all-your-base | interface or compile contract |
| allergies | interface or compile contract |
| bank-account | semantic |
| binary-search-tree | interface or compile contract |
| circular-buffer | interface or compile contract |
| clock | interface or compile contract |
| diamond | interface or compile contract |
| dnd-character | semantic |
| gigasecond | interface or compile contract |
| kindergarten-garden | interface or compile contract |
| linked-list | interface or compile contract |
| meetup | interface or compile contract |
| parallel-letter-frequency | interface or compile contract |
| perfect-numbers | interface or compile contract |
| phone-number | interface or compile contract |
| queen-attack | interface or compile contract |
| spiral-matrix | interface or compile contract |
| sublist | interface or compile contract |
| yacht | semantic |
| zebra-puzzle | semantic |

Assisted recoveries: `complex-numbers`, `crypto-square`, `grade-school`, `knapsack`, `robot-name`, `space-age`.

## Reproduce this inventory check

```bash
python3 scripts/verify_aider_sft_defect_inventory.py
```

The verifier checks the schema, evidence references, exact measured counts, failure taxonomy, report synchronization, and the 790-row non-shrink invariant.
