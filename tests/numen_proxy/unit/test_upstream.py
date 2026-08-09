import pytest

from numen_proxy.models import ChatRequest, Message
from numen_proxy.upstream import EchoUpstream


@pytest.mark.unit
async def test_echo_upstream_echoes_last_user_message():
    upstream = EchoUpstream()
    request = ChatRequest(
        messages=[
            Message(role="system", content="be nice"),
            Message(role="user", content="hello"),
        ]
    )

    response = await upstream.complete(request)

    assert response.content == "echo: hello"
