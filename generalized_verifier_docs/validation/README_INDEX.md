# Generalized verifier validation

The validation suite is intentionally hermetic and review-sized. All required
inputs are committed under `fixtures/`; it does not depend on local evaluation
corpora, absolute paths, or untracked `Reward_GRPO/multi_env_fixtures` data.

## Commands

- `bash generalized_verifier_docs/validation/run_all.sh` runs the 18 host
  controls and writes receipts to a temporary directory.
- `bash generalized_verifier_docs/validation/run_sandboxed.sh` runs the same
  matrix in the configured image using a read-only repository mount, no
  network, dropped capabilities, a non-root user, and an immutable resolved
  image ID.
- `python3 -m pytest -q tests/test_generalized_cpp_verifiers.py` checks the
  matrix plus the direct runner's positive and semantic-failure paths.

## Contents

- `self_check.py` orchestrates the engine CLIs and writes receipts.
- `self_check_cases.json` defines positive, fault, and tamper expectations.
- `fixtures/arithmetic/` is the minimal build and semantic oracle.
- `fixtures/candidates/` contains link, semantic, and namespace faults.
- `fixtures/responses/` and `fixtures/logs/` exercise non-build classifiers.
- `receipt_compat.py` converts engine verdicts to kernel receipts.

Generated reports and receipts are runtime artifacts and are deliberately not
stored in Git.
