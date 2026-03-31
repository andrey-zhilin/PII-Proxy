# Research: Outgoing HTTPS Proxy for Langfuse

**Branch**: `002-langfuse-outgoing-proxy` | **Date**: 2026-03-23

---

## R1: ext_proc Request Body Processing

**Question**: What changes are required in the ext_proc service to scrub request bodies instead of (or in addition to) response bodies?

**Decision**: Add a `request_body` handler branch to `ExtProcService.Process()`. The `ProcessingResponse.request_body` field uses the same `BodyResponse(response=CommonResponse(body_mutation=BodyMutation(...)))` structure as `response_body`. Enable `request_header_mode: SEND` in Envoy so the ext_proc can read the `Content-Type` from request headers and route to JSON vs plaintext scrubbing. Disable `response_body_mode` (set to `NONE`) for the outgoing proxy configuration since Langfuse ACKs require no scrubbing.

**Rationale**:

- Confirmed via inspection of `external_processor_pb2.py` binary descriptor: `ProcessingRequest.request_body` (field 4) carries `HttpBody`, and `ProcessingResponse.request_body` (field 3) carries `BodyResponse` — identical structure to the response path.
- `PiiScrubber.scrub_bytes()` is content-type-agnostic; no changes to the scrubber itself are needed. Only the ext_proc gRPC handler needs a new branch.
- The existing `content_type` variable capturing logic (currently reading `response_headers`) must be replicated for `request_headers` in the outgoing mode.
- `failure_mode_allow: false` is retained: if scrubbing fails, Envoy returns 5xx and the raw request body is never forwarded to Langfuse.

**Implementation delta** (`ext_proc/app.py`):

```python
# Existing (response path — UNCHANGED):
elif msg_type == "response_headers":
    for header in req.response_headers.headers.headers:
        if header.key.lower() == "content-type":
            content_type = header.value
    yield external_processor_pb2.ProcessingResponse()

elif msg_type == "response_body":
    # ... existing scrub logic ...

# New (request path — ADDED):
elif msg_type == "request_headers":
    for header in req.request_headers.headers.headers:
        if header.key.lower() == "content-type":
            content_type = header.value
    yield external_processor_pb2.ProcessingResponse()

elif msg_type == "request_body":
    original_body = req.request_body.body
    modified_body = _scrubber.scrub_bytes(original_body, content_type)
    yield external_processor_pb2.ProcessingResponse(
        request_body=external_processor_pb2.BodyResponse(
            response=external_processor_pb2.CommonResponse(
                body_mutation=external_processor_pb2.BodyMutation(body=modified_body)
            )
        )
    )
```

**Alternatives considered**:

- **Separate ext_proc service for outgoing mode**: creates a second Docker image to maintain. Rejected — the scrubber code is identical; only the gRPC handler needs a new branch.
- **Mode flag env var** (`SCRUB_MODE=request|response|both`): adds runtime complexity for a feature that can be expressed through Envoy's `processing_mode` configuration. Envoy `processing_mode` already controls which phases the ext_proc receives, so `app.py` only sees the phases it needs to handle. No mode flag needed.

---

## R2: Envoy TLS Listener (Inbound HTTPS Termination)

**Question**: How is the Envoy listener configured to terminate HTTPS from the calling application?

**Decision**: Use `DownstreamTlsContext` in the filter chain with a TLS certificate stored in a Kubernetes Secret mounted into the pod. The Langfuse SDK in the test environment is configured to trust the proxy's certificate (via `LANGFUSE_SDK_VERIFY_SSL=false` for testing, or by mounting the CA cert into the client pod for production-like tests). For Istio mesh deployments: configure `traffic.sidecar.istio.io/excludeInboundPorts: "443"` on the PII proxy pod so Istio does not intercept port 443 — Envoy handles TLS directly.

**Rationale**:

- Inside an Istio mesh, Istio's sidecar proxy (Envoy-xtail) intercepts all ports by default. If Istio intercepts port 443, it terminates mTLS and forwards plaintext to Envoy — breaking Envoy's expected HTTPS input. The port-exclusion annotation prevents this conflict.
- In the test environment (minikube), the test client needs to either skip TLS verification or trust a self-signed CA certificate. The self-signed cert is generated once and stored as a Kubernetes Secret.

**Envoy listener config snippet**:

```yaml
filter_chains:
  - transport_socket:
      name: envoy.transport_sockets.tls
      typed_config:
        "@type": type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.DownstreamTlsContext
        common_tls_context:
          tls_certificates:
            - certificate_chain: { filename: "/certs/tls.crt" }
              private_key: { filename: "/certs/tls.key" }
    filters:
      - name: envoy.filters.network.http_connection_manager
        # ... (unchanged HCM config)
```

**Certificate management for test environment**:

```bash
# Generate self-signed CA + server cert for testing
openssl req -x509 -newkey rsa:4096 -nodes -keyout ca.key -out ca.crt -days 365 \
  -subj "/CN=pii-proxy-test-ca"
openssl req -newkey rsa:4096 -nodes -keyout tls.key -out tls.csr \
  -subj "/CN=pii-proxy.pii-proxy.svc.cluster.local"
openssl x509 -req -in tls.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out tls.crt -days 365 -extfile <(printf "subjectAltName=DNS:pii-proxy.pii-proxy.svc.cluster.local")
kubectl create secret tls pii-proxy-tls --cert=tls.crt --key=tls.key -n pii-proxy
```

**Alternatives considered**:

- **cert-manager**: Fully automated certificate lifecycle. Preferred for production but adds a cert-manager dependency to the test setup. Deferred to a hardening task.
- **Istio's auto-mTLS with app sending HTTP**: Istio automatically upgrades HTTP to mTLS between pods; no certificate management needed in the application. This would be simpler. However, the spec explicitly requires the application to send HTTPS (clarification Q2, answer B). Istio port exclusion is the bridge that makes both work together.

---

## R3: Envoy TLS Origination (Outbound HTTPS to Langfuse)

**Question**: How does Envoy establish a TLS connection to the external Langfuse server?

**Decision**: Add a `transport_socket` with `UpstreamTlsContext` to the upstream Langfuse cluster definition. For `cloud.langfuse.com` (production), Envoy uses the system CA bundle. For the test mock server, the mock uses HTTP (no TLS) since it runs cluster-internally; the test exercises TLS termination on the inbound side, not the outbound side.

**Rationale**:

- Envoy's default upstream clusters do not use TLS — a `transport_socket` with `UpstreamTlsContext` must be explicitly added.
- The `sni` field must be set to the Langfuse hostname so SNI-based virtual hosting works correctly on the Langfuse server.
- For the Helm chart, the `langfuse.tls.enabled` value gates whether `UpstreamTlsContext` is rendered in the ConfigMap template, allowing the same chart to target the plain-HTTP mock server in tests.

**Envoy upstream cluster config snippet**:

```yaml
- name: langfuse_upstream
  connect_timeout: 5s
  type: LOGICAL_DNS
  lb_policy: ROUND_ROBIN
  transport_socket:
    name: envoy.transport_sockets.tls
    typed_config:
      "@type": type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext
      sni: "{{ .Values.langfuse.host }}"
      common_tls_context:
        validation_context:
          trusted_ca:
            filename: /etc/ssl/certs/ca-certificates.crt  # system CA bundle
  load_assignment:
    cluster_name: langfuse_upstream
    endpoints:
      - lb_endpoints:
          - endpoint:
              address:
                socket_address:
                  address: "{{ .Values.langfuse.host }}"
                  port_value: {{ .Values.langfuse.port }}
```

---

## R4: Istio Integration for Egress to External Langfuse

**Question**: What Istio resources are required so that the PII proxy pod can reach the external Langfuse HTTPS endpoint?

**Decision**: Add an Istio `ServiceEntry` for the external Langfuse host and a `DestinationRule` specifying `tls.mode: DISABLE` for traffic from the PII proxy pod to Langfuse (because Envoy handles its own TLS — Istio must not add another TLS layer). Annotate the PII proxy pod with `traffic.sidecar.istio.io/excludeOutboundPorts: "443"` to prevent the Istio sidecar from intercepting Envoy's outbound HTTPS connection.

**Rationale**:

- In Istio clusters with `outboundTrafficPolicy: REGISTRY_ONLY` (common in production), any traffic to an unknown external host is blocked. The `ServiceEntry` registers Langfuse as a known external host.
- Without port exclusion, the Istio sidecar would intercept Envoy's outbound connection to port 443, attempt to apply mTLS (or SIMPLE TLS via DestinationRule), and conflict with Envoy's own `UpstreamTlsContext`. Double-TLS causes handshake failures.
- The `excludeOutboundPorts` annotation only affects port 443 on the proxy pod — all other outbound traffic (including any internal services) remains under Istio control.

**Istio resources**:

```yaml
# ServiceEntry — register external Langfuse host
apiVersion: networking.istio.io/v1beta1
kind: ServiceEntry
metadata:
  name: langfuse-external
  namespace: pii-proxy
spec:
  hosts:
    - "{{ .Values.langfuse.host }}"
  ports:
    - number: {{ .Values.langfuse.port }}
      name: https
      protocol: HTTPS
  location: MESH_EXTERNAL
  resolution: DNS

---
# DestinationRule — tell Istio NOT to add TLS (Envoy does it already)
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: langfuse-external
  namespace: pii-proxy
spec:
  host: "{{ .Values.langfuse.host }}"
  trafficPolicy:
    tls:
      mode: DISABLE
```

**Pod annotation** (added to PII proxy Deployment template):

```yaml
annotations:
  traffic.sidecar.istio.io/excludeInboundPorts: "443"
  traffic.sidecar.istio.io/excludeOutboundPorts: "443"
```

**Alternatives considered**:

- **`sidecar.istio.io/inject: "false"`**: Disables the Istio sidecar entirely on the proxy pod, removing the need for a ServiceEntry. Simpler for the proxy itself but means the pod is invisible to Istio telemetry, mTLS between apps and the proxy is not enforced, and REGISTRY_ONLY egress is bypassed. Rejected: the proxy pod should remain a mesh participant for observability and policy enforcement.
- **Istio egress gateway**: Routes all external traffic through a dedicated egress gateway pod. Required in high-security environments. Significantly more complex to configure. Deferred as a hardening option — the Helm values structure leaves room for it.

---

## R5: Langfuse API — Mock Server Contract

**Question**: Which Langfuse API endpoints does the Langfuse Python SDK v2+ use, and what response format does it expect?

**Decision**: The Langfuse Python SDK v2+ uses a single batch ingestion endpoint: `POST /api/public/ingestion`. The mock server must implement this endpoint, accepting any valid JSON body and returning an HTTP 207 response with the Langfuse batch-result envelope.

**Rationale**:

- The Langfuse SDK collects events into an internal queue and flushes them in batches to `/api/public/ingestion`. Individual `lf.trace(...)`, `lf.generation(...)` calls do not send HTTP immediately — they enqueue events.
- Authentication: SDK sends `Authorization: Basic <base64(public_key:secret_key)>` — the mock server accepts any credentials without validation.
- Request body format (simplified):

  ```json
  {
    "batch": [
      {"id": "uuid", "type": "trace-create", "timestamp": "iso8601", "body": {...}}
    ]
  }
  ```

- Response format (HTTP 207):

  ```json
  {"successes": [{"id": "uuid", "status": 201}], "errors": []}
  ```

**Mock server also exposes** `GET /captured` — returns the list of all captured request bodies as JSON for test assertion (not part of the Langfuse API; test-only endpoint).

**Alternatives considered**:

- **Wiremock or pre-built Langfuse stub**: Adds a Java or Node.js dependency. A minimal FastAPI server in Python keeps the test stack uniform (all Python) and is trivial to extend with assertion endpoints.

---

## R6: Python Langfuse SDK Test Client Configuration

**Question**: How is the Python Langfuse SDK configured to target the PII proxy instead of the real Langfuse server?

**Decision**: Set `LANGFUSE_HOST=https://pii-proxy.pii-proxy.svc.cluster.local` and `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` to dummy values. In the test pod, mount the proxy's CA certificate and point `SSL_CERT_FILE` to it, or set `LANGFUSE_SSL_VERIFY=false` for quick local testing.

**Rationale**:

- The Langfuse Python SDK reads `LANGFUSE_HOST` from the environment and uses it as the base URL for all API calls. No code change is needed in an instrumented application — only the env var changes.
- `httpx` (the Langfuse SDK's HTTP client) respects `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` environment variables for custom CA trust. This is the cleanest way to trust a cluster-internal self-signed cert without modifying SDK code.
- `LANGFUSE_SSL_VERIFY=false` is the SDK's built-in flag to disable certificate verification — acceptable in test environments (minikube with self-signed cert), not acceptable in production.

**Test client snippet**:

```python
from langfuse import Langfuse
import os

lf = Langfuse(
    host=os.environ["LANGFUSE_HOST"],         # https://pii-proxy.pii-proxy.svc.cluster.local
    public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", "test-pk"),
    secret_key=os.environ.get("LANGFUSE_SECRET_KEY", "test-sk"),
)

# Trace containing PII that MUST be scrubbed before reaching the mock server
trace = lf.trace(
    name="pii-test",
    input={
        "user_message": "Hi, I'm Alice Johnson, my email is alice@example.com and my phone is 555-867-5309",
        "session_id": "sess-001",
    },
)
generation = trace.generation(
    name="llm-call",
    model="gpt-4",
    input=[{"role": "user", "content": "Hi, I'm Alice Johnson, please help me"}],
    output="Hello Alice, how can I help you?",
)
lf.flush()
print("Done. Check mock server /captured for scrubbed payload.")
```

**Assertion**: query mock server `GET /captured`, verify no occurrences of "Alice Johnson", "<alice@example.com>", "555-867-5309" in any captured body.

---

## R7: Istio + minikube Full TLS Test Cluster Setup

**Question**: What is the complete Istio + TLS configuration required on minikube for the end-to-end integration test, with TLS fully enabled between the test client and the proxy?

**Decision**: Use Istio's `demo` profile on minikube. The test uses **full TLS** on the inbound side (client → proxy over HTTPS using a self-signed CA certificate) and plain HTTP on the outbound side (proxy → mock Langfuse server, which is cluster-internal). The self-signed CA cert is generated by `test-fixtures/certs/gen-certs.sh`, stored as a `kubernetes.io/tls` Secret, mounted into the proxy pod, and trusted by the test client pod via `SSL_CERT_FILE`. Istio's ServiceEntry and DestinationRule are deployed and verified.

**Rationale**:

- Full TLS on inbound exercises the `DownstreamTlsContext` Envoy configuration and the Istio port-exclusion annotation (`excludeInboundPorts: "443"`) in the actual test — not just in theory.
- Plain HTTP on the outbound side (proxy → mock Langfuse) is correct because the mock server is cluster-internal (not a real external endpoint). This keeps the test deterministic and avoids needing a cert on the mock server.
- The test validates the key interaction: Langfuse SDK sends HTTPS → proxy terminates TLS → scrubs PII → forwards HTTP to mock → mock responds → proxy returns ACK to SDK. The entire chain is exercised.
- Using a self-signed CA (rather than `SSL_VERIFY=false`) makes the test more realistic — it verifies that the cert trust chain is correctly set up end-to-end.

**TLS certificate generation** (`test-fixtures/certs/gen-certs.sh`):

```bash
#!/usr/bin/env bash
# Generates a self-signed CA and a proxy TLS certificate valid for the cluster-internal DNS name.
set -euo pipefail

OUTDIR="${1:-/tmp/pii-proxy-certs}"
mkdir -p "$OUTDIR"
PROXY_SAN="pii-proxy.pii-proxy.svc.cluster.local"

# 1. Self-signed CA
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout "$OUTDIR/ca.key" -out "$OUTDIR/ca.crt" -days 3650 \
  -subj "/CN=pii-proxy-test-ca/O=Test"

# 2. Server key + CSR
openssl req -newkey rsa:4096 -nodes \
  -keyout "$OUTDIR/tls.key" -out "$OUTDIR/tls.csr" \
  -subj "/CN=$PROXY_SAN"

# 3. Sign with CA, include SAN
openssl x509 -req -in "$OUTDIR/tls.csr" \
  -CA "$OUTDIR/ca.crt" -CAkey "$OUTDIR/ca.key" -CAcreateserial \
  -out "$OUTDIR/tls.crt" -days 365 \
  -extfile <(printf "subjectAltName=DNS:%s" "$PROXY_SAN")

echo "Certificates written to $OUTDIR"
echo "  CA cert:     $OUTDIR/ca.crt"
echo "  Server cert: $OUTDIR/tls.crt"
echo "  Server key:  $OUTDIR/tls.key"
```

**Kubernetes Secret** (created from generated certs):

```bash
kubectl create secret tls pii-proxy-tls \
  --cert="$OUTDIR/tls.crt" \
  --key="$OUTDIR/tls.key" \
  -n pii-proxy
```

**Test client trust** (CA cert mounted into the client pod; Langfuse SDK uses `SSL_CERT_FILE`):

```bash
kubectl create configmap pii-proxy-ca \
  --from-file=ca.crt="$OUTDIR/ca.crt" \
  -n pii-proxy
```

The test client pod mounts this ConfigMap and sets `SSL_CERT_FILE=/certs/ca.crt`. The Langfuse Python SDK's underlying `httpx` client inherits `SSL_CERT_FILE` automatically.

**Istio configuration in test**:

- `demo` profile — includes all Istio components, PERMISSIVE mTLS mode by default.
- `pii-proxy` namespace: labeled `istio-injection=enabled`.
- `langfuse-mock` namespace: NOT labeled for injection (simulates external server).
- `istio.enabled=true` in Helm values: ServiceEntry + DestinationRule are deployed.
- ServiceEntry registers `mock-langfuse.langfuse-mock.svc.cluster.local` as a known host on port 8080 (HTTP).
- DestinationRule sets `tls.mode: DISABLE` for the mock Langfuse host (no Istio TLS to an HTTP server).
- Pod annotations: `excludeInboundPorts: "443"` prevents Istio intercepting Envoy's HTTPS listener; `excludeOutboundPorts: "8080"` prevents Istio from adding mTLS to the proxy's outbound HTTP connection to the mock.

**Full TLS test topology**:

```
[langfuse-client pod] --HTTPS (TLS, trusts CA cert)--> [pii-proxy pod :443]
                                                              |
                                                    Envoy terminates TLS
                                                    ext_proc scrubs PII
                                                              |
                                                   [mock-langfuse pod :8080] (HTTP)
                                                   (langfuse-mock namespace, no sidecar)
```

**minikube setup commands** (updated for full TLS):

```bash
minikube start --memory=8192 --cpus=4 --driver=docker
istioctl install --set profile=demo -y
kubectl get pods -n istio-system   # wait for all Running

kubectl create namespace pii-proxy
kubectl label namespace pii-proxy istio-injection=enabled

kubectl create namespace langfuse-mock
# langfuse-mock: deliberately NOT labeled for sidecar injection

# Generate certs
bash test-fixtures/certs/gen-certs.sh /tmp/pii-proxy-certs

# Store cert as Secret + CA as ConfigMap
kubectl create secret tls pii-proxy-tls \
  --cert=/tmp/pii-proxy-certs/tls.crt --key=/tmp/pii-proxy-certs/tls.key \
  -n pii-proxy
kubectl create configmap pii-proxy-ca \
  --from-file=ca.crt=/tmp/pii-proxy-certs/ca.crt \
  -n pii-proxy
```

**Alternatives considered**:

- **`LANGFUSE_SSL_VERIFY=false`**: simpler test setup (no cert generation). Rejected for the full test path because it does not verify the TLS configuration works correctly — the whole point of `tls.enabled=true` is to validate the cert chain.
- **cert-manager**: production-grade, automated cert renewal. Adds a cert-manager installation step to the test setup. Deferred to a hardening task.
- **Istio auto-mTLS for client→proxy**: would upgrade the client's HTTP to mTLS automatically. Conflicts with Envoy's `DownstreamTlsContext` (double TLS). Port exclusion on 443 is the correct solution.
