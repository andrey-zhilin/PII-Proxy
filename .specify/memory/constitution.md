<!--
SYNC IMPACT REPORT
==================
Version change:        N/A → 1.0.0 (initial ratification)
Modified principles:   N/A (first version)
Added sections:        Core Principles, Security Requirements,
                       Development Workflow, Governance
Removed sections:      N/A
Templates reviewed:
  ✅ .specify/templates/plan-template.md   — Constitution Check section is
     already generic; no project-specific text to remove.
  ✅ .specify/templates/spec-template.md   — No constitution references;
     no changes needed.
  ✅ .specify/templates/tasks-template.md  — No constitution references;
     no changes needed.
Deferred TODOs:        None
-->

# PII Proxy Constitution

## Core Principles

### I. Privacy-First (NON-NEGOTIABLE)

Every HTTP response body that passes through the proxy MUST be scrubbed of all
detectable PII before the response reaches the client. No PII entity (person
name, e-mail address, phone number, credit card number, etc.) MUST ever be
forwarded to a client in unredacted form.

- Scrubbing MUST happen on every response regardless of Content-Type or status
  code, unless the response body is empty.
- Both plain-text and JSON bodies MUST be supported; JSON fields MUST be walked
  recursively and each string value scrubbed individually.
- Failure to scrub (e.g., Presidio/spaCy timeout or error) MUST result in the
  request being rejected or the body being withheld — never forwarded raw.

**Rationale**: PII Proxy's sole reason for existence is privacy protection.
Allowing PII to leak, even partially, defeats the product entirely.

### II. Transparently Invisible

The proxy MUST interpose at the network/infrastructure layer only. Upstream
application code MUST require zero modifications to benefit from PII scrubbing.

- Integration MUST be achieved solely through Envoy's `ext_proc` filter; no
  SDK, agent, or library MUST be installed in the upstream service.
- Response semantics (status codes, headers, structure) MUST be preserved
  unchanged except for redacted string values within the body.
- The proxy MUST be deployable as a drop-in sidecar alongside any HTTP service.

**Rationale**: Requiring application changes would limit adoption and create a
maintenance burden every time upstream services are updated.

### III. Test-First (NON-NEGOTIABLE)

Tests MUST be written and reviewed before implementation code is written.
The Red → Green → Refactor cycle MUST be strictly followed.

- Every supported PII entity type MUST have at least one passing unit test in
  `ext_proc/tests/`.
- New scrubbing behavior MUST be covered by a failing test before the
  implementation is merged.
- Integration tests verifying end-to-end scrubbing via the Envoy+ext_proc
  pipeline SHOULD exist for each body format (plain-text, JSON).

**Rationale**: PII detection is inherently probabilistic; regressions are
subtle and dangerous. Only test-driven coverage provides adequate confidence.

### IV. Simplicity & Focused Scope (YAGNI)

The ext_proc sidecar MUST do exactly one thing: detect and redact PII from
response bodies. No feature outside that scope MUST be added without explicit
justification and a constitution amendment.

- Request bodies and request/response headers MUST NOT be modified unless a
  specific privacy requirement demands it and is ratified.
- No business logic, routing decisions, or data transformation beyond PII
  replacement MUST be performed by the sidecar.
- Code complexity MUST be justified. Any abstraction that serves only a
  hypothetical future requirement MUST be rejected.

**Rationale**: Keeping the sidecar laser-focused safeguards correctness,
reduces attack surface, and keeps the mental model simple.

### V. Containerized & Reproducible

All runtime components (Envoy, ext_proc sidecar, dummy upstream) MUST be
packaged as Docker containers and orchestrated via `docker-compose`.

- The full stack MUST start with `docker compose up --build` and no additional
  setup steps on a machine that has only `docker` and `docker compose`.
- Environment-specific configuration MUST be passed via environment variables;
  no hard-coded secrets or host-path dependencies MUST exist.
- The spaCy NER model (`en_core_web_lg`) MUST be downloaded at image build time
  so no network access is required at runtime.

**Rationale**: Reproducibility prevents "works on my machine" issues and is a
prerequisite for reliable CI/CD and security auditing.

## Security Requirements

- PII redaction MUST use a deterministic replacement token (e.g., `<PERSON>`,
  `<EMAIL_ADDRESS>`) rather than deletion, to preserve response structure while
  making the substitution observable.
- Dependency versions for Presidio, spaCy, grpcio, and protobuf MUST be pinned
  in `ext_proc/pyproject.toml`; unpinned ranges SHOULD be avoided.
- The ext_proc gRPC service MUST NOT be exposed outside the Docker network; it
  MUST be reachable only by the Envoy sidecar.
- Transport between Envoy and the ext_proc sidecar SHOULD use TLS in any
  environment beyond local development.
- All security-relevant events (scrubbing failures, unexpected body formats,
  gRPC errors) MUST be logged at WARNING or above with structured metadata.

## Development Workflow

- Feature work MUST start from a `/speckit.specify` spec, proceed through
  `/speckit.plan`, and be implemented via tasks generated by `/speckit.tasks`.
- Every PR MUST include a **Constitution Check** block confirming compliance
  with all five core principles.
- Dependency additions MUST be evaluated for supply-chain risk; prefer
  established, actively maintained packages (Presidio, spaCy, grpcio).
- Branch names MUST follow `<sequential-number>-<short-feature-slug>`
  (e.g., `001-json-scrubbing`).
- `docker compose up --build` MUST succeed from a clean checkout before a PR
  is merged.

## Governance

This constitution supersedes all other project practices and conventions. Any
conflict between a practice document and this constitution MUST be resolved in
favor of this constitution.

**Amendment procedure**:

1. Open a PR that edits `.specify/memory/constitution.md` with the proposed
   change and a clear rationale.
2. Bump the version according to semantic versioning rules:
   - MAJOR — backward-incompatible removal or redefinition of a principle.
   - MINOR — new principle, section added, or materially expanded guidance.
   - PATCH — clarification, wording fix, or non-semantic refinement.
3. Update `LAST_AMENDED_DATE` to today's date (ISO 8601).
4. Run the consistency propagation checklist: verify `.specify/templates/`
   still align with the amended principles.
5. Obtain at least one reviewer approval before merging.

**Compliance review**: All PRs and code reviews MUST verify adherence to the
five core principles. Violations MUST be flagged as blocking before merge.

**Version**: 1.0.0 | **Ratified**: 2026-03-21 | **Last Amended**: 2026-03-21
