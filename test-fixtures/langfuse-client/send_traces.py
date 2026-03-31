"""Langfuse SDK test client — sends traces with known PII through the PII proxy.

Environment variables:
  LANGFUSE_HOST       — PII proxy URL (e.g. http://pii-proxy.pii-proxy.svc.cluster.local:8080)
  LANGFUSE_PUBLIC_KEY — Any value (mock server accepts all)
  LANGFUSE_SECRET_KEY — Any value (mock server accepts all)
  SSL_CERT_FILE       — Path to CA cert if using HTTPS (optional)
"""

from __future__ import annotations

import os
import sys
import json
import urllib.request
import urllib.error

PROXY_HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:8080")
PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "test-pk")
SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "test-sk")


def send_trace(payload: dict) -> None:
    """Send a batch ingestion request to the proxy."""
    url = f"{PROXY_HOST}/api/public/ingestion"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {PUBLIC_KEY}:{SECRET_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            print(f"  Response {resp.status}: {body}")
    except urllib.error.HTTPError as e:
        print(f"  HTTP Error {e.code}: {e.read().decode()}", file=sys.stderr)
        raise


def main() -> None:
    print("=== Langfuse PII Test Client ===")

    # Trace 1: Baseline PII — name, email, phone
    print("Sending trace 1: baseline PII (Alice Johnson, alice@example.com, 555-867-5309)")
    send_trace(
        {
            "batch": [
                {
                    "id": "trace-001",
                    "type": "trace-create",
                    "timestamp": "2026-03-30T10:00:00.000Z",
                    "body": {
                        "id": "trace-uuid-001",
                        "name": "pii-test",
                        "input": {
                            "user_message": "Hi, I'm Alice Johnson, my email is alice@example.com and my phone is 555-867-5309"
                        },
                        "output": None,
                        "metadata": {"model": "gpt-4", "tokens": 42},
                    },
                }
            ]
        }
    )

    # Trace 2: Clean payload — no PII
    print("Sending trace 2: clean payload (no PII)")
    send_trace(
        {
            "batch": [
                {
                    "id": "trace-002",
                    "type": "trace-create",
                    "timestamp": "2026-03-30T10:01:00.000Z",
                    "body": {
                        "id": "trace-uuid-002",
                        "name": "clean-test",
                        "input": {
                            "user_message": "What is the capital of France?"
                        },
                        "output": {"response": "The capital of France is Paris."},
                        "metadata": {"model": "gpt-4", "tokens": 15},
                    },
                }
            ]
        }
    )

    # Trace 3: Nested PII — email buried in deeply nested messages
    print("Sending trace 3: nested PII (bob@corp.com in nested messages)")
    send_trace(
        {
            "batch": [
                {
                    "id": "trace-003",
                    "type": "trace-create",
                    "timestamp": "2026-03-30T10:02:00.000Z",
                    "body": {
                        "id": "trace-uuid-003",
                        "name": "nested-pii-test",
                        "input": {
                            "messages": [
                                {"role": "system", "content": "You are a helpful assistant."},
                                {"role": "user", "content": "Contact bob@corp.com for the report"},
                            ]
                        },
                        "output": {
                            "response": {
                                "choices": [
                                    {"message": {"content": "I'll reach out to bob@corp.com right away."}}
                                ]
                            }
                        },
                        "metadata": {"model": "gpt-4", "tokens": 85},
                    },
                }
            ]
        }
    )

    # Trace 4: Multi-PII — name, email, phone, and physical address
    print("Sending trace 4: multi-PII (name, email, phone, address)")
    send_trace(
        {
            "batch": [
                {
                    "id": "trace-004",
                    "type": "trace-create",
                    "timestamp": "2026-03-30T10:03:00.000Z",
                    "body": {
                        "id": "trace-uuid-004",
                        "name": "multi-pii-test",
                        "input": {
                            "user_message": (
                                "Send the package to Jane Smith at 456 Oak Avenue, "
                                "Chicago, IL 60601. Her email is jane.smith@example.com "
                                "and her phone is 312-555-0199."
                            )
                        },
                        "output": None,
                        "metadata": {"model": "gpt-4", "tokens": 120},
                    },
                }
            ]
        }
    )

    # Trace 5: Clean batch with multiple spans — no PII
    print("Sending trace 5: clean multi-span batch (no PII)")
    send_trace(
        {
            "batch": [
                {
                    "id": "span-001",
                    "type": "span-create",
                    "timestamp": "2026-03-30T10:04:00.000Z",
                    "body": {
                        "id": "span-uuid-001",
                        "traceId": "trace-uuid-002",
                        "name": "embedding-lookup",
                        "input": {"query": "machine learning fundamentals"},
                        "output": {"vectors": 1536},
                        "metadata": {"dimension": 1536, "latency_ms": 42},
                    },
                },
                {
                    "id": "span-002",
                    "type": "span-create",
                    "timestamp": "2026-03-30T10:04:01.000Z",
                    "body": {
                        "id": "span-uuid-002",
                        "traceId": "trace-uuid-002",
                        "name": "llm-completion",
                        "input": {"prompt": "Summarize the key concepts"},
                        "output": {"response": "The key concepts include supervised and unsupervised learning."},
                        "metadata": {"model": "gpt-4", "tokens": 200, "stream": False},
                    },
                },
            ]
        }
    )

    print("Done — 5 traces sent via proxy. Check mock server /captured for scrubbed payloads.")


if __name__ == "__main__":
    main()
