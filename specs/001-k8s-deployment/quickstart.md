# Quick Start: PII Proxy on Kubernetes (minikube)

**Branch**: `001-k8s-deployment` | **Date**: 2026-03-22

This guide walks you through deploying PII Proxy to a local **minikube** cluster from
a clean checkout. No container registry is required for local testing.

---

## Prerequisites

| Tool | Minimum version | Install |
|------|----------------|---------|
| `docker` | 24.x | [docs.docker.com](https://docs.docker.com/get-docker/) |
| `minikube` | v1.32 | [minikube.sigs.k8s.io](https://minikube.sigs.k8s.io/docs/start/) |
| `kubectl` | 1.27+ | [kubernetes.io](https://kubernetes.io/docs/tasks/tools/) |
| `helm` | 3.14+ | [helm.sh/docs](https://helm.sh/docs/intro/install/) |

---

## Step 1 — Start minikube

Allocate enough RAM for the spaCy `en_core_web_lg` model (~2 GB resident):

```bash
minikube start --cpus=4 --memory=8g --driver=docker
```

Verify:

```bash
kubectl cluster-info
```

---

## Step 2 — Build the ext_proc Image

```bash
docker build -t pii-proxy/ext-proc:dev ./ext_proc
```

This step takes several minutes on first build (downloads spaCy model into the image).

---

## Step 3 — Load Images into minikube

`minikube image load` copies the locally-built image into minikube's container runtime.
No registry is needed.

```bash
minikube image load pii-proxy/ext-proc:dev
```

The Envoy image (`envoyproxy/envoy:v1.33.0`) is pulled automatically from Docker Hub
by Kubernetes during pod scheduling.

---

## Step 4 — Create a Namespace

```bash
kubectl create namespace pii-proxy
```

---

## Step 5 — Deploy with Helm

Create a values override file for minikube:

```bash
cat > /tmp/minikube-values.yaml << 'EOF'
upstream:
  host: "dummy-server-svc"     # adjust to your upstream service name
  port: 80

image:
  extProc:
    repository: "pii-proxy/ext-proc"
    tag: "dev"
  pullPolicy: Never             # use image loaded via `minikube image load`
EOF
```

Install the chart:

```bash
helm upgrade --install pii-proxy helm/pii-proxy \
  --namespace pii-proxy \
  -f /tmp/minikube-values.yaml
```

To re-apply after config changes:

```bash
helm upgrade --install pii-proxy helm/pii-proxy \
  --namespace pii-proxy \
  -f /tmp/minikube-values.yaml
```

---

## Step 6 — Wait for Pods to Become Ready

The ext_proc container loads the spaCy model during startup (~2–3 minutes).
The pod will remain `NotReady` until the model finishes loading — this is expected.

```bash
kubectl -n pii-proxy rollout status deployment/pii-proxy --timeout=600s
```

Watch pod status in real time:

```bash
kubectl -n pii-proxy get pods -w
```

---

## Step 7 — Access the Proxy

Open a tunnel to the ClusterIP Service:

```bash
kubectl -n pii-proxy port-forward svc/pii-proxy 8080:80
```

In a second terminal, send a test request containing PII:

```bash
curl -s -X POST http://localhost:8080/ \
  -H "Content-Type: text/plain" \
  -d "My name is Jane Smith and my email is jane.smith@example.com"
```

Expected response — PII replaced with placeholder tokens:

```
My name is <PERSON> and my email is <EMAIL_ADDRESS>
```

---

## Step 8 — Run the Helm Test (End-to-End Verification)

```bash
helm test pii-proxy --namespace pii-proxy
```

The test Pod sends a POST with known PII and asserts the response contains
`<PERSON>` and `<EMAIL_ADDRESS>`. Exit code 0 = pass.

---

## Cleanup

```bash
helm uninstall pii-proxy --namespace pii-proxy
kubectl delete namespace pii-proxy
minikube stop
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Pod stuck in `ImagePullBackOff` | Image not loaded into minikube | Re-run `minikube image load pii-proxy/ext-proc:dev` |
| Pod stuck in `NotReady` > 5 min | OOMKill during model load | Increase `resources.extProc.limits.memory` in values |
| Envoy returns 503 | ext_proc not ready | Wait for readiness probe to pass (check `kubectl -n pii-proxy describe pod`) |
| PII not scrubbed | Wrong `upstream.host` | Verify the upstream host resolves inside the cluster |
| `helm install` fails immediately | Missing required values | Provide `upstream.host` and `image.extProc.repository` |
