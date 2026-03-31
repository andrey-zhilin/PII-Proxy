# PII Proxy — Helm Chart

Deploys the PII Proxy stack to a Kubernetes cluster: an **Envoy** proxy paired
with an **ext_proc** PII-scrubbing sidecar in a single Pod. The chart supports two modes:

- **Reverse Proxy** (`mode: reverse-proxy`): Scrubs PII from **response** bodies before they reach the client. Default mode.
- **Outgoing Proxy** (`mode: outgoing-proxy`): Scrubs PII from **request** bodies before forwarding to an external Langfuse endpoint. Used when applications inside the mesh send LLM traces through the proxy.

All HTTP bodies routed through Envoy are automatically scanned by a Presidio + spaCy NLP pipeline and
PII entities are replaced with safe placeholder tokens (`<PERSON>`, `<EMAIL_ADDRESS>`, etc.).

---

## Prerequisites

| Tool | Minimum version | Notes |
|------|----------------|-------|
| `helm` | 3.14+ | [helm.sh/docs/intro/install](https://helm.sh/docs/intro/install/) |
| `kubectl` | 1.27+ | Must have `apply` permissions to the target namespace |
| OCI registry | — | Operator-managed; docker.io or private registry for ext_proc image |
| **minikube** (local only) | v1.32+ | Local testing only; no registry required when using `minikube image load` |

---

## Build & Push the ext_proc Image

The ext_proc image must be built and pushed to your registry **before** deploying.
No public image is published.

```bash
# Build
docker build -t my-registry.example.com/pii-proxy/ext-proc:1.0.0 ./ext_proc

# Push to your registry
docker push my-registry.example.com/pii-proxy/ext-proc:1.0.0
```

### minikube (local testing — no registry needed)

```bash
# Build locally
docker build -t pii-proxy/ext-proc:dev ./ext_proc

# Load into minikube's container runtime
minikube image load pii-proxy/ext-proc:dev
```

When using `minikube image load`, set `image.pullPolicy: Never` in your values file
so Kubernetes does not attempt to pull from a registry.

---

## Quick Deploy

### 1. Create a values override file

```yaml
# my-values.yaml

upstream:
  host: "my-api-service.default.svc.cluster.local"
  port: 8080

image:
  extProc:
    repository: "my-registry.example.com/pii-proxy/ext-proc"
    tag: "1.0.0"
  pullPolicy: IfNotPresent
```

### 2. Deploy

```bash
helm upgrade --install pii-proxy helm/pii-proxy \
  --namespace pii-proxy \
  --create-namespace \
  -f my-values.yaml
```

### 3. Wait for readiness

The ext_proc sidecar loads the spaCy model at startup — this takes **2–3 minutes**.
The pod remains `NotReady` until the model finishes loading.

```bash
kubectl -n pii-proxy rollout status deployment/pii-proxy --timeout=600s
```

### 4. Test the proxy

```bash
kubectl -n pii-proxy port-forward svc/pii-proxy 8080:80

curl -X POST http://localhost:8080/ \
  -H "Content-Type: text/plain" \
  -d "My name is Jane Smith and her email is jane@example.com"
# Expected: My name is <PERSON> and her email is <EMAIL_ADDRESS>
```

### 5. Run the Helm test

```bash
helm test pii-proxy --namespace pii-proxy
```

---

## minikube Quick Start

See [specs/001-k8s-deployment/quickstart.md](../../specs/001-k8s-deployment/quickstart.md)
for the full 8-step minikube walkthrough.

Summary:

```bash
minikube start --cpus=4 --memory=8g --driver=docker
docker build -t pii-proxy/ext-proc:dev ./ext_proc
minikube image load pii-proxy/ext-proc:dev

cat > /tmp/minikube-values.yaml << 'EOF'
upstream:
  host: "dummy-server-svc"
  port: 80
image:
  extProc:
    repository: "pii-proxy/ext-proc"
    tag: "dev"
  pullPolicy: Never
EOF

helm upgrade --install pii-proxy helm/pii-proxy \
  --namespace pii-proxy --create-namespace \
  -f /tmp/minikube-values.yaml
```

---

## Outgoing Proxy Mode (Langfuse)

To deploy as an outgoing proxy for Langfuse traffic:

### Required Values

```yaml
# langfuse-values.yaml
mode: outgoing-proxy

langfuse:
  host: "cloud.langfuse.com"   # Your Langfuse endpoint
  port: 443
  tls:
    enabled: true               # TLS to upstream Langfuse

tls:
  enabled: true                 # TLS listener (HTTPS inbound)
  secretName: "pii-proxy-tls"  # kubernetes.io/tls Secret

istio:
  enabled: true                 # Creates ServiceEntry + DestinationRule

image:
  extProc:
    repository: "my-registry.example.com/pii-proxy/ext-proc"
    tag: "1.0.0"
```

### Deploy

```bash
helm upgrade --install pii-proxy helm/pii-proxy \
  --namespace pii-proxy --create-namespace \
  -f langfuse-values.yaml
```

### Application Configuration

Point the Langfuse SDK to the proxy instead of Langfuse directly:

```python
# Before: LANGFUSE_HOST=https://cloud.langfuse.com
# After:
LANGFUSE_HOST=https://pii-proxy.pii-proxy.svc.cluster.local:443
```

Applications must trust the proxy's TLS certificate (via `SSL_CERT_FILE` or system CA store).

### How It Works

1. Application sends Langfuse trace to the proxy (HTTPS)
2. Envoy receives the request and streams headers + body to ext_proc
3. ext_proc scrubs PII from the request body (names, emails, phones, addresses)
4. Envoy forwards the scrubbed request to the real Langfuse endpoint
5. Langfuse response is relayed back unchanged (acknowledgement only)

### Quickstart

See [specs/002-langfuse-outgoing-proxy/quickstart.md](../../specs/002-langfuse-outgoing-proxy/quickstart.md) for the full end-to-end setup guide with minikube, Istio, TLS, and security audit steps.

---

## Configuration Reference

All configurable fields in `values.yaml`:

### `image` — Container images

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `image.envoy.repository` | string | `envoyproxy/envoy` | No | Envoy image repository |
| `image.envoy.tag` | string | `v1.33.0` | No | Envoy image tag |
| `image.extProc.repository` | string | — | **YES** | ext_proc image (operator-built). Helm fails if empty. |
| `image.extProc.tag` | string | `latest` | No | ext_proc tag |
| `image.pullPolicy` | string | `IfNotPresent` | No | K8s `imagePullPolicy`. Use `Never` with minikube `image load`. |

### `upstream` — Backend routing (reverse-proxy mode)

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `upstream.host` | string | — | **YES** (reverse mode) | Upstream service hostname. Helm fails if empty in reverse-proxy mode. |
| `upstream.port` | int | `80` | No | Upstream TCP port |

### `mode` — Proxy mode

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `mode` | string | `reverse-proxy` | `reverse-proxy` (scrub responses) or `outgoing-proxy` (scrub requests to Langfuse) |

### `langfuse` — Langfuse endpoint (outgoing-proxy mode)

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `langfuse.host` | string | — | **YES** (outgoing mode) | Langfuse server hostname |
| `langfuse.port` | int | `443` | No | Langfuse server port |
| `langfuse.tls.enabled` | bool | `true` | No | Enable TLS to upstream Langfuse (UpstreamTlsContext) |

### `tls` — TLS listener

| Key | Type | Default | Required | Description |
|-----|------|---------|----------|-------------|
| `tls.enabled` | bool | `false` | No | Enable HTTPS listener (DownstreamTlsContext) |
| `tls.secretName` | string | — | **YES** (when `tls.enabled`) | Name of `kubernetes.io/tls` Secret with cert + key |

### `istio` — Istio mesh integration

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `istio.enabled` | bool | `false` | Create ServiceEntry + DestinationRule for Langfuse egress |

### `replicaCount`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `replicaCount` | int | `1` | Number of Envoy + ext_proc Pod replicas (scale together) |

### `envoy`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `envoy.listenPort` | int | `8080` | Port Envoy listens on inside the container |

### `extProc`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `extProc.grpcPort` | int | `50051` | gRPC port (pod-local only, never exposed outside pod) |
| `extProc.spacyModel` | string | `en_core_web_lg` | spaCy model name (`SPACY_MODEL` env var) |

### `service`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `service.type` | string | `ClusterIP` | `ClusterIP` or `LoadBalancer` (see External Access below) |
| `service.port` | int | `80` | Service port (maps to `envoy.listenPort`) |

### `resources`

| Key | Default | Description |
|-----|---------|-------------|
| `resources.extProc.requests.cpu` | `500m` | ext_proc CPU request |
| `resources.extProc.requests.memory` | `2Gi` | ext_proc memory request (**do not reduce below 2Gi**) |
| `resources.extProc.limits.cpu` | `2000m` | ext_proc CPU limit |
| `resources.extProc.limits.memory` | `4Gi` | ext_proc memory limit |
| `resources.envoy.requests.cpu` | `100m` | Envoy CPU request |
| `resources.envoy.requests.memory` | `128Mi` | Envoy memory request |
| `resources.envoy.limits.cpu` | `1000m` | Envoy CPU limit |
| `resources.envoy.limits.memory` | `512Mi` | Envoy memory limit |

### `probes`

| Key | Default | Description |
|-----|---------|-------------|
| `probes.readiness.initialDelaySeconds` | `180` | Seconds before first readiness check (spaCy load time) |
| `probes.readiness.periodSeconds` | `15` | Readiness probe interval |
| `probes.readiness.failureThreshold` | `10` | Failures before NotReady |
| `probes.liveness.initialDelaySeconds` | `300` | Seconds before first liveness check |
| `probes.liveness.periodSeconds` | `30` | Liveness probe interval |
| `probes.liveness.failureThreshold` | `3` | Failures before pod restart |

---

## External Access (LoadBalancer)

By default the Service type is `ClusterIP`. To expose the proxy externally:

```yaml
service:
  type: LoadBalancer
  port: 80
```

> **Cloud clusters**: Requires cloud-provider load-balancer support (AWS ELB, GCP GCLB, Azure LB).  
> **Bare-metal clusters**: Requires [MetalLB](https://metallb.universe.tf/) to be pre-installed.

---

## Horizontal Scaling

Change `replicaCount` and re-apply. Envoy and ext_proc scale together as a unit
(sidecar pattern — they share a Pod):

```bash
helm upgrade --install pii-proxy helm/pii-proxy \
  -f my-values.yaml \
  --set replicaCount=2
```

Each new replica loads the spaCy model independently — allow 2–3 minutes per replica.

---

## Updating Configuration

All changes are applied without rebuilding container images:

```bash
# Change upstream
helm upgrade pii-proxy helm/pii-proxy -f my-values.yaml --set upstream.host=new-host

# Change spaCy model (pod restarts to pick up new env var)
helm upgrade pii-proxy helm/pii-proxy -f my-values.yaml --set extProc.spacyModel=en_core_web_md
```

---

## Uninstall

```bash
helm uninstall pii-proxy --namespace pii-proxy
kubectl delete namespace pii-proxy
```

---

## Security Notes

- The gRPC port (`extProc.grpcPort`) is **never exposed** outside the Pod. The Kubernetes
  Service only exposes the Envoy HTTP port.
- `failure_mode_allow: false` is hardcoded in the Envoy ConfigMap template — it cannot
  be changed via values. Envoy returns `5xx` on any scrubbing failure; PII is never
  forwarded raw.
- Dependency versions for Presidio, spaCy, and grpcio are pinned in
  `ext_proc/pyproject.toml`.
