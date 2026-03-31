# Helm Values Schema: PII Proxy (v2 — Outgoing Proxy Mode)

**Branch**: `002-langfuse-outgoing-proxy` | **Date**: 2026-03-23

This document describes the complete public API of `helm/pii-proxy/values.yaml` after the additions in this feature. New fields added by this feature are marked **[NEW]**.

---

## Top-Level Values

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `mode` | string | `"outgoing-proxy"` | No | Operating mode: `"outgoing-proxy"` or `"reverse-proxy"` |
| `replicaCount` | int | `1` | No | Number of pod replicas |

---

## `image` Group

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `image.envoy.repository` | string | `envoyproxy/envoy` | No | Envoy image repo |
| `image.envoy.tag` | string | `v1.33.0` | No | Envoy image tag |
| `image.extProc.repository` | string | `""` | **Yes** | ext_proc container image path |
| `image.extProc.tag` | string | `latest` | No | ext_proc image tag |
| `image.pullPolicy` | string | `IfNotPresent` | No | Image pull policy |

---

## `langfuse` Group **[NEW]**

Used when `mode: outgoing-proxy`.

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `langfuse.host` | string | `""` | **Yes** (outgoing mode) | External Langfuse FQDN (e.g. `cloud.langfuse.com` or `mock-langfuse.langfuse-mock.svc.cluster.local`) |
| `langfuse.port` | int | `443` | No | Langfuse server port |
| `langfuse.tls.enabled` | bool | `true` | No | Whether Envoy uses TLS when connecting to Langfuse. Set `false` when targeting the local mock server over HTTP. |

---

## `tls` Group **[NEW]**

Controls the Envoy HTTPS listener (inbound TLS from application).

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `tls.enabled` | bool | `false` | No | Enable HTTPS listener on Envoy (terminates TLS from calling application) |
| `tls.secretName` | string | `""` | **Yes** if `tls.enabled=true` | Name of a `kubernetes.io/tls` Secret in the same namespace containing `tls.crt` and `tls.key` |

---

## `envoy` Group

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `envoy.listenPort` | int | `8080` | No | Envoy HTTP listener port |
| `envoy.httpsPort` | int | `443` | No | **[NEW]** Envoy HTTPS listener port (active when `tls.enabled=true`) |

---

## `upstream` Group

Used when `mode: reverse-proxy` (existing behavior, unchanged).

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `upstream.host` | string | `""` | **Yes** (reverse-proxy mode) | Upstream service hostname |
| `upstream.port` | int | `80` | No | Upstream service port |

---

## `extProc` Group

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `extProc.grpcPort` | int | `50051` | No | Pod-local gRPC port for Envoy→ext_proc |
| `extProc.spacyModel` | string | `en_core_web_lg` | No | spaCy model name baked into ext_proc image |

---

## `istio` Group **[NEW]**

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `istio.enabled` | bool | `false` | No | Render Istio `ServiceEntry` + `DestinationRule` and add port-exclusion annotations to the pod |

---

## `service` Group

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `service.type` | string | `ClusterIP` | No | Kubernetes Service type |
| `service.port` | int | `80` | No | HTTP port exposed by the Service |
| `service.httpsPort` | int | `443` | No | **[NEW]** HTTPS port exposed by the Service (active when `tls.enabled=true`) |

---

## `resources` Group

Unchanged from spec 001. See `helm/pii-proxy/values.yaml` for full resource defaults.

---

## Validation Rules

Enforced by `helm required` calls in `_helpers.tpl`:

| Condition | Error |
|-----------|-------|
| `mode == "outgoing-proxy"` and `langfuse.host == ""` | `langfuse.host is required in outgoing-proxy mode` |
| `mode == "reverse-proxy"` and `upstream.host == ""` | `upstream.host is required in reverse-proxy mode` |
| `tls.enabled == true` and `tls.secretName == ""` | `tls.secretName is required when tls.enabled is true` |

---

## Example: Outgoing Proxy to Cloud Langfuse with Istio

```yaml
mode: outgoing-proxy

image:
  extProc:
    repository: my-registry.example.com/pii-proxy/ext-proc

langfuse:
  host: cloud.langfuse.com
  port: 443
  tls:
    enabled: true

tls:
  enabled: true
  secretName: pii-proxy-tls

istio:
  enabled: true

service:
  type: ClusterIP
  port: 80
  httpsPort: 443
```

## Example: Test Setup with Mock Langfuse (Full TLS + Istio on minikube)

This is the canonical integration test configuration. TLS is enabled on the inbound listener (application → proxy over HTTPS). The mock Langfuse server is reached over plain HTTP (no TLS between proxy and internal mock). Istio ServiceEntry and DestinationRule are deployed.

```yaml
mode: outgoing-proxy

image:
  extProc:
    repository: pii-proxy/ext-proc   # loaded via: eval $(minikube docker-env)
  pullPolicy: Never

langfuse:
  # Internal cluster DNS name of the mock Langfuse server
  host: mock-langfuse.langfuse-mock.svc.cluster.local
  port: 8080
  tls:
    # false: proxy → mock Langfuse uses plain HTTP (mock is internal, not a real external server)
    enabled: false

tls:
  # true: application → proxy uses HTTPS (cert from pii-proxy-tls Secret)
  enabled: true
  secretName: pii-proxy-tls   # created by: kubectl create secret tls pii-proxy-tls ...

istio:
  # true: renders ServiceEntry + DestinationRule; adds port-exclusion annotations
  enabled: true

service:
  type: ClusterIP
  port: 8080      # HTTP (unused in TLS test, kept for health checks)
  httpsPort: 443  # HTTPS listener (active because tls.enabled=true)
```
