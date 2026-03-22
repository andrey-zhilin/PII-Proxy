# Research: Kubernetes Deployment Package

**Branch**: `001-k8s-deployment` | **Date**: 2026-03-22

---

## R1: Readiness / Liveness Probe Strategy for ext_proc

**Question**: How to signal Kubernetes that the ext_proc container is ready after the
spaCy model loads (~2-3 minutes), with zero code changes to `ext_proc/app.py`?

**Decision**: TCP socket probe on gRPC port 50051.

**Rationale**:

- `PiiScrubber.__init__()` (model load) runs at module-import time — before
  `grpc.server().start()` is ever called. The port does NOT open until the model
  is fully loaded and `serve()` calls `server.start()`. Therefore: port open ⟺
  model ready. TCP socket probe is a sound readiness signal.
- No extra dependency (`grpcio-health-checking`), no HTTP server sidecar, and no
  changes to existing application code. Simplest correct solution.
- Liveness TCP probe on the same port detects a crashed/hung process; if the
  gRPC server stops accepting connections, the pod is restarted.

**Alternatives considered**:

- **gRPC health protocol** (`grpcio-health-checking` + K8s native gRPC probe): correct
  and standards-compliant, but requires application code changes. Deferred to a future
  hardening step.
- **HTTP `/health` endpoint** on a second port: requires adding an HTTP server to
  app.py. More invasive than TCP socket. Rejected.
- **exec probe with `grpc_health_probe` binary**: requires baking binary into container
  image. Unnecessary when TCP socket works.

**Probe configuration** (in `values.yaml` with configurable delays):

```yaml
readinessProbe:
  tcpSocket:
    port: 50051
  initialDelaySeconds: 180   # spaCy en_core_web_lg takes 2-3 min
  periodSeconds: 15
  failureThreshold: 10       # allow up to 2.5 min past initialDelay

livenessProbe:
  tcpSocket:
    port: 50051
  initialDelaySeconds: 300   # only liveness-check after model has had time to load
  periodSeconds: 30
  failureThreshold: 3
```

---

## R2: Helm Chart Structure

**Question**: Flat chart or full sub-chart structure?

**Decision**: Single flat chart at `helm/pii-proxy/`. No sub-charts, no library charts.

**Rationale**:

- All deployable resources fit naturally in a single chart (1 Deployment, 1 ConfigMap,
  1 Service, 1 Namespace-scoped test Pod). Sub-charts add complexity with no benefit.
- Operators apply the chart with a single `helm upgrade --install` command (FR-009).
- `_helpers.tpl` provides shared label/selector macros. No other abstractions needed.

**Templates**:

| File | Resource |
|------|----------|
| `deployment.yaml` | Deployment with Envoy + ext_proc containers (sidecar) |
| `configmap-envoy.yaml` | ConfigMap holding rendered `envoy.yaml` |
| `service.yaml` | Service (ClusterIP or LoadBalancer) |
| `tests/test-scrubbing.yaml` | Helm test hook Pod (constitution III: Test-First) |
| `NOTES.txt` | Post-install usage hints |

---

## R3: Envoy ConfigMap Templating

**Question**: Which fields in `envoy.yaml` must be templatized?

**Decision**: Upstream cluster host/port, Envoy listen port, and ext_proc gRPC address.

**Changes from current `envoy.yaml`**:

| Field | Current value | Helm template |
|-------|--------------|---------------|
| Upstream socket address | `dummy-server:80` | `{{ .Values.upstream.host }}:{{ .Values.upstream.port }}` |
| Envoy listen port | `8080` | `{{ .Values.envoy.listenPort }}` |
| ext_proc address | `ext-proc:50051` | `127.0.0.1:{{ .Values.extProc.grpcPort }}` |

`failure_mode_allow: false` is **hardcoded** in the template (not a value) to enforce
constitution Principle I (Privacy-First). Operators cannot accidentally enable pass-through.

---

## R4: minikube Local Testing Strategy

**Question**: How should operators load container images into minikube for local testing
without a container registry?

**Decision**: `minikube image load <image>:<tag>` after building locally.

**Rationale**:

- No registry required for local development. Single command per image.
- Works on all minikube drivers (docker, containerd, virtualbox).
- Alternative (`eval $(minikube docker-env)` + build in-daemon) works only with the
  Docker driver; `image load` is driver-agnostic.
- `imagePullPolicy: Never` in values must be set when using `image load` to prevent
  Kubernetes from attempting registry pulls (which would fail).

**Recommended minikube start command** (allocate enough RAM for spaCy):

```bash
minikube start --cpus=4 --memory=8g --driver=docker
```

**Image loading workflow**:

```bash
docker build -t pii-proxy/ext-proc:dev ./ext_proc
minikube image load pii-proxy/ext-proc:dev
# Envoy uses public image — minikube pulls it automatically
```

---

## R5: Resource Defaults

**Question**: What CPU/memory defaults prevent ext_proc OOMKill during model load (FR-005)?

**Decision**:

| Container | CPU request | CPU limit | Memory request | Memory limit |
|-----------|-------------|-----------|----------------|--------------|
| ext_proc  | 500m        | 2000m     | 2Gi            | 4Gi          |
| envoy     | 100m        | 1000m     | 128Mi          | 512Mi        |

**Rationale**:

- `en_core_web_lg` spaCy model is ~800 MB on disk; in-memory footprint including
  Presidio pattern matchers is ~1.5-2 GB. 2 Gi request + 4 Gi limit gives headroom.
- Envoy is lightweight; 128 Mi request is conservative and sufficient for proxy
  workloads at 50 req/s.
- minikube with `--memory=8g` can run at least 1 replica comfortably.

---

## R6: Idempotency (FR-007, SC-003)

**Decision**: Standard `helm upgrade --install` is inherently idempotent via Helm's
3-way strategic merge patch. No special handling required.

**Rationale**:

- Helm tracks release state in a Secret; re-applying computes a diff and applies only
  changes. Existing resources are updated, not deleted and re-created (unless the
  resource type changes).
- The Helm test makes idempotency observable: run twice, both succeed.

---

## R7: Upstream URL Validation (edge case from spec)

**Question**: What happens if `upstream.host` is left empty or uses the placeholder value?

**Decision**: `NOTES.txt` warns about the placeholder; `values.yaml` uses a clearly
invalid sentinel (`"UPSTREAM_HOST_REQUIRED"`) as the default so any deployment using
the default will fail at the Envoy routing level with a clear DNS error (logged by
Envoy), not a silent misconfiguration.

**Alternative considered**: Helm `required` function to fail `helm install` if the value
is the sentinel. Chosen as the preferred approach — Helm itself rejects the installation
rather than deploying a broken config.
