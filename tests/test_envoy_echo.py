import time
import requests
import pytest


@pytest.mark.parametrize("payload", ["Hello, Envoy and Nginx!", ""])
def test_envoy_echo(payload):
    url = "http://localhost:8080/"
    resp = post_with_retry(url, payload, timeout=10)
    assert resp.status_code == 200
    assert resp.text == payload
    # If Content-Length is present it should match payload length
    if "Content-Length" in resp.headers:
        assert int(resp.headers["Content-Length"]) == len(payload)
