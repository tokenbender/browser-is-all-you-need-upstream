# Policy 6 — Diamond Geometry and Byte-Exact Output

Policy 6 independently checks the complete A-Z output domain, including trailing spaces.

## Kernel table

| Kernel | Function | Verification | `+1` | `-1` | Evidence |
|---|---|---|---|---|---|
| 6A | `verify_6a_exact_anchor_outputs()` | Exact A, B, C, D, Z vectors | Every byte matches | Any anchor differs | Probe log and hashes |
| 6B | `verify_6b_square_dimensions()` | `2n+1` rows and bytes for A-Z | All dimensions match | Wrong row count/width | Case receipt |
| 6C | `verify_6c_spacing_and_glyph_counts()` | Outer/inner spacing and one/two-glyph rule | All positions match | Filled interior, trimming, or glyph-count error | First-mismatch receipt |
| 6D | `verify_6d_letter_order_and_center()` | Ascending top, requested center, descending bottom | Exact order | Missing/wrong center or order | Case receipt |
| 6E | `verify_6e_horizontal_vertical_symmetry()` | Reverse every row and row sequence | Both symmetries hold | Any asymmetry | Case receipt |
| 6F | `verify_6f_full_domain_oracle()` | Formula oracle for all 26 inputs | All vectors byte-identical | Any divergence | Expected/actual hashes and mismatch |

## Method and aggregation

Generated probes use the formula frozen in `diamond-setup.md` and never read `.meta/example.*`. Full pass is `+6`.

## Exclusions

Inputs outside uppercase A-Z are excluded. Output is never trimmed or normalized.

## Execution

```bash
python3 "Reward_GRPO/Diamond Verifiers/verifiers/verifier_06_diamond_geometry_relational_logic.py" --exercise-dir <diamond> --output-dir <new-output>
```
