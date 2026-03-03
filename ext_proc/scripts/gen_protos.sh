#!/usr/bin/env bash
# Generate Python gRPC stubs for envoy.service.ext_proc (and its transitive deps).
#
# Usage:
#   bash scripts/gen_protos.sh                # default: cache under .proto-cache/
#   PROTO_CACHE=/tmp/my-cache bash scripts/gen_protos.sh
#
# Output always goes to ./generated/ (relative to the script's parent dir).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."          # ext-proc/
CACHE="${PROTO_CACHE:-$ROOT/.proto-cache}"
OUT="$ROOT/generated"

echo "▶  Cache dir : $CACHE"
echo "▶  Output dir: $OUT"

# ── Helper: shallow-clone or update a repo ────────────────────────────────────
clone_or_update() {
  local url="$1"
  local dest="$2"
  if [[ -d "$dest/.git" ]]; then
    echo "  ↻  $(basename "$dest") already cloned, skipping"
  else
    echo "  ↓  Cloning $(basename "$dest") …"
    git clone --depth=1 --quiet "$url" "$dest"
  fi
}

mkdir -p "$CACHE"

clone_or_update \
  https://github.com/envoyproxy/data-plane-api        "$CACHE/envoy-api"
clone_or_update \
  https://github.com/bufbuild/protoc-gen-validate      "$CACHE/pgv"
clone_or_update \
  https://github.com/cncf/xds                         "$CACHE/xds"

# Sparse-checkout googleapis (only google/rpc + google/api)
if [[ ! -d "$CACHE/googleapis/.git" ]]; then
  echo "  ↓  Cloning googleapis (sparse) …"
  git clone --depth=1 --quiet --no-checkout \
    https://github.com/googleapis/googleapis "$CACHE/googleapis"
  cd "$CACHE/googleapis"
  git sparse-checkout init --cone
  git sparse-checkout set google/rpc google/api
  git checkout --quiet
  cd "$ROOT"
else
  echo "  ↻  googleapis already cloned, skipping"
fi

# ── Locate grpcio-tools' bundled .proto files ─────────────────────────────────
GRPC_TOOLS_PROTO=$(uv run python -c \
  "import grpc_tools, os; print(os.path.join(grpc_tools.__path__[0], '_proto'))")

# ── Collect .proto files to compile ───────────────────────────────────────────
PROTOS=$(
  # Envoy: only the slices we actually need at runtime
  find "$CACHE/envoy-api" -name "*.proto" \( \
    -path "*/envoy/service/ext_proc/*" \
    -o -path "*/envoy/config/core/v3/*" \
    -o -path "*/envoy/extensions/filters/http/ext_proc/*" \
    -o -path "*/envoy/type/v3/*" \
    -o -path "*/envoy/annotations/*" \
  \) ;
  # xds repo bundles both xds/* and udpa/* at its root
  find "$CACHE/xds/udpa/annotations" -name "*.proto" ;
  find "$CACHE/xds/xds/annotations"  -name "*.proto" ;
  find "$CACHE/xds/xds/core"         -name "*.proto" ;
  # protoc-gen-validate (validate/validate.proto)
  find "$CACHE/pgv/validate" -name "*.proto"
)

echo "▶  Compiling $(echo "$PROTOS" | wc -l | tr -d ' ') proto files …"

mkdir -p "$OUT"

# shellcheck disable=SC2086
uv run python -m grpc_tools.protoc \
  -I "$CACHE/envoy-api" \
  -I "$CACHE/googleapis" \
  -I "$CACHE/xds" \
  -I "$CACHE/pgv" \
  -I "$GRPC_TOOLS_PROTO" \
  --python_out="$OUT" \
  --grpc_python_out="$OUT" \
  $PROTOS

# Make every generated sub-directory a proper Python package
find "$OUT" -type d -exec touch {}/__init__.py \;

echo "✔  Done – stubs written to $OUT"
