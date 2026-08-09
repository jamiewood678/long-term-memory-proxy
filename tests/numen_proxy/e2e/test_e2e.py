import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn

from numen_proxy.app import app


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def running_server() -> Iterator[str]:
    """Runs the real ASGI app on a real socket, no mocking of the transport.

    This is the layer that stands in for Cypress/Playwright: there's no
    browser to drive, but the thing under test is the actual process
    boundary — real HTTP, real serialization, real routing.
    """
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    while not server.started:
        time.sleep(0.01)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.e2e
def test_chat_completions_over_real_http(running_server: str):
    response = httpx.post(
        f"{running_server}/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200
    assert response.json() == {"content": "echo: hello"}
