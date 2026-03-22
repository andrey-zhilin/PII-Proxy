# Tasks: Kubernetes Deployment Package

**Input**: Design documents from `/specs/001-k8s-deployment/`  
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/values-schema.md ✅, quickstart.md ✅  
**Branch**: `001-k8s-deployment` | **Date**: 2026-03-22

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no block on incomplete sibling tasks)
- **[Story]**: User story phase tasks only — [US1], [US2], [US3], [US4]
- All file paths are relative to the repository root

---

## Phase 1: Setup

**Purpose**: Create the Helm chart skeleton and project structure.  
No dependencies — can start immediately.

- [ ] T001 Create Helm chart directory structure: `helm/pii-proxy/Chart.yaml`, `values.yaml`, `templates/`, `templates/tests/`
- [ ] T002 [P] Author `helm/pii-proxy/Chart.yaml` with name `pii-proxy`, version `0.1.0`, appVersion matching Envoy tag, and description
- [ ] T003 [P] Author `helm/pii-proxy/templates/_helpers.tpl` with `pii-proxy.fullname`, `pii-proxy.labels`, and `pii-proxy.selectorLabels` named templates

**Checkpoint**: `helm lint helm/pii-proxy` passes (empty chart, no templating errors).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core chart infrastructure that ALL user story templates depend on.  
**⚠️ CRITICAL**: Phases 3–6 cannot begin until this phase is complete.

- [ ] T004 Author `helm/pii-proxy/values.yaml` with all fields from `contracts/values-schema.md`: `upstream`, `replicaCount`, `image`, `envoy`, `extProc`, `service`, `resources`, `probes` — sentinel defaults for required fields (`upstream.host`, `image.extProc.repository`) via `required` helper
- [ ] T005 [P] Author `helm/pii-proxy/templates/configmap-envoy.yaml` — ConfigMap holding rendered `envoy.yaml` with template variables: `{{ .Values.envoy.listenPort }}`, `{{ .Values.upstream.host }}`, `{{ .Values.upstream.port }}`, `127.0.0.1:{{ .Values.extProc.grpcPort }}`; `failure_mode_allow: false` hardcoded (not a value)
- [ ] T006 [P] Author `helm/pii-proxy/templates/service.yaml` — Service with `spec.type: {{ .Values.service.type }}`, port `{{ .Values.service.port }}` → targetPort `{{ .Values.envoy.listenPort }}`; no port 50051 selector

**Checkpoint**: `helm lint helm/pii-proxy` passes; `helm template helm/pii-proxy --set upstream.host=test --set image.extProc.repository=test` renders ConfigMap and Service without errors.

---

## Phase 3: User Story 1 — One-Command Cluster Deployment (Priority: P1) 🎯 MVP

**Goal**: Deploy Envoy + ext_proc sidecar to a Kubernetes cluster with a single `helm upgrade --install` command; traffic is proxied and PII is scrubbed.

**Independent Test**: Run `helm upgrade --install` against a minikube namespace with `upstream.host` and `image.extProc.repository` set. Both containers reach `Running`/`Ready`. `curl` POST with name+email returns `<PERSON>` and `<EMAIL_ADDRESS>`.

### Helm Test — User Story 1

> **Constitution III (Test-First)**: Write and verify the test template BEFORE the Deployment template.

- [ ] T007 [US1] Author `helm/pii-proxy/templates/tests/test-scrubbing.yaml` — Helm test hook Pod (`helm.sh/hook: test`) that runs `curl -sf -X POST http://{{ include "pii-proxy.fullname" . }}:{{ .Values.service.port }}/ -H "Content-Type: text/plain" -d "My name is Jane Smith and her email is jane@example.com"` and pipes to `grep -q "<PERSON>"` && `grep -q "<EMAIL_ADDRESS>"`; exits non-zero on failure

### Implementation — User Story 1

- [ ] T008 [US1] Author `helm/pii-proxy/templates/deployment.yaml` — Kubernetes Deployment with `spec.replicas: {{ .Values.replicaCount }}`, two containers:
  - **envoy**: image `{{ .Values.image.envoy.repository }}:{{ .Values.image.envoy.tag }}`, port `{{ .Values.envoy.listenPort }}`, volumeMount `/etc/envoy/envoy.yaml` from ConfigMap volume, resources from `{{ .Values.resources.envoy }}`
  - **ext_proc**: image `{{ .Values.image.extProc.repository }}:{{ .Values.image.extProc.tag }}`, port `{{ .Values.extProc.grpcPort }}`, env `GRPC_PORT` and `SPACY_MODEL` from values, resources from `{{ .Values.resources.extProc }}`; NO readiness/liveness probes yet (added in Phase 5)
  - Pod volume mounting EnvoyConfigMap at `/etc/envoy/envoy.yaml`
  - `imagePullPolicy: {{ .Values.image.pullPolicy }}`
- [ ] T009 [US1] Author `helm/pii-proxy/templates/NOTES.txt` — Post-install message showing the `port-forward` command, prerequisite reminder (set `upstream.host` and `image.extProc.repository`), and minikube `image load` note
- [ ] T010 [US1] Validate end-to-end on minikube: `minikube start --cpus=4 --memory=8g`, build + load ext_proc image, `helm upgrade --install` with minikube-values.yaml (from quickstart.md), confirm both containers reach `Running`, send test PII request, verify scrubbing response

**Checkpoint**: User Story 1 fully functional. `helm test pii-proxy` passes. Ready for MVP demo.

---

## Phase 4: User Story 2 — Runtime Configuration Without Manifest Editing (Priority: P2)

**Goal**: All environment-specific settings are in `values.yaml`; changing upstream URL or spaCy model name and re-applying requires no manifest edits and no container rebuild.

**Independent Test**: Deploy, then `helm upgrade` with a new `upstream.host`; confirm requests route to the new upstream. Change `extProc.spacyModel` and re-apply; confirm pod env var is updated.

### Implementation — User Story 2

- [ ] T011 [US2] Verify `helm/pii-proxy/values.yaml` fully exposes: `upstream.host`, `upstream.port`, `extProc.spacyModel`, `extProc.grpcPort`, `envoy.listenPort`, `replicaCount`, `image.*`, `service.*`, `resources.*`, `probes.*` — all drawn from `contracts/values-schema.md`; add any missing keys
- [ ] T012 [P] [US2] Verify `helm/pii-proxy/templates/configmap-envoy.yaml` template variables cover every configurable Envoy field (upstream host, upstream port, listen port, ext_proc address) from research R3; fix any gaps
- [ ] T013 [P] [US2] Verify `helm/pii-proxy/templates/deployment.yaml` ext_proc container env vars `GRPC_PORT` and `SPACY_MODEL` are templated from values (not hardcoded); fix any gaps
- [ ] T014 [US2] Validate on minikube: `helm upgrade` with a changed `upstream.host` re-routes traffic; `helm upgrade` with a changed `extProc.spacyModel` causes pod restart with the new env var (`kubectl -n pii-proxy exec ... -- printenv SPACY_MODEL`)

**Checkpoint**: Operator can change any documented value and re-apply without touching templates or rebuilding images.

---

## Phase 5: User Story 3 — Health Checks and Readiness Signals (Priority: P3)

**Goal**: ext_proc pod is `NotReady` during spaCy model load; transitions to `Ready` automatically once the model is loaded; Kubernetes restarts crashed pods within 30 s.

**Independent Test**: Deploy fresh; watch `kubectl get pods -w`; confirm pod stays `NotReady` for 2–3 minutes then becomes `Ready` without operator action. Kill the ext_proc process; confirm pod restarts within 30 s.

### Implementation — User Story 3

- [ ] T015 [US3] Add `readinessProbe` and `livenessProbe` to ext_proc container in `helm/pii-proxy/templates/deployment.yaml`:
  - `readinessProbe.tcpSocket.port: {{ .Values.extProc.grpcPort }}`
  - `readinessProbe.initialDelaySeconds: {{ .Values.probes.readiness.initialDelaySeconds }}`
  - `readinessProbe.periodSeconds: {{ .Values.probes.readiness.periodSeconds }}`
  - `readinessProbe.failureThreshold: {{ .Values.probes.readiness.failureThreshold }}`
  - `livenessProbe.tcpSocket.port`, `initialDelaySeconds`, `periodSeconds`, `failureThreshold` from `probes.liveness.*`
  - Defaults per data-model.md: readiness delay 180 s / period 15 s / threshold 10; liveness delay 300 s / period 30 s / threshold 3
- [ ] T016 [US3] Validate on minikube: fresh deploy → observe `NotReady` during load, `Ready` after; `kubectl -n pii-proxy exec <pod> -c ext-proc -- kill 1` → pod restarts automatically within 30 s

**Checkpoint**: Pod lifecycle is fully Kubernetes-managed. Zero requests flow while pod is `NotReady`.

---

## Phase 6: User Story 4 — Horizontal Scaling (Priority: P4)

**Goal**: Changing `replicaCount` in values and re-applying scales both Envoy and ext_proc together as a unit (sidecar pattern); all replicas participate in serving requests.

**Independent Test**: `helm upgrade` with `replicaCount=2`; send 20+ requests; pod logs show both pods processed at least one request each.

### Implementation — User Story 4

- [ ] T017 [US4] Confirm `helm/pii-proxy/templates/deployment.yaml` uses `spec.replicas: {{ .Values.replicaCount }}` (should already be present from T008); update `values.yaml` default comment to indicate single-replica is the default and scaling is via this value
- [ ] T018 [US4] Validate on minikube: `helm upgrade pii-proxy helm/pii-proxy --set replicaCount=2 ...`; wait for both pods `Ready`; send 20 requests via `port-forward`; verify both pod logs contain processed-request entries

**Checkpoint**: Horizontal scaling works. Each replica serves requests independently.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, `helm lint` validation, optional LoadBalancer service, and idempotency verification.

- [ ] T019 [P] Author `helm/pii-proxy/README.md` covering all requirements from FR-009:
  - (a) Minimum prerequisites: `helm` 3.x, `kubectl` 1.27+, OCI registry access (or minikube for local)
  - (b) How to build and push ext_proc image: `docker build` + `docker push` commands
  - (c) All `values.yaml` fields with types, defaults, and descriptions (reference `contracts/values-schema.md`)
  - (d) The deploy command: `helm upgrade --install pii-proxy helm/pii-proxy -f my-values.yaml`
  - (e) minikube quick-start section (from quickstart.md)
- [ ] T020 [P] Verify optional `LoadBalancer` Service: confirm `helm/pii-proxy/templates/service.yaml` renders correctly with `service.type: LoadBalancer`; add comment in `values.yaml` noting bare-metal clusters require MetalLB (FR-010)
- [ ] T021 [P] Run `helm lint helm/pii-proxy` and fix any warnings or errors
- [ ] T022 Verify idempotency (FR-007, SC-003): run `helm upgrade --install` twice in succession on minikube; confirm no errors and no unintended state changes on the second run; `helm test` passes both times

**Checkpoint**: Chart is lint-clean, documented, idempotent, and all 4 user stories are functional.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS Phases 3–6
- **Phase 3 (US1 — MVP)**: Depends on Phase 2 — **delivers MVP when complete**
- **Phase 4 (US2)**: Depends on Phase 2; independent of Phase 3 at the template level; integration test requires US1 deployed
- **Phase 5 (US3)**: Depends on Phase 3 (adds probes to Deployment template from T008)
- **Phase 6 (US4)**: Depends on Phase 3 (replicaCount is in same Deployment resource)
- **Phase 7 (Polish)**: Depends on all story phases being complete

### User Story Dependencies

| Story | Depends on | Can start after |
|-------|-----------|----------------|
| US1 (P1) | Phase 2 complete | T006 |
| US2 (P2) | Phase 2 complete | T006 (template changes are independent; validation needs US1) |
| US3 (P3) | US1 complete (T008 Deployment template) | T010 |
| US4 (P4) | US1 complete (T008 Deployment template) | T010 |

### Within Each User Story

- Test template (T007) MUST be authored before Deployment template (T008) — constitution Test-First
- ConfigMap (T005) before Deployment (T008) — Deployment references ConfigMap volume
- Service (T006) before test pod (T007) — test pod curl targets Service DNS name

---

## Parallel Opportunities

### Phase 2 Parallel Execution

```
T004 values.yaml          ─────────────────────► done
T005 configmap-envoy.yaml ──────────────────────► done   (parallel with T004)
T006 service.yaml         ──────────────────────► done   (parallel with T004, T005)
```

### Phase 3 Execution (sequential by constitution)

```
T007 test-scrubbing.yaml  ──────────► done (FIRST — Test-First)
T008 deployment.yaml      ──────────────────────► done
T009 NOTES.txt            ──────────────────────► done   (parallel with T008)
T010 minikube validation  ────────────────────────────────────────► done
```

### Phase 4 (US2) Parallel Within Story

```
T011 values.yaml check     ─────────────────────► done
T012 configmap verify      ──────────────────────► done  (parallel with T011)
T013 deployment env verify ──────────────────────► done  (parallel with T011, T012)
T014 minikube validation  ────────────────────────────────────────► done
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T003)
2. Complete Phase 2: Foundational (T004–T006) — CRITICAL BLOCKER
3. Complete Phase 3: User Story 1 (T007–T010) — **Constitution: write test T007 first**
4. **STOP and VALIDATE**: `helm test pii-proxy` passes on minikube
5. **MVP DEMO READY**: one-command deploy + PII scrubbing verified

### Incremental Delivery

1. MVP: Phase 1 + 2 + 3 → working single-command deploy with PII scrubbing
2. Phase 4 (US2) → runtime reconfiguration via values
3. Phase 5 (US3) → K8s-managed health / readiness lifecycle
4. Phase 6 (US4) → horizontal scaling
5. Phase 7 → documentation polish + idempotency verification

### Suggested MVP Scope

**Complete Phases 1–3** for MVP. This delivers the core value proposition (US1: one-command deploy + PII scrubbing) and satisfies SC-001, SC-002, SC-005 immediately.
