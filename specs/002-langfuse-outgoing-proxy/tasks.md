# Tasks: Outgoing HTTPS Proxy for Langfuse

**Input**: Design documents from `/specs/002-langfuse-outgoing-proxy/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/values-schema.md ✅, contracts/istio-resources.md ✅, contracts/langfuse-mock-api.md ✅, quickstart.md ✅
**Branch**: `002-langfuse-outgoing-proxy` | **Date**: 2026-03-30

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete sibling task)
- **[Story]**: User story phase tasks only — [US1], [US2], [US3]
- All file paths are relative to the repository root

---

## Phase 1: Setup

**Purpose**: Create test-fixture scaffolding and baseline structure required by all stories.
No dependencies — can start immediately.

- [x] T001 Create directory skeleton with `.gitkeep` placeholders in `test-fixtures/mock-langfuse/`, `test-fixtures/langfuse-client/`, and `test-fixtures/certs/`
- [x] T002 [P] Add section stub for outgoing-proxy execution notes in `specs/002-langfuse-outgoing-proxy/quickstart.md` to record command outputs captured during validation runs

**Checkpoint**: Fixture directories exist and quickstart has a dedicated validation-notes section.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Helm values and validation gates that block all downstream template work.
**⚠️ CRITICAL**: No user-story implementation can begin before this phase completes.

- [x] T003 [P] Extend `helm/pii-proxy/values.yaml` with outgoing mode keys from `specs/002-langfuse-outgoing-proxy/contracts/values-schema.md`: `mode`, `langfuse.*`, `tls.*`, `istio.*`, `envoy.httpsPort`, `service.httpsPort`
- [x] T004 [P] Add/verify value guards in `helm/pii-proxy/templates/_helpers.tpl` using `required` for `langfuse.host` in outgoing mode, `upstream.host` in reverse mode, and `tls.secretName` when `tls.enabled=true`
- [x] T005 Add chart-level smoke validation commands to `specs/002-langfuse-outgoing-proxy/quickstart.md`: `helm lint` and two `helm template` invocations (one success path and one expected failure path)

**Checkpoint**: `helm lint helm/pii-proxy` passes and value-gate behavior matches schema contract.

---

## Phase 3: User Story 1 - Application Routes Langfuse Traffic Through PII Proxy (Priority: P1) 🎯 MVP

**Goal**: Outgoing Langfuse request bodies are scrubbed before forwarding; acknowledgements are relayed unchanged.

**Independent Test**: Deploy without TLS (`tls.enabled=false`, `langfuse.tls.enabled=false`) and verify captured upstream payload contains placeholders and no raw PII.

### Tests for User Story 1

> **Constitution III (Test-First)**: Write tests first, verify they fail, then implement.

- [x] T006 [US1] Create request-path unit tests in `ext_proc/tests/test_request_scrubbing.py` for email redaction, non-PII fidelity, and `text/plain` content-type handling through `request_headers` + `request_body` flow

### Implementation for User Story 1

- [x] T007 [US1] Implement request handling branches in `ext_proc/app.py` for `request_headers` and `request_body`, including warning-level structured logging on scrub failures without logging raw body content
- [x] T008 [P] [US1] Add outgoing-mode Envoy config in `helm/pii-proxy/templates/configmap-envoy.yaml` with `request_header_mode: SEND`, `request_body_mode: BUFFERED`, `response_body_mode: NONE`, and `max_request_bytes` limit for large-payload protection
- [x] T009 [P] [US1] Create mock Langfuse fixture files `test-fixtures/mock-langfuse/app.py`, `test-fixtures/mock-langfuse/Dockerfile`, and `test-fixtures/mock-langfuse/requirements.txt` implementing `POST /api/public/ingestion`, `GET /captured`, `DELETE /captured`, `GET /health`
- [x] T010 [US1] Add HTTP-only MVP validation procedure in `specs/002-langfuse-outgoing-proxy/quickstart.md` that deploys mock + proxy and verifies `alice@example.com` is absent from `GET /captured`

**Checkpoint**: US1 independently passes with scrubbed outgoing requests and unchanged non-PII data.

---

## Phase 4: User Story 2 - Platform Engineer Deploys and Wires the Proxy in the Istio Mesh (Priority: P2)

**Goal**: Helm deploys full TLS listener + Istio wiring; application reaches proxy over HTTPS with trusted CA.

**Independent Test**: Execute full quickstart path (minikube + Istio + TLS) and verify SDK client succeeds and Istio resources render correctly.

### Implementation for User Story 2

- [x] T011 [P] [US2] Create `helm/pii-proxy/templates/istio-resources.yaml` with conditional `ServiceEntry` and `DestinationRule` (`tls.mode: DISABLE` as a constant, no redundant conditional)
- [x] T012 [P] [US2] Update `helm/pii-proxy/templates/deployment.yaml` to mount TLS Secret at `/certs`, expose HTTPS container port, and add Istio exclude-port annotations when `istio.enabled=true`
- [x] T013 [US2] Update `helm/pii-proxy/templates/configmap-envoy.yaml` to support TLS listener via `DownstreamTlsContext` and upstream TLS origination via conditional `UpstreamTlsContext` (depends on T008)
- [x] T014 [P] [US2] Update `helm/pii-proxy/templates/service.yaml` to expose conditional HTTPS service port while retaining HTTP port
- [x] T015 [P] [US2] Create certificate helper script `test-fixtures/certs/gen-certs.sh` to generate `ca.crt`, `tls.crt`, and `tls.key` for `pii-proxy.pii-proxy.svc.cluster.local`
- [x] T016 [P] [US2] Create SDK client fixture files `test-fixtures/langfuse-client/send_traces.py`, `test-fixtures/langfuse-client/Dockerfile`, and `test-fixtures/langfuse-client/requirements.txt` with baseline PII trace (`Alice Johnson`, `alice@example.com`, `555-867-5309`)
- [x] T017 [US2] Add full TLS+Istio validation steps to `specs/002-langfuse-outgoing-proxy/quickstart.md` covering cert secret/configmap creation, Helm install flags, client run, and captured-payload assertion

**Checkpoint**: US2 independently passes with HTTPS client-to-proxy path and Istio egress resources present.

---

## Phase 5: User Story 3 - Security Engineer Audits That No PII Leaves the Cluster (Priority: P3)

**Goal**: Security verification proves 0% leakage for required PII categories and confirms reliability in failure paths.

**Independent Test**: Execute extended payload suite and failure scenarios; confirm placeholders appear, raw PII does not, and upstream failures are propagated.

### Tests for User Story 3

- [x] T018 [P] [US3] Extend `ext_proc/tests/test_request_scrubbing.py` with nested JSON, multi-category PII, physical-address redaction, clean payload fidelity, and malformed JSON safety cases

### Implementation and Validation for User Story 3

- [x] T019 [P] [US3] Extend scenario generator in `test-fixtures/langfuse-client/send_traces.py` with nested PII, multi-PII (including address), and clean payload traces
- [x] T020 [US3] Add security audit procedure to `specs/002-langfuse-outgoing-proxy/quickstart.md` validating SC-001/SC-002 via `GET /captured`, plus ext-proc log inspection ensuring no raw PII appears in logs
- [x] T021 [US3] Add upstream-unreachable test steps to `specs/002-langfuse-outgoing-proxy/quickstart.md` by stopping mock service and asserting proxy returns 5xx error (FR-009)

**Checkpoint**: US3 independently demonstrates privacy guarantees and correct failure behavior.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final docs, deterministic Helm test behavior, and non-functional verification.

- [x] T022 [P] Update outgoing-mode operator guidance in `helm/pii-proxy/README.md` including required values, TLS/Istio options, and quickstart links
- [x] T023 [P] Add outgoing Helm test hook in `helm/pii-proxy/templates/tests/test-scrubbing-outgoing.yaml` that validates HTTP status behavior only (no dependency on external mock endpoint)
- [x] T024 [P] Add TLS-render verification commands to `specs/002-langfuse-outgoing-proxy/quickstart.md` using `helm template` checks for `UpstreamTlsContext` when `langfuse.tls.enabled=true`
- [x] T025 Add latency verification instructions for SC-004 in `specs/002-langfuse-outgoing-proxy/quickstart.md` with baseline direct-call timing vs proxy-call timing and p95/p99 capture notes
- [x] T026 Add runtime upstream TLS verification steps in `specs/002-langfuse-outgoing-proxy/quickstart.md`: deploy mock Langfuse with TLS listener, set `langfuse.tls.enabled=true`, send trace through proxy, and assert successful TLS handshake plus scrubbed payload on `GET /captured` (FR-003)
- [x] T027 Run full clean-cluster validation checklist in `specs/002-langfuse-outgoing-proxy/quickstart.md` and record actual outputs in the validation-notes section

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no dependencies
- **Phase 2 (Foundational)**: depends on Phase 1; blocks all user stories
- **Phase 3 (US1)**: depends on Phase 2
- **Phase 4 (US2)**: depends on Phase 3
- **Phase 5 (US3)**: depends on Phase 4
- **Phase 6 (Polish)**: depends on Phase 5

### User Story Dependencies

- **US1 (P1)**: independent after Foundational; MVP slice
- **US2 (P2)**: builds on US1 Envoy outgoing-mode foundation (`helm/pii-proxy/templates/configmap-envoy.yaml`)
- **US3 (P3)**: builds on US2 deployment/fixture stack

### Within Each User Story

- Write tests first and verify fail state before implementation
- Implement core logic before deployment/integration validation
- Complete independent test criteria before proceeding to the next story

### Parallel Opportunities

- **Phase 2**: T003 and T004 can run in parallel
- **US1**: T008 and T009 can run in parallel after T007
- **US2**: T011, T012, T014, T015, T016 can run in parallel; T013 depends on T008
- **US3**: T018 and T019 can run in parallel
- **Polish**: T022, T023, T024 can run in parallel; T026 depends on T015 (certs) and T009 (mock)

---

## Parallel Example: User Story 2

```bash
# After US1 checkpoint, run independent US2 tasks in parallel

# Terminal 1
vim helm/pii-proxy/templates/istio-resources.yaml  # T011

# Terminal 2
vim helm/pii-proxy/templates/deployment.yaml       # T012

# Terminal 3
vim helm/pii-proxy/templates/service.yaml          # T014

# Terminal 4
vim test-fixtures/certs/gen-certs.sh               # T015

# Terminal 5
vim test-fixtures/langfuse-client/send_traces.py   # T016

# Then update TLS-specific Envoy rendering
vim helm/pii-proxy/templates/configmap-envoy.yaml  # T013
```

---

## Implementation Strategy

**MVP first (US1 only)**:

Deliver request-body scrubbing to Langfuse over HTTP with deterministic mock verification. This proves core privacy value quickly.

**Increment 2 (US2)**:

Add production-like deployment behavior: TLS listener, CA trust path, and Istio egress resources.

**Increment 3 (US3 + Polish)**:

Harden security confidence with broader PII suites, unreachable-upstream behavior, deterministic Helm tests, TLS-render assertions, and latency verification.
