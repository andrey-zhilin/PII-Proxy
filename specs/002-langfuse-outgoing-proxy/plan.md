# Implementation Plan: Outgoing HTTPS Proxy for Langfuse

**Branch**: `002-langfuse-outgoing-proxy` | **Date**: 2026-03-23 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-langfuse-outgoing-proxy/spec.md`

## Summary

Add an outgoing-proxy operation mode to the PII proxy so that LLM applications running inside an Istio service mesh can route their Langfuse telemetry traffic through the proxy. The proxy scrubs all PII from request bodies before forwarding them over HTTPS to the external Langfuse server, then relays the Langfuse acknowledgement response unchanged back to the application. The existing Helm chart is extended with new configuration groups (`langfuse`, `tls`, `istio`) and a new Istio resource template is added. The ext_proc service gains a request-body processing path alongside the existing response-body path. The integration test harness uses minikube + Istio with **full TLS enabled end-to-end**: a self-signed CA issues a certificate for the proxy's HTTPS listener, the Python Langfuse SDK client trusts it via `SSL_CERT_FILE`, and Istio mesh policies (ServiceEntry + DestinationRule) are exercised.

## Technical Context

**Language/Version**: Python 3.11 (ext_proc), Helm 3 / YAML (deployment config), Envoy v1.33.0
**Primary Dependencies**: Envoy ext_proc v3 gRPC API (existing), Presidio + spaCy `en_core_web_lg` (existing scrubber), Langfuse Python SDK `langfuse>=2.0` (test client only), FastAPI (mock Langfuse server), Istio 1.20+ CRDs (ServiceEntry, DestinationRule), Kubernetes 1.28+, openssl (cert generation in test setup)
**Storage**: N/A
**Testing**: pytest (unit — request body scrubbing), minikube full-stack integration test (Istio + TLS enabled, Langfuse SDK client + mock server), Helm test hook
**Target Platform**: Kubernetes 1.28+, Istio 1.20+, minikube v1.32+ (testing)
**Project Type**: Infrastructure sidecar proxy service
**Performance Goals**: ≤ 500 ms additional latency p99 per request (SC-004)
**Constraints**: Full TLS in test environment (application → proxy over HTTPS using self-signed cert; proxy → mock Langfuse over HTTP since mock is internal); Istio configured in cluster (`demo` profile on minikube); compatible with Istio mTLS (PERMISSIVE mode); no application code changes beyond `LANGFUSE_HOST` and `SSL_CERT_FILE` env vars; `failure_mode_allow: false` hardcoded
**Scale/Scope**: Single proxy deployment per namespace; one upstream target (Langfuse server)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Privacy-First | ⚠️ JUSTIFIED DEVIATION | Constitution I was written for the reverse-proxy case (scrub response bodies). This feature scrubs **request** bodies instead (outgoing prompts to Langfuse). Langfuse response bodies (trace-ID ACKs) are not user data and are not scrubbed — this is the correct privacy decision. `failure_mode_allow: false` is retained: scrub failure blocks the request, never forwards raw PII. |
| II. Transparently Invisible | ⚠️ MINIMAL DEVIATION | Application must set `LANGFUSE_HOST` and `SSL_CERT_FILE` (or equivalent). No SDK installation, no library code change. Configuration-only change; acceptable. |
| III. Test-First | ✅ COMPLIANT | Unit tests for request-body scrubbing must be written first. Full-stack integration test (Langfuse SDK client → HTTPS proxy → mock server, Istio ServiceEntry enforced) validates end-to-end before implementation is merged. |
| IV. Simplicity (YAGNI) | ⚠️ RATIFIED EXTENSION | Constitution IV states request bodies MUST NOT be modified unless a specific privacy requirement is ratified. This plan ratifies request-body scrubbing for the Langfuse outgoing proxy use case only. |
| V. Containerized & Reproducible | ✅ COMPLIANT | All test components (mock server, client) are Docker containers loadable via `minikube image load`. Certificate generation is scripted. `docker compose up --build` still functions for existing local-dev usage. |

**Gate result**: PASS with documented justified deviations on Principles I and IV. No blocking violations.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
ext_proc/
├── app.py                             # MODIFIED: add request_body handling path
├── scrubber/
│   └── scrubber.py                    # UNCHANGED: scrub_bytes() already handles request bodies
└── tests/
    └── test_request_scrubbing.py      # NEW: unit tests for outgoing request body scrubbing

helm/pii-proxy/
├── values.yaml                        # MODIFIED: add langfuse, tls, istio, mode value groups
├── templates/
│   ├── configmap-envoy.yaml           # MODIFIED: outgoing-proxy config (request scrubbing, DownstreamTlsContext, UpstreamTlsContext)
│   ├── deployment.yaml                # MODIFIED: TLS cert volume mount, Istio sidecar annotations
│   ├── service.yaml                   # MODIFIED: expose HTTPS port (443)
│   └── istio-resources.yaml           # NEW: ServiceEntry + DestinationRule (conditional on istio.enabled)

test-fixtures/
├── mock-langfuse/
│   ├── app.py                         # NEW: FastAPI mock Langfuse server (/api/public/ingestion, /captured)
│   ├── Dockerfile                     # NEW
│   └── requirements.txt               # NEW
├── langfuse-client/
│   ├── send_traces.py                 # NEW: Python Langfuse SDK test script with PII payloads
│   ├── Dockerfile                     # NEW
│   └── requirements.txt               # NEW
└── certs/
    └── gen-certs.sh                   # NEW: generates self-signed CA + proxy TLS cert for test environment
```

**Structure Decision**: Two-container sidecar Pod (Envoy + ext_proc) is retained from spec 001. New resources added to the existing Helm chart — no new chart. Test fixtures live under `test-fixtures/` (separate from `dummy-server/` used for reverse-proxy testing).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Principle I deviation: Langfuse ACK bodies not scrubbed | Langfuse ACKs contain trace IDs and status codes — zero user PII. Scrubbing them wastes latency and CPU. | Scrubbing 50-byte ACKs adds 100–300 ms per round-trip with no privacy benefit. |
| Principle II deviation: `SSL_CERT_FILE` env var required | Application must trust the proxy's self-signed cert. This is a one-env-var configuration change, not a code change. | No simpler alternative when operating in full-TLS mode — the SDK's HTTP client must trust the cert. |
| Principle IV ratification: request body mutation | This feature's entire value is scrubbing outgoing LLM prompts before they reach Langfuse. | No simpler alternative exists — the whole point is modifying the outbound request body. |
