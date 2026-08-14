FROM gcc:13@sha256:4f86732b7340848efeb2b4ea4d907e2eb754eaeb6d4d26ab462b14c1e4a90c3a AS gcc13

FROM silkeh/clang:18-bookworm@sha256:9388794775d1393c16b6897b4775b6d3e29459319de0bfafec59a20262e1fa68

# Keep all historical build/test stages on GCC 13 while reserving Clang 18 for
# the private AST-backed public-API verifier.
COPY --from=gcc13 /usr/local /usr/local

RUN c++ --version | head -1 | grep -F 'c++ (GCC) 13.' \
    && clang-18 --version | head -1 | grep -F 'clang version 18.' \
    && python3 --version \
    && cmake --version | head -1 \
    && make --version | head -1

WORKDIR /work

LABEL org.opencontainers.image.title="GLM-4.7 full-v5 CHARM verifier" \
      glm47.network="none" \
      glm47.modal.policy="denied" \
      glm47.compile.compiler="gcc-13" \
      glm47.public-api.compiler="clang-18"
