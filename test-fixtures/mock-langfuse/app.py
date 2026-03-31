"""Mock Langfuse server for integration testing.

Implements the minimum Langfuse batch ingestion API required by the Python SDK.
All captured request bodies are stored in-memory for test assertions.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock Langfuse Server")

# In-memory store of captured request bodies
_captured: list[dict[str, Any]] = []


@app.post("/api/public/ingestion")
async def ingestion(request: Request) -> JSONResponse:
    """Accept a Langfuse batch ingestion payload and store it for assertions."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    _captured.append(body)

    # Build successes list from batch items
    successes = []
    batch = body.get("batch", [])
    for item in batch:
        successes.append({"id": item.get("id", str(uuid.uuid4())), "status": 201})

    return JSONResponse(
        status_code=207,
        content={"successes": successes, "errors": []},
    )


@app.get("/captured")
async def get_captured() -> JSONResponse:
    """Return all captured request bodies for test assertions."""
    return JSONResponse(content=_captured)


@app.delete("/captured")
async def clear_captured() -> JSONResponse:
    """Clear the captured request list (test setup/teardown)."""
    _captured.clear()
    return JSONResponse(status_code=204, content=None)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check for Kubernetes probes."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
