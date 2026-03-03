# PII Proxy

An Envoy-based reverse proxy that intercepts HTTP traffic and scrubs Personally Identifiable Information (PII) from response bodies before they reach the client.

## Architecture

```
Client
  |
  v
Envoy :8080
  |  envoy.filters.http.ext_proc (BUFFERED response body)
  |  <--------------------------------------->
  |                                        ext_proc gRPC service :50051
  |                                          |
  |                                          +- Stage 1: Regex / Rules
  |                                          +- Stage 2: NER model
  |                                          +- Stage 3: LLM (hard cases)
  |
  v
Upstream (dummy-server :8081)
```

### Components

| Service       | Port  | Description                                              |
|---------------|-------|----------------------------------------------------------|
| `envoy`       | 8080  | Entry point — all traffic flows through here             |
| `dummy-server`| 8081  | Upstream echo server (simulates a real backend)          |
| `ext_proc`    | 50051 | Python gRPC ext_proc service — scrubs PII from responses |

## Running the project

### Option A — Docker Compose (recommended)

Requires: `docker`, `docker compose`

```bash
# Build and start all services
docker compose up --build

# Detached (background)
docker compose up -d --build

# Stop and remove containers
docker compose down
```

### Option B — Local development with mise

Requires: [`mise`](https://mise.jdx.dev), `git`

```bash
# Install mise (if not already installed)
curl -sSf https://mise.run | sh
echo 'eval "$(mise activate bash)"' >> ~/.bashrc
source ~/.bashrc

# From the project root — first time setup:
# installs Python + uv, compiles proto stubs, then starts the server
mise run dev

---

## Testing with curl

All requests go through Envoy on **port 8080**. The dummy-server echoes the request
body back as the response body — the ext_proc filter then processes that body.

**Basic echo test:**

```bash
curl -X POST -d "Hello, downstream!" http://localhost:8080/
```

**Test PII scrubbing — email address:**

```bash
curl -X POST \
  -d "Please contact john.doe@example.com for support" \
  http://localhost:8080/
```

**Test PII scrubbing — phone and credit card:**

```bash
curl -X POST \
  -d "Call +1-800-555-0199 or pay with card 4111 1111 1111 1111" \
  http://localhost:8080/
```

**Verbose (shows headers and full exchange):**

```bash
curl -v -X POST -d "SSN: 123-45-6789" http://localhost:8080/
```

**Direct upstream — bypasses Envoy and the scrubber:**

```bash
curl -X POST -d "Hello, direct downstream!" http://localhost:8081/
```

---

## Project layout

```
.
|-- docker-compose.yml        # Orchestrates envoy + dummy-server + ext_proc
|-- envoy.yaml                # Envoy config with ext_proc filter (response body BUFFERED)
|-- .mise.toml                # mise tasks: install / gen-protos / run / dev
|-- dummy-server/             # Minimal Flask echo server (upstream backend)
+-- ext_proc/                 # Python gRPC ext_proc service
```
