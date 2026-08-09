from fastapi import Depends, FastAPI

from numen_proxy.models import ChatRequest, ChatResponse
from numen_proxy.upstream import EchoUpstream, Upstream

app = FastAPI(title="numen-proxy")


def get_upstream() -> Upstream:
    """The one place a concrete Upstream is chosen.

    Swap implementations by pointing this at a different class, or override
    it per-test with `app.dependency_overrides[get_upstream] = ...` — no
    container library required, FastAPI's Depends() already is one.
    """
    return EchoUpstream()


@app.post("/v1/chat/completions", response_model=ChatResponse)
async def chat_completions(
    request: ChatRequest, upstream: Upstream = Depends(get_upstream)
) -> ChatResponse:
    return await upstream.complete(request)
