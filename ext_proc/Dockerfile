# Stage 1: compile Envoy protobuf stubs
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

RUN apt-get update \
      && apt-get install -y --no-install-recommends git ca-certificates \
      && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install Python deps including grpcio-tools (needed only at compile time)
COPY pyproject.toml .
RUN uv sync --group build

# Pre-seed the proto cache so each repo is a separate Docker layer.
# gen_protos.sh skips cloning when the dir already exists, so these layers are
# reused on rebuilds even when the script itself changes.

RUN git clone --depth=1 \
      https://github.com/envoyproxy/data-plane-api /build/.proto-cache/envoy-api

RUN git clone --depth=1 --no-checkout \
      https://github.com/googleapis/googleapis /build/.proto-cache/googleapis \
      && cd /build/.proto-cache/googleapis \
      && git sparse-checkout init --cone \
      && git sparse-checkout set google/rpc google/api \
      && git checkout

RUN git clone --depth=1 \
      https://github.com/cncf/xds /build/.proto-cache/xds

RUN git clone --depth=1 \
      https://github.com/bufbuild/protoc-gen-validate /build/.proto-cache/pgv

# Run the shared generation script (same one used by `mise gen-protos`)
COPY scripts/ scripts/
RUN PROTO_CACHE=/build/.proto-cache bash scripts/gen_protos.sh

# Stage 2: lean runtime image
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /srv/ext_proc

# Install only runtime deps (skip the build group with grpcio-tools)
COPY pyproject.toml .
RUN uv sync --no-group build

# Copy compiled proto stubs and application code
COPY --from=builder /build/generated ./generated
COPY __init__.py app.py .

ENV PYTHONPATH=/srv:/srv/ext_proc/generated

EXPOSE 50051
CMD ["uv", "run", "python", "app.py"]
