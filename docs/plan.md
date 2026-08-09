# Implementation plan

Companion to [idea.md](idea.md) (what this is for) and
[findings.md](findings.md) (what has been measured).

---

## The shape of this plan

The investigation inverted the original priorities. The project was proposed as
a retrieval system; measurement showed retrieval targets **5.7%** of the prompt
while a prompt-ordering fix delivered a measured **10x** on repeat requests. So
this plan front-loads the cheap, proven work and puts retrieval behind an
explicit go/no-go gate.

Phases 0–2 are worth doing regardless of whether the memory project ever ships.
Phases 3–5 are the actual project, and Phase 0 decides whether they are
justified.

```
0  Close the gating questions        measurement only, no product code
1  Harden the proxy                  make it safe to leave running
2  Cache hygiene                     make the reorder actually pay
   ── GO / NO-GO ──
3  Archive                           capture what Numen is about to discard
4  Offline distillation              raw events -> retrievable memory
5  Retrieval                         surface memory Numen's own window can't reach
```

---

## Phase 0 — Close the gating questions

No product code. Instrumentation and measurement only. Everything downstream is
speculative until these are answered.

| # | Question | Method | Decides |
|---|---|---|---|
| 0.1 | ~~Why does a ~9100-token stable prefix still report `cache_n = 0`?~~ | Restart llama-server with `--swa-full`; replay identical captures; compare `cache_n`. Then `--cache-reuse 256`. | **Answered — fixed.** `--swa-full --cache-reuse 256` restores full reuse on a genuinely stable prefix, reproduced on the original flagged pair. Phase 2 has value. See findings.md §2. |
| 0.2 | ~~Does the prompt actually approach the context ceiling?~~ | Log `prompt_n` per request over a long play session; plot against in-game days | **Provisionally closed, 9 August — de-risked, not measured.** No long-save growth curve was run (can't be synthetically stress-tested — see findings.md §3, spammed events get skipped by the compression model). Closed instead by spec analysis: every major prompt section has a documented bound (`[Backstory]` capped at 8000 chars, `[Glossary]` a fixed 381 in-scope, `[Journal]`/catalogs render-windowed) except `[Personality]`, which grew slowly in the one NPC checked. Phases 3–5 proceed on this basis. One concrete residual risk not covered: `[Recent Events]` (30% of the prompt) could burst toward `lossy=200` — roughly double its observed steady state — if events outpace the 120s compression backoff during a chaotic session; worth a spot-check if that happens, not a blocker. See findings.md §7 Q2. |
| 0.3 | ~~Do barks evict the slot?~~ | Split barks onto their own port, count requests between dialog turns | **Answered — yes.** Captured a real Dialog→Bark→Dialog sequence; a controlled A/B (same pair, with/without the bark) reproduced eviction twice (`cache_n` 4913 → 0). Memory-chain requests didn't evict; barks do. `-np 1` is **not** safely bark-tolerant as-is — llama-server's context-checkpoint flags were tested directly as a fix and ruled out. See findings.md §2. |
| 0.4 | How much does `lossy=200` really discard? | Let one NPC run past 200 events with the proxy capturing | The archive's headline justification |

**Exit criterion:** 0.1 and 0.2 addressed. 0.3 and 0.4 can run in
background during Phase 1.

**Cost:** hours, not days. 0.1 is a server restart and a replay script.

> **Kill criterion — did not trigger, but on soft evidence.** 0.2 was closed
> by spec analysis rather than a measured long-save growth curve, so this
> isn't the hard data-driven check the plan originally called for. Phases
> 3–5 proceed on a de-risked assumption, with the `[Recent Events]` burst
> scenario above as the one flagged way this could still turn out wrong.

---

## Phase 1 — Harden the proxy

`tools/logging_proxy.py` is investigation-grade. **Decided, 9 August (D10):**
the hardened proxy is built as `src/numen_proxy/` — a proper package
with the SOLID/DI/test standards set up that day — rather than evolving
`logging_proxy.py` in place. `logging_proxy.py` keeps doing capture/
investigation duty until `numen_proxy` reaches feature parity with it, then
gets retired.

To leave the real proxy in the request path during normal play it needs to be
boring and unbreakable.

- **Never 5xx.** Any internal failure forwards the original bytes. A proxy error
  costs a 30 s agent cooldown in-game (`iAgentCooldownSeconds=30`).
- **Multi-port listener.** One process, one port per Numen chain
  (Dialog / Bark / Memory), all forwarding to 8080. Chain identity becomes
  structural instead of a body heuristic.
- **Bounded capture.** Rotation and a size cap; captures are currently unbounded
  and each dialog request is ~37 KB.
- **Structured request log.** One JSONL line per request:
  chain, NPC, `prompt_n`, `cache_n`, timings, rewrite applied, outcome. This is
  the dataset every later decision reads from.
- **Streaming verified.** Numen sends `stream: false` today, but the SSE path
  should be tested rather than assumed.
- **Config file** rather than a growing pile of CLI flags.
- **Fully Unit Tested** — ensure the rewrite works as intended, and that the proxy forwards bytes unchanged when it should.
- **Integration Tested** — ensure the proxy forwards bytes unchanged when it should.
- **SOLID and DI** — the proxy is a package, not a script, so that its components can be
  tested in isolation and swapped out for mocks.

**Exit criterion:** runs for a full play session with zero in-game failures, and
produces a queryable request log.

---

## Phase 2 — Cache hygiene

Only if 0.1 shows the prefix can be reused.

- Promote `--reorder` from opt-in flag to default behaviour.
- Make the Memory-chain no-op **explicit** rather than incidental — currently it
  only skips because those requests have no `system` message.
- Extend beyond the three volatile sections: `[Entrances nearby]` is also
  distance-bearing and volatile, and was missed in the first pass.
- Handle the known limitation: when Numen trims the head of `[Recent Events]`,
  the prefix shifts and the turn pays full reprocessing. Measure how often before
  deciding whether it is worth addressing.
- Regression guard: alert if median `cache_n` drops, which is how a Numen update
  changing the prompt format would announce itself.

**Exit criterion:** measured cache hit rate across a play session, before and
after, from the Phase 1 request log.

---

## Phase 3 — Archive

The safety net. Preserve what `lossy=200` destroys.

- **Watch memory files**, don't parse prompts.
  `{GameDir}\Numen\NPCContext\{Plugin}\{FormID:6}.txt` gives stable NPC identity
  and a `# last-summary:` compression watermark.
- **Content-hash every `[Recent Events]` line** into a per-NPC set. Not a
  timestamp cursor — save reloads move in-game time backwards.
- **Capture the Memory chain both ways.** The request holds the batch being
  distilled; the response holds what survived. The difference is exactly what
  Numen discarded, identified with certainty.
- **Append-only storage.** SQLite, WAL mode, out of the request path.
- Snapshot whole memory files on change so nothing depends on parsing being right.

**Exit criterion:** a week of play archived, and a demonstrated reconstruction of
events that Numen has since dropped.

---

## Phase 4 — Offline distillation

Runs with the game closed. Full VRAM, no latency budget, LLM permitted.

- Reuse Numen's own compression prompt (`numen/prompts/memory-prompt.md`) — it is
  tuned, and its delta format is already the storage schema.
- Without `trigger=100` / `batch=50` / `lossy=200` forcing its hand, this can be
  slower, more thorough, and repeatable.
- Build the retrieval index: entity keys, day ranges, tags from Numen's closed
  vocabulary, FTS5 over bodies.
- **Idempotent and re-runnable.** Distillation improves; the archive is the
  source of truth and must survive re-processing.

**Exit criterion:** an index over the archive that answers "what does this NPC
know about X" better than Numen's flat journal does.

---

## Phase 5 — Retrieval

**Re-justified, 9 August — no longer gated on 0.2.** Originally gated on 0.2
showing prompts approach the context ceiling; 0.2 found the opposite (prompts
run 8-9.5k against a ~20k budget, most sections already render-windowed).
The real justification is the recall gap confirmed in findings.md §3: Numen's
own compression drops real content (a full thread, in one examined pass) and
its render window makes anything old, non-pinned, and untagged invisible to
the model even though it still exists on disk. Phase 5 exists to surface that,
not to fit more tokens into a small prompt.

- **Select against `[Journal]` and the catalogs** (`[Locations]`/`[Personas]`/
  `[Threads]`) — this is where confirmed-durable-but-invisible material lives
  (idea.md "What Numen already does"). `[Glossary]`/`[Recent Events]` are
  large but already Numen-managed (fixed vocabulary / actively compressed);
  they're not where the recall gap is.
- **Augment, don't substitute** (D2) — add alongside what Numen renders,
  don't strip and replace it.
- **Pin per conversation.** Re-select on conversation start, location change, or
  clear topic shift. Never mid-conversation: it churns the prefix and gives the
  NPC selective amnesia between lines.
- Query from situational context — location, actors present, active threads —
  because what the player types is often contentless.
- Keyword and entity search first. Embeddings only after keyword search is shown
  to fail.
- Hard floor: identity sections (`[State]`, `[Trust Log]`, `[Personality]`,
  `[Personal goals]`, backstory) always go in whole.

**Exit criterion:** demonstrate the NPC correctly referencing a specific real
fact that was outside Numen's own render window — not pinned, not in the
Journal's latest-50, not tag-matched as relevant — something it provably
couldn't have done unaided. Archive-size-vs-context-window ratio was the old
criterion; it measured archive size, not whether recall actually improved.

---

## Decisions to be made

| # | Decision | Options | Resolved by | Needed by |
|---|---|---|---|---|
| D1 | Chain classification | Port per chain / body heuristics | — recommend **port per chain**; heuristics break silently on a Numen retune | Phase 1 |
| D2 | Substitute or augment | Strip Numen's memory and replace it / append alongside | **Flipped, 9 August — recommend augment.** Originally recommended substitution because "augmenting cannot reduce anything," under the assumption that token budget was the binding constraint. It isn't (findings.md §7 Q2 — prompts run 8-9.5k against a ~20k budget, most sections already render-windowed). Augmenting is now the safer default: it can only add recall Numen's own window wouldn't otherwise surface, and can't accidentally break Numen's existing working memory the way a bad substitution could. See idea.md "Select memory per situation." | Phase 5 |
| D3 | Touch the Memory chain? | Pass through untouched / rewrite it too | — recommend **untouched in v1**. It is Numen's core loop and the blast radius of getting it wrong is permanent memory corruption | Phase 1 |
| D4 | Write back to memory files? | Read-only / proxy also edits them | — recommend **read-only**. Numen owns those files and will clobber concurrent writes | Phase 3 |
| D5 | `-c 12000` vs `-c 20000` | Faster cold requests / more headroom | 0.1 and 0.3 both answered: cache hits are reliable on a genuinely stable prefix, but barks reliably evict them — so cold-request cost matters more in practice than the optimistic case assumed. Still open, now with data instead of a hypothesis | Phase 2 |
| D6 | Archive scope | Per-NPC files / one SQLite DB | Phase 3, once event volume is known | Phase 3 |
| D7 | Save-state coupling | Ignore / detect save reloads | Memory files are keyed by FormID, **not by save** — loading an old save does not roll memory back. Needs a decision on whether the archive should model this | Phase 3 |
| D8 | Distillation model | Same Gemma 12B / something larger offline | Phase 4, by output quality | Phase 4 |
| D9 | Re-selection triggers | Conversation start only / + location / + topic shift | Phase 5, by measuring how often each fires | Phase 5 |
| D10 | Where does the hardened proxy live? | `tools/logging_proxy.py` evolved in place / new `src/numen_proxy/` package | **Decided, 9 August — `src/numen_proxy/`.** Ruff/basedpyright/pytest tiers and a Protocol-based DI seam were set up against this package that day; building Phase 1 there gets the benefit of that investment instead of retrofitting it onto the loose script. `logging_proxy.py` retired once parity is reached | Phase 1 |

---

## Requirements still to gather

Things currently unknown that will change the design:

- **The real `Agent.ini`.** Not readable at
  `Data\NVSE\Plugins\Numen\` — MO2's virtual filesystem means it lives in the
  mod folder. Needed to know exactly how multi-agent URLs and chains are declared
  before D1 can be implemented.
- ~~**Bark request shape.**~~ **Resolved, 9 August.** Captured in isolation
  (capture `0002`, 01:36). Same `system`+`user`, 2-message shape as a fresh
  Dialog turn, but the `user` content is a distinct scene-reaction trigger
  ("You and the player just stepped back out into the open. Look back, not
  around...") rather than typed player dialogue — reliably distinguishable.
  Used to build the 0.3 eviction test in findings.md §2.
- **N2N request shape.** `bEnableNPCtoNPC=1` and `iNPCToNPCTurns=2`, so these
  exist and are multi-turn. Never captured.
- **Numen's failure behaviour.** What it does with a slow response near
  `iChainTimeoutSeconds=90`, a truncated body, or an unexpected field. Determines
  how defensive the proxy must be.
- **Version drift.** `Numen.log` reports v1.5.1.0; the documentation describes
  v1.6.0. Prompt format is unversioned and can change under us — hence the
  Phase 2 regression guard.
- **Whether `[Glossary]` content varies per NPC or is global.** It is 12% of the
  prompt and a Phase 5 target; if it is identical across NPCs it is also a
  cross-NPC cache opportunity.

---

## Test plan

### The golden corpus is the core asset

Real captured request bodies, checked in with save content scrubbed. Every
rewrite is tested by replaying these. Without it, "does this break Numen" can
only be answered by playing the game.

`tools/echo_upstream.py` already exists as the fake upstream and should be
promoted into the test suite.

### Layers

**1. Invariants (property tests).** For every capture in the corpus, every
rewrite must satisfy:

- lossless — identical line multiset before and after
- idempotent — `rewrite(rewrite(x)) == rewrite(x)`
- structure-preserving — same section set, same user message, same sampling params
- fail-safe — a missing or renamed section forwards the original body untouched

**2. Contract tests.** Chain classification returns the right answer for every
corpus body. Malformed JSON, empty body, unknown endpoint, non-completion route:
all forward untouched.

**3. Integration.** Proxy against the fake upstream. Assert forwarded bytes,
response passthrough fidelity, and header handling.

**4. Chaos.** Upstream down; upstream slower than 90 s; upstream returns 500;
client disconnects mid-stream. Every case must forward or fail *transparently* —
the current abort-logging bug is exactly this class and should have a regression
test.

**5. Cache-effectiveness regression.** Replay a captured conversation against a
real llama-server and assert median `cache_n` stays above a threshold. This is
the test that catches a Numen prompt-format change.

**6. In-game acceptance.** The only test for behaviour. A fixed script of
interactions with one NPC, run with the proxy transparent and with it active,
comparing replies for character consistency and continuity. Subjective, so it
gates releases rather than commits.

### What is deliberately not tested

LLM output quality. Distillation quality is judged by reading it (Phase 4), not
asserted. Pinning a non-deterministic model's prose in a test suite buys nothing.

---

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Numen update changes prompt format | Rewrites silently no-op or corrupt | Fail-safe by default; cache-hit regression alert; version pin in the request log |
| 0.1 finds the prefix is unusable | Phase 2 has no value | Phase 0 exists precisely to find this out cheaply |
| 0.2 finds prompts plateau | Phases 3–5 unjustified | Kill criterion, stated up front |
| Bad retrieval surfaces the wrong memory | Confuses the NPC, but doesn't erase working memory (D2: augment, not substitute) | Identity floor always sent whole; in-game acceptance testing; archive makes it recoverable |
| Proxy adds latency near the 90 s timeout | Requests fail, agent benched 30 s | Selection is per conversation, not per turn; hard internal deadline with passthrough fallback |
| Scope creep into rebuilding Numen's compression | Competing with something that works | Explicitly out of scope in idea.md; the Memory chain passes through untouched (D3) |

---

## Sequencing

Phase 0 is days. Phases 1–2 are the first real increment and are independently
useful. The GO/NO-GO gate sits after Phase 2, which is the point of the whole
structure: by then the cheap win is banked and the expensive half has evidence
behind it either way.
