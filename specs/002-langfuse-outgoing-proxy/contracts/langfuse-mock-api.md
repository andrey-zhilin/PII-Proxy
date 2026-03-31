# Mock Langfuse Server API Contract

**Branch**: `002-langfuse-outgoing-proxy` | **Date**: 2026-03-23

Defines the HTTP API that the mock Langfuse server (`test-fixtures/mock-langfuse/`) must implement for the integration test suite. The mock implements the minimum subset of the Langfuse public API required by the Python SDK v2+.

---

## `POST /api/public/ingestion`

The primary batch ingestion endpoint used by the Langfuse Python SDK.

**Authentication**: Basic Auth — any credentials accepted; never rejected.

**Request**:

| Field | Type | Notes |
|-------|------|-------|
| `Content-Type` | `application/json` | Required by SDK |
| `Authorization` | `Basic <base64(pk:sk)>` | Any value accepted |
| Body | JSON object | Langfuse batch envelope (see below) |

**Request body (simplified Langfuse batch format)**:

```json
{
  "batch": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "type": "trace-create",
      "timestamp": "2026-03-23T10:00:00.000Z",
      "body": {
        "id": "trace-uuid",
        "name": "pii-test",
        "input": {"user_message": "..."},
        "output": null,
        "metadata": {}
      }
    }
  ]
}
```

**Response** (HTTP 207 Multi-Status):

```json
{
  "successes": [
    {"id": "550e8400-e29b-41d4-a716-446655440000", "status": 201}
  ],
  "errors": []
}
```

**Behavior**:

1. Parse request body as JSON.
2. Append the raw parsed body (dict) to the in-memory captured list.
3. Build a `successes` list: one entry per item in `batch` (using the item's `id`), all with `status: 201`.
4. Return HTTP 207.

**Error handling**: If request body is not valid JSON, return HTTP 400. Never return 500.

---

## `GET /captured`

Returns all request bodies captured since server start (or last `DELETE /captured`). Used by test assertions to verify PII scrubbing.

**Response** (HTTP 200):

```json
[
  {
    "batch": [
      {
        "id": "...",
        "type": "trace-create",
        "body": {
          "name": "pii-test",
          "input": {"user_message": "<PERSON> <EMAIL_ADDRESS>"},
          ...
        }
      }
    ]
  }
]
```

The response is a JSON array where each element is one previously received `/api/public/ingestion` request body.

---

## `DELETE /captured`

Clears the in-memory captured list. Used in test setup/teardown.

**Response** (HTTP 204, no body).

---

## `GET /health`

Liveness check for Kubernetes probes.

**Response** (HTTP 200): `{"status": "ok"}`

---

## Non-Goals

The mock server does NOT implement:

- Real Langfuse authentication (any credentials are accepted)
- Persistence (data lost on pod restart)  
- Score endpoints (`POST /api/public/scores`)
- Dataset endpoints
- Pagination on `/captured`
- HTTPS (the mock server runs plain HTTP; TLS is exercised on the PII proxy's inbound listener in the test setup)
