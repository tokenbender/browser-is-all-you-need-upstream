# Policy G05 — Candidate Boundary and Reconstruction

## Purpose

Enforce the editable-file contract on the parsed response and reconstruct omitted unchanged files from the task template, so partial responses are scored on their content rather than discarded.

| Kernel | Question | `+1` | `-1` | `INVALID` |
|---|---|---|---|---|
| G05-A | Does the response respect the editable-file boundary? | OK, or OK_WITH_MODIFICATIONS (omitted files filled from template and reported) | FORBIDDEN_FILE (unauthorized filename), DUPLICATE_FILE (conflicting listings), NO_FILES (no usable listing) | No response available or template unusable |

## Shared method

The response is parsed into whole-file listings. Filenames must belong to the manifest's editable set; duplicate listings are flagged (identical vs conflicting distinguished); editable files absent from the response keep template content and the fill is reported; unclosed trailing fences are classified as truncation rather than format failure.

## Aggregation

Single-kernel policy with an issue list in facts. Boundary violations are model failures; reconstruction is reported transparently and never silently.

## Execution

`python verifier_05_candidate_boundary.py --candidate-dir TASK --manifest MANIFEST --expected-manifest-sha256 DIGEST --output-dir OUT` (requires `trajectory` response in the manifest)

## Evidence

`generalized_verifier_docs/validation/VALIDATION_06.md` (13/13 agreement with recorded production verdicts across 4 task families; reconstruction reproduces the recorded downstream link error byte-identically).
