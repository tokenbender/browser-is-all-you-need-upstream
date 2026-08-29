# Global Verifiers Set 2

This directory contains exactly ten task-independent Python modules. Task facts
live only in authenticated bundles such as `task_bundle_example/`.

Mandatory live order: reconstruction, G01, dependency preflight, G02, G03, G04,
then receipt authentication. G05 and G07 are optional diagnostics. `FAIL` means
a healthy evaluator rejected the candidate; `INVALID` means no trustworthy
candidate judgment was possible; downstream policies use `NOT_RUN`.

Run the included canary from this directory:

```bash
python3 runner.py --executor host --full \
  --bundle task_bundle_example \
  --candidate task_bundle_example/starter \
  --output /tmp/global-verifiers-set2-receipt
```

Production runs should use the default Docker executor and a pinned image digest.
No task-specific Python verifier is permitted; onboarding changes only the task
bundle and its authenticated controls. G03 reads the protected `public_api.json`,
validates it with Clang AST, then compiles a trusted caller. Regex extraction from
official tests is intentionally not authoritative because it cannot model general C++.
