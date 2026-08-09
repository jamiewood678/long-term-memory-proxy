from typing import Protocol

from numen_proxy.models import ChatRequest, ChatResponse


class Upstream(Protocol):
    """Anything that can complete a chat request.

    A Protocol is structural typing: a class satisfies this interface just by
    having a matching `complete` method, no explicit inheritance needed. This
    is what stands in for a Laravel interface/contract here.
    """

    async def complete(self, request: ChatRequest) -> ChatResponse: ...


class EchoUpstream:
    """Dev/test double: echoes the last user message back as the reply."""

    async def complete(self, request: ChatRequest) -> ChatResponse:
        last_user = next(
            (message.content for message in reversed(request.messages) if message.role == "user"),
            "",
        )
        return ChatResponse(content=f"echo: {last_user}")
