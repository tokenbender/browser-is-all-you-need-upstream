# Aider C++ SFT v5: 1,340-row, three-epoch run

This is the canonical reproduction record for the SFT v5 experiment. The
training corpus, checkpoint, responses, and receipts are access controlled.
The fixed-26 response archive excludes benchmark source trees, fixtures,
hidden tests, rubrics, and grader/oracle material.

## Immutable identities

| Item | Identity |
| --- | --- |
| Reproduction branch | `run/glm47-sft-v5-modal-3ep` |
| Training source | `0bb26d2d0b281ad0be623d650c21f9a83667ca32` |
| Canonical evaluation source | `33572c480776b1d13f1896e3282223159124bf4a` |
| Base model | `zai-org/GLM-4.7-Flash@7dd20894a642a0aa287e9827cb1a1f7f91386b67` |
| Dataset | [`TokenBender/glm47-aider-posttraining-data`](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/f21122d33f99e552aee0557699b5e3e71b6e12e5/datasets/sft-v5-experimental-1340) |
| Dataset revision | `f21122d33f99e552aee0557699b5e3e71b6e12e5` |
| Dataset manifest SHA-256 | `0906e1abcec775ca52362679fe39d83af9ac1744c984faf1125f4de0c7b2e130` |
| Train JSONL SHA-256 | `a01a07c9d4e2706683814a3d5afc2bcd47172ff92b08f15e2c673729f185bd66` |
| Training run | `glm47-aider-sft-v5-1340-modal-3ep-20260723T210506Z` |
| Final checkpoint | `iter_0000200` |
| Adapter SHA-256 | `bdd808bf98d26b467af7fec1a20d7ed6502bac0ffd50eae9cb6a1e702613daaa` |
| Adapter config SHA-256 | `0bd6d85f88fc42fefa52627b3c261f1ad58bb2c9519332ae8034dd5dffe2498e` |
| W&B | [`glm47-aider-sft-v5-1340-modal-3ep-20260723T210506Z`](https://wandb.ai/ahm-rimer/glm47-aider-v1-sft/runs/glm47-aider-sft-v5-1340-modal-3ep-20260723T210506Z) |
| Checkpoint repository | [`TokenBender/glm47-aider-sft-v5-1340-modal-3ep@43110cf`](https://huggingface.co/TokenBender/glm47-aider-sft-v5-1340-modal-3ep/tree/43110cf15fa9cd87373b726638bf80c8f08858ce) |
| Response repository | [`TokenBender/glm47-aider-fixed26-responses@53a7e4f`](https://huggingface.co/datasets/TokenBender/glm47-aider-fixed26-responses/tree/53a7e4f41b72bdbe7c67db4408bca6796d33ceb3/evals/sft-v5-experimental-1340-3ep-fixed26-20260723) |

## Training configuration

- 1,340 rows, shuffled once per epoch; 3 epochs and 4,020 row exposures.
- 201 optimizer steps; global and rollout batch size 20; micro-batch size 1.
- Sequence length 4,096; dynamic token batching with 16,384 tokens per GPU.
- LoRA rank 16 and alpha 32.
- Eight H100 GPUs; tensor parallel 4 and expert parallel 8.
- Wall time 1,786 seconds; recorded peak device memory 65,407 MiB.
- The evidence logger retained 4,020 SFT rollout/sample rows. Its timing
  verification field is `unverified`; this does not change the terminal
  training receipt or checkpoint identity.

The exact launch was:

```bash
run_id=glm47-aider-sft-v5-1340-modal-3ep-20260723T210506Z
modal run --detach --timestamps --name "$run_id" \
  examples/modal/modal_app.py::sft \
  --run-id "$run_id" \
  --num-epoch 3 \
  --save-interval 67 \
  --data-dir /workspace/assets/prepared-v5-1340 \
  --seq-length 4096
```

Before launching, materialize the exact gated dataset revision at
`/workspace/assets/prepared-v5-1340`, then verify both SHA-256 values in the
table. Do not rebuild the corpus from floating inputs.

## Fixed-26 evaluation

The evaluation is pinned to Aider
`5dc9490bb35f9729ef2c95d00a19ccd30c26339c` and Polyglot
`7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`, with whole-file edits,
temperature 0.7, top-p 1.0, and at most two assisted attempts. It ran as two
TP4 shards on eight H100 GPUs.

```bash
modal run --detach --timestamps examples/modal/aider_eval_app.py \
  --run-id glm47-aider-sft-v5-1340-modal-3ep-fixed26-20260723T221500Z \
  --adapter-path /runs/glm47-aider-sft-v5-1340-modal-3ep-20260723T210506Z/checkpoints/sft_lora_r16/iter_0000200/adapter \
  --adapter-sha256 bdd808bf98d26b467af7fec1a20d7ed6502bac0ffd50eae9cb6a1e702613daaa \
  --training-data-manifest-sha256 0906e1abcec775ca52362679fe39d83af9ac1744c984faf1125f4de0c7b2e130 \
  --expected-training-phase sft
```

The terminal result is 2/26 on the first attempt and 5/26 by the second
assisted attempt. All 26 tasks are terminal and well formed. There are no
malformed responses or test timeouts; two outputs report errors and two
attempts exhaust their context windows. The run consumed 1,003,126 prompt
tokens and 677,481 completion tokens.

| Task | Attempt outcomes |
| --- | --- |
| allergies | fail, pass |
| grade-school | pass |
| knapsack | fail, pass |
| linked-list | pass |
| space-age | fail, pass |
| Remaining 21 tasks | fail, fail |

The two single-turn passes short-circuit the second attempt, hence 50 emitted
attempts rather than the maximum 52.

## Provenance correction

The manually authored post-training gate recorded source commit `7a81e71`.
The launch directory and commit timestamps establish that the training source
was `0bb26d2`: that commit was created at `2026-07-23T21:04:46Z`, immediately
before the detached launch at `2026-07-23T21:05Z`. The original gate and
completed evaluation receipt remain unchanged. A separate correction receipt
is stored in Git, the checkpoint repository, and the response corpus. Adapter
and dataset SHA-256 bindings are unaffected.

## Preserve and verify

With authenticated access, rerun the publication and remote round-trip checks:

```bash
python3 scripts/preserve_sft_v5_run.py \
  --results-root /path/to/glm47-aider-sft-v5-1340-modal-3ep-fixed26-20260723T221500Z \
  --checkpoint-root /path/to/iter_0000200/adapter \
  --training-root /path/to/sft_lora_r16 \
  --output docs/receipts/glm47-aider-sft-v5-1340-preservation.json
```

The publisher validates all 26 response/result pairs and observed scores,
constructs a deterministic archive, enforces private manual gating, uploads
the checkpoint and evidence, and downloads the critical files again to verify
their hashes. It is idempotent for an already-catalogued response evaluation.
Add `--verify-only` to perform the local identity, response-count, score, and
publication-boundary checks without changing either Hugging Face repository.
