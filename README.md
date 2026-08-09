# numen-long-term-memory

A transparent proxy between **Numen** (an AI NPC mod for Fallout: New Vegas)
and **llama-server**, on an OpenAI-compatible endpoint. The goal is to raise
the ceiling on how much an NPC can remember — see [CLAUDE.md](CLAUDE.md) for
the full project brief, and [docs/plan.md](docs/plan.md) and
[docs/findings.md](docs/findings.md) for the phased plan and measured
findings behind it.

The `numen_proxy` package (`src/numen_proxy/`) is the hardened proxy under
active development — see
[src/numen_proxy/docs/ARCHITECTURE.md](src/numen_proxy/docs/ARCHITECTURE.md)
for its design and
[src/numen_proxy/docs/IMPLEMENTATION_STEPS.md](src/numen_proxy/docs/IMPLEMENTATION_STEPS.md)
for the build checklist. [tools/](tools/README.md) holds legacy, single-file
debug scripts that predate the package and are kept for ad-hoc investigation.

## Setup

Dependencies and the virtual environment are managed by
[uv](https://docs.astral.sh/uv/). Run this once (and again whenever
`pyproject.toml` changes), from the repo root:

```
uv sync
```

That creates `.venv` and installs both runtime deps (fastapi, uvicorn, httpx)
and dev deps (ruff, basedpyright, pytest, pytest-cov, pre-commit).

## Tooling

| Command | What it does |
|---|---|
| `uv run ruff check .` | Lint (add `--fix` to auto-fix) |
| `uv run ruff format .` | Format |
| `uv run basedpyright` | Static type-check `src/` and `tests/` |
| `uv run pytest --cov` | Run all tests with a coverage report |

Config for all four lives in `pyproject.toml` — no separate ini files.

Git pre-commit hooks (installed via `uv run pre-commit install`) run
`ruff check`, `ruff format`, and `basedpyright` automatically on
`src/**/*.py` and `tests/**/*.py` before every commit.

## Tests

Tests live in `tests/`, split into three tiers by `pytest.mark`:

- **`unit`** — isolated functions/classes, no I/O
- **`integration`** — the FastAPI app in-process (`TestClient`), collaborators
  swapped via `app.dependency_overrides`
- **`e2e`** — the real ASGI app on a real socket, hit with real HTTP — this is
  the tier that stands in for a browser E2E tool, since there's no browser here

Run one tier at a time with `uv run pytest -m unit` (or `integration` / `e2e`).

### Example: swappable implementations without a DI container

`src/numen_proxy/upstream.py` defines an `Upstream` as a `typing.Protocol`
(structural typing — no `implements` needed) with one real implementation and
one test double. `src/numen_proxy/app.py` picks the concrete implementation in
exactly one place (`get_upstream`), and tests swap it out via
`app.dependency_overrides[get_upstream] = ...`. That's FastAPI's built-in DI —
no separate container library required. See `tests/integration/test_app.py`
for the swap in action.
