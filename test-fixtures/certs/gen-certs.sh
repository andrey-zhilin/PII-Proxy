#!/usr/bin/env bash
# Generate a self-signed CA and TLS certificate for the PII proxy test environment.
#
# Usage:
#   bash test-fixtures/certs/gen-certs.sh [OUTPUT_DIR]
#
# Output files:
#   OUTPUT_DIR/ca.crt    — CA certificate (trust by test client)
#   OUTPUT_DIR/ca.key    — CA private key
#   OUTPUT_DIR/tls.crt   — Server certificate (for Envoy DownstreamTlsContext)
#   OUTPUT_DIR/tls.key   — Server private key
#
# The server certificate is valid for:
#   DNS: pii-proxy.pii-proxy.svc.cluster.local

set -euo pipefail

OUTPUT_DIR="${1:-/tmp/pii-proxy-certs}"
DAYS=365
SAN="DNS:pii-proxy.pii-proxy.svc.cluster.local"
CA_SUBJECT="/CN=pii-proxy-test-ca"
SERVER_SUBJECT="/CN=pii-proxy.pii-proxy.svc.cluster.local"

mkdir -p "$OUTPUT_DIR"

echo "==> Generating CA key and certificate..."
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout "$OUTPUT_DIR/ca.key" \
  -out "$OUTPUT_DIR/ca.crt" \
  -days "$DAYS" \
  -subj "$CA_SUBJECT" \
  2>/dev/null

echo "==> Generating server key and CSR..."
openssl req -newkey rsa:4096 -nodes \
  -keyout "$OUTPUT_DIR/tls.key" \
  -out "$OUTPUT_DIR/tls.csr" \
  -subj "$SERVER_SUBJECT" \
  2>/dev/null

echo "==> Signing server certificate with CA..."
openssl x509 -req \
  -in "$OUTPUT_DIR/tls.csr" \
  -CA "$OUTPUT_DIR/ca.crt" \
  -CAkey "$OUTPUT_DIR/ca.key" \
  -CAcreateserial \
  -out "$OUTPUT_DIR/tls.crt" \
  -days "$DAYS" \
  -extfile <(printf "subjectAltName=%s" "$SAN") \
  2>/dev/null

# Clean up intermediate files
rm -f "$OUTPUT_DIR/tls.csr" "$OUTPUT_DIR/ca.srl"

echo "==> Certificates generated in $OUTPUT_DIR:"
ls -la "$OUTPUT_DIR"
echo ""
echo "Next steps:"
echo "  kubectl create secret tls pii-proxy-tls --cert=$OUTPUT_DIR/tls.crt --key=$OUTPUT_DIR/tls.key -n pii-proxy"
echo "  kubectl create configmap pii-proxy-ca --from-file=ca.crt=$OUTPUT_DIR/ca.crt -n pii-proxy"
