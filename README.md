# PII Proxy

> **⚠️ Prototype** — This is an early-stage proof of concept. It is not production-ready and has not been audited for security or performance.

---

## What is this?

Every time an API responds with user data, there's a chance PII slips through — names, emails, phone numbers, credit card numbers. **PII Proxy** sits in front of your upstream service and automatically strips that data before it reaches the client, with zero changes to your application code.

It works by running all traffic through **Envoy**, which buffers each response body and hands it off via gRPC to a Python sidecar. The sidecar uses [Microsoft Presidio](https://github.com/microsoft/presidio) (backed by a spaCy NER model) to detect and redact PII, then returns the cleaned body to Envoy, which forwards it to the client.

```
Client
  │
  ▼
Envoy :8080  ──── ext_proc (gRPC) ────▶  ext_proc service :50051
  │                                           │
  │                                           └─ Presidio + spaCy NER
  │                                               detects & redacts PII
  ▼
Upstream service :8081
```

Both **plain-text** and **JSON** response bodies are supported — JSON fields are walked recursively and each string value is scrubbed individually.

---

## Quick start

Requires: `docker`, `docker compose`

```bash
git clone https://github.com/your-username/PII_proxy.git
cd PII_proxy
docker compose up --build
```

The first build downloads the spaCy `en_core_web_lg` model (~750 MB), so it takes a few minutes. Subsequent starts are fast.

```bash
# Stop
docker compose down
```

---

## Try it out

The dummy upstream server simply echoes back whatever body you send. Run these after `docker compose up` to see PII scrubbing live.

**No PII — passes through unchanged:**

```bash
curl -X POST -d "Hello, world!" http://localhost:8080/
# → Hello, world!
```

**Email address:**

```bash
curl -X POST \
  -d "Please contact john.doe@example.com for support" \
  http://localhost:8080/
# → Please contact <EMAIL_ADDRESS> for support
```

**Phone number:**

```bash
curl -X POST \
  -d "Call us at +1-800-555-0199 any time" \
  http://localhost:8080/
# → Call us at <PHONE_NUMBER> any time
```

**Credit card number:**

```bash
curl -X POST \
  -d "Charge card 4111 1111 1111 1111 for the order" \
  http://localhost:8080/
# → Charge card <CREDIT_CARD> for the order
```

**Multiple PII types in one request:**

```bash
curl -X POST \
  -d "Contact Jane Smith at jane@acme.com or +44 20 7946 0958" \
  http://localhost:8080/
# → Contact <PERSON> at <EMAIL_ADDRESS> or <PHONE_NUMBER>
```

**JSON body — each field scrubbed individually:**

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"name":"Alice Brown","email":"alice@example.com"}' \
  http://localhost:8080/
# → {"name":"<PERSON>","email":"<EMAIL_ADDRESS>"}
```

**Bypass Envoy — hit the upstream directly (no scrubbing):**

```bash
curl -X POST -d "john.doe@example.com" http://localhost:8081/
# → john.doe@example.com  (raw, unredacted)
```

---

## Project layout

```
.
├── docker-compose.yml    # Orchestrates envoy + dummy-server + ext_proc
├── envoy.yaml            # Envoy config — ext_proc filter with BUFFERED response body
├── dummy-server/         # Minimal Flask echo server (stand-in for a real upstream)
└── ext_proc/ # gRPC ExternalProcessor service (Envoy ext_proc protocol with Presidio integration)

```
