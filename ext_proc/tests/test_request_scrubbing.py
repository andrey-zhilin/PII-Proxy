"""Tests for request-body scrubbing in ext_proc (outgoing-proxy mode).

These tests exercise the request_headers → request_body flow, simulating
what Envoy sends to ext_proc when processing_mode has:
  request_header_mode: SEND
  request_body_mode: BUFFERED

Run from the project root:
    cd ext_proc
    PYTHONPATH=. uv run pytest tests/test_request_scrubbing.py -v
"""

from __future__ import annotations

import json
import sys
import os
import pytest

# Ensure generated protos are importable (same as test_scrubber.py convention)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generated"))

from ext_proc.generated.envoy.service.ext_proc.v3 import (
    external_processor_pb2,
)
from envoy.config.core.v3 import base_pb2
from ext_proc.app import ExtProcService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request_headers(content_type: str = "application/json"):
    """Build a ProcessingRequest with request_headers containing Content-Type."""
    return external_processor_pb2.ProcessingRequest(
        request_headers=external_processor_pb2.HttpHeaders(
            headers=base_pb2.HeaderMap(
                headers=[
                    base_pb2.HeaderValue(
                        key="content-type",
                        value=content_type,
                    ),
                ]
            )
        )
    )


def _make_request_body(body: bytes):
    """Build a ProcessingRequest with a request_body."""
    return external_processor_pb2.ProcessingRequest(
        request_body=external_processor_pb2.HttpBody(body=body)
    )


def _process(messages: list[external_processor_pb2.ProcessingRequest]):
    """Run messages through ExtProcService.Process() and return responses."""
    service = ExtProcService()
    return list(service.Process(iter(messages), context=None))


# ---------------------------------------------------------------------------
# Tests — email redaction in request body
# ---------------------------------------------------------------------------


class TestRequestBodyEmailRedaction:
    def test_email_redacted_from_json_request(self):
        """PII email in a JSON request body must be replaced with a placeholder."""
        payload = json.dumps(
            {"message": "Contact alice@example.com for details"}
        ).encode()
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        assert len(responses) == 2
        # Second response should have a body mutation
        body_resp = responses[1]
        assert body_resp.HasField("request_body")
        mutated = body_resp.request_body.response.body_mutation.body
        assert b"alice@example.com" not in mutated

    def test_email_redacted_from_langfuse_trace_payload(self):
        """Langfuse-shaped batch ingestion payload gets email scrubbed."""
        payload = json.dumps(
            {
                "batch": [
                    {
                        "type": "trace-create",
                        "body": {
                            "name": "pii-test",
                            "input": {
                                "user_message": "Hi, I'm Alice, my email is alice@example.com"
                            },
                        },
                    }
                ]
            }
        ).encode()
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert b"alice@example.com" not in mutated


# ---------------------------------------------------------------------------
# Tests — non-PII fidelity
# ---------------------------------------------------------------------------


class TestRequestBodyNonPiiFidelity:
    def test_non_pii_fields_preserved(self):
        """Fields without PII pass through unchanged."""
        payload = json.dumps(
            {
                "batch": [
                    {
                        "type": "trace-create",
                        "body": {
                            "name": "my-trace",
                            "metadata": {"model": "gpt-4", "tokens": 150},
                        },
                    }
                ]
            }
        ).encode()
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        result = json.loads(mutated)
        assert result["batch"][0]["type"] == "trace-create"
        assert result["batch"][0]["body"]["name"] == "my-trace"
        assert result["batch"][0]["body"]["metadata"]["model"] == "gpt-4"
        assert result["batch"][0]["body"]["metadata"]["tokens"] == 150


# ---------------------------------------------------------------------------
# Tests — text/plain content type
# ---------------------------------------------------------------------------


class TestRequestBodyPlainText:
    def test_plain_text_email_redacted(self):
        """Plain text request body also gets PII scrubbed."""
        payload = b"Send a message to alice@example.com"
        responses = _process(
            [_make_request_headers("text/plain"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert b"alice@example.com" not in mutated

    def test_plain_text_no_pii_unchanged(self):
        """Plain text without PII passes through (still gets body mutation)."""
        payload = b"Hello world, no sensitive data here"
        responses = _process(
            [_make_request_headers("text/plain"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert mutated == payload


# ---------------------------------------------------------------------------
# Tests — nested JSON PII (US3 / T018)
# ---------------------------------------------------------------------------


class TestRequestBodyNestedJsonPii:
    """PII buried in deeply nested JSON structures must be scrubbed."""

    def test_deeply_nested_email_scrubbed(self):
        """Email in a 4-level nested field is detected and scrubbed."""
        payload = json.dumps(
            {
                "batch": [
                    {
                        "type": "trace-create",
                        "body": {
                            "input": {
                                "messages": [
                                    {"role": "user", "content": "Contact bob@corp.com"}
                                ]
                            }
                        },
                    }
                ]
            }
        ).encode()
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert b"bob@corp.com" not in mutated

    def test_nested_phone_number_scrubbed(self):
        """Phone number nested inside metadata is scrubbed."""
        payload = json.dumps(
            {
                "batch": [
                    {
                        "type": "span-create",
                        "body": {
                            "output": {"response": "Call 212-555-0100 to reach support"}
                        },
                    }
                ]
            }
        ).encode()
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert b"212-555-0100" not in mutated


# ---------------------------------------------------------------------------
# Tests — multi-category PII (US3 / T018)
# ---------------------------------------------------------------------------


class TestRequestBodyMultiCategoryPii:
    """Payloads with multiple PII types must have all categories scrubbed."""

    def test_email_and_phone_both_scrubbed(self):
        """Both email and phone in the same payload are replaced."""
        payload = json.dumps(
            {
                "batch": [
                    {
                        "type": "trace-create",
                        "body": {
                            "input": {
                                "user_message": (
                                    "Hi, I'm Alice. Email alice@example.com "
                                    "or call 555-867-5309"
                                )
                            }
                        },
                    }
                ]
            }
        ).encode()
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert b"alice@example.com" not in mutated
        assert b"555-867-5309" not in mutated

    def test_name_and_email_scrubbed(self):
        """Person name and email address in plain text are both scrubbed."""
        payload = b"Contact Alice Johnson at alice.johnson@example.com"
        responses = _process(
            [_make_request_headers("text/plain"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert b"alice.johnson@example.com" not in mutated
        assert b"Alice Johnson" not in mutated


# ---------------------------------------------------------------------------
# Tests — physical address redaction (US3 / T018)
# ---------------------------------------------------------------------------


class TestRequestBodyPhysicalAddress:
    """Physical addresses are a required PII category per FR-002 / SC-001."""

    def test_us_street_address_scrubbed_in_json(self):
        """A recognizable US street address in JSON is detected and scrubbed."""
        payload = json.dumps(
            {
                "batch": [
                    {
                        "type": "trace-create",
                        "body": {
                            "input": {
                                "user_message": (
                                    "Ship to 123 Main Street, Springfield, IL 62704"
                                )
                            }
                        },
                    }
                ]
            }
        ).encode()
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        # Presidio detects the city/state as LOCATION at minimum
        assert b"Springfield" not in mutated


# ---------------------------------------------------------------------------
# Tests — clean payload fidelity (US3 / T018)
# ---------------------------------------------------------------------------


class TestRequestBodyCleanPayloadFidelity:
    """Non-PII payloads must pass through with structural and value fidelity (SC-002)."""

    def test_complex_clean_payload_preserved(self):
        """A realistic Langfuse payload without PII is forwarded unmodified."""
        payload_dict = {
            "batch": [
                {
                    "type": "trace-create",
                    "body": {
                        "name": "llm-call",
                        "metadata": {
                            "model": "gpt-4",
                            "tokens": 1500,
                            "latency_ms": 342.7,
                            "stream": False,
                        },
                        "tags": ["production", "release-candidate"],
                    },
                },
                {
                    "type": "span-create",
                    "body": {
                        "name": "embedding-lookup",
                        "metadata": {"dimension": 1536},
                    },
                },
            ]
        }
        payload = json.dumps(payload_dict).encode()
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        result = json.loads(mutated)
        assert result["batch"][0]["body"]["metadata"]["model"] == "gpt-4"
        assert result["batch"][0]["body"]["metadata"]["tokens"] == 1500
        assert result["batch"][0]["body"]["metadata"]["latency_ms"] == 342.7
        assert result["batch"][0]["body"]["metadata"]["stream"] is False
        assert result["batch"][0]["body"]["tags"] == ["production", "release-candidate"]
        assert result["batch"][1]["body"]["metadata"]["dimension"] == 1536

    def test_numeric_and_boolean_fields_not_altered(self):
        """Numeric and boolean fields must not be changed by the scrubber."""
        payload_dict = {
            "count": 42,
            "ratio": 0.95,
            "active": True,
            "deleted": False,
            "note": None,
        }
        payload = json.dumps(payload_dict).encode()
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        result = json.loads(mutated)
        assert result == payload_dict


# ---------------------------------------------------------------------------
# Tests — malformed JSON safety (US3 / T018)
# ---------------------------------------------------------------------------


class TestRequestBodyMalformedJsonSafety:
    """Malformed or non-JSON request bodies must be handled safely (edge case)."""

    def test_truncated_json_does_not_crash(self):
        """Truncated JSON falls through to plain-text scrubbing."""
        payload = b'{"email": "alice@example.com"'  # missing closing brace
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert b"alice@example.com" not in mutated

    def test_empty_json_body_handled(self):
        """Empty body does not crash the scrubber."""
        payload = b""
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert mutated == b""

    def test_binary_body_returned_unchanged(self):
        """Non-UTF-8 binary data is returned unchanged (no crash)."""
        payload = bytes(range(256))  # not valid UTF-8
        responses = _process(
            [
                _make_request_headers("application/octet-stream"),
                _make_request_body(payload),
            ]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert mutated == payload

    def test_invalid_json_with_pii_scrubs_as_text(self):
        """Body that looks like JSON but isn't valid still scrubs PII as text."""
        payload = b"{ not real json: alice@example.com }"
        responses = _process(
            [_make_request_headers("application/json"), _make_request_body(payload)]
        )
        mutated = responses[1].request_body.response.body_mutation.body
        assert b"alice@example.com" not in mutated
