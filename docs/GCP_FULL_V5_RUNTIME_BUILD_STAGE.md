# Source-first full-v5 runtime build and GCS staging

The GCP full-v5 + CHARM profile requires the runtime to be built from the
pinned producer inputs before those verified bytes are copied to GCS. Access
to a prebuilt model-host artifact is not authorized or required by this path.
No VM or GPU is provisioned by the build helper.

## Required local material

Use branch 29july-aider-glm47-posttrain at exact revision
0efce27cd2c333f769afc74c9f9b852823256322. Prepare the private inputs under
one normalized root:

    v5/train.jsonl
    registry/manifest.json
    registry/rows.jsonl
    registry/targets.jsonl
    inventory/manifest.json
    inventory/executable.jsonl
    inventory/excluded.jsonl
    current-tasks/cpp/exercises/practice/...
    holistic-packages/<slug>/...
    exercism-cpp/exercises/practice/...
    exercism-cpp/exercises/concept/...
    signals/<family>/<task>/...
    split/split.jsonl

The exact input and output identities are recorded in
configs/full_v5_charm_grpo/runtime-producer-r1.json. The helper verifies the
file-level producer inputs before it builds. The deterministic runtime output
then binds the task source trees through its frozen manifest and tree hashes.

## Three deliberate phases

    export FULL_V5_PRODUCER_DIR=/path/to/browser-is-all-you-need-at-0efce27
    export FULL_V5_PRODUCER_INPUT_ROOT=/path/to/full-v5-private-producer-inputs
    export FULL_V5_RUNTIME_BUILD_ROOT=/path/to/fresh/full-v5-runtime-build

    bash scripts/gcp_full_v5_runtime_build_stage.sh preflight
    bash scripts/gcp_full_v5_runtime_build_stage.sh build
    bash scripts/gcp_full_v5_runtime_build_stage.sh stage

The preflight phase checks the producer revision, all required files and
directories, and every published file digest. The build phase creates the
615-target runtime, packages its deterministic archive, and independently
extracts and verifies it. The stage phase refuses to overwrite a non-empty GCS
prefix, uploads only the verified extracted runtime, downloads the GCS tree
again, rebuilds the deterministic archive, and requires the same frozen
identities.

The combined build-stage mode exists for automation, but the three separate
commands above are preferred for operator review.

## Current blocker

As of 2026-08-11, exhaustive local SHA-256 and GCP object-name audits found the
verified ep50 adapter but not the pinned private full-v5 producer inputs. The
GCS runtime destination is empty. Therefore:

- runtime materialization is NOT_COMPLETED;
- GCS staging is NOT_COMPLETED;
- the paid SkyPilot H100 smoke must not start.

Provide the normalized producer-input root locally or in GCS. A model-host
credential is neither requested nor authorized.
