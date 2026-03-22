# Contract: Helm Chart `values.yaml` Schema

**Chart**: `pii-proxy` | **Branch**: `001-k8s-deployment` | **Date**: 2026-03-22

This document is the **canonical interface contract** for the `helm/pii-proxy` chart.
It defines every key in `values.yaml`, its type, default, and validation rule.
Operators interact with this chart exclusively through this interface.

---

## Overview

The chart exposes one Deployment (Envoy + ext_proc sidecar), one Service, and one
ConfigMap (Envoy configuration). All behaviour is controlled by the values below.
Re-apply after changes with:

```bash
helm upgrade --install pii-proxy helm/pii-proxy -f my-values.yaml
```

---

## Schema

### `image` — Container image references

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `image.envoy.repository` | string | `"envoyproxy/envoy"` | No | Envoy image repository |
| `image.envoy.tag` | string | `"v1.33.0"` | No | Envoy image tag |
| `image.extProc.repository` | string | *(sentinel)* | **YES** | ext_proc image repository. Must be overridden. |
| `image.extProc.tag` | string | `"latest"` | No | ext_proc image tag |
| `image.pullPolicy` | string | `"IfNotPresent"` | No | K8s `imagePullPolicy`. Use `Never` with minikube `image load`. |

**Validation**: `image.extProc.repository` uses Helm `required` — chart installation
fails with a clear message if not provided.

---

### `upstream` — Backend service routing

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `upstream.host` | string | *(sentinel)* | **YES** | Hostname of the upstream HTTP service. DNS name or IP. |
| `upstream.port` | int | `80` | No | TCP port of the upstream HTTP service. |

**Validation**: `upstream.host` uses Helm `required` — fails fast with a clear error on
missing value (research R7: fail-fast principle).

---

### `replicaCount` — Horizontal scaling

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `replicaCount` | int | `1` | No | Number of Envoy+ext_proc Pod replicas. |

Envoy and ext_proc scale together as a unit (FR-001 sidecar pattern).

---

### `envoy` — Envoy configuration

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `envoy.listenPort` | int | `8080` | No | Port the Envoy listener binds to inside the container. |

---

### `extProc` — ext_proc sidecar configuration

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `extProc.grpcPort` | int | `50051` | No | gRPC port for Envoy→ext_proc communication (pod-local). |
| `extProc.spacyModel` | string | `"en_core_web_lg"` | No | spaCy model name passed as `SPACY_MODEL` env var. |

---

### `service` — Kubernetes Service

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `service.type` | string | `"ClusterIP"` | No | `ClusterIP` (in-cluster only) or `LoadBalancer` (external). |
| `service.port` | int | `80` | No | Port exposed by the Service (maps to Envoy `listenPort`). |

**Allowed values for `service.type`**: `ClusterIP`, `LoadBalancer`.  
`LoadBalancer` requires cloud-provider support (AWS ELB, GCP GCLB, Azure LB) or
MetalLB on bare-metal clusters.

---

### `resources` — CPU and memory

#### `resources.extProc`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `resources.extProc.requests.cpu` | string | `"500m"` | CPU request |
| `resources.extProc.requests.memory` | string | `"2Gi"` | Memory request (sized for en_core_web_lg) |
| `resources.extProc.limits.cpu` | string | `"2000m"` | CPU limit |
| `resources.extProc.limits.memory` | string | `"4Gi"` | Memory limit |

#### `resources.envoy`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `resources.envoy.requests.cpu` | string | `"100m"` | CPU request |
| `resources.envoy.requests.memory` | string | `"128Mi"` | Memory request |
| `resources.envoy.limits.cpu` | string | `"1000m"` | CPU limit |
| `resources.envoy.limits.memory` | string | `"512Mi"` | Memory limit |

---

### `probes` — Kubernetes health probes

All probes are **TCP socket probes on `extProc.grpcPort`**. Port opens only after the
spaCy model fully loads, making it a safe readiness signal (research R1).

#### `probes.readiness`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `probes.readiness.initialDelaySeconds` | int | `180` | Seconds before first readiness check |
| `probes.readiness.periodSeconds` | int | `15` | Probe interval |
| `probes.readiness.failureThreshold` | int | `10` | Consecutive failures before NotReady |

#### `probes.liveness`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `probes.liveness.initialDelaySeconds` | int | `300` | Seconds before first liveness check |
| `probes.liveness.periodSeconds` | int | `30` | Probe interval |
| `probes.liveness.failureThreshold` | int | `3` | Consecutive failures before pod restart |

---

## Example: Minimal Override Values

```yaml
# my-values.yaml — minimum required overrides

upstream:
  host: "my-api-service.default.svc.cluster.local"
  port: 8080

image:
  extProc:
    repository: "my-registry.example.com/pii-proxy/ext-proc"
    tag: "1.0.0"
  pullPolicy: IfNotPresent
```

## Example: minikube Local Testing

```yaml
# minikube-values.yaml

upstream:
  host: "dummy-server-svc"
  port: 80

image:
  extProc:
    repository: "pii-proxy/ext-proc"
    tag: "dev"
  pullPolicy: Never        # Images loaded via `minikube image load`
```

## Example: External Exposure via LoadBalancer

```yaml
# loadbalancer-values.yaml (on top of base values)

service:
  type: LoadBalancer
  port: 80
```

---

## Invariants (Not Overridable)

The following are **hardcoded in templates** and cannot be changed via values:

| Invariant | Value | Rationale |
|-----------|-------|-----------|
| `failure_mode_allow` | `false` | Constitution Principle I: PII must never be forwarded raw |
| ext_proc gRPC bind address (in ConfigMap) | `127.0.0.1` | Localhost-only; gRPC never leaves the pod |
| No Service for port 50051 | absent | Constitution Security: gRPC not exposed outside pod |
