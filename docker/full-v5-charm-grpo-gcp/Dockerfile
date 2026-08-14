ARG MILES_BASE_IMAGE=radixark/miles:latest-cu12@sha256:efc8027fc47aaa9687dc4f1046093ed4e2f9789e52a932fcefb7031402aeff37
FROM ${MILES_BASE_IMAGE}

ARG GLM47_FLASHINFER_VERSION=0.6.14
ARG GLM47_FLASHINFER_CUDA_INDEX=129
ENV FLASHINFER_VERSION=${GLM47_FLASHINFER_VERSION} \
    FLASHINFER_CUDA_INDEX=${GLM47_FLASHINFER_CUDA_INDEX}
RUN python3 -m pip install --no-cache-dir --no-deps --upgrade --force-reinstall \
      "flashinfer-python==${FLASHINFER_VERSION}" \
    && python3 -m pip install --no-cache-dir --no-deps --upgrade --force-reinstall \
      "flashinfer-cubin==${FLASHINFER_VERSION}" \
      --index-url "https://flashinfer.ai/whl" \
    && python3 -m pip install --no-cache-dir --no-deps --upgrade --force-reinstall \
      "flashinfer-jit-cache==${FLASHINFER_VERSION}" \
      --index-url "https://flashinfer.ai/whl/cu${FLASHINFER_CUDA_INDEX}" \
    && python3 -c 'import os; from importlib.metadata import version; expected = os.environ["FLASHINFER_VERSION"]; packages = ("flashinfer-python", "flashinfer-cubin", "flashinfer-jit-cache"); actual = {name: version(name).split("+")[0] for name in packages}; assert all(item == expected for item in actual.values()), actual; print(actual)'

ARG GLM47_SGLANG_KERNEL_VERSION=0.4.5
ARG GLM47_TORCH_MEMORY_SAVER_VERSION=0.0.9.post1
ENV SGLANG_KERNEL_VERSION=${GLM47_SGLANG_KERNEL_VERSION} \
    TORCH_MEMORY_SAVER_VERSION=${GLM47_TORCH_MEMORY_SAVER_VERSION}
RUN python3 -m pip install --no-cache-dir --no-deps --force-reinstall \
      "sglang-kernel==${SGLANG_KERNEL_VERSION}" \
      --index-url "https://docs.sglang.ai/whl/cu${FLASHINFER_CUDA_INDEX}/" \
    && python3 -m pip install --no-cache-dir --no-deps --upgrade --force-reinstall \
      "torch-memory-saver==${TORCH_MEMORY_SAVER_VERSION}" \
    && python3 -c 'import os; from importlib.metadata import version; expected = {"sglang-kernel": os.environ["SGLANG_KERNEL_VERSION"], "torch-memory-saver": os.environ["TORCH_MEMORY_SAVER_VERSION"]}; actual = {name: version(name).split("+")[0] for name in expected}; assert actual == expected, actual; print(actual)' \
    && python3 -c 'from sglang.srt.utils.common import assert_pkg_version; assert_pkg_version("flashinfer_python", "0.6.14", "FlashInfer is below the pinned SGLang minimum"); assert_pkg_version("sglang-kernel", "0.4.5", "SGLang kernel is below the pinned SGLang minimum")'

ENV PYTHONPATH=/opt/full-v5-charm/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GLM47_LIBCLANG_RESOURCE_DIR=/usr/local/lib/clang/18 \
    TZ=UTC \
    LC_ALL=C.UTF-8

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
         ca-certificates docker.io git rsync \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --no-deps libclang==18.1.1

WORKDIR /opt/full-v5-charm
COPY src/glm47_posttraining/__init__.py src/glm47_posttraining/__init__.py
COPY src/glm47_posttraining/constants.py src/glm47_posttraining/constants.py
COPY src/glm47_posttraining/aider_polyglot src/glm47_posttraining/aider_polyglot
COPY src/glm47_posttraining/cpp_perf src/glm47_posttraining/cpp_perf
COPY src/glm47_posttraining/integrations src/glm47_posttraining/integrations
COPY scripts/train_grpo.sh scripts/train_grpo.sh
COPY scripts/check_runtime.py scripts/check_runtime.py
COPY scripts/prepare_grpo_adapter.py scripts/prepare_grpo_adapter.py
COPY scripts/convert_checkpoint.sh scripts/convert_checkpoint.sh
COPY scripts/publish_results.py scripts/publish_results.py
COPY examples/grpo.sh examples/grpo.sh
COPY configs/full_v5_charm_grpo/gcp-r1.json configs/gcp-r1.json
COPY dataset/configs/glm47-flash-tokenizer-manifest.json dataset/configs/glm47-flash-tokenizer-manifest.json
COPY dataset/configs/glm47-flash-chat-template.jinja dataset/configs/glm47-flash-chat-template.jinja

ARG GLM47_ENFORCE_R8_TRAINER_CONTRACT=0
ARG GLM47_MILES_COMMIT=""
ARG GLM47_MILES_ADVANTAGES_SHA256=""
ARG GLM47_MILES_LOSS_SHA256=""
ARG GLM47_MILES_LOSSES_SHA256=""
ARG GLM47_MILES_MATH_UTILS_SHA256=""
ARG GLM47_MILES_TRAIN_DATA_CONVERSION_SHA256=""
ARG GLM47_MILES_ARGUMENTS_SHA256=""
ARG GLM47_MILES_MODEL_ARGS_UTILS_SHA256=""
ARG GLM47_MILES_GLM47_FLASH_MODEL_ARGS_SHA256=""
ARG GLM47_MILES_CONVERTER_SHA256=""
RUN if [ "${GLM47_ENFORCE_R8_TRAINER_CONTRACT}" = "1" ]; then \
      env -u CPLUS_INCLUDE_PATH \
      python3 -m glm47_posttraining.aider_polyglot.grpo_advantage_contract \
        --miles-root /root/miles \
        --expected-commit "${GLM47_MILES_COMMIT}" \
        --expected-file "miles/backends/training_utils/loss_hub/advantages.py=${GLM47_MILES_ADVANTAGES_SHA256}" \
        --expected-file "miles/backends/training_utils/loss.py=${GLM47_MILES_LOSS_SHA256}" \
        --expected-file "miles/backends/training_utils/loss_hub/losses.py=${GLM47_MILES_LOSSES_SHA256}" \
        --expected-file "miles/backends/training_utils/loss_hub/math_utils.py=${GLM47_MILES_MATH_UTILS_SHA256}" \
        --expected-file "miles/ray/rollout/train_data_conversion.py=${GLM47_MILES_TRAIN_DATA_CONVERSION_SHA256}" \
        --expected-file "miles/utils/arguments.py=${GLM47_MILES_ARGUMENTS_SHA256}" \
        --expected-file "miles/utils/external_utils/model_args_utils.py=${GLM47_MILES_MODEL_ARGS_UTILS_SHA256}" \
        --expected-file "scripts/models/glm4.7-flash.py=${GLM47_MILES_GLM47_FLASH_MODEL_ARGS_SHA256}" \
        --expected-file "tools/convert_hf_to_torch_dist.py=${GLM47_MILES_CONVERTER_SHA256}"; \
    fi

RUN python3 -c 'from glm47_posttraining.aider_polyglot.ast_evaluator import validate_libclang_runtime; assert validate_libclang_runtime()' \
    && python3 -c 'from glm47_posttraining.aider_polyglot.full_v5_charm import SCHEDULE_KIND; assert SCHEDULE_KIND == "aider-cpp-rl-full-v5-charm-schedule"' \
    && test ! -e examples/modal \
    && test ! -e src/glm47_posttraining/public_pr_eval

LABEL org.opencontainers.image.title="GLM-4.7 full-v5 CHARM GRPO on GCP" \
      org.opencontainers.image.description="Modal-free, admission-gated 8xH100 GRPO runtime" \
      glm47.execution.cloud="gcp" \
      glm47.modal.policy="denied"

CMD ["/bin/bash"]
