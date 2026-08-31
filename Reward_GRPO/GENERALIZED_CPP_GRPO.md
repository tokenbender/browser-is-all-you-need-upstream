# Generalized C++ GRPO vertical integration

`Reward_GRPO/generalized_cpp_grpo.py` is the custom-reward adapter. It resolves
the rollout's `metadata.problem_id` through
`Reward_GRPO/generalized_cpp_grpo_registry.json`, authenticates the base
manifest and protected fixture files, reconstructs an Aider whole-file
response over the registered starter files, runs the aggregate verifier, and
projects its receipt into a Miles `score` / `reward` record.

The checked-in `portable-arithmetic` entry is an end-to-end canary, not a
training curriculum. Run its import, registry, response, verifier, and reward
preflight with:

```bash
PYTHONPATH=src python3 -m Reward_GRPO.generalized_cpp_grpo preflight
```

Miles discovery variables for the adapter are:

```yaml
MILES_DATA_BUILD_MODULE: Reward_GRPO.generalized_cpp_grpo
MILES_CUSTOM_RM_PATH: Reward_GRPO.generalized_cpp_grpo.reward_func
MILES_REWARD_PREFLIGHT_MODULE: Reward_GRPO.generalized_cpp_grpo
GENERALIZED_CPP_VERIFIER_PROFILE: live
GENERALIZED_CPP_REWARD_WORKERS: "4"
```

`build-data` synthesizes an answer-free Aider shadow task tree from the
registry (starter files, official instructions, and the official test as the
integrity-pinned hidden test) and delegates to the repository's existing Aider
dataset builder, so the registry must contain every `problem_id` selected for
a run.  The checked-in curriculum is `generalized-cpp-v1` (six tasks; the
`portable-arithmetic` canary opts out with `"train": false`).  Regenerate the
registry and per-task manifests with:

```bash
python3 Reward_GRPO/build_generalized_cpp_grpo_manifests.py
```

The launch configuration is `Reward_GRPO/generalized_cpp_grpo_skypilot.yaml`.
Infrastructure invalids are marked and neutralized within a rollout/problem
group; malformed or forbidden model responses remain model-caused numeric
failures.

This vertical slice invokes the direct runner in the reward worker. Production
training must switch that invocation to the pinned offline sandbox launcher
before enabling untrusted rollouts outside an already-isolated worker.
