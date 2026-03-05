"""Tests for ext_proc.scrubber.scrubber.

Run from the project root:
    cd ext_proc
    PYTHONPATH=..:generated uv run pytest tests/ -v

The module-scoped ``scrubber`` fixture loads the spaCy model once per test
session, which is the expensive part (~2–3 s for en_core_web_lg).
"""

from __future__ import annotations

import json
import pytest

from ext_proc.scrubber.scrubber import PiiScrubber, _looks_like_json


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def s():
    """Shared PiiScrubber instance (model loaded once for the whole module)."""
    return PiiScrubber()


# ---------------------------------------------------------------------------
# _looks_like_json helper
# ---------------------------------------------------------------------------


class TestLooksLikeJson:
    @pytest.mark.parametrize(
        "text",
        [
            '{"key": "val"}',
            "[1, 2, 3]",
            '   {"a": 1}',
            "{not valid json at all}",  # heuristic: opening brace is enough
        ],
    )
    def test_returns_true(self, text):
        assert _looks_like_json(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Hello world",
            "",
            "   ",
            "42",
            '"hello"',
        ],
    )
    def test_returns_false(self, text):
        assert not _looks_like_json(text)


# ---------------------------------------------------------------------------
# scrub_text – plain text
# ---------------------------------------------------------------------------


class TestScrubText:
    @pytest.mark.parametrize(
        "text, pii",
        [
            ("Contact john.doe@example.com for help.", "john.doe@example.com"),
            ("Call +1-800-555-0199 for support.", "+1-800-555-0199"),
            ("Card number: 4111 1111 1111 1111", "4111 1111 1111 1111"),
            # 123-45-6789 is in Presidio's deny-list; use a real-looking fictional SSN.
            ("SSN: 234-56-7891", "234-56-7891"),
        ],
    )
    def test_pii_redacted(self, s, text, pii):
        assert pii not in s.scrub_text(text)

    @pytest.mark.parametrize(
        "text",
        [
            "john@example.com is my address.",  # PII at start
            "My email address is john@example.com",  # PII at end
            "Email john@example.com – again: john@example.com",  # PII repeated
        ],
    )
    def test_email_redacted_regardless_of_position(self, s, text):
        assert "john@example.com" not in s.scrub_text(text)

    @pytest.mark.parametrize("text", ["", "   "])
    def test_empty_or_whitespace_returned_unchanged(self, s, text):
        assert s.scrub_text(text) == text

    def test_multiple_pii_in_sentence(self, s):
        result = s.scrub_text("Email john@acme.io or call 212-555-0100.")
        assert "john@acme.io" not in result
        assert "212-555-0100" not in result

    def test_two_different_emails_both_redacted(self, s):
        result = s.scrub_text("alice@acme.io and bob@acme.io are colleagues.")
        assert "alice@acme.io" not in result
        assert "bob@acme.io" not in result

    def test_clean_text_no_pii_unchanged(self, s):
        clean = "The server returned status 200 OK with no issues."
        assert s.scrub_text(clean) == clean

    def test_non_ascii_surroundings_preserved(self, s):
        result = s.scrub_text("Контакт: alice@acme.io — звоните!")
        assert "alice@acme.io" not in result
        assert "Контакт" in result  # non-PII context survives


# ---------------------------------------------------------------------------
# scrub_json – structured JSON
# ---------------------------------------------------------------------------


class TestScrubJson:
    @pytest.mark.parametrize(
        "text, pii",
        [
            ({"payment": "Card: 4111 1111 1111 1111"}, "4111 1111 1111 1111"),
            ({"user": {"contact": "reach me at bob@example.org"}}, "bob@example.org"),
            ({"a": {"b": {"c": {"email": "deep@example.com"}}}}, "deep@example.com"),
        ],
    )
    def test_pii_redacted_in_dict(self, s, text, pii):
        result = s.scrub_json(text)
        assert pii not in json.dumps(result)

    @pytest.mark.parametrize(
        "data",
        [
            {"status": "ok", "count": 42, "message": "No PII here."},
            {"count": 0, "ratio": 0.5, "flag": False, "note": None},
        ],
    )
    def test_no_pii_data_unchanged(self, s, data):
        assert s.scrub_json(data) == data

    @pytest.mark.parametrize("empty", [{}, []])
    def test_empty_container_returned_unchanged(self, s, empty):
        assert s.scrub_json(empty) == empty

    def test_flat_dict_non_string_fields_preserved(self, s):
        data = {"name": "Alice", "email": "alice@example.com", "age": 30}
        result = s.scrub_json(data)
        assert result["email"] != "alice@example.com"
        assert result["age"] == 30

    def test_list_of_records(self, s):
        data = [
            {"id": 1, "email": "xtest@example.com"},
            {"id": 2, "email": "atest@sample.org"},
        ]
        result = s.scrub_json(data)
        assert "xtest@example.com" not in result[0]["email"]
        assert "atest@sample.org" not in result[1]["email"]
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    def test_list_of_dicts_preserves_non_string_fields(self, s):
        data = [{"id": 7, "email": "g@example.com"}, {"id": 8, "score": 9.5}]
        result = s.scrub_json(data)
        assert result[0]["id"] == 7
        assert result[1]["score"] == 9.5

    def test_none_value_preserved(self, s):
        result = s.scrub_json({"email": None, "name": "Alice"})
        assert result["email"] is None

    def test_boolean_values_preserved(self, s):
        data = {"active": True, "verified": False, "email": "x@y.com"}
        result = s.scrub_json(data)
        assert result["active"] is True
        assert result["verified"] is False

    def test_list_of_plain_strings_bypasses_scrubbing(self, s):
        # Strings that are direct list items (not inside a dict) are NOT
        # currently walked by scrub_json – this test documents that behaviour.
        data = ["nopii@example.com"]
        result = s.scrub_json(data)
        assert result == ["nopii@example.com"]


# ---------------------------------------------------------------------------
# scrub_bytes – end-to-end bytes interface
# ---------------------------------------------------------------------------


class TestScrubBytes:
    @pytest.mark.parametrize(
        "body, content_type, pii",
        [
            (
                b"Email me at charlie@test.com please.",
                "text/plain",
                b"charlie@test.com",
            ),
            (b"Call 212-555-0100 now.", "text/plain; charset=utf-8", b"212-555-0100"),
        ],
    )
    def test_plain_text_pii_redacted(self, s, body, content_type, pii):
        assert pii not in s.scrub_bytes(body, content_type=content_type)

    @pytest.mark.parametrize(
        "content_type",
        [
            "application/json",
            "application/json; charset=utf-8",
        ],
    )
    def test_json_email_redacted_for_content_type(self, s, content_type):
        payload = json.dumps({"email": "g@example.com"}).encode()
        result = s.scrub_bytes(payload, content_type=content_type)
        assert "g@example.com" not in json.loads(result)["email"]

    @pytest.mark.parametrize(
        "body, content_type",
        [
            (b"The server returned status 200 and all checks passed.", "text/plain"),
            (b"42", "application/json"),  # top-level scalar – not a dict/list
        ],
    )
    def test_non_pii_body_returned_unchanged(self, s, body, content_type):
        assert s.scrub_bytes(body, content_type=content_type) == body

    def test_json_body_email(self, s):
        payload = json.dumps({"user": "dave@corp.com"}).encode()
        result = s.scrub_bytes(payload, content_type="application/json")
        assert "dave@corp.com" not in json.loads(result)["user"]

    def test_json_array_body(self, s):
        payload = json.dumps([{"email": "frank@example.net"}]).encode()
        result = s.scrub_bytes(payload, content_type="application/json")
        assert "frank@example.net" not in json.loads(result)[0]["email"]

    def test_auto_detect_json_without_content_type(self, s):
        """Body starting with '{' must be detected as JSON even without explicit header."""
        payload = json.dumps({"email": "eve@example.net"}).encode()
        result = s.scrub_bytes(payload, content_type="")
        assert "eve@example.net" not in json.loads(result)["email"]

    def test_binary_body_returned_unchanged(self, s):
        body = bytes(range(256))  # valid bytes but not UTF-8
        assert s.scrub_bytes(body, content_type="application/octet-stream") == body

    def test_empty_body_returns_empty(self, s):
        assert s.scrub_bytes(b"", content_type="text/plain") == b""

    def test_invalid_json_falls_through_to_text_scrubbing(self, s):
        # Truncated JSON – should fail to parse and be scrubbed as plain text.
        body = b'{"email": "h@example.com"'  # missing closing brace
        assert b"h@example.com" not in s.scrub_bytes(
            body, content_type="application/json"
        )

    def test_looks_like_json_but_invalid_falls_to_text(self, s):
        # _looks_like_json returns True for '{...}' but json.loads will raise,
        # so it falls through to plain-text scrubbing.
        body = b"{ definitely not json: email@example.com }"
        assert b"email@example.com" not in s.scrub_bytes(body, content_type="")

    def test_json_preserves_encoding_round_trip(self, s):
        payload = {"status": "ok", "code": 200, "flag": True, "note": None}
        result = json.loads(
            s.scrub_bytes(json.dumps(payload).encode(), content_type="application/json")
        )
        assert result == payload
