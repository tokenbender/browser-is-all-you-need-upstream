FROM gcc:13@sha256:3617a214e52a25bde5375dc9503b5e67f01b6c7322a30137e2790aa8e6db5d1f
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir pydantic==2.12.5 \
    && rm -rf /var/lib/apt/lists/*
COPY src/ /opt/reward/src/
COPY Reward_GRPO/ /opt/reward/Reward_GRPO/
COPY generalized_verifier_docs/ /opt/reward/generalized_verifier_docs/
RUN chmod -R a+rX /opt/reward
ENV PATH="/opt/venv/bin:/usr/local/bin:/usr/bin:/bin"
ENV PYTHONPATH="/opt/reward/src:/opt/reward"
ENV PYTHONDONTWRITEBYTECODE=1
ENV HOME=/tmp
WORKDIR /opt/reward
