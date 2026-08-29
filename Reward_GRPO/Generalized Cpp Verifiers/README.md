# Generalized C++ verifier pack

This directory is the trusted policy pack used by
`Reward_GRPO/global_cpp_verifier_runner.py`. It contains seven task-agnostic
wrappers, a manifest validator, and a receipt-binding helper. The engines live
in `generalized_verifier_docs/`; task-specific facts live in an authenticated
manifest and fixture directory.

## Policies

| Policy | Role | Result |
|---|---|---|
| G01 | Structural API gate | Required declarations derived from the official test |
| G02 | Two-stage build | Candidate compile, test compile, and link classification |
| G03 | Differential semantics | Reference positive control and assertion score |
| G04 | Response integrity | OK, EMPTY, LOOP, or TRUNCATED |
| G05 | Candidate boundary | Editable-file enforcement and omitted-file reconstruction |
| G06 | Warning hygiene | Compiler diagnostic classification |
| G07 | Sanitizer safety | ASan/UBSan diagnostic, separate from semantic aggregation |

The `live` profile runs G01-G05. The `full` profile adds diagnostic policies
G06 and G07. Every wrapper re-authenticates the manifest digest and candidate
source before writing a schema-version-2 receipt. The runner validates those
bindings again and emits one aggregate receipt.

## Clean-checkout validation

The committed 6-by-3 engine matrix uses only the compact fixtures under
`generalized_verifier_docs/validation/fixtures/`:

```bash
bash generalized_verifier_docs/validation/run_all.sh
```

It covers positive, fault, and tamper controls for structural, build,
semantic, response-integrity, candidate-boundary, and warning engines.
Generated receipts are written to a temporary directory, not committed.

For the production-style container boundary, using the locally installed
verifier image:

```bash
bash generalized_verifier_docs/validation/run_sandboxed.sh
```

The script resolves the configured image to an immutable image ID before
execution and records that ID and the sandbox controls in its receipt.

Repository integration tests cover the hermetic matrix, both runner outcomes,
all seven policies, candidate immutability, and manifest rejection:

```bash
python3 -m pytest -q tests/test_generalized_cpp_verifiers.py
```

## Direct runner

From the repository root:

```bash
MANIFEST="Reward_GRPO/Generalized Cpp Verifiers/generalized_verifier_manifest.example.json"
DIGEST=$(sha256sum "$MANIFEST" | cut -d' ' -f1)

python3 Reward_GRPO/global_cpp_verifier_runner.py \
  --candidate-dir generalized_verifier_docs/validation/fixtures/arithmetic \
  --manifest "$MANIFEST" \
  --expected-manifest-sha256 "$DIGEST" \
  --output-dir /tmp/generalized-verifier-run \
  --reward-root Reward_GRPO \
  --profile full
```

Exit code 0 means the requested profile passed, 1 means a trustworthy candidate
failure, and 2 means invalid evaluator evidence.

## Production boundary

The arithmetic fixture is a small smoke test for wiring and receipt integrity;
it is not evidence that arbitrary tasks are correctly specified. A production
task must supply its own official test, reference implementation, candidate
file list, raw response, and an out-of-band manifest digest. Candidate,
manifest, reward root, and output paths must remain separate.
