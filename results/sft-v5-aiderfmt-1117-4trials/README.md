# SFT v5

## Results

- Pass@1 trials: `8, 4, 6, 6`
- Mean Pass@1: **6/26 (23.1%)**
- Pass@1 variability: **SD 1.63; range 4-8; 95% CI 3-9.25**
- Multi turn with feedback (turn=2) trials: `12, 10, 11, 8`
- Mean multi turn with feedback (turn=2): **10.25/26 (39.4%)**
- Multi turn variability: **SD 1.71; range 8-12; 95% CI 7-13.75**
- Conditional turn-2 recovery: **17/80 (21.2%; 95% CI 11.9-31.6%)**
- Samples: **104**
- Statistics: [summary](../statistics.md) · [per-task frequencies](../per_task_success.csv)
- Checkpoint: [TokenBender/glm47-aider-sft-v5-aiderfmt-1117-3ep](https://huggingface.co/TokenBender/glm47-aider-sft-v5-aiderfmt-1117-3ep/tree/5d06951941a30939920fb2b7558aa95085531d52)
- Training dataset: [sft-v5-aiderfmt-1117-api-contracts.jsonl](https://huggingface.co/datasets/TokenBender/glm47-aider-posttraining-data/blob/6ef50c6fd1aca637c3df2df00c9aab4120140797/datasets/aiderfmt-api-contracts-20260727/sft/sft-v5-aiderfmt-1117-api-contracts.jsonl)
- Evaluation evidence: [fixed26 pass-8 archive](https://huggingface.co/datasets/WootzappLab/glm47-aider-fixed26-responses/tree/b47e31f014c4128cad19d625317229637f337996/evals/sft-v5-aiderfmt-1117-fixed26contract-pass8-20260727) (private; authorized HF access required; exact payload preserved)

The training-dataset link above is historical provenance. Its URL/hash mapping
remains unverified; it is not a verified current download instruction.

## How to reproduce

```bash
cd reproduction
./run.sh
```
