<!--
SYNC IMPACT REPORT
==================
Version change:        1.0.0 → 1.1.0 (MINOR — materially expanded guidance)
Modified principles:   I. Privacy-First (outgoing-proxy operation mode added)
                       IV. Simplicity & Focused Scope (ratified exception added)
Added sections:        "Ratified Feature Exceptions" subsection under §IV
Removed sections:      None
Templates reviewed:
  ✅ .specify/templates/plan-template.md   — Constitution Check rows are
     generic placeholders; no changes needed.
  ✅ .specify/templates/spec-template.md   — No constitution references;
     no changes needed.
  ✅ .specify/templates/tasks-template.md  — No constitution references;
     no changes needed.
Deferred TODOs:        None
Bump rationale:        Two existing principles received materially expanded
                       guidance (new mode clause in §I, formal ratification
                       block in §IV). Content is additive — no removal or
                       redefinition — therefore MINOR, not MAJOR.
-->

# PII Proxy Constitution

## Core Principles

### I. Privacy-First (NON-NEGOTIABLE)

No PII entity (person name, e-mail address, phone number, credit card number,
etc.) MUST ever leave the proxy boundary in unredacted form, whether flowing
toward a downstream client or toward an external upstream service.

The proxy operates in one of two modes. The scrubbing obligation applies in
both; only the body direction differs:

**Reverse-proxy mode** (default): Every HTTP *response* body received from the
upstream service MUST be scrubbed before it is forwarded to the calling client.

- Scrubbing MUST happen on every response regardless of Content-Type or status
  code, unless the response body is empty.
- Both plain-text and JSON bodies MUST be supported; JSON fields MUST be walked
  recursively and each string value scrubbed individually.

**Outgoing-proxy mode** (e.g., Langfuse telemetry forwarding): Every HTTP
*request* body originating from an internal application MUST be scrubbed before
it is forwarded to the external upstream service. Response bodies returned by
the external upstream (e.g., acknowledgement payloads containing trace IDs and
status codes) contain no user-submitted content and are relayed unchanged.

- Scrubbing MUST happen on every outgoing request body regardless of
  Content-Type, unless the body is empty.
- Both plain-text and JSON bodies MUST be supported; JSON fields MUST be walked
  recursively and each string value scrubbed individually.

**Applies to both modes**: Failure to scrub (e.g., Presidio/spaCy timeout or
error) MUST result in the transaction being rejected — never forwarded raw.
`failure_mode_allow: false` MUST be hardcoded; it MUST NOT be a configurable
value.

**Rationale**: PII Proxy's sole reason for existence is privacy protection.
Allowing PII to leak, even partially, defeats the product entirely. The
two-mode design extends this guarantee to outbound LLM telemetry (prompts,
completions) that would otherwise leave the cluster unredacted.

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
HTTP bodies at the appropriate interception point for the active operating mode.
No feature outside that scope MUST be added without explicit justification and
a constitution amendment.

- Request/response headers MUST NOT be modified for any reason.
- Request bodies MUST NOT be modified except to redact PII, and only when
  operating in outgoing-proxy mode (see Ratified Feature Exceptions below).
- No business logic, routing decisions, or data transformation beyond PII
  replacement MUST be performed by the sidecar.
- Code complexity MUST be justified. Any abstraction that serves only a
  hypothetical future requirement MUST be rejected.

#### Ratified Feature Exceptions

The following request-body modifications have been formally ratified. Each
entry MUST cite the originating feature branch and the privacy requirement that
demands the modification.

| # | Feature Branch | Scope | Rationale |
|---|---------------|-------|-----------|
| 1 | `002-langfuse-outgoing-proxy` | PII redaction of outgoing HTTP request bodies in `outgoing-proxy` mode only | LLM applications send prompts and user inputs to Langfuse as request payloads. These payloads may contain PII (names, emails, phone numbers). Scrubbing must occur before the payload leaves the cluster. No other request body modification is performed. |

To add a new ratified exception: amend this table in a PR that also bumps the
constitution version and passes the consistency propagation checklist.

**Rationale**: Keeping the sidecar laser-focused safeguards correctness,
reduces attack surface, and keeps the mental model simple. Explicit ratification
of each exception ensures deviations are intentional, documented, and auditable.

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

**Version**: 1.1.0 | **Ratified**: 2026-03-21 | **Last Amended**: 2026-03-30
