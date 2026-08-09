# numen_proxy Phase 1 — implementation steps

A build checklist for `src/numen_proxy/`, companion to `ARCHITECTURE.md`
(the design/why) and `../.claude/plans/i-want-to-start-ticklish-panda.md` (the
planning conversation this came from). This file is the *order and process*;
`ARCHITECTURE.md` is the *design* — read a step's linked section there before
building it if the reasoning isn't already clear.

## How to work through this

- **One step at a time.** Each step below is sized to be one sitting: a
  single class, a single method, or a small tightly-related group (e.g. "the
  four config models"). Not a whole package in one go.
- **Explain before moving on.** For each step: write the code, then walk
  through what it does and why it's shaped that way — the "concepts" line
  under each step is what should get covered, not just "it works." The goal
  is that the code is something you could maintain solo afterward, not just
  something that passes review.
- **Test alongside, not after.** Each step lists the test file that proves
  it. Write the test as part of the same step, not as cleanup later —
  several of these classes (fail-open wrappers, rotation logic) are easy to
  believe work and wrong in a way only a test catches.
- **Check off as you go.** `- [ ]` → `- [x]`. This file is meant to survive
  across sessions — if you stop partway through a step, leave a note under
  it about where you got to.
- **Dependency order matters.** Steps are ordered so nothing depends on
  something built later. If a step seems to need something from further
  down the list, that's worth stopping on — either the order's wrong or the
  step's doing too much.

---

## Phase A — foundations (no behavior yet)

*Why first: everything else imports these. Getting the shape right here
means nothing downstream needs revisiting.*

- [ ] **A1. `chains.py` — the `Chain` enum.**
  `StrEnum`: `DIALOG`, `BARK`, `MEMORY`, `UNKNOWN`. That's the whole file.
  Concepts to cover: why `StrEnum` over a plain `Enum` (serializes cleanly
  into the JSONL log and TOML config without a custom encoder), why
  `UNKNOWN` exists at all (see ARCHITECTURE.md "Data model").
  No test file needed — nothing to assert on an enum definition.

- [ ] **A2. `config.py` — the four config models.**
  `ChainConfig`, `CaptureConfig`, `LogConfig`, `ProxyConfig` as plain
  pydantic `BaseModel`s, no methods yet, no file loading. Concepts: how
  pydantic field defaults work, how a nested model (`ProxyConfig.chains:
  dict[Chain, ChainConfig]`) gets validated recursively, why this file
  never imports `BoundedFileCapture`/`ReorderRewriter`/etc. (schema vs.
  choice — ARCHITECTURE.md "Composition root / factory").
  Test: `tests/unit/test_config.py` — construct each model directly with
  valid data, confirm defaults apply when fields are omitted.

- [ ] **A3. `config.py` — `load_config(path) -> ProxyConfig`.**
  `tomllib.load` + `ProxyConfig.model_validate`. Concepts: why this fails
  loud (`ValidationError` at startup) instead of fail-open like everything
  else in the proxy — this is the one place "safe to leave running" means
  "safe to refuse to start."
  Test: extend `test_config.py` — a real TOML fixture parses correctly; a
  broken one (bad type, unknown `representations` value) raises with a
  clear field name in the error.

## Phase B — the upstream seam

*Why second: it's the riskiest interface change (byte-level, not the toy
`ChatRequest`/`ChatResponse` shape already in the skeleton) and has no
dependency on rewrite/capture/logging, so it's worth isolating and getting
right before anything else builds on it.*

- [ ] **B1. `upstream.py` — `UpstreamResponse` Protocol.**
  `status_code`, `headers`, `aiter_bytes()`. Concepts: why this exists at
  all instead of using `httpx.Response` directly everywhere (Adapter
  pattern — decouples `ProxyService` and its tests from httpx's concrete
  type).

- [ ] **B2. `upstream.py` — `Upstream` Protocol, byte-level.**
  `forward(method, path, headers, body: bytes) -> UpstreamResponse`.
  Concepts: why bytes in/out instead of the current `ChatRequest`/
  `ChatResponse` pydantic models — the losslessness argument
  (ARCHITECTURE.md "Package layout", the `models.py` paragraph).

- [ ] **B3. `upstream.py` — `HttpxUpstream`.**
  Real implementation: holds a shared `httpx.AsyncClient`, `forward()` calls
  `client.send(req, stream=True)`. Concepts: why `stream=True` even though
  Numen sends `stream: false` today (keeps the SSE path possible without a
  later rewrite), what `connect_timeout_s` protects against vs. why there's
  deliberately no read timeout.

- [ ] **B4. `upstream.py` — adapt `EchoUpstream`.**
  Update the existing test double to the new `Upstream` shape. Concepts:
  this is the moment the existing skeleton's `ChatRequest`/`ChatResponse`
  path either gets adapted or explicitly kept separate for the demo route —
  decide which here and note it in the code.

- [ ] **B5. Tests — `tests/unit/test_httpx_upstream.py`.**
  Use `httpx.MockTransport` (no real network) for three cases: normal
  response passes through status/headers/body unchanged; `ConnectError`;
  `ConnectTimeout`/`ReadTimeout`. Concepts: why `MockTransport` instead of
  spinning up a real fake server for a unit test — this is the
  unit/integration boundary this project's test tiers already draw.

## Phase C — rewrite

*Why third: depends only on Chain (Phase A). `npc.py` is grouped in here
since it's a similarly-shaped small fail-safe parser.*

- [ ] **C1. `rewrite/protocol.py` — `Rewriter` Protocol + `RewriteResult`.**
  `apply(chain, body: bytes) -> RewriteResult`; `RewriteResult(body, applied,
  note)`. Concepts: why `RewriteResult` carries `applied`/`note` rather than
  just returning bytes — this is what feeds `rewrite_applied`/`rewrite_note`
  in the JSONL log later.

- [ ] **C2. `rewrite/noop.py` — `NoopRewriter`.**
  Simplest possible implementation — build this before the real one to
  prove the Protocol shape end-to-end with something trivial. Concepts: why
  Memory's no-op is a real class, not just "skip calling rewrite" —
  ARCHITECTURE.md's point about making it explicit rather than incidental.

- [ ] **C3. `rewrite/reorder.py` — port `split_sections`/`SECTION_RE`.**
  Pure parsing, no rewriting logic yet — just get section-splitting working
  and tested in isolation. Concepts: the `^\[([A-Z][A-Za-z ]*)\]` regex,
  why this is kept as a standalone reusable function rather than inlined
  into `ReorderRewriter` (Phase 5 forward-compat note in ARCHITECTURE.md
  depends on this being reusable).

- [ ] **C4. `rewrite/reorder.py` — `ReorderRewriter.apply()`.**
  The actual volatile-section-to-tail logic, wrapped to return
  `RewriteResult`. Concepts: the fail-safe behavior — what happens when a
  volatile section is missing, and why that's "forward original, note why"
  rather than raising.

- [ ] **C5. `rewrite/__init__.py` — `build_rewriter(name) -> Rewriter`.**
  The factory, currently just `{"reorder": ReorderRewriter, "noop":
  NoopRewriter}[name]()`. Concepts: this is the extension point discussed
  at length in ARCHITECTURE.md's "Extending per-chain behavior" — worth
  actually pointing at that section here.

- [ ] **C6. Tests — `tests/unit/test_noop.py`, `test_reorder.py`.**
  `NoopRewriter` never changes input. `ReorderRewriter`: lossless (identical
  line multiset), idempotent (`apply(apply(x)) == apply(x)`), fail-safe on
  a missing volatile section. These three properties are the ones CLAUDE.md
  requires of every rewrite — worth writing them as named test cases, not
  folded into one big assertion.

- [ ] **C7. `npc.py` — `extract_npc(body: bytes) -> str | None`.**
  Regex over `[Your character]`, returns `None` on anything unexpected.
  Concepts: fail-safe-by-returning-`None` vs. fail-open-by-catching-
  exceptions — this function shouldn't need a try/except if the regex
  itself can't raise, worth discussing which failure mode actually applies
  here.
  Test: `tests/unit/test_npc.py` — happy path, missing section, malformed
  section.

## Phase D — capture and logging

*Why fourth: depends only on Phase A's config models. Independent of
rewrite/upstream, so could technically swap order with Phase C — kept after
it here only because the fail-open wrapper (Phase E) is easier to explain
once you've seen it show up in both rewrite and capture.*

- [ ] **D1. `capture/protocol.py` — `CaptureSink` Protocol.**
  `write_request(stem, body)`, `write_response(stem, body)`.

- [ ] **D2. `capture/null_capture.py` — `NullCapture`.**
  No-op, same "build the trivial one first" reasoning as `NoopRewriter`.

- [ ] **D3. `capture/file_capture.py` — `BoundedFileCapture`, writing only.**
  Constructor takes `dir`/`representations`; `write_request`/`write_response`
  check `representations` membership and write files. No rotation yet.
  Concepts: the stem-naming scheme (timestamp + counter), why
  `representations` is checked per-call rather than baked into which method
  exists.

- [ ] **D4. `capture/file_capture.py` — add rotation.**
  Enforce `max_bytes_total`/`max_files`, evicting oldest first. Concepts:
  why this is bounds + rotation rather than content-hash dedup (that's
  Phase 3's job, ARCHITECTURE.md "Capture & persistence") — this step is
  purely "don't grow forever," not "don't store duplicates."

- [ ] **D5. `capture/__init__.py` — `build_capture_sink(chain_config,
  capture_config) -> CaptureSink`.**
  Reads `raw_capture` to pick `NullCapture` vs `BoundedFileCapture`.
  Concepts: this is "Level 1" of the two-level decision in
  ARCHITECTURE.md's "Where the choice gets made" — worth re-reading that
  section here since it took a few passes to land on in the planning
  conversation.

- [ ] **D6. Tests — `tests/unit/test_file_capture.py`.**
  Writes the right files for a given `representations` set; rotation
  actually evicts the oldest file once the cap is exceeded (this is the one
  most worth testing carefully — an off-by-one here silently keeps growing
  disk usage forever).

- [ ] **D7. `logging_/schema.py` — `RequestLogEntry`.**
  Plain pydantic model, matches the fields in ARCHITECTURE.md's "Data
  model." No methods.

- [ ] **D8. `logging_/jsonl_logger.py` — `StructuredLogger.append()`.**
  Opens the file in append mode, writes one JSON line, flushes. Concepts:
  why append-only + immediate flush (crash safety — a row either fully
  landed or didn't), why this has no "which chains" toggle unlike capture
  (ARCHITECTURE.md — metadata rows carry no duplication cost).

- [ ] **D9. Tests — `tests/unit/test_jsonl_logger.py`.**
  Appended rows are valid JSON, one per line, match the schema; appending
  twice doesn't overwrite the first row.

## Phase E — ProxyService (where it all meets)

*Why fifth: this is the orchestrator — it needs Upstream (B), Rewriter (C),
and CaptureSink+StructuredLogger (D) to exist first, since it composes all
four.*

- [ ] **E1. `proxy.py` — the fail-open wrapper.**
  One small function/decorator: try the risky call, on exception log a
  warning and return a fallback. Build and test this in isolation before
  wiring it into `ProxyService` — it's used three times (rewrite, both
  capture writes) and is worth trusting on its own first.
  Test: `tests/unit/test_proxy.py` (or wherever this lands) — wrapped
  function's exception is caught, fallback returned, warning logged.

- [ ] **E2. `proxy.py` — `ProxyService.__init__`.**
  Constructor takes `chain`, `upstream`, `rewriter`, `capture`, `logger` as
  plain arguments. Concepts: this is the DI seam in practice — no framework
  import here at all, which is what makes step E-tests possible without
  FastAPI.

- [ ] **E3. `proxy.py` — `handle()`, the happy path only.**
  Read body → `capture.write_request` → `rewriter.apply` →
  `upstream.forward` → stream response back. No error handling, no logging
  yet — get bytes flowing end-to-end with fakes first.
  Test: `tests/integration/test_proxy_service.py` — fake collaborators,
  assert the happy path calls each in the right order with the right
  arguments.

- [ ] **E4. `proxy.py` — response accumulation + `npc`/`timings` parsing.**
  The `finally`-block accumulation pattern from `logging_proxy.py`, plus
  `extract_npc`/timings parsing, both wrapped fail-open (parsing failure
  here must never affect what Numen already received). Concepts: why
  accumulation happens *before* the upstream connection closes — the
  cancellation-ordering comment carried over from `logging_proxy.py`.

- [ ] **E5. `proxy.py` — `write_response` + `logger.append` wired in.**
  Completes the happy path. Test: extend `test_proxy_service.py` — capture
  and log both fire exactly once per request with the expected
  `RequestLogEntry` fields.

- [ ] **E6. `proxy.py` — the upstream-failure branch.**
  Catch `ConnectError`/timeouts specifically (not the generic fail-open
  wrapper — this is the one intentionally-not-fail-open path). Map to
  502/504, log `outcome`+`error_detail`, no retry. Concepts: re-walk the
  "Upstream failure policy" reasoning in ARCHITECTURE.md — this is the one
  piece of the design that's a documented open tension with CLAUDE.md's
  literal wording, worth being deliberate about while writing it.
  Test: extend `test_proxy_service.py` — fake upstream raises each
  exception type, assert status code and logged outcome.

- [ ] **E7. Regression test — rewrite failure still forwards original body.**
  A fake `Rewriter` that raises; assert the request still reaches upstream
  unchanged and the response still comes back normally. This is the
  concrete proof of "fail-safe by default" for the rewrite path
  specifically, called out as its own test because it's the guarantee the
  whole fail-open wrapper exists for.

## Phase F — HTTP wiring

*Why sixth: everything below is "put ProxyService behind FastAPI, one app
per port." Nothing here should contain proxy logic — if it does, that logic
belongs in Phase E instead.*

- [ ] **F1. `app.py` — `create_app(chain, service) -> FastAPI`.**
  One catch-all route, delegates straight to `service.handle(request)`.
  Concepts: why there's no per-request chain detection here — the chain
  was decided when `service` was constructed, not now.
  Test: extend `tests/integration/test_app.py` — round-trip a body with
  unknown/extra JSON fields, assert byte-for-byte passthrough (this is the
  concrete losslessness regression test for the real path, not just
  `EchoUpstream`'s toy one).

- [ ] **F2. `server.py` — `MultiPortServer`.**
  For each `[chains.*]` entry: `build_rewriter`, `build_capture_sink`,
  construct `ProxyService`, `create_app`, wrap in a `uvicorn.Server`. Run
  all servers via `asyncio.gather`.
  Test: `tests/e2e/test_multiport_e2e.py` — bind N real free ports
  concurrently, one POST per port, confirm each lands on the right chain.

- [ ] **F3. `__main__.py`.**
  `load_config` → `MultiPortServer(config).run()`. Should be almost nothing
  — if it's growing logic, that logic belongs in `server.py`.

- [ ] **F4. Streaming test.**
  Extend `tests/e2e/test_e2e.py`: fake upstream serves SSE, assert the
  client receives it chunked rather than buffered. This is the "tested, not
  assumed" item from CLAUDE.md re: the SSE path.

## Phase G — golden corpus + retirement

*Last, because it depends on everything above existing and working.*

- [ ] **G1. Build the golden corpus.**
  Select a handful of real captures from `tools/captures/`, scrub anything
  identifying, commit under `tests/golden_corpus/`. This doesn't
  exist yet despite CLAUDE.md treating it as the core test asset — this is
  the step that actually creates it.
  Test: `tests/golden/test_golden_corpus.py`, new `golden` pytest marker in
  `pyproject.toml`. Runs `ReorderRewriter` over each real capture, asserts
  lossless/idempotent/structure-preserving.

- [ ] **G2. Retire the old scripts.**
  `tools/rewrite.py`'s logic should already be fully absorbed into
  `rewrite/reorder.py` by now (C3) — delete it via a tracked rename if it
  wasn't already. Retire `tools/logging_proxy.py` and `tools/replay.py` per
  D10, once a full play session has run clean against the new
  `numen_proxy` (see the Phase 1 exit criterion in `docs/plan.md`).

- [ ] **G3. Create `tools/echo_upstream.py`.**
  Thin script wrapping `create_app(Chain.DIALOG, ...)` with `EchoUpstream`,
  so the existing doc references to it (CLAUDE.md, `docs/plan.md`) become true.

---

## After this file

Once every box is checked, the Phase 1 exit criterion from `docs/plan.md`
applies: run a full play session with the proxy in the request path, zero
in-game failures, and confirm the JSONL log is queryable for real session
data — not just synthetic test fixtures.
