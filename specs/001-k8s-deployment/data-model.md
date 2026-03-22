# Data Model: Kubernetes Deployment Package

**Branch**: `001-k8s-deployment` | **Date**: 2026-03-22

---

## Entities

### 1. PiiProxyDeployment (Kubernetes Deployment)

The primary workload resource. Runs two containers in a single Pod (sidecar pattern).

| Field path | Type | Default | Notes |
|-----------|------|---------|-------|
| `spec.replicas` | int | `1` | Horizontal scale; each replica has both containers |
| `spec.selector` | LabelSelector | chart labels | Immutable after creation |
| `spec.template.spec.containers[envoy].image` | string | `envoyproxy/envoy:v1.33.0` | Full image ref |
| `spec.template.spec.containers[envoy].ports[0].containerPort` | int | `8080` | Envoy listener |
| `spec.template.spec.containers[envoy].volumeMounts[0]` | VolumeMount | configmap-envoy | Mounts ConfigMap at `/etc/envoy/envoy.yaml` |
| `spec.template.spec.containers[envoy].resources` | ResourceRequirements | see Defaults | CPU/mem request+limit |
| `spec.template.spec.containers[ext_proc].image` | string | `"EXTPROC_IMAGE_REQUIRED"` | Operator must override |
| `spec.template.spec.containers[ext_proc].ports[0].containerPort` | int | `50051` | gRPC port (not exposed outside pod) |
| `spec.template.spec.containers[ext_proc].env[GRPC_PORT]` | string | `"50051"` | Matches `extProc.grpcPort` |
| `spec.template.spec.containers[ext_proc].env[SPACY_MODEL]` | string | `"en_core_web_lg"` | Matches `extProc.spacyModel` |
| `spec.template.spec.containers[ext_proc].readinessProbe` | TCPSocketProbe | port 50051, delay 180s | Model-aware; see R1 |
| `spec.template.spec.containers[ext_proc].livenessProbe` | TCPSocketProbe | port 50051, delay 300s | Crash detection |
| `spec.template.spec.containers[ext_proc].resources` | ResourceRequirements | see Defaults | Sized for en_core_web_lg |
| `spec.template.spec.volumes[0]` | Volume (ConfigMap) | configmap-envoy | Provides envoy.yaml |

**State transitions**:

```
Pod scheduled
  → Init (ext_proc loading spaCy model, ~2-3 min)
    → NotReady (readinessProbe failing until port 50051 opens)
      → Ready (port 50051 open; all traffic forwarded)
        → Terminated (on crash: Kubernetes restarts within 30s)
```

**Constraint**: `failure_mode_allow: false` in EnvoyConfigMap means traffic is NOT
forwarded while ext_proc is NotReady — Envoy returns 5xx (constitution Principle I).

---

### 2. EnvoyConfigMap (Kubernetes ConfigMap)

Holds the Envoy static configuration (`envoy.yaml`). Decoupled from the container image
so routing can be updated without rebuilding (FR-006).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `.data["envoy.yaml"]` | string (YAML) | rendered template | See template variables below |

**Template variables injected into envoy.yaml**:

| Template var | values.yaml key | Description |
|-------------|-----------------|-------------|
| `{{ .Values.envoy.listenPort }}` | `envoy.listenPort` | Envoy listener port (8080) |
| `{{ .Values.upstream.host }}` | `upstream.host` | Upstream service hostname (REQUIRED) |
| `{{ .Values.upstream.port }}` | `upstream.port` | Upstream service port (80) |
| `127.0.0.1` | hardcoded | ext_proc gRPC address — always localhost |
| `{{ .Values.extProc.grpcPort }}` | `extProc.grpcPort` | ext_proc gRPC port (50051) |

**Immutable field**: `failure_mode_allow: false` — hardcoded in template, not a value.

---

### 3. EnvoyService (Kubernetes Service)

Exposes the Envoy proxy within the cluster (FR-003) and optionally externally (FR-010).

| Field | Type | Default | Condition |
|-------|------|---------|-----------|
| `spec.type` | string | `ClusterIP` | `service.type = ClusterIP` |
| `spec.type` | string | `LoadBalancer` | `service.type = LoadBalancer` |
| `spec.ports[0].port` | int | `80` | External port |
| `spec.ports[0].targetPort` | int | `8080` | Envoy listen port |

**No Service is created for gRPC port 50051** — gRPC is pod-local (localhost) only.
This satisfies constitution Security Requirements (gRPC not exposed outside pod).

---

### 4. Values / Configuration File (`values.yaml`)

The single interface the operator edits. Full schema in `contracts/values-schema.md`.

**Required fields** (have invalid sentinels, `helm install` fails without override):

| Key | Sentinel | Description |
|-----|----------|-------------|
| `upstream.host` | `"UPSTREAM_HOST_REQUIRED"` | Upstream service hostname |
| `image.extProc.repository` | `"EXTPROC_IMAGE_REQUIRED"` | ext_proc image (operator-built) |

**Optional fields with defaults**:

| Key | Default | Description |
|-----|---------|-------------|
| `replicaCount` | `1` | Deployment replicas |
| `upstream.port` | `80` | Upstream port |
| `envoy.listenPort` | `8080` | Envoy listener port |
| `extProc.grpcPort` | `50051` | gRPC port (pod-local) |
| `extProc.spacyModel` | `"en_core_web_lg"` | spaCy model name env var |
| `image.envoy.repository` | `"envoyproxy/envoy"` | Envoy image repo |
| `image.envoy.tag` | `"v1.33.0"` | Envoy image tag |
| `image.extProc.tag` | `"latest"` | ext_proc image tag |
| `image.pullPolicy` | `"IfNotPresent"` | K8s imagePullPolicy |
| `service.type` | `"ClusterIP"` | `ClusterIP` or `LoadBalancer` |
| `service.port` | `80` | Service port |
| `resources.extProc.requests.cpu` | `"500m"` | ext_proc CPU request |
| `resources.extProc.requests.memory` | `"2Gi"` | ext_proc memory request |
| `resources.extProc.limits.cpu` | `"2000m"` | ext_proc CPU limit |
| `resources.extProc.limits.memory` | `"4Gi"` | ext_proc memory limit |
| `resources.envoy.requests.cpu` | `"100m"` | Envoy CPU request |
| `resources.envoy.requests.memory` | `"128Mi"` | Envoy memory request |
| `resources.envoy.limits.cpu` | `"1000m"` | Envoy CPU limit |
| `resources.envoy.limits.memory` | `"512Mi"` | Envoy memory limit |
| `probes.readiness.initialDelaySeconds` | `180` | Readiness probe start delay |
| `probes.readiness.periodSeconds` | `15` | Readiness probe interval |
| `probes.readiness.failureThreshold` | `10` | Readiness failure count before NotReady |
| `probes.liveness.initialDelaySeconds` | `300` | Liveness probe start delay |
| `probes.liveness.periodSeconds` | `30` | Liveness probe interval |
| `probes.liveness.failureThreshold` | `3` | Liveness failure count before restart |

---

### 5. Helm Test Pod (`test-scrubbing.yaml`)

A Kubernetes Pod run by `helm test` to verify end-to-end PII scrubbing after deployment.
Annotated with `helm.sh/hook: test`.

| Field | Value |
|-------|-------|
| Runs | `curl` POST with a body containing a test person name + email |
| Assertion | Response body contains `<PERSON>` and `<EMAIL_ADDRESS>` |
| Exit code | 0 on success, non-zero on failure |
| Target URL | `http://{{ include "pii-proxy.fullname" . }}:{{ .Values.service.port }}/` |

This satisfies constitution Principle III (Test-First): the test contract is defined
here in Phase 1, before any template code is written.
