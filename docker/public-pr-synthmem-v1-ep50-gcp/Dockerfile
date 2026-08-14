FROM radixark/miles:latest-cu12@sha256:efc8027fc47aaa9687dc4f1046093ed4e2f9789e52a932fcefb7031402aeff37

ARG AIDER_COMMIT=5dc9490bb35f9729ef2c95d00a19ccd30c26339c
ENV PYTHONPATH=/opt/public-pr-eval/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CC=gcc-13 \
    CXX=g++-13 \
    TZ=UTC \
    LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
      software-properties-common git make curl python3-venv ca-certificates \
    && add-apt-repository -y ppa:ubuntu-toolchain-r/test \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gcc-13 g++-13 \
    && update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-13 100 \
    && update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-13 100 \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --no-deps --force-reinstall \
      sglang-kernel==0.4.4 --index-url https://docs.sglang.ai/whl/cu129/ \
    && python3 -m pip install --no-cache-dir cmake==3.27.9 \
    && cmake --version | head -1 | grep -Fx "cmake version 3.27.9"

RUN git clone https://github.com/Aider-AI/aider.git /aider \
    && git -C /aider checkout --detach "${AIDER_COMMIT}" \
    && python3 -m venv /opt/aider-venv \
    && /opt/aider-venv/bin/python -m pip install --no-cache-dir -e '/aider[dev]'

WORKDIR /opt/public-pr-eval
COPY configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v8.jsonl configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v8.jsonl
COPY configs/public_pr_eval/private_probes configs/public_pr_eval/private_probes
COPY src/glm47_posttraining/public_pr_eval src/glm47_posttraining/public_pr_eval
COPY scripts/public_pr_repo_eval.py scripts/public_pr_repo_eval.py
COPY scripts/validate_public_pr_eval.py scripts/validate_public_pr_eval.py

RUN printf '%s  %s\n' \
      '38f567a074a5a61e53ee1dad478833f10d9f7a40738d8d6c0baedfe1fe5294b6' \
      'configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v8.jsonl' | sha256sum -c -

RUN python3 scripts/validate_public_pr_eval.py \
      configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v8.jsonl \
      --out /tmp/public-pr-static-validation-demo-fmtlib-v8.json \
    && python3 scripts/public_pr_repo_eval.py prepare \
      configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v8.jsonl \
      --output /opt/public-pr-prepared/demo-fmtlib-v8 \
    && cp /tmp/public-pr-static-validation-demo-fmtlib-v8.json /opt/public-pr-prepared/demo-fmtlib-v8/static-validation.json \
    && python3 scripts/public_pr_repo_eval.py verify-oracles \
      configs/public_pr_eval/public-pr-repo-eval-demo-fmtlib-v8.jsonl \
      --prepared-root /opt/public-pr-prepared/demo-fmtlib-v8 \
      --output /opt/public-pr-oracles/demo-fmtlib-v8

RUN /opt/aider-venv/bin/python -m pip freeze | LC_ALL=C sort > /opt/public-pr-prepared/aider-pip-freeze.txt

COPY scripts/gcp_public_pr_synthmem_50ep_eval.py scripts/gcp_public_pr_synthmem_50ep_eval.py

ENTRYPOINT ["python3", "/opt/public-pr-eval/scripts/gcp_public_pr_synthmem_50ep_eval.py"]
