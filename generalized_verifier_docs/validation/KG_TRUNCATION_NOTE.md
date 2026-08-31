# kindergarten-garden truncation note (verifier-v2, evidence from grpo_0..19.pt)

## Numbers

- 339/576 KG training rows (58.9%) hit the 8,192-token rollout cap
  (`status=truncated`, `response_length=8192`). Other tasks: crypto-square
  12.1%, clock 0.3%, grade-school 0.3%, complex-numbers / perfect-numbers 0%.
- Flat across the whole run — per-update truncation share 53%–69% from
  update 0 to update 19, no trend. KG never learns, because its rows never
  produce a deliverable: of the 237 non-truncated rows, 235 are G01-fail
  (-1.0), 1 forbidden_file, and exactly 1 row in 576 ever reached G02+.
- KG's prompt is NOT large: median prompt 1,083 tokens (grade-school 995,
  clock 1,087, perfect-numbers 1,169; only complex-numbers is bigger at
  1,666). Prompt/fixture size is not the mechanism.

## Mechanism

Response-side, not prompt-side. KG's task core is a combinatorial mapping:
a 48-plant diagram string -> 12 children x 4 cups via alphabetical seat
assignment across 2 rows x 24 positions. The model does not code this
directly; it hand-simulates the assignment in the reasoning channel,
enumerating "Alice (0): Row 0, Col 0 -> V / Bob (1): Row 0, Col 1 -> R ..."
for all 12 children, then re-derives it to cross-check, then drifts into
CJK re-phrasings of the same enumeration (90/339 KG truncations have a CJK
tail fraction >= 0.15 — semantic repetition that G04's exact-match LOOP
detectors cannot see; they classify it TRUNCATED).

The generation cap is shared between thinking and the answer channel, so
the enumeration burns the budget before the file listing is committed:
median 7 complete fenced blocks exist in the truncated text, but they are
analysis drafts, not `path + fence` whole-file listings, so the Aider
parser rejects the row (`invalid_format`, flat -0.8) and G01–G05 never run.
Median KG non-truncated response is 3,780 tokens vs 1,428–3,466 for other
tasks — even KG's "successful" generations are the longest in the
curriculum; KG simply lives closest to the cap.

crypto-square shows the same pattern in miniature (rectangle/grid
reasoning, 28/85 truncations with CJK drift), which supports this being a
task-shape effect (enumerate-the-grid tasks), not a fixture defect.

The eval side agrees: KG had 13 context-exhaustion events and 0/9 passes in
the Fixed26 trials — the same over-thinking failure at the 32k eval cap.

## Suggested curriculum-side fix

1. Prefer: raise the generation cap for KG (and grid-enumeration tasks
   generally) or give the answer channel a reserved budget, so a
   committed deliverable is at least possible; today the verifier never
   sees 59% of KG rows.
2. Alternatively drop or down-weight KG until the format contract is
   learned: its current training signal is 100% format/API penalties
   (-0.8 / -1.0) with zero semantic gradient, and its per-group advantage
   comes only from mixing those two penalties.
3. Do NOT treat KG truncations as loops for reward shaping: 0/339 are
   exact-match loops. They are productive-but-overlong generations
   (median 7 drafted code blocks), so the flat TRUNCATED -0.8 (with the
   G04 verdict now recorded, Fix 3) is the right penalty level; the fix
   belongs in the curriculum/serving config, not in harsher rewards.
