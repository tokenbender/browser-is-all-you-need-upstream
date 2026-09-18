# Policy G03 — Differential Semantic

## Purpose

Require successful official-test execution against a healthy reference. Counts can shape failed-candidate feedback only after completed execution; they cannot authenticate PASS.

| Kernel | PASS | FAIL / not_run | INVALID |
|---|---|---|---|
| G03-1 | Reference officially completes with healthy exit and passing assertions | Never blame candidate for reference failure | Reference missing, broken or unusable |
| G03-2 | Candidate officially completes, verified_pass is true, exits agree and no timeout/crash occurred | Candidate failure; build failure is not_run because G02 owns it | Malformed/inconsistent engine evidence or runtime infrastructure failure |

## Shared method

The fixture reference (`.meta/example.*`) is built and run first. A broken
reference invalidates the comparison. The trusted harness entry point is wrapped;
a separate completion pipe and process status witness its return. Candidate stdout
and rounded assertion fractions cannot prove completion. This is an execution
check, not security isolation from arbitrary native code. Worker containment is
still required. Runtime INVALID needs launcher evidence, not candidate-written
loader/resource-error phrases.

## Aggregation

Two binary kernels separate reference integrity and candidate semantics. Failed
but completed executions can expose an exact, bounded diagnostic fraction for
reward projection; it remains below full correctness and is never rounded to PASS.
Timeout cleanup kills the process group and bounds output drain/reap to 250 ms each.

## Execution

`python verifier_03_differential_semantic.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT` (requires `fixture_dir` in the manifest)

## Evidence boundary

The previous release cited the following historical evidence (not bundled or
revalidated by this focused PR):

> The committed reference scores 1.0 and the semantic-fault candidate scores 0.5 with a named failing case; the direct-runner pytest verifies this remains a model failure rather than INVALID.

For current implementation checks, run the repository's hermetic
`generalized_verifier_docs/validation/self_check.py` and
`tests/test_generalized_cpp_reward_reliability.py`. Synthetic local checks do not
establish those historical counts or full benchmark/task coverage.
