import pytest
from fastapi.testclient import TestClient

from numen_proxy.app import app, get_upstream
from numen_proxy.models import ChatRequest, ChatResponse


class StubUpstream:
    """A second Upstream implementation, used only in tests.

    Swapping it in below is the concrete proof that `Upstream` is a real
    seam: production code never needs to know this class exists.
    """

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(content="stubbed")


@pytest.mark.integration
def test_chat_completions_uses_injected_upstream():
    app.dependency_overrides[get_upstream] = lambda: StubUpstream()
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"content": "stubbed"}
