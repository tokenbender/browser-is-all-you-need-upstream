# R8 H100 GRPO result — 2026-08-14

## Claim boundary

This report records only the completed six-step R8 execution and Job 19's
first completed optimizer checkpoint. The profile is
`UNADMITTED_EXPERIMENT_ONLY`; every checkpoint remains
`QUARANTINE_ONLY`. Pre-training admission, the exact CHARM canary,
checkpoint selection, matched fixed-26 promotion evaluation, consumer
verification, and deployment certification are `NOT_COMPLETED`. A separate
raw-prompt fixed-26 evaluation completed in Job 30; it is reported below and is
not promotion evidence.

## Completed Run 21

Managed job 22 used base run:

```text
unadmitted-r8-r87-run21-20260814T030808Z
```

and durable attempt:

```text
unadmitted-r8-r87-run21-20260814T030808Z-attempt-20260814T031719Z-d951d40e
```

The terminal train marker records `status=passed`, `exit_code=0`, and
`checkpoint_disposition=QUARANTINE_ONLY`. The execution receipt records
source commit `19c68240991563e4ddbc0171485b1850101e7e2b`, immutable training
image `sha256:5df1c41efb6062a292ac68a49d68ad955d9f8209c182d3fc2f7e8c634ca076a2`,
`status=passed`, and completion at `2026-08-14T04:32:30.413207+00:00`.

The run used eight H100s with TP4/PP1/EP8, LoRA rank 16, six rollouts,
20 prompts per rollout, eight samples per prompt, global batch 160, and
learning rate `5e-7`. Its run receipt records `ray_status=0`, wall time
3,138 seconds, and peak memory 73,933 MiB.

### Training hyperparameters

| Hyperparameter | Job 22 value |
| --- | ---: |
| GPU topology | 8 x H100, TP4 / PP1 / EP8 / ETP1 |
| LoRA rank / alpha | 16 / 32 |
| Optimizer updates | 6 |
| Epochs | 3 |
| Training targets | 40 |
| Prompts per rollout | 20 |
| Samples per prompt | 8 |
| Global batch size | 160 |
| Learning rate | `5e-7` |
| KL loss / coefficient | enabled / `0.02` |
| Reference model | enabled |
| Sampling temperature | `0.7` |
| Maximum prompt length | 2,048 tokens |
| Maximum response length | 16,384 tokens |
| Packed sequence length | 34,816 tokens |
| Maximum tokens per GPU | 18,432 |
| Rollout shuffle | disabled |
| Thinking mode | enabled |
| Development targets / interval | 11 / every 6 updates |
| Checkpoint save interval | every update |

All optimizer steps 0 through 5 completed. At step 5:

| Metric | Value |
| --- | ---: |
| Training loss | `0.0002915225923061371` |
| KL loss | `0.014576050639152526` |
| Gradient norm | `0.10643636595899715` |
| Learning rate | `5e-7` |

The evidence summary records 960/960 rollout rows, 22/22
development-evaluation rows, 377 metrics, 26 metric events, and 26 reward
outcomes. The 11-row `full-v5-development` monitor changed as follows:

| Development metric | Eval 0 | Eval 5 |
| --- | ---: | ---: |
| Mean Hybrid45 reward | `-0.5681818181818182` | `-0.4090909090909091` |
| Missing-reward ratio | `0.0` | `0.0` |
| Truncation ratio | `0.0` | `0.0` |
| Repetition fraction | `0.0` | `0.0` |

This development monitor is not the official fixed-26 Aider benchmark and is
not promotion evidence.

Durable synchronization completed 51/51 cycles with no periodic failures.
Complete checkpoints `iter_0000000` through `iter_0000005` were published.
The final COMPLETE manifest SHA-256 is
`87f5df2c5329852ebd10da48d2e688dbc0c7ac73868532f922a0c8983bb7a0da`.
The final HF PEFT `adapter_model.bin` is 485,940,769 bytes with SHA-256
`7fb350de045fb1d476fefcdaeb59a5c69ea7f5e2fe744516b63e146f26d8bfc2`.

## Job 30 fixed-26 evaluation

Managed Job 30 evaluated Job 22 checkpoint `iter_0000005` with two attempts
per task. It completed with pass@1 `0/26`, pass@2 `4/26`, and all
`26/26` outputs well formed. The attempt-two-only passes were:

| Passing task | Topic area |
| --- | --- |
| `allergies` | bitmask-based classification |
| `complex-numbers` | complex-number arithmetic |
| `knapsack` | dynamic-programming optimization |
| `space-age` | numerical conversion and floating-point arithmetic |

This raw-prompt result ties the single raw base receipt and is not directly
comparable with the historical SFT prompt-overlay trials. It therefore proves
evaluation completion, not benchmark uplift or promotion eligibility.

## Job 19 first checkpoint

Managed job 19 used durable attempt:

```text
unadmitted-r8-r87-20260814T014330Z-attempt-20260814T015326Z-a8e0fd49
```

It completed initial development evaluation, the first 160-sample rollout,
optimizer step 0, and checkpoint `iter_0000000`. It then failed while
resuming SGLang memory:

```text
[torch_memory_saver.cpp] CUresult error: 2 (out of memory)
```

The run receipt records `status=failed`, `ray_status=1`, wall time 1,120
seconds, and peak memory 79,835 MiB. The exact command used resident trainer
mode (`--no-offload-train`), SGLang static memory fraction 0.60, and older
training image
`sha256:6f69ff6617a448c03ec990d33adff88f504b7394bc0a7ba2c73f179efd531cc6`.
The train-stage marker records exit 2 at `20260814T023504Z`.

Job 19 therefore proves the first optimizer/checkpoint boundary only. Run 21
is the completed six-step engineering execution. Neither result changes the
admission or promotion state.
