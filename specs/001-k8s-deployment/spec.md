# Feature Specification: Kubernetes Deployment Package

**Feature Branch**: `001-k8s-deployment`  
**Created**: 2026-03-21  
**Status**: Draft  
**Input**: User description: "Productize this application by making it easily deployable to existing k8s cluster."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One-Command Cluster Deployment (Priority: P1)

A cluster operator with `kubectl` access to an existing Kubernetes cluster wants
to add PII scrubbing in front of an upstream HTTP service. They clone the
repository, supply the upstream service URL and container image references in a
single configuration file, and run one command. Within minutes, all HTTP traffic
to the upstream is flowing through the PII Proxy and all PII is being redacted.

**Why this priority**: This is the primary deliverable. Without a working,
single-command deployment path the feature has no value. Every other story
builds on top of this baseline.

**Independent Test**: Can be fully tested by running the deployment command
against an empty namespace in any Kubernetes cluster, sending a sample request
containing a name and e-mail address, and verifying the response contains
`<PERSON>` and `<EMAIL_ADDRESS>` placeholders instead of the originals.

**Acceptance Scenarios**:

1. **Given** an operator has `kubectl` access to a cluster and has built (or
   pulled) the `ext_proc` image, **When** they apply the deployment package with
   only the upstream URL and image references configured, **Then** both the Envoy
   sidecar and ext_proc sidecar pods reach `Running` state within 5 minutes and
   traffic is being proxied.
2. **Given** the proxy is running, **When** the operator sends an HTTP POST
   containing a person name and e-mail address, **Then** the response body
   replaces those values with `<PERSON>` and `<EMAIL_ADDRESS>` respectively.
3. **Given** the proxy is running, **When** the operator sends an HTTP request
   with no PII, **Then** the response body reaches the client unmodified.

---

### User Story 2 - Runtime Configuration Without Manifest Editing (Priority: P2)

An operator wants to point the proxy at a different upstream service or change
which PII entity types are redacted. They modify a single configuration values
file (not individual manifests) and re-apply. No container rebuild is required
for purely configuration changes (upstream URL, Envoy routing, spaCy model name,
gRPC port).

**Why this priority**: Production deployments always need environment-specific
tuning. Configuration inflexibility is the most common adoption blocker for
infrastructure packages.

**Independent Test**: Deployable independently: change only the upstream URL
value and re-apply; confirm requests are now routed to the new upstream and PII
is still scrubbed.

**Acceptance Scenarios**:

1. **Given** the proxy is deployed with upstream A, **When** the operator
   changes the upstream URL in the values file and re-applies, **Then** the
   proxy forwards requests to upstream B without rebuilding any container.
2. **Given** a values file entry controls the spaCy model name, **When** the
   operator changes it and re-applies, **Then** the ext_proc pod restarts with
   the new model name available as an environment variable.

---

### User Story 3 - Health Checks and Readiness Signals (Priority: P3)

A platform team running the cluster wants confidence that Kubernetes will
automatically restart unhealthy pods and only route traffic to fully initialised
pods (the spaCy model takes ~2-3 minutes to load). The deployment package
includes liveness and readiness probes so Kubernetes manages pod lifecycle
automatically.

**Why this priority**: Without probes, pods receive traffic before the spaCy
model is ready, causing errors during startup. Correct probes also enable
safe rolling upgrades with zero dropped requests.

**Independent Test**: Deploy to a namespace, observe that the ext_proc pod is
marked `NotReady` during the first 2-3 minutes of startup, and transitions to
`Ready` once the model has loaded. Verify no requests are forwarded to the pod
while it is `NotReady`.

**Acceptance Scenarios**:

1. **Given** a fresh deployment, **When** the ext_proc pod is still loading the
   spaCy model, **Then** Kubernetes marks the pod `NotReady` and Envoy does not
   forward requests to it.
2. **Given** the ext_proc pod is `Running` and `Ready`, **When** the process
   crashes, **Then** Kubernetes restarts the pod automatically within 30 seconds.

---

### User Story 4 - Horizontal Scaling (Priority: P4)

An operator needs to handle increased concurrent traffic. They change the
Deployment replica count and re-apply. Because Envoy and ext_proc share a Pod,
both scale together as a unit — each replica contains both containers.

**Why this priority**: Scaling is a standard production requirement; the
deployment package must not structurally prevent it. However, a single-replica
default is acceptable for initial delivery.

**Independent Test**: Scale the ext_proc Deployment to 2 replicas and confirm
both pods participate in serving requests (visible via pod logs).

**Acceptance Scenarios**:

1. **Given** the ext_proc Deployment replica count is changed to 2, **When**
   traffic is sent, **Then** both pods appear in logs as having processed at
   least one request.

---

### Edge Cases

- What happens when the `ext_proc` pod is not yet ready and Envoy tries to
  establish the gRPC connection? Traffic must not be forwarded to the upstream
  without scrubbing; Envoy should return a 5xx until the sidecar is healthy.
- What happens when a namespace already contains resources with the same names?
  The deployment package must be idempotent: re-applying MUST update existing
  resources rather than fail.
- What happens when the upstream URL is left unconfigured or points to an
  unreachable host? The deployment package must fail fast with a clear error
  message, not silently deploy a broken configuration.
- What happens when the operator deploys to a namespace that lacks the
  container image in the specified registry? The pod must enter `ImagePullBackOff`
  with a legible error, not an opaque crash.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The deployment package MUST deploy both the Envoy proxy and the
  ext_proc PII-scrubbing sidecar as containers within the **same Pod** (sidecar
  pattern). The ext_proc container shares the pod network namespace with Envoy;
  gRPC communication occurs over `localhost`.
- **FR-002**: All configuration that differs between environments (upstream
  service URL, container image references, replica counts, resource limits, gRPC
  port, spaCy model name) MUST be expressible through a single values/configuration
  file without editing individual manifest files.
- **FR-003**: The Envoy proxy MUST be reachable from within the cluster via a
  Kubernetes `ClusterIP` Service, so that in-cluster clients can route traffic
  through it without requiring external network access.
- **FR-004**: The deployment package MUST define readiness and liveness probes for
  the ext_proc container that account for the spaCy model load time (typically
  2-3 minutes).
- **FR-005**: Resource requests and limits (CPU, memory) for both containers MUST
  be configurable and MUST have sensible defaults that ensure the ext_proc
  container is not OOMKilled during model loading.
- **FR-006**: The Envoy configuration (routing rules, ext_proc filter settings)
  MUST be managed as a Kubernetes ConfigMap so it can be updated without
  rebuilding container images.
- **FR-007**: Re-applying the deployment package to a namespace that already
  contains a previous version MUST be idempotent: existing resources are updated,
  new ones created, and none are erroneously deleted.
- **FR-008**: The gRPC communication between Envoy and the ext_proc sidecar MUST
  occur over `localhost` within the shared pod network namespace. No gRPC Service
  port MUST be exposed outside the pod.
- **FR-009**: The deployment package MUST include a `README` documenting: (a) the
  minimum prerequisites (`helm`, `kubectl`, OCI registry access), (b) how to
  build and push the ext_proc container image to the operator's registry, (c)
  all required values file fields and their defaults, and (d) the
  `helm upgrade --install` deploy command.
- **FR-010**: The deployment package SHOULD support an optional `LoadBalancer`
  Service (disabled by default) to expose the proxy to external clients. When
  enabled via the values file, the Service type switches from `ClusterIP` to
  `LoadBalancer`; no Ingress controller is required.

### Key Entities

- **Deployment Package**: The set of all artifacts (manifests, chart, values
  file, documentation) that an operator applies to a Kubernetes cluster to run
  PII Proxy.
- **Envoy + ext_proc Pod**: A single Kubernetes Pod running two containers —
  the Envoy proxy and the ext_proc PII-scrubbing sidecar — sharing a network
  namespace. gRPC calls between them are loopback (`localhost`).
- **Values / Configuration File**: The single file an operator edits to customise
  the deployment without touching individual manifests.
- **Envoy ConfigMap**: The Kubernetes ConfigMap that holds the rendered Envoy
  configuration (`envoy.yaml`), decoupled from the container image.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator with basic Kubernetes familiarity can deploy the full
  PII Proxy stack to a clean namespace in under 10 minutes, following only the
  README instructions.
- **SC-002**: All PII types supported by the existing scrubber (person names,
  e-mail addresses, phone numbers, credit card numbers) continue to be redacted
  correctly after Kubernetes deployment, with no regression from the Docker
  Compose baseline.
- **SC-003**: The deployment package is fully idempotent: running the deployment
  command twice in succession produces no errors and no unintended state changes.
- **SC-004**: The deployed proxy handles at least 50 requests per second with a
  single ext_proc replica on a standard CPU allocation (2 cores, 4 GB RAM).
  Higher throughput is achieved by scaling ext_proc replicas horizontally.
- **SC-005**: Zero requests containing PII reach the client during normal
  operation; PII scrubbing failures result in a 5xx response rather than a
  pass-through of the unredacted body.
- **SC-006**: The ext_proc pod transitions from `NotReady` to `Ready` without
  operator intervention once the spaCy model finishes loading, and serves zero
  requests during the loading period.

## Assumptions

- The target cluster runs a CNCF-conformant Kubernetes distribution (1.27 or
  later) and the operator has `kubectl apply` permissions to the target namespace.
- Container images (Envoy and ext_proc) must be built and pushed to an
  operator-controlled OCI registry before deployment. No public image is
  published as part of this feature. The Helm chart default image reference is a
  documented placeholder (`image.repository` / `image.tag`) that the operator
  must override.
- **Helm is the sole packaging format.** The deployment package is a Helm chart.
  Plain-manifest (`kubectl apply`) and Kustomize fallbacks are explicitly out of
  scope. The deploy command is `helm upgrade --install`.
- An IngressClass is not required. Optional external exposure uses a `LoadBalancer`
  Service; this requires cloud-provider load-balancer support (e.g., AWS ELB,
  GCP GCLB, Azure LB). On bare-metal clusters, an alternative like MetalLB must
  be pre-installed.
- The dummy upstream server included in the repository is for local development
  and testing only; it is not part of the Kubernetes deployment package.

## Clarifications

### Session 2026-03-21

- Q: What is the intended throughput target for a single ext_proc replica? → A: 50 req/s — realistic single-replica CPU target; higher throughput achieved via horizontal scale-out.
- Q: Should the deployment packaging format be Helm only, or also support plain manifests? → A: Helm only — single format; no plain-manifest fallback.
- Q: Should Envoy and ext_proc run in separate Deployments or as sidecars in the same Pod? → A: Sidecar — ext_proc runs as a second container in the same Pod as Envoy; gRPC on localhost.
- Q: What Kubernetes Service type exposes Envoy, and how is optional external access provided? → A: ClusterIP (default in-cluster) + optional LoadBalancer Service for external exposure.
- Q: How is the ext_proc container image expected to reach the cluster? → A: Operator-managed registry — no public image published; chart default is a placeholder; README documents build-and-push steps.

## Out of Scope

- Provisioning or managing the Kubernetes cluster itself.
- Building and pushing container images (CI/CD pipeline).
- Multi-cluster or cross-namespace routing.
- mTLS between Envoy and the ext_proc sidecar (noted as a future hardening step
  in the constitution; out of scope for this feature).
- Monitoring dashboards, alerting rules, or metrics exporters.
