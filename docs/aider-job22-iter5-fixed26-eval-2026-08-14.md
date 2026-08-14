# Aider fixed-26 audit — Job 22 final GRPO adapter

## Outcome

Managed Job 30, `job22-iter5-fixed26-v5-pathfix-20260814T071410Z`, completed a
two-attempt evaluation of Job 22's final GRPO LoRA adapter.

| Metric | Job 30 |
| --- | ---: |
| pass@1 | 0/26 |
| pass@2 | 4/26 |
| well formed | 26/26 |
| malformed | 0 |
| errors | 9 |
| context exhausted | 9 |
| timeouts | 0 |

The four second-attempt passes and their represented topic areas were:

| Passing task | Topic area |
| --- | --- |
| `allergies` | bitmask-based classification |
| `complex-numbers` | complex-number arithmetic |
| `knapsack` | dynamic-programming optimization |
| `space-age` | numerical conversion and floating-point arithmetic |

These were attempt-two-only passes; Job 30 had no first-attempt successes. The
run receipt status is `complete` and the durable GCS and local receipt bytes match
at SHA-256
`f630418b3f107ad8f7bec18617c22d30edbd822861b95f8dab8c6af0ca4e2c62`.

## Adapter identity

Job 22's final GRPO adapter is checkpoint `iter_0000005`, LoRA rank 16 and
alpha 32, SHA-256
`7fb350de045fb1d476fefcdaeb59a5c69ea7f5e2fe744516b63e146f26d8bfc2`.
It warm-started from the SynthMem v1 epoch-50 SFT adapter with SHA-256
`4acb7f23c295f45380155c5d9ee6bc59422262f0cb51f0c02f7e550d405b575a`.

## Comparison boundary

The historical SynthMem v1 epoch-50 SFT evaluation on
`client/5-aug-release` recorded four trials:

| Trial | pass@1 | pass@2 |
| --- | ---: | ---: |
| 1 | 10/26 | 11/26 |
| 2 | 9/26 | 13/26 |
| 3 | 10/26 | 12/26 |
| 4 | 9/26 | 12/26 |
| Mean | 9.5/26 | 12/26 |

The common shorthand “9 at pass@1 and 12 at pass@2” is therefore directionally
correct, but the exact pass@1 mean is 9.5.

This is not yet an apples-to-apples SFT-versus-GRPO comparison. The historical
SFT trials used the `fixed26-contract-v2` prompt overlay; Job 30 used the raw
fixed-26 prompts. Job 30 ties the single raw base receipt at pass@1 0/26 and
pass@2 4/26, while increasing errors/context exhaustion from 6 to 9. The audit
verdict is therefore `inconclusive`: no matched uplift is demonstrated, and a
causal regression claim is not justified until both checkpoints are evaluated
under the exact same task bytes, prompt overlay, harness, decoding controls,
and repeated-trial protocol.

## Provenance

- Aider revision: `5dc9490bb35f9729ef2c95d00a19ccd30c26339c`
- Polyglot revision: `7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`
- Training manifest SHA-256:
  `72296f7bae1b4690a613922f3f29b2011e4a8646d356a4e7663cfc5822e7bfd2`
- Attempts per task: 2
- Temperature: 0.7
- Top-p: 1
- Maximum response tokens: 32768
- Job 30 receipt SHA-256:
  `f630418b3f107ad8f7bec18617c22d30edbd822861b95f8dab8c6af0ca4e2c62`
- Job 22 execution-receipt SHA-256:
  `4db1d7f775cb6167c357aa172d5e6e3a259afa6662be40cdbd77d24dc8a87007`

Durable evaluation root:

```text
gs://lifeandhalf-24122025-w8-biayn/runs/glm47/evaluations/aider-fixed26/job22-iter5-fixed26-v5-pathfix-20260814T071410Z/
```

Job 22's training execution passed, but its admission remains `NOT_COMPLETED`,
CHARM eligibility remains false, and its checkpoint disposition remains
`QUARANTINE_ONLY`.
