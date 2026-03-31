# PII_proxy Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-23

## Active Technologies
- Python 3.11 (ext_proc), Helm 3 / YAML (deployment config), Envoy v1.33.0 + Envoy ext_proc v3 gRPC API (existing), Presidio + spaCy `en_core_web_lg` (existing scrubber), Langfuse Python SDK `langfuse>=2.0` (test client only), FastAPI or Flask (mock Langfuse server), Istio 1.20+ CRDs (ServiceEntry, DestinationRule), Kubernetes 1.28+ (002-langfuse-outgoing-proxy)
- Python 3.11 (ext_proc), Helm 3 / YAML (deployment config), Envoy v1.33.0 + Envoy ext_proc v3 gRPC API (existing), Presidio + spaCy `en_core_web_lg` (existing scrubber), Langfuse Python SDK `langfuse>=2.0` (test client only), FastAPI (mock Langfuse server), Istio 1.20+ CRDs (ServiceEntry, DestinationRule), Kubernetes 1.28+, openssl (cert generation in test setup) (002-langfuse-outgoing-proxy)

- Helm 3.x (YAML templates); Python 3.12 (ext_proc — existing) + Helm 3.x, kubectl 1.27+, envoyproxy/envoy:v1.33.0, minikube v1.32+ (local testing), spaCy `en_core_web_lg`, Presidio (001-k8s-deployment)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Helm 3.x (YAML templates); Python 3.12 (ext_proc — existing): Follow standard conventions

## Recent Changes
- 002-langfuse-outgoing-proxy: Added Python 3.11 (ext_proc), Helm 3 / YAML (deployment config), Envoy v1.33.0 + Envoy ext_proc v3 gRPC API (existing), Presidio + spaCy `en_core_web_lg` (existing scrubber), Langfuse Python SDK `langfuse>=2.0` (test client only), FastAPI (mock Langfuse server), Istio 1.20+ CRDs (ServiceEntry, DestinationRule), Kubernetes 1.28+, openssl (cert generation in test setup)
- 002-langfuse-outgoing-proxy: Added Python 3.11 (ext_proc), Helm 3 / YAML (deployment config), Envoy v1.33.0 + Envoy ext_proc v3 gRPC API (existing), Presidio + spaCy `en_core_web_lg` (existing scrubber), Langfuse Python SDK `langfuse>=2.0` (test client only), FastAPI or Flask (mock Langfuse server), Istio 1.20+ CRDs (ServiceEntry, DestinationRule), Kubernetes 1.28+

- 001-k8s-deployment: Added Helm 3.x (YAML templates); Python 3.12 (ext_proc — existing) + Helm 3.x, kubectl 1.27+, envoyproxy/envoy:v1.33.0, minikube v1.32+ (local testing), spaCy `en_core_web_lg`, Presidio

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
