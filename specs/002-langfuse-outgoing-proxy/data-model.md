# Data Model: Outgoing HTTPS Proxy for Langfuse

**Branch**: `002-langfuse-outgoing-proxy` | **Date**: 2026-03-23

---

## Entities

### 1. PiiProxyDeployment (Kubernetes Deployment) — MODIFIED

Extends the spec 001 Deployment. The key changes are:

- A TLS certificate Secret volume is mounted into the Envoy container.
- Pod annotations exclude port 443 from Istio interception.
- The `langfuse.host` / `langfuse.port` values replace `upstream.host` / `upstream.port` for the outgoing proxy configuration (the old upstream values remain for reverse-proxy compatibility).

**New fields / changes**:

| Field path | Type | Default | Notes |
|-----------|------|---------|-------|
| `spec.template.metadata.annotations["traffic.sidecar.istio.io/excludeInboundPorts"]` | string | `"443"` (conditional on `istio.enabled`) | Prevents Istio intercepting Envoy's HTTPS listener |
| `spec.template.metadata.annotations["traffic.sidecar.istio.io/excludeOutboundPorts"]` | string | `"443"` (conditional on `istio.enabled`) | Prevents double-TLS on outbound connection to Langfuse |
| `spec.template.spec.volumes[tls-certs]` | Volume (Secret) | Secret name from `tls.secretName` | Mounted at `/certs/` |
| `spec.template.spec.containers[envoy].volumeMounts[tls-certs]` | VolumeMount | `/certs/` | Read-only |
| `spec.template.spec.containers[envoy].ports[https]` | ContainerPort | `443` | Added alongside existing HTTP port |

---

### 2. EnvoyConfigMap (Kubernetes ConfigMap) — MODIFIED

**New template variable group: `langfuse`**

| Template var | values.yaml key | Description |
|-------------|-----------------|-------------|
| `{{ .Values.langfuse.host }}` | `langfuse.host` | External Langfuse server hostname (REQUIRED for outgoing mode) |
| `{{ .Values.langfuse.port }}` | `langfuse.port` | Langfuse server port (default: 443) |
| `{{ .Values.langfuse.tls.enabled }}` | `langfuse.tls.enabled` | Render `UpstreamTlsContext` for Langfuse cluster (default: true) |

**New template variable group: `tls` (listener)**

| Template var | values.yaml key | Description |
|-------------|-----------------|-------------|
| `{{ .Values.tls.enabled }}` | `tls.enabled` | Render `DownstreamTlsContext` on Envoy listener (default: false) |
| `{{ .Values.tls.secretName }}` | `tls.secretName` | Name of `kubernetes.io/tls` Secret with `tls.crt` / `tls.key` |
| `{{ .Values.envoy.httpsPort }}` | `envoy.httpsPort` | Port for the HTTPS listener (default: 443) |

**Processing mode changes** (outgoing proxy vs reverse proxy):

| Mode field | Reverse proxy (existing) | Outgoing proxy (new) |
|-----------|--------------------------|----------------------|
| `request_header_mode` | `SKIP` | `SEND` (needed for Content-Type) |
| `request_body_mode` | `NONE` | `BUFFERED` |
| `response_header_mode` | `SKIP` | `SKIP` |
| `response_body_mode` | `BUFFERED` | `NONE` |

**Note on dual-mode**: A single `mode` value (`reverse-proxy` | `outgoing-proxy`) gates which processing mode block is rendered in the ConfigMap template, and which upstream cluster definition is rendered.

---

### 3. EnvoyService (Kubernetes Service) — MODIFIED

| Field | Type | Default | Condition |
|-------|------|---------|-----------|
| `spec.ports[https].port` | int | `443` | `tls.enabled = true` |
| `spec.ports[https].targetPort` | int | `443` | `tls.enabled = true` |
| `spec.ports[https].name` | string | `https` | `tls.enabled = true` |

The existing HTTP port (`8080` → `80`) remains for non-TLS deployments and backward compatibility.

---

### 4. IstioServiceEntry (Istio CRD) — NEW

Registers the external Langfuse host in the Istio service registry.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `spec.hosts[0]` | string | `{{ .Values.langfuse.host }}` | External Langfuse FQDN |
| `spec.ports[0].number` | int | `{{ .Values.langfuse.port }}` | Default: 443 |
| `spec.ports[0].name` | string | `https` | Protocol label |
| `spec.ports[0].protocol` | string | `HTTPS` | Langfuse always HTTPS |
| `spec.location` | string | `MESH_EXTERNAL` | Outside the mesh |
| `spec.resolution` | string | `DNS` | Resolved at runtime via DNS |

**Conditionally rendered**: only when `istio.enabled = true` in Helm values.

---

### 5. IstioDestinationRule (Istio CRD) — NEW

Tells Istio that the PII proxy pod handles its own TLS to Langfuse — Istio must not add another TLS layer.

| Field | Type | Value | Notes |
|-------|------|-------|-------|
| `spec.host` | string | `{{ .Values.langfuse.host }}` | Same host as ServiceEntry |
| `spec.trafficPolicy.tls.mode` | string | `DISABLE` | Envoy owns TLS origination; Istio passthrough |

**Conditionally rendered**: only when `istio.enabled = true`.

---

### 6. MockLangfuseServer (Kubernetes Deployment) — NEW (test fixtures)

A minimal FastAPI server that simulates the Langfuse batch ingestion API. Deployed in the `langfuse-mock` namespace without Istio sidecar injection.

| Field | Type | Notes |
|-------|------|-------|
| `POST /api/public/ingestion` | Endpoint | Accepts any JSON body, appends to in-memory list, returns 207 |
| `GET /captured` | Endpoint | Returns list of all captured request body payloads (test assertion) |
| `DELETE /captured` | Endpoint | Clears captured list (test setup/teardown) |
| Authentication | Basic (ignored) | Accepts any credentials without validation |
| Response body | `{"successes": [{"id": "...", "status": 201}], "errors": []}` | Per Langfuse API |

**State**: in-memory list of captured request dicts. Ephemeral — lost on pod restart. Sufficient for integration tests.

---

### 7. HelmValues (Updated Schema)

New top-level value groups added to `values.yaml`:

```yaml
# ── Proxy operating mode ──────────────────────────────────────
# "reverse-proxy"   — scrub response bodies (existing behavior, spec 001)
# "outgoing-proxy"  — scrub request bodies and forward to external upstream
mode: "outgoing-proxy"

# ── Langfuse upstream (outgoing-proxy mode only) ──────────────
langfuse:
  # REQUIRED in outgoing-proxy mode — external Langfuse FQDN
  host: ""
  port: 443
  tls:
    # Set to false when targeting the local mock Langfuse server (HTTP)
    enabled: true

# ── TLS listener (HTTPS inbound) ─────────────────────────────
tls:
  # Set to true when the application sends HTTPS to the proxy
  enabled: false
  # Name of a kubernetes.io/tls Secret containing tls.crt and tls.key
  secretName: ""

# ── Istio integration ─────────────────────────────────────────
istio:
  # Set to true to render ServiceEntry + DestinationRule
  # and add Istio sidecar port-exclusion annotations
  enabled: false
```

**Validation rules** (implemented in `_helpers.tpl`):

- `mode == "outgoing-proxy"` → `langfuse.host` MUST be non-empty (fail with `required`)
- `tls.enabled == true` → `tls.secretName` MUST be non-empty (fail with `required`)
- `mode == "reverse-proxy"` → `upstream.host` MUST be non-empty (existing validation, unchanged)

---

### State Transitions (Outgoing Proxy Pod)

```
Pod scheduled
  → Init (ext_proc loading spaCy model, ~2-3 min)
    → NotReady (readinessProbe TCPSocket port 50051 failing)
      → Ready (port 50051 open; all requests scrubbed and forwarded)
        ↓ on scrub failure (Presidio exception)
      → Envoy returns 5xx to caller (failure_mode_allow: false)
        ↓ on upstream Langfuse unreachable
      → Envoy returns 502/503 to caller (upstream connect timeout)
```
