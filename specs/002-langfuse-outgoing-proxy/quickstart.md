# Quickstart: Outgoing HTTPS Proxy for Langfuse

**Branch**: `002-langfuse-outgoing-proxy` | **Date**: 2026-03-23

End-to-end setup guide for testing the Langfuse outgoing proxy on a local minikube cluster with **Istio and full TLS enabled**. This is the canonical test path.

---

## Prerequisites

| Tool | Minimum version | Install |
|------|-----------------|---------|
| minikube | 1.32 | <https://minikube.sigs.k8s.io/docs/start/> |
| kubectl | 1.28 | bundled with minikube or separate |
| istioctl | 1.20 | <https://istio.io/latest/docs/setup/getting-started/> |
| helm | 3.12 | <https://helm.sh/docs/intro/install/> |
| Docker | 24+ | required by minikube with docker driver |
| openssl | any | for certificate generation (pre-installed on Linux/macOS) |

---

## Step 0: Chart-Level Smoke Validation

Run these before deploying to a cluster to verify Helm values and template rendering.

```bash
# Lint outgoing-proxy mode (should pass)
helm lint helm/pii-proxy \
  --set mode=outgoing-proxy \
  --set langfuse.host=cloud.langfuse.com \
  --set image.extProc.repository=test

# Template success path — outgoing-proxy renders without error
helm template test helm/pii-proxy \
  --set mode=outgoing-proxy \
  --set langfuse.host=cloud.langfuse.com \
  --set image.extProc.repository=test > /dev/null && echo "PASS: outgoing-proxy template renders"

# Expected failure — langfuse.host missing in outgoing-proxy mode
helm template test helm/pii-proxy \
  --set mode=outgoing-proxy \
  --set image.extProc.repository=test 2>&1 | grep -q "langfuse.host is required" \
  && echo "PASS: langfuse.host guard fires" || echo "FAIL: guard did not fire"
```

---

## Step 1: Start minikube and Install Istio

```bash
minikube start --memory=8192 --cpus=4 --driver=docker

# Install Istio (demo profile — permissive mTLS, all components)
istioctl install --set profile=demo -y

# Verify Istio is healthy before continuing
kubectl rollout status deployment/istiod -n istio-system --timeout=120s
kubectl get pods -n istio-system
```

Expected: all Istio pods in `Running` state.

---

## Step 2: Create Namespaces

```bash
# PII proxy namespace — Istio sidecar injection ENABLED
kubectl create namespace pii-proxy
kubectl label namespace pii-proxy istio-injection=enabled

# Mock Langfuse namespace — NO sidecar injection (simulates external/non-mesh server)
kubectl create namespace langfuse-mock
```

---

## Step 3: Generate TLS Certificates

The proxy's HTTPS listener requires a real TLS certificate. A self-signed CA is used for the test environment.

```bash
# Generate CA + proxy server cert (script to be created at test-fixtures/certs/gen-certs.sh)
bash test-fixtures/certs/gen-certs.sh /tmp/pii-proxy-certs

# Expected output files:
#   /tmp/pii-proxy-certs/ca.crt    — CA certificate (trusted by test client)
#   /tmp/pii-proxy-certs/tls.crt   — Proxy TLS certificate (signed by CA)
#   /tmp/pii-proxy-certs/tls.key   — Proxy TLS private key

# Store proxy cert as a Kubernetes TLS Secret
kubectl create secret tls pii-proxy-tls \
  --cert=/tmp/pii-proxy-certs/tls.crt \
  --key=/tmp/pii-proxy-certs/tls.key \
  -n pii-proxy

# Store CA cert as a ConfigMap so the test client pod can mount and trust it
kubectl create configmap pii-proxy-ca \
  --from-file=ca.crt=/tmp/pii-proxy-certs/ca.crt \
  -n pii-proxy
```

---

## Step 4: Build and Load Docker Images

```bash
# Use minikube's Docker daemon — images are available without a registry
eval $(minikube docker-env)

# Build ext_proc image
docker build -t pii-proxy/ext-proc:latest ./ext_proc

# Build mock Langfuse server image
docker build -t pii-proxy/mock-langfuse:latest ./test-fixtures/mock-langfuse

# Build test client image  
docker build -t pii-proxy/langfuse-client:latest ./test-fixtures/langfuse-client
```

---

## Step 5: Deploy Mock Langfuse Server

The mock server runs in the `langfuse-mock` namespace **without an Istio sidecar**, simulating an external (non-mesh) target server.

```bash
kubectl apply -n langfuse-mock -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mock-langfuse
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mock-langfuse
  template:
    metadata:
      labels:
        app: mock-langfuse
    spec:
      containers:
        - name: mock-langfuse
          image: pii-proxy/mock-langfuse:latest
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: mock-langfuse
spec:
  selector:
    app: mock-langfuse
  ports:
    - port: 8080
      targetPort: 8080
EOF

kubectl rollout status deployment/mock-langfuse -n langfuse-mock --timeout=60s
```

---

## Step 6: Deploy PII Proxy via Helm (Full TLS + Istio)

```bash
helm upgrade --install pii-proxy ./helm/pii-proxy \
  --namespace pii-proxy \
  --set mode=outgoing-proxy \
  --set image.extProc.repository=pii-proxy/ext-proc \
  --set image.pullPolicy=Never \
  --set langfuse.host=mock-langfuse.langfuse-mock.svc.cluster.local \
  --set langfuse.port=8080 \
  --set langfuse.tls.enabled=false \
  --set tls.enabled=true \
  --set tls.secretName=pii-proxy-tls \
  --set istio.enabled=true \
  --set service.port=8080 \
  --set service.httpsPort=443
```

The ext_proc container takes **2–3 minutes** to become Ready (spaCy model loading):

```bash
kubectl rollout status deployment/pii-proxy -n pii-proxy --timeout=360s
```

Verify Istio resources were created:

```bash
kubectl get serviceentry,destinationrule -n pii-proxy
# Should show: pii-proxy-langfuse ServiceEntry and pii-proxy-langfuse DestinationRule

# Verify pod annotations are applied
kubectl get pod -n pii-proxy -l app.kubernetes.io/name=pii-proxy -o jsonpath=\
  '{.items[0].metadata.annotations}' | python3 -m json.tool | grep -i "istio\|sidecar"
# Should show excludeInboundPorts and excludeOutboundPorts entries
```

---

## Step 7: Run the Test Client (Python Langfuse SDK, HTTPS)

The test client connects to the proxy over HTTPS, trusting the self-signed CA cert. PII payloads are sent via the Langfuse Python SDK.

```bash
kubectl run langfuse-client \
  --image=pii-proxy/langfuse-client:latest \
  --image-pull-policy=Never \
  --restart=Never \
  -n pii-proxy \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "langfuse-client",
        "image": "pii-proxy/langfuse-client:latest",
        "imagePullPolicy": "Never",
        "env": [
          {"name": "LANGFUSE_HOST",       "value": "https://pii-proxy.pii-proxy.svc.cluster.local"},
          {"name": "LANGFUSE_PUBLIC_KEY",  "value": "test-pk"},
          {"name": "LANGFUSE_SECRET_KEY",  "value": "test-sk"},
          {"name": "SSL_CERT_FILE",        "value": "/certs/ca.crt"}
        ],
        "volumeMounts": [{"name": "ca-cert", "mountPath": "/certs", "readOnly": true}],
        "command": ["python", "send_traces.py"]
      }],
      "volumes": [{"name": "ca-cert", "configMap": {"name": "pii-proxy-ca"}}],
      "restartPolicy": "Never"
    }
  }' \
  -- python send_traces.py

# Wait for the job to succeed
kubectl wait pod/langfuse-client -n pii-proxy --for=condition=Succeeded --timeout=60s
kubectl logs langfuse-client -n pii-proxy
```

Expected log output: `Done — traces flushed via HTTPS proxy. Check mock server /captured for scrubbed payload.`

---

## Step 8: Assert PII Was Scrubbed

```bash
# Port-forward the mock Langfuse server
kubectl port-forward svc/mock-langfuse 9090:8080 -n langfuse-mock &
PF_PID=$!
sleep 2

# Fetch all captured request bodies (what the proxy forwarded to "Langfuse")
CAPTURED=$(curl -sf http://localhost:9090/captured)
echo "$CAPTURED" | python3 -m json.tool

# Assert no raw PII is present
echo "--- Checking for PII leakage ---"
for pii in "Alice Johnson" "alice@example.com" "555-867-5309"; do
  if echo "$CAPTURED" | grep -q "$pii"; then
    echo "FAIL: PII found in captured payload: '$pii'"
    kill $PF_PID; exit 1
  fi
done
echo "PASS: No raw PII found in forwarded payloads."

# Assert placeholders are present
for placeholder in "<PERSON>" "<EMAIL_ADDRESS>" "<PHONE_NUMBER>"; do
  if echo "$CAPTURED" | grep -q "$placeholder"; then
    echo "PASS: Placeholder '$placeholder' found."
  else
    echo "WARN: Placeholder '$placeholder' not found (may depend on spaCy model confidence)."
  fi
done

kill $PF_PID
```

Expected output (excerpt in captured payload — no raw PII):

```json
[
  {
    "batch": [
      {
        "type": "trace-create",
        "body": {
          "name": "pii-test",
          "input": {
            "user_message": "Hi, I'm <PERSON>, my email is <EMAIL_ADDRESS> and my phone is <PHONE_NUMBER>"
          }
        }
      }
    ]
  }
]
```

---

## Step 9: Run Unit Tests (Local, No Cluster)

```bash
cd ext_proc
uv run pytest tests/test_request_scrubbing.py -v
# Runs without minikube — only requires the Python venv with spaCy loaded
```

---

## Step 10: Security Audit — PII Leakage Verification (SC-001 / SC-002)

This step validates that **no tested PII pattern reaches the external endpoint** and that **non-PII data is forwarded with full fidelity**.

### 10a. Send Extended PII Payload Suite

Run the test client which sends 5 traces: baseline PII, clean, nested PII, multi-category PII (name + email + phone + address), and clean multi-span.

```bash
# If client pod already ran, delete and re-run with extended traces:
kubectl delete pod langfuse-client -n pii-proxy --ignore-not-found

kubectl run langfuse-client -n pii-proxy \
  --image=langfuse-client:local \
  --restart=Never \
  --env="LANGFUSE_HOST=https://pii-proxy.pii-proxy.svc.cluster.local:443" \
  --env="LANGFUSE_PUBLIC_KEY=test-pk" \
  --env="LANGFUSE_SECRET_KEY=test-sk" \
  --env="SSL_CERT_FILE=/certs/ca.crt" \
  --overrides='{
    "spec": {
      "volumes": [{"name":"ca","configMap":{"configMapName":"pii-proxy-ca"}}],
      "containers": [{
        "name":"langfuse-client",
        "image":"langfuse-client:local",
        "env":[
          {"name":"LANGFUSE_HOST","value":"https://pii-proxy.pii-proxy.svc.cluster.local:443"},
          {"name":"LANGFUSE_PUBLIC_KEY","value":"test-pk"},
          {"name":"LANGFUSE_SECRET_KEY","value":"test-sk"},
          {"name":"SSL_CERT_FILE","value":"/certs/ca.crt"}
        ],
        "volumeMounts":[{"name":"ca","mountPath":"/certs"}]
      }]
    }
  }'

kubectl wait --for=condition=Ready pod/langfuse-client -n pii-proxy --timeout=30s 2>/dev/null || true
kubectl logs -n pii-proxy langfuse-client
```

### 10b. Capture and Assert — SC-001 (0% PII Leakage)

```bash
# Retrieve all captured payloads from mock Langfuse
CAPTURED=$(kubectl exec -n langfuse-mock deploy/mock-langfuse -- \
  wget -qO- http://localhost:8080/captured)

echo "$CAPTURED" | python3 -c "
import sys, json
data = json.load(sys.stdin)
pii_patterns = [
    'alice@example.com', 'Alice Johnson', '555-867-5309',
    'bob@corp.com',
    'jane.smith@example.com', 'Jane Smith', '312-555-0199',
    '456 Oak Avenue', 'Chicago',
]
leaked = []
captured_str = json.dumps(data)
for pii in pii_patterns:
    if pii in captured_str:
        leaked.append(pii)
if leaked:
    print(f'FAIL — PII leaked: {leaked}', file=sys.stderr)
    sys.exit(1)
else:
    print(f'PASS — SC-001: 0 of {len(pii_patterns)} PII patterns found in {len(data)} captured payloads')
"
```

### 10c. Verify Fidelity — SC-002 (Non-PII Fields Intact)

```bash
echo "$CAPTURED" | python3 -c "
import sys, json
data = json.load(sys.stdin)
# Check that clean payload (trace-002) metadata is intact
for payload in data:
    for item in payload.get('batch', []):
        if item.get('id') == 'trace-002':
            meta = item['body'].get('metadata', {})
            assert meta.get('model') == 'gpt-4', f'model mismatch: {meta}'
            assert meta.get('tokens') == 15, f'tokens mismatch: {meta}'
            msg = item['body']['input']['user_message']
            assert msg == 'What is the capital of France?', f'clean payload altered: {msg}'
            print('PASS — SC-002: clean payload metadata and content preserved')
            sys.exit(0)
print('WARN — trace-002 not found in captured data; manual inspection required')
"
```

### 10d. ext-proc Log Audit — No Raw PII in Logs

```bash
# Grep ext-proc container logs for known PII patterns
EXT_LOGS=$(kubectl logs -n pii-proxy deploy/pii-proxy -c ext-proc 2>&1)

echo "$EXT_LOGS" | python3 -c "
import sys
logs = sys.stdin.read()
pii_patterns = [
    'alice@example.com', 'Alice Johnson', '555-867-5309',
    'bob@corp.com',
    'jane.smith@example.com', 'Jane Smith', '312-555-0199',
]
leaked = [p for p in pii_patterns if p in logs]
if leaked:
    print(f'FAIL — raw PII found in ext-proc logs: {leaked}', file=sys.stderr)
    sys.exit(1)
else:
    print(f'PASS — no raw PII in ext-proc logs ({len(logs)} chars checked)')
"

# Verify scrubbing activity is logged (positive confirmation)
echo "$EXT_LOGS" | grep -c "Scrubbed request body" || echo "WARN: no scrub log entries found"
```

---

## Step 11: Upstream-Unreachable Failure Test (FR-009)

This step validates that when the upstream Langfuse endpoint is unreachable, the proxy propagates an error to the calling application rather than silently dropping the request.

### 11a. Stop the Mock Langfuse Server

```bash
# Scale mock to zero replicas — simulates upstream being unreachable
kubectl scale -n langfuse-mock deployment/mock-langfuse --replicas=0
kubectl rollout status -n langfuse-mock deployment/mock-langfuse --timeout=30s
```

### 11b. Send a Request and Assert 5xx Error

```bash
# Re-run the client — the proxy should return a 5xx since upstream is down
kubectl delete pod langfuse-client -n pii-proxy --ignore-not-found

kubectl run langfuse-client -n pii-proxy \
  --image=langfuse-client:local \
  --restart=Never \
  --env="LANGFUSE_HOST=https://pii-proxy.pii-proxy.svc.cluster.local:443" \
  --env="LANGFUSE_PUBLIC_KEY=test-pk" \
  --env="LANGFUSE_SECRET_KEY=test-sk" \
  --env="SSL_CERT_FILE=/certs/ca.crt" \
  --overrides='{
    "spec": {
      "volumes": [{"name":"ca","configMap":{"configMapName":"pii-proxy-ca"}}],
      "containers": [{
        "name":"langfuse-client",
        "image":"langfuse-client:local",
        "env":[
          {"name":"LANGFUSE_HOST","value":"https://pii-proxy.pii-proxy.svc.cluster.local:443"},
          {"name":"LANGFUSE_PUBLIC_KEY","value":"test-pk"},
          {"name":"LANGFUSE_SECRET_KEY","value":"test-sk"},
          {"name":"SSL_CERT_FILE","value":"/certs/ca.crt"}
        ],
        "volumeMounts":[{"name":"ca","mountPath":"/certs"}]
      }]
    }
  }'

# Wait for client to finish, then check logs
sleep 10
CLIENT_LOG=$(kubectl logs -n pii-proxy langfuse-client 2>&1)
echo "$CLIENT_LOG"

# Assert the client received an error (HTTP 5xx or connection refused)
echo "$CLIENT_LOG" | python3 -c "
import sys
log = sys.stdin.read()
if 'HTTP Error 5' in log or 'Error 503' in log or 'Error 502' in log or 'URLError' in log or 'Connection refused' in log:
    print('PASS — FR-009: proxy returned error when upstream unreachable')
else:
    print(f'FAIL — expected 5xx or connection error, got: {log[:200]}', file=sys.stderr)
    sys.exit(1)
"
```

### 11c. Restore the Mock Langfuse Server

```bash
# Scale mock back up for subsequent tests
kubectl scale -n langfuse-mock deployment/mock-langfuse --replicas=1
kubectl rollout status -n langfuse-mock deployment/mock-langfuse --timeout=60s
```

---

## Step 12: TLS-Render Verification (T024)

Verify that `helm template` renders the expected TLS contexts when TLS flags are set.

### 12a. Verify UpstreamTlsContext (langfuse.tls.enabled=true)

```bash
helm template test helm/pii-proxy \
  --set mode=outgoing-proxy \
  --set langfuse.host=cloud.langfuse.com \
  --set langfuse.tls.enabled=true \
  --set image.extProc.repository=test \
  -s templates/configmap-envoy.yaml 2>&1 | grep -A5 "transport_socket" | head -20

# Expected: You should see "name: envoy.transport_socket.tls" and "sni: cloud.langfuse.com"
```

### 12b. Verify NO UpstreamTlsContext when langfuse.tls.enabled=false

```bash
helm template test helm/pii-proxy \
  --set mode=outgoing-proxy \
  --set langfuse.host=mock-langfuse.langfuse-mock.svc.cluster.local \
  --set langfuse.tls.enabled=false \
  --set image.extProc.repository=test \
  -s templates/configmap-envoy.yaml 2>&1 | grep -c "UpstreamTlsContext" || echo "0"

# Expected: 0 (no UpstreamTlsContext rendered)
```

### 12c. Verify DownstreamTlsContext (tls.enabled=true)

```bash
helm template test helm/pii-proxy \
  --set mode=outgoing-proxy \
  --set langfuse.host=cloud.langfuse.com \
  --set tls.enabled=true \
  --set tls.secretName=pii-proxy-tls \
  --set image.extProc.repository=test \
  -s templates/configmap-envoy.yaml 2>&1 | grep -c "DownstreamTlsContext"

# Expected: 1
```

### 12d. Verify listener port changes with TLS

```bash
# TLS enabled → port 443
helm template test helm/pii-proxy \
  --set mode=outgoing-proxy \
  --set langfuse.host=cloud.langfuse.com \
  --set tls.enabled=true --set tls.secretName=pii-proxy-tls \
  --set image.extProc.repository=test \
  -s templates/configmap-envoy.yaml 2>&1 | grep "port_value:"

# TLS disabled → port 8080
helm template test helm/pii-proxy \
  --set mode=outgoing-proxy \
  --set langfuse.host=cloud.langfuse.com \
  --set tls.enabled=false \
  --set image.extProc.repository=test \
  -s templates/configmap-envoy.yaml 2>&1 | grep "port_value:"
```

---

## Step 13: Latency Verification (SC-004)

Validate that the proxy adds no more than 500 ms of additional latency per request.

### 13a. Baseline: Direct Call to Mock Langfuse

```bash
# From inside the cluster, measure direct latency to mock server
kubectl run latency-test -n pii-proxy --image=curlimages/curl:8.6.0 --restart=Never --rm -it -- \
  sh -c '
    for i in 1 2 3 4 5; do
      curl -s -o /dev/null -w "direct_ms: %{time_total}\n" \
        -X POST "http://mock-langfuse.langfuse-mock.svc.cluster.local:8080/api/public/ingestion" \
        -H "Content-Type: application/json" \
        -d "{\"batch\":[{\"type\":\"trace-create\",\"body\":{\"name\":\"latency-test\",\"input\":{\"msg\":\"hello world\"}}}]}"
    done
  '
```

### 13b. Proxy Call (via PII Proxy)

```bash
kubectl run latency-test -n pii-proxy --image=curlimages/curl:8.6.0 --restart=Never --rm -it -- \
  sh -c '
    for i in 1 2 3 4 5; do
      curl -s -o /dev/null -w "proxy_ms: %{time_total}\n" -k \
        -X POST "https://pii-proxy.pii-proxy.svc.cluster.local:443/api/public/ingestion" \
        -H "Content-Type: application/json" \
        -d "{\"batch\":[{\"type\":\"trace-create\",\"body\":{\"name\":\"latency-test\",\"input\":{\"msg\":\"hello world\"}}}]}"
    done
  '
```

### 13c. Calculate Delta

```text
Compare p95/p99 of proxy_ms vs direct_ms.
SC-004 threshold: proxy overhead < 500 ms.

Example:
  direct p95: 0.025s
  proxy  p95: 0.180s
  delta:      0.155s (155 ms) — PASS
```

---

## Step 14: Runtime Upstream TLS Verification (FR-003)

Verify the proxy can establish TLS connections to upstream Langfuse when `langfuse.tls.enabled=true`.

### 14a. Deploy Mock Langfuse with TLS

```bash
# Generate server cert for mock-langfuse
cd /tmp/pii-proxy-certs
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout mock-tls.key -out mock-tls.crt -days 1 \
  -subj "/CN=mock-langfuse.langfuse-mock.svc.cluster.local" \
  -addext "subjectAltName=DNS:mock-langfuse.langfuse-mock.svc.cluster.local"

# Create TLS secret for mock
kubectl create secret tls mock-langfuse-tls -n langfuse-mock \
  --cert=mock-tls.crt --key=mock-tls.key --dry-run=client -o yaml | kubectl apply -f -
```

### 14b. Re-deploy PII Proxy with langfuse.tls.enabled=true

```bash
helm upgrade pii-proxy helm/pii-proxy \
  --namespace pii-proxy \
  --set mode=outgoing-proxy \
  --set langfuse.host=mock-langfuse.langfuse-mock.svc.cluster.local \
  --set langfuse.port=443 \
  --set langfuse.tls.enabled=true \
  --set tls.enabled=true \
  --set tls.secretName=pii-proxy-tls \
  --set istio.enabled=true \
  --set image.extProc.repository=pii-proxy/ext-proc \
  --set image.extProc.tag=dev \
  --set image.pullPolicy=Never

kubectl -n pii-proxy rollout status deployment/pii-proxy --timeout=600s
```

### 14c. Send Trace and Verify

```bash
kubectl delete pod langfuse-client -n pii-proxy --ignore-not-found

kubectl run langfuse-client -n pii-proxy \
  --image=langfuse-client:local \
  --restart=Never \
  --env="LANGFUSE_HOST=https://pii-proxy.pii-proxy.svc.cluster.local:443" \
  --env="LANGFUSE_PUBLIC_KEY=test-pk" \
  --env="LANGFUSE_SECRET_KEY=test-sk" \
  --env="SSL_CERT_FILE=/certs/ca.crt" \
  --overrides='{
    "spec": {
      "volumes": [{"name":"ca","configMap":{"configMapName":"pii-proxy-ca"}}],
      "containers": [{
        "name":"langfuse-client",
        "image":"langfuse-client:local",
        "env":[
          {"name":"LANGFUSE_HOST","value":"https://pii-proxy.pii-proxy.svc.cluster.local:443"},
          {"name":"LANGFUSE_PUBLIC_KEY","value":"test-pk"},
          {"name":"LANGFUSE_SECRET_KEY","value":"test-sk"},
          {"name":"SSL_CERT_FILE","value":"/certs/ca.crt"}
        ],
        "volumeMounts":[{"name":"ca","mountPath":"/certs"}]
      }]
    }
  }'

sleep 15
kubectl logs -n pii-proxy langfuse-client

# Verify Envoy established upstream TLS
kubectl logs -n pii-proxy deploy/pii-proxy -c envoy 2>&1 | grep -i "tls\|ssl\|handshake" | tail -5

# Verify scrubbed payload arrived at mock
kubectl exec -n langfuse-mock deploy/mock-langfuse -- wget -qO- http://localhost:8080/captured | python3 -c "
import sys, json
data = json.load(sys.stdin)
if len(data) > 0:
    print(f'PASS — FR-003: {len(data)} payloads received over TLS upstream')
else:
    print('FAIL — no payloads captured; TLS handshake may have failed', file=sys.stderr)
    sys.exit(1)
"
```

---

## Cleanup

```bash
helm uninstall pii-proxy -n pii-proxy
kubectl delete pod langfuse-client -n pii-proxy --ignore-not-found
kubectl delete -n langfuse-mock deployment/mock-langfuse service/mock-langfuse
kubectl delete namespace pii-proxy langfuse-mock
rm -rf /tmp/pii-proxy-certs
minikube stop          # or: minikube delete
```

---

## TLS Trust Chain (Summary)

```
test-fixtures/certs/gen-certs.sh
        │
        ├── ca.crt  →  ConfigMap pii-proxy-ca  →  mounted in langfuse-client pod
        │                                          SSL_CERT_FILE=/certs/ca.crt
        │                                          Langfuse SDK httpx trusts it
        │
        ├── tls.crt  →  Secret pii-proxy-tls  →  mounted in pii-proxy pod /certs/tls.crt
        └── tls.key  →  Secret pii-proxy-tls  →  mounted in pii-proxy pod /certs/tls.key
                                                   Envoy DownstreamTlsContext uses it
```

---

## Configuration Reference

See [contracts/values-schema.md](contracts/values-schema.md) for the full Helm values API.  
See [contracts/istio-resources.md](contracts/istio-resources.md) for ServiceEntry and DestinationRule details.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| ext_proc pod stays NotReady for > 5 min | spaCy model load OOMKilled | Increase `resources.extProc.limits.memory` to at least `4Gi` |
| `x509: certificate signed by unknown authority` in client pod | CA cert not mounted or `SSL_CERT_FILE` not set | Verify ConfigMap `pii-proxy-ca` exists and the pod's `SSL_CERT_FILE` env var points to `/certs/ca.crt` |
| `tls: oversized record received` in Envoy logs | Istio sidecar intercepting port 443 before Envoy | Verify `traffic.sidecar.istio.io/excludeInboundPorts: "443"` annotation on the pii-proxy pod |
| Double TLS error on outbound (proxy → mock) | Istio adding mTLS to the HTTP connection to mock | Verify DestinationRule `tls.mode: DISABLE` for mock Langfuse host; verify `excludeOutboundPorts: "8080"` annotation |
| 503 from proxy to mock Langfuse | `langfuse.host` misconfigured or mock not ready | `kubectl get svc -n langfuse-mock` and confirm host/port matches Helm values |
| PII not scrubbed (raw PII in captured payload) | ext_proc not in the request processing path | Check `kubectl logs -n pii-proxy deploy/pii-proxy -c ext-proc` for "Scrubbed request body" log lines |
| `RBAC: access denied` from Istio on outbound | `outboundTrafficPolicy: REGISTRY_ONLY` active but ServiceEntry missing | Verify `istio.enabled=true` in Helm values and that ServiceEntry was created |

---

## Prerequisites

| Tool | Minimum version | Install |
|------|-----------------|---------|
| minikube | 1.32 | <https://minikube.sigs.k8s.io/docs/start/> |
| kubectl | 1.28 | bundled with minikube or separate |
| istioctl | 1.20 | <https://istio.io/latest/docs/setup/getting-started/> |
| helm | 3.12 | <https://helm.sh/docs/intro/install/> |
| Docker | 24+ | required by minikube with docker driver |
| Python | 3.11 | for running the test client locally |

---

## Step 1: Start minikube and Install Istio

```bash
minikube start --memory=8192 --cpus=4 --driver=docker

# Install Istio (demo profile — includes all components needed for testing)
istioctl install --set profile=demo -y

# Verify Istio is running
kubectl get pods -n istio-system
# All pods should be Running before continuing
```

---

## Step 2: Create Namespaces

```bash
# PII proxy namespace — Istio sidecar injection ENABLED
kubectl create namespace pii-proxy
kubectl label namespace pii-proxy istio-injection=enabled

# Mock Langfuse namespace — NO sidecar injection (simulates external server)
kubectl create namespace langfuse-mock
```

---

## Step 3: Build and Load Docker Images

```bash
# Use minikube's Docker daemon so images are available without a registry
eval $(minikube docker-env)

# Build ext_proc image
docker build -t pii-proxy/ext-proc:latest ./ext_proc

# Build mock Langfuse server image
docker build -t pii-proxy/mock-langfuse:latest ./test-fixtures/mock-langfuse

# Build test client image
docker build -t pii-proxy/langfuse-client:latest ./test-fixtures/langfuse-client
```

---

## Step 4: Deploy Mock Langfuse Server

```bash
kubectl apply -n langfuse-mock -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mock-langfuse
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mock-langfuse
  template:
    metadata:
      labels:
        app: mock-langfuse
    spec:
      containers:
        - name: mock-langfuse
          image: pii-proxy/mock-langfuse:latest
          imagePullPolicy: Never
          ports:
            - containerPort: 8080
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: mock-langfuse
spec:
  selector:
    app: mock-langfuse
  ports:
    - port: 8080
      targetPort: 8080
EOF

# Wait for mock server to be ready
kubectl rollout status deployment/mock-langfuse -n langfuse-mock
```

---

## Step 5: Deploy PII Proxy via Helm

```bash
helm upgrade --install pii-proxy ./helm/pii-proxy \
  --namespace pii-proxy \
  --set mode=outgoing-proxy \
  --set image.extProc.repository=pii-proxy/ext-proc \
  --set image.pullPolicy=Never \
  --set langfuse.host=mock-langfuse.langfuse-mock.svc.cluster.local \
  --set langfuse.port=8080 \
  --set langfuse.tls.enabled=false \
  --set tls.enabled=false \
  --set istio.enabled=true \
  --set service.port=8080

# The ext_proc pod takes 2-3 minutes to become Ready (spaCy model loading)
kubectl rollout status deployment/pii-proxy -n pii-proxy --timeout=300s
```

---

## Step 6: Run the Integration Test

```bash
# Deploy the test client pod and wait for it to complete
kubectl run langfuse-client \
  --image=pii-proxy/langfuse-client:latest \
  --image-pull-policy=Never \
  --env="LANGFUSE_HOST=http://pii-proxy.pii-proxy.svc.cluster.local:8080" \
  --env="LANGFUSE_PUBLIC_KEY=test-pk" \
  --env="LANGFUSE_SECRET_KEY=test-sk" \
  --restart=Never \
  -n pii-proxy \
  -- python send_traces.py

# Wait for the job to finish
kubectl wait pod/langfuse-client -n pii-proxy --for=condition=Succeeded --timeout=60s

# Check the test client output
kubectl logs langfuse-client -n pii-proxy
```

---

## Step 7: Assert PII Was Scrubbed

```bash
# Port-forward the mock Langfuse server to query captured payloads
kubectl port-forward svc/mock-langfuse 9090:8080 -n langfuse-mock &
PF_PID=$!

# Query captured request bodies
curl -s http://localhost:9090/captured | python3 -m json.tool

# Verify no PII appears in the output — these strings MUST NOT appear:
# "Alice Johnson", "alice@example.com", "555-867-5309"
# PII should be replaced with Presidio placeholders:
# "<PERSON>", "<EMAIL_ADDRESS>", "<PHONE_NUMBER>"

# Kill port-forward
kill $PF_PID
```

Expected output (excerpt — no raw PII):

```json
[
  {
    "batch": [
      {
        "type": "trace-create",
        "body": {
          "name": "pii-test",
          "input": {
            "user_message": "Hi, I'm <PERSON>, my email is <EMAIL_ADDRESS> and my phone is <PHONE_NUMBER>"
          }
        }
      }
    ]
  }
]
```

---

## Step 8: Run Unit Tests

```bash
# Unit tests do not require minikube — run locally
cd ext_proc
uv run pytest tests/test_request_scrubbing.py -v
```

---

## Cleanup

```bash
helm uninstall pii-proxy -n pii-proxy
kubectl delete pod langfuse-client -n pii-proxy --ignore-not-found
kubectl delete -n langfuse-mock deployment/mock-langfuse service/mock-langfuse
kubectl delete namespace pii-proxy langfuse-mock
minikube stop  # or: minikube delete
```

---

## Configuration Reference

See [contracts/values-schema.md](contracts/values-schema.md) for the full Helm values API.

For production deployment with real Langfuse (`cloud.langfuse.com`):

1. Create or obtain a TLS certificate for the proxy's HTTPS listener.
2. Store it as a `kubernetes.io/tls` Secret in the `pii-proxy` namespace.
3. Set `tls.enabled=true`, `tls.secretName=<your-secret>`, `langfuse.host=cloud.langfuse.com`.
4. Configure your application's `LANGFUSE_HOST` env var and SSL trust accordingly.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| ext_proc pod stays NotReady for > 5 minutes | spaCy model load OOMKilled | Increase `resources.extProc.limits.memory` to at least `4Gi` |
| 503 from proxy to mock Langfuse | `langfuse.host` misconfigured or mock server not ready | Verify `kubectl get svc -n langfuse-mock` and match host value |
| Istio sidecar blocks egress to mock server | `outboundTrafficPolicy: REGISTRY_ONLY` on cluster | Verify `istio.enabled=true` so ServiceEntry is created |
| PII not scrubbed (raw PII in captured payload) | ext_proc is not in the request path | Check `kubectl logs -n pii-proxy deploy/pii-proxy -c ext-proc` for "Scrubbed request body" log lines |
| Double TLS error (`tls: oversized record` in Envoy logs) | Istio intercepting outbound 443 in addition to Envoy | Verify `traffic.sidecar.istio.io/excludeOutboundPorts: "443"` annotation is present on the pod |

---

## Validation Notes

> Execution notes captured during validation runs. Record actual command outputs here.

### Full Validation Checklist

Complete each item and record PASS/FAIL with the step number where it was verified.

| # | Check | Requirement | Step | Status |
|---|-------|-------------|------|--------|
| 1 | `helm lint` passes for outgoing-proxy mode | Chart validity | Step 0 | |
| 2 | `helm template` fails without `langfuse.host` in outgoing mode | Value guard | Step 0 | |
| 3 | `helm template` fails without `tls.secretName` when `tls.enabled=true` | Value guard | Step 0 | |
| 4 | Unit tests pass (all `test_request_scrubbing.py` tests) | Code correctness | Step 9 | |
| 5 | Email PII scrubbed from captured payload | FR-002, SC-001 | Step 8 | |
| 6 | Phone number PII scrubbed from captured payload | FR-002, SC-001 | Step 10 | |
| 7 | Person name PII scrubbed from captured payload | FR-002, SC-001 | Step 10 | |
| 8 | Physical address/location PII scrubbed | FR-002, SC-001 | Step 10 | |
| 9 | Non-PII fields preserved unchanged | FR-005, SC-002 | Step 10 | |
| 10 | No raw PII in ext-proc container logs | Security | Step 10 | |
| 11 | Scrubbing activity logged (positive confirmation) | Observability | Step 10 | |
| 12 | Proxy returns 5xx when upstream unreachable | FR-009 | Step 11 | |
| 13 | Mock restored successfully after failure test | Resilience | Step 11 | |
| 14 | `UpstreamTlsContext` renders when `langfuse.tls.enabled=true` | FR-003 | Step 12 | |
| 15 | No `UpstreamTlsContext` when `langfuse.tls.enabled=false` | Conditional render | Step 12 | |
| 16 | `DownstreamTlsContext` renders when `tls.enabled=true` | TLS listener | Step 12 | |
| 17 | Listener port is 443 with TLS, 8080 without | Port mapping | Step 12 | |
| 18 | Proxy latency overhead < 500 ms (p95) | SC-004 | Step 13 | |
| 19 | Upstream TLS handshake succeeds at runtime | FR-003 | Step 14 | |
| 20 | Istio ServiceEntry + DestinationRule rendered | FR-008 | Helm template | |
| 21 | Istio port-exclusion annotations present | Deployment | Helm template | |
| 22 | Langfuse response relayed to client (HTTP 2xx) | FR-006 | Step 7 | |
| 23 | `helm test` passes in outgoing-proxy mode | Helm test hook | `helm test` | |

### Run 1 — Date: ___

**Environment**: minikube v___/ Istio v___ / Helm v___

**Helm lint**:

```text
(paste output here)
```

**Unit tests**:

```text
(paste output here)
```

**Integration test (PII assertion)**:

```text
(paste output here)
```

**Security audit (SC-001 / SC-002)**:

```text
(paste output here)
```

**Upstream-unreachable (FR-009)**:

```text
(paste output here)
```

**TLS-render verification**:

```text
(paste output here)
```

**Latency verification (SC-004)**:

```text
(paste output here)
```

**Issues encountered**:

- (none yet)
