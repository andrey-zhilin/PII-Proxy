# Feature Specification: Outgoing HTTPS Proxy for Langfuse

**Feature Branch**: `002-langfuse-outgoing-proxy`
**Created**: March 23, 2026
**Status**: Draft
**Input**: User description: "Build ability for PII proxy to be used as proxy for outgoing HTTPs for langfuse server. Target application itself is supposed to be deployed inside Istio service mesh. Langfuse is outside of the cluster"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Application Routes Langfuse Traffic Through PII Proxy (Priority: P1)

An application developer has an LLM-powered service running inside the Istio service mesh. The application instruments its LLM calls using the Langfuse SDK, which sends traces, prompts, completions, and metadata to an external Langfuse server. Some of these payloads may contain PII (e.g., user-provided prompts, model responses with names or contact details). The developer wants to ensure no PII reaches Langfuse by routing all Langfuse-bound traffic through the PII proxy instead of sending it directly. The developer reconfigures the Langfuse SDK base URL to point to the PII proxy service within the cluster; the proxy scrubs PII from every request body and forwards the sanitized payload to the real Langfuse endpoint over a secure connection.

**Why this priority**: This is the core value proposition. Without this working end-to-end, no other story delivers value.

**Independent Test**: Can be fully tested by sending a Langfuse trace payload containing synthetic PII through the proxy and verifying that the captured upstream request to Langfuse does not contain the original PII, with the Langfuse SDK receiving a valid acknowledgement response.

**Acceptance Scenarios**:

1. **Given** the PII proxy is deployed and configured with the Langfuse external endpoint, **When** an application sends a trace payload containing an email address to the proxy, **Then** the proxy forwards the payload to Langfuse with the email address replaced by a placeholder and returns a valid Langfuse response to the application.
2. **Given** the PII proxy is running, **When** an application sends a payload containing no PII, **Then** the proxy forwards the payload unmodified to Langfuse and returns the response unchanged.
3. **Given** the PII proxy is running, **When** the application sends a batch of traces over multiple sequential requests, **Then** all requests are processed independently and each receives the correct Langfuse response.

---

### User Story 2 - Platform Engineer Deploys and Wires the Proxy in the Istio Mesh (Priority: P2)

A platform engineer needs to deploy the PII proxy as a reachable service within the Istio service mesh and configure the mesh to allow the proxy to open egress connections to the external Langfuse server. The engineer must be able to set the Langfuse target endpoint via configuration (not hardcoded), so the same proxy deployment can target different environments (cloud Langfuse, self-hosted Langfuse, staging vs production).

**Why this priority**: A working business logic layer (P1) is useless if it cannot be deployed and wired correctly within the target infrastructure.

**Independent Test**: Can be fully tested by deploying the proxy with a configured Langfuse endpoint, sending a test request from a pod inside the mesh, and confirming the request reaches the real Langfuse endpoint (using a mock or test Langfuse instance outside the cluster).

**Acceptance Scenarios**:

1. **Given** a Kubernetes cluster with Istio installed, **When** the platform engineer deploys the PII proxy with the Langfuse host and port configured, **Then** the proxy service is reachable from other pods in the mesh on a known internal address.
2. **Given** the proxy is deployed, **When** the proxy attempts to reach the configured Langfuse external endpoint, **Then** Istio mesh egress policies permit the outbound connection and the request is delivered.
3. **Given** the Langfuse endpoint configuration is changed (e.g., switched from staging to production Langfuse), **When** the new configuration is applied, **Then** the proxy routes all subsequent requests to the new endpoint without requiring changes to applications.

---

### User Story 3 - Security Engineer Audits That No PII Leaves the Cluster (Priority: P3)

A security or compliance engineer needs to verify that the PII proxy is effective: that actual PII present in LLM trace payloads is consistently removed or masked before the data is transmitted to the external Langfuse server. The engineer should be able to confirm this through proxy logs or by capturing traffic between the proxy and Langfuse.

**Why this priority**: Compliance validation is important but depends on P1 and P2 being in place first.

**Independent Test**: Can be tested by running a suite of test payloads with known PII patterns through the proxy and comparing the payload captured going out to Langfuse against the original, confirming all PII instances are replaced.

**Acceptance Scenarios**:

1. **Given** a request payload containing names, email addresses, and phone numbers, **When** the proxy processes it, **Then** all recognized PII is replaced with non-identifying placeholder values in the forwarded payload.
2. **Given** a request payload where PII appears in deeply nested JSON fields, **When** the proxy processes it, **Then** the nested PII is still detected and scrubbed before forwarding.
3. **Given** the proxy has processed a batch of requests, **When** the security engineer reviews proxy logs, **Then** the logs confirm scrubbing activity occurred without exposing the original PII values in the log output.

---

### Edge Cases

- What happens when the Langfuse external endpoint is unreachable? The proxy must return an appropriate error status to the calling application without silently dropping the request.
- What happens when the request body is not valid JSON? The proxy must handle non-JSON or malformed bodies gracefully — either pass them through unmodified or return a clear error — without crashing.
- What happens when a payload is extremely large (e.g., a long prompt/completion)? The system must either process it within a reasonable time or reject it with a clear size-limit error rather than timing out silently.
- What happens when the Istio sidecar proxy intercepts or mutates the connection before it reaches the PII proxy? The design must account for potential double-proxying or TLS re-negotiation introduced by Istio.
- What happens when Langfuse returns an error response? The proxy must relay the error status and body back to the calling application unchanged.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The PII proxy MUST accept inbound HTTPS requests from applications inside the Istio service mesh and forward them to a configurable external Langfuse endpoint.
- **FR-002**: The PII proxy MUST scrub all recognized PII categories from outgoing request bodies before forwarding to Langfuse. Supported PII categories include at minimum: person names, email addresses, phone numbers, and physical addresses.
- **FR-003**: The PII proxy MUST establish a secure (TLS-encrypted) connection to the external Langfuse endpoint when forwarding requests, regardless of the protocol used by the internal calling application.
- **FR-004**: The PII proxy MUST be configurable with the Langfuse server hostname and port without requiring a code change or container rebuild.
- **FR-005**: The PII proxy MUST preserve all non-PII fields in the request payload without alteration, modification of field order, or re-encoding.
- **FR-006**: The PII proxy MUST relay Langfuse responses back to the calling application with HTTP or HTTPS status code and body intact.
- **FR-007**: The PII proxy MUST be deployable as a standalone Kubernetes service within an Istio service mesh, with Istio sidecar injection either enabled or explicitly excluded based on operational needs.
- **FR-008**: The Istio mesh configuration MUST define an egress policy that permits the PII proxy to reach the external Langfuse host and port.
- **FR-009**: The PII proxy MUST propagate connection errors from the upstream Langfuse endpoint to the calling application as appropriate HTTP error responses rather than silently failing.
- **FR-010**: The PII proxy MUST scrub outgoing request bodies only. Langfuse response bodies are relayed back to the calling application without scrubbing, as they contain acknowledgement data (trace IDs, status) rather than user-submitted content.

### Key Entities

- **PII Proxy**: The proxy service — receives inbound requests from internal applications, passes bodies through a scrubbing service, and forwards sanitized requests to an external destination over a secure connection.
- **Scrubbing Service**: The co-deployed processing service that inspects and modifies request (and optionally response) bodies, replacing detected PII with non-identifying placeholders.
- **Target Application**: Any application pod inside the Istio service mesh that uses the Langfuse SDK or sends HTTP requests to a Langfuse endpoint. It is the source of outbound trace traffic.
- **Langfuse Server**: The external LLM observability platform (cloud-hosted or self-hosted outside the cluster) that receives trace, span, and event data from instrumented applications.
- **Trace Payload**: The structured data body sent by the application to Langfuse — contains LLM inputs (prompts), outputs (completions), metadata, tags, and scores. This is the primary artifact subject to PII scrubbing.
- **Egress Policy**: The Istio mesh-level configuration that controls which external hosts the proxy is permitted to contact.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All tested PII patterns (names, emails, phone numbers, addresses) present in outgoing Langfuse payloads are replaced with placeholders — 0% of tested PII instances reach the external Langfuse endpoint.
- **SC-002**: Non-PII fields in every scrubbed payload are delivered to Langfuse without modification — 100% structural and value fidelity for non-PII data.
- **SC-003**: Applications using the Langfuse SDK require no code changes beyond updating the Langfuse base URL to point to the proxy service — all other SDK behaviour remains unchanged.
- **SC-004**: The proxy adds no more than 500 ms of additional end-to-end latency per request under normal operating conditions (measured as the difference between direct Langfuse call latency and proxy-routed Langfuse call latency).
- **SC-005**: The platform engineer can deploy the proxy and complete end-to-end wiring within the Istio mesh using only the provided deployment configuration artifacts, with no manual cluster-level steps beyond applying standard Kubernetes resources.

## Assumptions

- The Langfuse SDK used by target applications supports configuring a custom base URL, making it possible to redirect traffic to the PII proxy without modifying SDK internals.
- The Langfuse external endpoint is reachable from the Kubernetes cluster via a standard HTTPS connection on port 443 (or a configurable port).
- The application sends HTTPS to the PII proxy. The proxy terminates the inbound TLS connection and establishes a new TLS connection to the external Langfuse server. The proxy must hold a TLS certificate trusted by the calling application. This keeps the entire traffic path encrypted and requires no protocol downgrade inside the mesh, at the cost of additional certificate management on the proxy.
- The PII detection and scrubbing capabilities already in use in this project are sufficient for the Langfuse use case, or can be extended using the existing scrubber interface.
- The proxy operates in a trusted internal network segment; authentication between the application and the proxy is not required (the mesh enforces access at the network level).
