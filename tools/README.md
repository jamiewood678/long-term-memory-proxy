# tools — legacy debug scripts

`logging_proxy.py`, `replay.py`, and `rewrite.py` are single-file scripts
that predate the `numen_proxy` package (`src/numen_proxy/`, see the repo root
[README.md](../README.md) and
[src/numen_proxy/docs/ARCHITECTURE.md](../src/numen_proxy/docs/ARCHITECTURE.md)).
They're kept as-is for ad-hoc investigation and are slated for retirement
once the package reaches parity with them
(`src/numen_proxy/docs/IMPLEMENTATION_STEPS.md`, step G2).

They depend on the same runtime deps (`fastapi`, `uvicorn`, `httpx`) declared
in the repo root `pyproject.toml`, so run them via `uv run` from the repo
root — `uv sync` there first if you haven't (see the root README's
[Setup](../README.md#setup)):

```
uv run python tools/logging_proxy.py
```

## Quick reference

```
logging_proxy.py                 capture only, forward untouched
logging_proxy.py --reorder       also move volatile scene state to the prompt tail
```

| Flag | Default |
|------|---------|
| `--listen-host` / `--listen-port` | `127.0.0.1` / `8081` |
| `--upstream` | `http://127.0.0.1:8080` |
| `--capture-dir` | `tools/captures` |
| `--reorder` | off |

## logging_proxy.py

Sits between Numen and llama-server, records every request verbatim, and
forwards it untouched. Use it to find out what Numen's prompt actually looks
like before building anything that rewrites it.

### Run

Start llama-server as normal on port 8080, then, from the repo root (after
`uv sync` — see the root [README.md](../README.md)):

```
uv run python tools/logging_proxy.py
```

Point Numen at the proxy — in `Data\NVSE\Plugins\Numen\Agent.ini`, change the
endpoint from `http://127.0.0.1:8080` to `http://127.0.0.1:8081`. Play as
normal; nothing else changes.

If llama-server is on a different port, pass `--upstream http://127.0.0.1:PORT`.

### Output

Per request, in `tools/captures/`:

| File | Contents |
|------|----------|
| `*-prompt.txt` | The prompt flattened into something readable — start here |
| `*-request.json` | Pretty-printed request body |
| `*-request.raw` | Byte-exact request body |
| `*-response.raw` | Raw response, including SSE frames when streaming |

Requests with an empty body (health polls) are forwarded but not captured.

The console prints a live summary per request, including llama-server's
`timings` block:

```
>> POST /v1/chat/completions  (7393 bytes)  -> 20260808-231951-0001
   shape=messages n=2 chars=7264 (~1816 tokens)
   stream=true
<< 421 bytes in 0.04s
   timings: prompt 13012 tok in 9.80s (1328 tok/s)  |  gen 180 tok in 7.20s (25.0 tok/s)
```

### What to look for

- **Prompt shape** — a `messages` array or a single `prompt` string, and which
  role carries the memory block.
- **Section boundaries** — where `[Journal]`, `[Personas]`, `[Recent Events]`
  etc. sit relative to the backstory and the player's line. This determines
  where a rewrite can inject without invalidating llama-server's KV cache.
- **Prefix stability** — diff consecutive `*-prompt.txt` files from one
  conversation. However much of the head stays byte-identical is what
  llama-server can reuse today.
- **`prompt_n` vs `predicted_n` timings** — how much of the wait is context
  processing versus generation.

## rewrite.py — `--reorder`

Numen places volatile scene state partway through the system prompt:

```
[Scene]          Timestamp = D8 04:03, Time of day, Current location
[Player]         Sex, Name, Wearing
[Actors nearby]  Moira Brown = ahead, ..., 1m
```

All of it changes as time passes and the player moves — the actor distances
change on practically every request. llama-server can only reuse an unchanged
*prefix*, so these ~95 tokens invalidate everything after them. On a real
captured prompt that is glossary, personality, locations, personas, threads,
journal and the entire recent-events log: **~3700 tokens reprocessed every turn
for nothing.**

`--reorder` moves those three sections to the end of the system message. Same
information, same content, but the invalidation point moves from 52% of the way
through the prompt to 99%:

```
volatile block moved 4086 -> 7799 tokens (~3713 fewer tokens reprocessed per turn)
```

When it fires, the forwarded body is also written to `*-request.rewritten.json`
so you can diff it against what Numen actually sent.

### Safety

- If any of the three sections is missing (a Numen update renaming things), the
  request is forwarded **unmodified** and the reason is printed.
- Any unexpected error falls back to forwarding the original body.
- The rewrite is lossless and idempotent: same lines, same count, just reordered.

### Verifying it works

Compare `cache_n` in the response timings with the flag off versus on. Off, it
should sit near zero. On, it should jump to roughly the token offset of the
volatile block once a conversation is past its first turn.

### Known limitation

When Numen trims the head of `[Recent Events]`, the prefix shifts and that turn
pays a full reprocess regardless. How often that happens is worth watching in
the captures.
