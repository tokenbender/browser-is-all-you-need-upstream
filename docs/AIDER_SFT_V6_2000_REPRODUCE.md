# Aider C++ SFT v6: audited 2,000-row corpus

SFT v6 is row-level train-ready. It has not yet been trained or evaluated, so
this record makes no model-improvement claim.

## Immutable identity

| Item | Identity |
| --- | --- |
| Base model tokenizer | `zai-org/GLM-4.7-Flash@7dd20894a642a0aa287e9827cb1a1f7f91386b67` |
| Gated dataset | [`TokenBender/glm47-aider-posttraining-data`](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/tree/d52fbe24f5b629e732b4ba96bd7820f30da9e97d/datasets/sft-v6-audited-2000) |
| Dataset revision | `d52fbe24f5b629e732b4ba96bd7820f30da9e97d` |
| Package manifest SHA-256 | `04b51b576e34ba90355cee0268297a0ee9093da239fd98db346dd023ef8d8c32` |
| Train JSONL SHA-256 | `debe8081a7f780afa23942e7a0ab06358aeaaba6f6006557eb5cff93779d9995` |
| Checked-in builder SHA-256 | `a4e7f16bf20ef55b1820aed3f7a9b213298b25e35feb7eb3c4fc647a2a517db1` |
| Access boundary | Private, manual approval |

## Corpus contract

- 2,000 C++17 single-turn repository-edit rows in Aider whole-file format.
- 949 quality-cleared, target-distinct rows retained from the v5 lineage.
- 70 executable-verified first-pass capability rows.
- 3 previously unused answer-blind, sanitizer, starter-rejection, and
  mutation-adequate direct rows.
- 978 cross-family multi-file compositions. Both independent component test
  suites were replayed for every selected composition.
- A component parent appears at most five times; 509 distinct component
  parents are represented.

The final audit reports 2,000 unique task IDs, normalized prompts, normalized
answers, and normalized message pairs. All rows fit the exact pinned tokenizer:
the median is 1,496 tokens, p90 is 2,228, and the maximum is 4,013 under the
4,096-token limit. The review queue is empty. The fixed-26 task-ID overlap is
zero, and no fixed-26 answer, test, rubric, or grader state is included.

The 14-row rejection ledger contains only candidate compositions excluded by
the pre-execution token-limit gate. No rejected row is present in training.

## Download and verify

With approved Hugging Face access:

```bash
python3 scripts/download_assets.py aider-data --output-root /workspace/assets

data_root=/workspace/assets/aider-data/datasets/sft-v6-audited-2000/data
(cd "$data_root" && shasum -a 256 -c SHA256SUMS)
test "$(wc -l < "$data_root/sft/train.jsonl")" -eq 2000
test "$(shasum -a 256 "$data_root/sft/train.jsonl" | awk '{print $1}')" = \
  debe8081a7f780afa23942e7a0ab06358aeaaba6f6006557eb5cff93779d9995
```

## Rebuild from bundled sources

The gated package carries all 12 immutable input files needed by the builder,
including the 260 holistic executable tests and the candidate executable
receipts. Copy the inputs outside the output directory because a successful
build atomically replaces that directory.

```bash
python3 -m venv .venv-v6
. .venv-v6/bin/activate
pip install transformers

data_root=/workspace/assets/aider-data/datasets/sft-v6-audited-2000/data
input_root=$(mktemp -d /tmp/aider-sft-v6-inputs.XXXXXX)
cp -R "$data_root/inputs/." "$input_root/"

export AIDER_SFT_V6_INPUT_ROOT="$input_root"
export AIDER_SFT_V6_ARTIFACT_ROOT="$PWD/artifacts/aider-cpp-sft-v6-2000"
python3 scripts/build_aider_sft_v6_2000.py --workers 8

(cd "$AIDER_SFT_V6_ARTIFACT_ROOT/package" && \
  shasum -a 256 -c SHA256SUMS)
shasum -a 256 "$AIDER_SFT_V6_ARTIFACT_ROOT/package/sft/train.jsonl"
```

The verified cached rebuild completes without recompiling unchanged pairs and
must reproduce the train SHA-256 above. Removing
`artifacts/aider-cpp-sft-v6-2000/cache/composition_verification` forces a full
C++17 `-Wall -Wextra -Werror -pedantic` ASan/UBSan replay of both component
test suites for every selected composition.

## Training contract

The unchanged SFT profile is sequence length 4,096, global batch size 20, LoRA
rank 16 and alpha 32. With exactly 2,000 rows, every epoch consumes all rows:
100 optimizer steps per epoch, 300 steps for the recommended three-epoch run,
and no dropped tail.

Promotion requires a new checkpoint and the preserved external fixed-26
evaluation. Dataset quality gates alone do not establish checkpoint benefit.
