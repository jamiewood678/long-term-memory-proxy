# Findings

Measured facts from instrumenting Numen with a logging proxy, 8–9 August 2026.

This document records what was **measured**. [idea.md](idea.md) records what the
project is *for*; where the two disagree, this one wins.

---

## 1. What Numen actually sends

### Three request chains, not one

`Numen.log` resolves the agent config at startup and names the chains outright:

```
AgentConfig: loaded [Agent.LlamaCpp]        url=http://127.0.0.1:8081/... temp=1.00
AgentConfig: loaded [Agent.MemoryLlamaCpp]  url=http://127.0.0.1:8081/... temp=0.60
AgentConfig: Dialog chain (1): LlamaCpp
AgentConfig: Bark   chain (1): LlamaCpp
AgentConfig: Memory chain (1): MemoryLlamaCpp
```

So the proxy sees **three** kinds of traffic, not two:

| Chain | Trigger | Shape |
|---|---|---|
| **Dialog** | player talks to an NPC; also NPC-to-NPC | `system` + alternating `user`/`assistant` |
| **Bark** | unprompted comments — cell entry, quest done, trade, idle | same agent as Dialog |
| **Memory** | compression pass (see §3) | **one `user` message, no `system`** |

NPC-to-NPC is live in this config — `bEnableNPCtoNPC=1`, `iOnNPCHello=10`,
`iNPCToNPCTurns=2` — and idle barks fire on a 120 s interval
(`iIdleBarkInterval=120s`). Both land on the Dialog agent.

Observed discriminators in the captured bodies:

| | Dialog / Bark | Memory |
|---|---|---|
| roles | `system` + `user` (+ `assistant`…) | single `user` |
| `temperature` | 1.0 | 0.5 |
| `max_tokens` | 8192 | 16384 |

**But don't classify on those.** `Agent.MemoryLlamaCpp` is already a separate
config entry — point its `url` at a different port and the proxy can listen on
both, forwarding both to 8080. Routing becomes structural rather than a
heuristic that breaks the next time Numen retunes a temperature. Barks can be
split off the same way with a third agent entry.

Numen also tags every response it logs with the agent that produced it
(`--- [response openai [LlamaCpp]] ---`), so `Numen.log` can label captures
retroactively if needed.

### Timeouts the middleware must respect

```
iChainTimeoutSeconds=90, queryWatchdog=120000ms, iAgentCooldownSeconds=30
```

Anything the proxy adds has to fit inside 90 s, and a proxy error benches that
agent for 30 s.

### The dialog prompt

A `system` message (~31.6k chars) plus the conversation turns, with
`stream: false`.

The system message contains 22 sections delimited by `[Name]` headers. The
regex `^\[([A-Z][A-Za-z ]*)\]` matches all 22 and nothing else; the `[D8 04:03]`
and `[D1]` timestamps inside `[Recent Events]` and `[Journal]` are correctly
excluded.

### Where the tokens live

Measured on a real capture totalling ~8000 tokens:

| Group | ~tokens | % |
|---|---:|---:|
| Static instructions (Output, Caret commands, Voice, Your world, Who you are…) | 3367 | 42% |
| `[Recent Events]` | 2333 | 30% |
| `[Glossary]` | 919 | 12% |
| `[Backstory]` | 411 | 5% |
| `[Journal]` + `[Personas]` + `[Locations]` + `[Threads]` + `[Personality]` | 457 | **5.7%** |
| State, Trust Log, Team, Inventory, Scene, Player, Actors | 115 | 1.5% |

**This is the most important number in the document.** The sections the project
originally proposed to retrieve from are 5.7% of the prompt. Deleting all of
them entirely would save 5.7%. The prompt is dominated by fixed instruction
scaffolding and recent conversation.

If retrieval is ever built, the targets are `[Glossary]` and `[Recent Events]`.

---

## 2. The volatile block was destroying the prompt cache

`[Scene]`, `[Player]` and `[Actors nearby]` total ~95 tokens and sat at token
~4086 of ~7900 — 52% of the way through the prompt. They contain:

- an in-game clock (`Timestamp = D8 04:03`)
- current location and surroundings
- **actor distances in metres** (`Moira Brown = ahead, ..., 1m`)

Two consecutive captures were byte-identical except for a single timestamp line.
Because llama-server can only reuse an unchanged *prefix*, those ~95 tokens
invalidated ~3700 tokens of otherwise-identical content — glossary, personality,
locations, personas, threads, journal and the entire recent-events log — on
every request.

Actor distances change on practically every request, so this was near-constant.

### The fix

[`tools/rewrite.py`](../tools/rewrite.py) moves the three sections to the end of
the system message. Same content, same lines, invalidation point moves from 52%
to 99%:

```
volatile block moved 4086 -> 7799 tokens (~3713 fewer tokens reprocessed per turn)
```

Verified: round-trip lossless, identical line multiset, identical length,
idempotent, fail-safe when sections are missing, and confirmed end-to-end
through the proxy with the user message and all sampling params intact.

The rewrite is a no-op on Memory-chain requests because they carry no `system`
message and `rewrite_payload` finds nothing to move. That is currently luck
rather than design and should be made an explicit check.

### A second volatile section family, not covered by the reorder

Captures `0002`–`0008` (one play session, 8–9 August) all carry a section named
`[Entrances nearby]` sitting right after `[Backstory]`, before `[Glossary]` —
roughly 5000 tokens in, nowhere near the tail. Capture `0010`, ~3 minutes and
one player-movement later, carries `[Objects nearby]` in that exact slot
instead: different name, different content.

Numen apparently swaps in whichever "what's near the player" section applies
(`Entrances nearby`, `Objects nearby`, presumably others — doors, containers,
items) depending on context, in addition to the already-known `[Actors
nearby]`. `rewrite.py`'s `DEFAULT_VOLATILE = ("Scene", "Player", "Actors
nearby")` doesn't know about this family, so when it changes, the prefix breaks
~5000 tokens in regardless of whether `[Scene]`/`[Player]`/`[Actors nearby]`
have been successfully moved to the tail. This alone would produce `cache_n =
0` on the very next turn a player walks near a different kind of object —
independent of any llama-server cache setting.

### Resolved, 9 August: cache reuse works — two different pairs were conflated

Retested after restarting llama-server with `--swa-full --cache-reuse 256`,
using `tools/replay.py` to resend exact captured bodies straight to
llama-server (bypassing Numen and the proxy, to isolate the server's caching
behaviour from prompt-content drift during live play).

**`0007` sent twice, byte-identical:**

```
#1: cache_n=0     prompt_n=9518  prompt_ms=35806  (cold)
#2: cache_n=9517  prompt_n=1     prompt_ms=49      (byte-identical replay)
```

Full reuse — the mechanism itself works.

**The originally-flagged pair is fixed.** The whole question was based on
0003→0004→0005: a measured ~99% stable prefix (36419/36802 chars) that still
produced `cache_n=0` on the old server config. Replaying that exact pair under
the new flags:

| pair | common prefix (measured independently of the server) | `cache_n` |
|---|---|---:|
| 0003 → 0004 | 99.0% (36419/36802 chars) | **9080** (full reuse) |
| 0004 → 0005 | 99.0% (36419/36802 chars) | **9080** (full reuse) |

Both hit, reproducing the exact original prefix numbers. `--swa-full`/
`--cache-reuse 256` fixes the pair this question was actually about.

**0008→0010 is a different pair with a different, real cause — not the same
bug.** Its lower `cache_n` (4909/8316, ~59%) tracks its actual common prefix
of only 60.7% (20266/33367 chars), which lines up exactly with the
`[Entrances nearby]`/`[Objects nearby]` section swap above: real content
change, not a caching failure.

**0002→0003 also diverges for real (39.3%, 14446/36728 chars) — cause not yet
identified.** Both captures carry `[Entrances nearby]` in the same slot, so
it isn't the section-swap bug above. Noted as an open item below rather than
guessed at.

**Bonus finding: single shared cache slot.** `GET /slots` reports
`total_slots: 1` — Dialog, Bark, and Memory all forward to the same
llama-server port and share one KV-cache slot; there's no per-chain isolation
today. Despite that, replaying 0003 → **0009 (a Memory-chain request
sandwiched in between — single `user` message, no `system`, structurally
unrelated)** → 0004 still produced `cache_n=9080` for 0004: the intervening
Memory-chain request did not evict the cache in this test.

**Barks are a different story — confirmed eviction, with a clean control.**
Captured a real Dialog → Bark → Dialog sequence live via the running proxy
(new captures `0001`–`0003`, 01:35–01:37). The bark's `user` content ("You
and the player just stepped back out into the open. Look back, not
around...") is clearly distinct from typed player dialogue, confirming it's
a genuine bark, not another dialogue turn. `0001`→`0003` has a real 58.6%
common prefix (20282/34640 chars, measured independently of the server) —
the same order of overlap as 0008→0010 above.

| sequence | prefix overlap | disruptor | `cache_n` |
|---|---|---|---:|
| 0001 → 0003 | 58.6% | none | **4913** (proportional, matches overlap) |
| 0001 → 0002 (bark) → 0003 | 58.6% | Bark | **0** (reproduced twice) |

Same pair, same content — only variable is whether the bark ran in between.
Unlike the Memory-chain case, the bark **does** evict the reusable cache
content. This contradicts a plausible-sounding prediction made before
testing (that Bark, sharing more structural content with Dialog, should
evict *less* than Memory) — disproved by direct measurement, not confirmed
by it. One guess at the mechanism: near-total overlap (99%, the Memory case)
leaves enough long matching chunks (≥256 tokens, the `--cache-reuse`
threshold) to survive a disruptor, while moderate overlap (~58%, the Bark
case) doesn't — not verified against server internals, so held loosely.

**Tested as a fix: llama-server's context-checkpoint flags — ruled out.**
`--ctx-checkpoints`/`--checkpoint-min-step` are real flags on this build
(`llama-server.exe --help`, `build_info: b10098-0278d8362`) that looked
promising — per-slot checkpoints that could in principle let a displaced
conversation be recovered instead of reprocessed. Retested the exact
0001→0002(bark)→0003 sequence with `--ctx-checkpoints 32
--checkpoint-min-step 512` (well under the ~8-9k token dialog prompts, vs.
the 8192-token default, which is nearly a whole prompt — at the default,
a single dialog turn likely never produces more than one checkpoint) in two
configurations:

| config | `cache_n` for 0003 after the bark |
|---|---:|
| `--swa-full` + checkpoints | 0 |
| checkpoints, no `--swa-full` | 0 |

No effect either way. The mechanism that would actually work is
`--slot-save-path`, which exposes an explicit slot save/restore REST API —
but that requires the *proxy* to manage checkpoints itself (save after each
Dialog turn per NPC-conversation, restore before the next one if a
Bark/Memory pass may have run in between), not a server config flag. A real
option for later, but a build, not a flag; not attempted here.

Separate per-chain KV-cache slots (llama-server's `-np` + `id_slot`) were
also considered and **rejected for now**: `-c` divides across `-np` slots
rather than multiplying it, and dialog prompts already run 9195–9590 tokens
in the single slot available today. Splitting the budget risks a prompt not
fitting at all, undercutting question 0.2 before retrieval is even reached.

**Conclusion:** the reorder fix (§2 "The fix") has real, now-verified value on
a genuinely stable prefix — Phase 2 is justified. The remaining prefix-drift
sources (`[Entrances nearby]`/`[Objects nearby]` family confirmed above;
0002→0003's cause still unknown) are real content-change bugs for Phase 2 to
fix, not evidence against the caching mechanism.

---

## 3. How Numen's memory compression works

Captured directly: `20260809-001834-0006` is a Memory-chain request (29,176
chars, single `user` message, `max_tokens: 16384`, `temperature: 0.5`).

### The trigger

`Numen.log` prints the whole policy:

```
Memory config: trigger=100, batch=50, lossy=200, backoff=120000, journalLatestWindow=50
Timeline: init (persist=400, ephem=50)
```

| Setting | Meaning |
|---|---|
| `trigger=100` | a pass fires once `[Recent Events]` reaches 100 entries |
| `batch=50` | each pass distils the 50 oldest events |
| `lossy=200` | at 200 entries events are dropped **without** being distilled |
| `backoff=120000` | 120 s between attempts |
| `journalLatestWindow=50` | only the newest 50 journal entries are evictable |

The result is written into the memory file's first line:

```
# last-summary: D7 21:48 ok | passes 1 | events 105->54
```

By 9 August the same NPC's file showed a later state — `# last-summary: D8
09:18 ok | passes 1 | events 102->54` — confirming at least one further
compression cycle happened after the original observation. `passes` appears
to count consecutive batches within a single trigger invocation, not a
lifetime total, so this is evidence of "at least twice," not necessarily
"exactly twice."

**`lossy=200` is the justification for the archive.** It is the one place
Numen discards raw material with no summary written. Of 38 NPC memory files on
disk, exactly one has ever run a pass — the rest have not reached 100 events.

### It emits deltas, not a rewrite

The prompt hands the model the catalogs, the journal, and the batch of recent
events, then asks for a delta document:

```
[Locations] / [Personas] / [Threads]      Key = description   (new or refined)
[Journal append]   D<day> [tag] ... <one sentence, ~25 words>
[Journal edit]     - old body verbatim / + new body
[Journal evict]    echo the body to drop
[Catalog rename]   OldKey = NewKey
```

Numen applies them. Catalogs and journal are **append-only — keys are never
removed**. `[Personality]` and `[Personal goals]` are separate append-only
stores routed to by the `[Personality]` and `[Goal]` tags, and are *never*
evicted or edited. There is a closed tag vocabulary (`Remember`, `FirstMeeting`,
`Recap`, `Commitment`, `Threat`, `Gift`, `Romance`, `Sex`, `Death`, `Conflict`,
`Finding`, `Intel`, `Reflection`, `Personality`, `Goal`, `Unclassified`); the
three pin tags mark entries that can never be evicted.

The actual response to capture 0006 was five `[Journal append]` lines, one
location and one persona. Of the five, only three land in `[Journal]` itself
— the other two carry `[Personality]` and `[Goal]` tags, which the engine
strips and reroutes to the separate `[Personality]`/`[Personal goals]` stores
per the routing rule above. 51 events reduced to 7 delta lines total.

**This prompt is a tuned, working distillation spec.** Anything built offline
should reuse its output format rather than invent one.

### What actually reaches the prompt is windowed, not the full store — mostly

The persisted catalogs/journal are append-only (confirmed above), so the real
question for 0.2 is whether the *prompt* grows with them forever. It mostly
doesn't — `numen/prompts/dialog-prompt.md`'s own data-block spec documents
the caps:

- `[Journal]`: "three merged tiers: oldest pinned, relevance-picked, latest
  50" — same shape as `[Recent Events]`'s own compression, just implemented
  as a render window instead of distillation.
- `[Locations]`/`[Personas]`/`[Threads]`: "out-of-scope keys collapse to
  names" — only catalog keys relevant to the current scene render with a
  full description; the rest shrink to a cheap name-only mention.
- `[Personality]`: documented in the Dialog prompt only as "append-only,
  never evicted" — **no windowing noted for the Dialog render**, unlike
  Journal. The Memory-compression prompt separately says it works from "the
  latest 10 entries," but that's the compression pass's own working set, not
  necessarily what Dialog renders every turn. Still open.

So most of what looked like unbounded prompt growth in question 0.2 is
actually capped by design — Numen already solved this the same way it solved
`[Recent Events]`, just less visibly. `[Personality]` is the one section
without a documented cap on the Dialog side.

### A documented "never evicted" Personality entry is missing from the real file

Verified round-trip, not a guess: capture `0006`'s response (read directly
from `-response.raw`) added the `[Personality]`-tagged line *"You view the
deaths of commoners as a necessary cleansing of the land."* The current
on-disk file (`Numen\NPCContext\CFEE - TTW.esp\0719DB.txt`), captured well
after that response was applied, has four `[Personality]` entries — this is
not one of them (confirmed absent by direct grep). The compression prompt
spec is explicit that "`[Personality]` entries are NEVER evicted and NEVER
edited," so this contradicts documented behavior.

Two live possibilities, not distinguished yet: Numen's real implementation
caps or replaces `[Personality]` entries despite documenting otherwise, or
the entry was lost some other way (a similarly-themed entry — "The commoners
of Megaton are merely obstacles to be cleared for the Swarm's progression"
— is present, but the two are textually distinct, not an edit of one into
the other by any visible mechanism).

**This matters beyond 0.2.** §8's framing of `lossy=200` as "the one place
Numen discards raw material with no summary written" may be incomplete — if
already-distilled `[Personality]` memory can also silently disappear, that's
a second, undocumented loss path the archive (Phase 3) would need to guard
against, distinct from raw-event loss.

**Testing this is hard by design, not just inconvenient.** Scripting a flood
of filler events won't stress-test the render window or reproduce the
Personality-loss path — the compression model has to judge an event
meaningful enough to promote into `[Journal]`/`[Personality]`/a catalog key
in the first place, and spammed, contentless events are exactly what it's
instructed to skip ("do NOT log... skip entirely unless something meaningful
happened," per the compression prompt's own task rules). Confirming either
finding at scale needs a long, genuinely varied real play session, not
synthetic load.

### Compression loses real content well below `lossy=200` — a second, independent case

Captures `0016`/`0018` (9 August, 02:31 and 02:48 — byte-identical, a real
Numen retry of the same batch) are a complete Memory-chain request/response
pair for the AntAgonizer: a 46-line batch (`D7 21:46`→`D8 08:34`, well under
the 200-event `lossy` ceiling — this was an ordinary ~100-event trigger)
compressed via an actual LLM pass. The batch contains two distinct
significant threads: Moira Brown's subjugation (claimed as a servant,
ordered to strip, threatened with forced "ant" transformation), and a
separate six-exchange strategy discussion about gathering intel on the
Brotherhood/Citadel (`D8 03:38`–`06:08`). The response:

```
[Journal append]
D8 [Finding] Moira Brown has been designated as a drone of the hive.
D8 [Personality] You view the removal of a servant's possessions as a way to strip away their former life.
D8 [Finding] The plan to physically transform Moira into a "true ant" was discussed.
D8 [Goal] I will physically transform the scavenger to better suit the swarm's aesthetic.
```

captured the Moira thread but **completely dropped the Citadel thread** — no
Journal entry, no `[Threads]` update, nothing, despite the spec instructing
the model to promote "significant happenings." Not a budget problem (batch
was small, well inside `trigger=100`); a judgment-call miss by the
compression model, favoring emotionally vivid content over practical/
strategic content.

**The `[Personality]`-tagged line from this response is also missing from
the persisted file** — second independent case of this, not a one-off (see
above). The current file's `[Journal]` instead has a *different-worded*
entry covering similar ground — `[D8] [Reflection] Moira's resistance to the
lack of clothing is a mere lingering vestige of her former self` — under a
different tag ([Reflection], routes to Journal, not Personality), evidently
written by a later, uncaptured pass that re-covered the theme independently
rather than building on the original entry, which had already vanished.

**This changes the archive's justification, without answering 0.4 itself.**
0.4 ("how much does `lossy=200` really discard") is still open — this batch
never approached 200, so the hard-discard mechanism is untested. But §8's
framing — *"`lossy=200` is the one place Numen discards raw material with no
summary written"* — assumed that below 200, compression is lossless-in-
spirit. It isn't: a full conversational thread was dropped by an ordinary,
well-inside-budget compression pass, and distilled `[Personality]` content
is failing to persist at all. Real memory loss starts well before `lossy=200`
becomes relevant, through passes running exactly as designed.

---

## 4. Detecting what is new

Three sources, in increasing order of usefulness.

**Don't derive novelty from the prompt.** The canonical store is on disk at
`{GameDir}\Numen\NPCContext\{PluginName}\{FormID:6}.txt`. Watching those files
gives stable NPC identity (the FormID — the prompt only carries a display name),
a mtime signal, and the `# last-summary:` header announcing every compression
pass. It costs the request path nothing.

**For events, hash the lines.** Every `[Recent Events]` line is
`[D<day> HH:MM] <text>`. Keep a per-NPC set of line hashes; new means not in the
set. Hashing rather than a timestamp cursor matters because:

- compression removes from the **head**, never inserts into the middle, so the
  tail is append-only and diffs cleanly;
- several lines share one minute, so a `(day, time)` cursor is not a unique key;
- loading an earlier save moves in-game time **backwards**, which silently
  breaks a monotonic cursor but not a hash set.

Cost is trivial — the timeline holds 400 persistent events, so a few KB per NPC.

**Use the Memory request as the ground truth for loss.** It contains the exact
batch being distilled, and its response contains everything Numen chose to keep.
Diffing the two yields precisely what is about to be discarded. That is the
material worth archiving, identified with certainty rather than heuristics.

---

## 5. Hardware and inference performance

**GPU: AMD Radeon RX 6750 XT**, Vulkan backend, `matrix cores: none` (RDNA2).
Not NVIDIA — early analysis in this project wrongly assumed CUDA.

### Benchmarks (`llama-bench`, no game running)

| config | pp t/s | gen t/s |
|---|---:|---:|
| `-ngl 99` alone | 293 | 10.8 |
| `-ngl 99 -fa 1 -ctk q4_0 -ctv q4_0` | 498 | 43.7 |
| …at depth 4096 | 296 | 32.7 |
| …at depth 9216 | 219 | 31.4 |

Two conclusions:

- **Flash attention plus quantised KV is worth ~4x on generation.** These flags
  should stay. Note that `-ctk/-ctv q4_0` requires `-fa 1`; without it, context
  creation fails outright.
- **Context depth is expensive on its own.** Going from empty to ~9k tokens
  costs 55% of prompt-processing speed and 28% of generation speed, before any
  VRAM considerations.

### In-game progression

| stage | prompt tok | cache_n | gen t/s | total |
|---|---:|---:|---:|---:|
| original | 9195 | 0 | 8.5 | **68.3s** |
| after `-c 12000 -b 2048 -ub 512` | 9320 | 0 | 26.9 | **36.6s** |
| cache hit, same NPC | 312 | 9080 | 27.5 | **3.1s** |

Roughly 22x end to end. Generation tripled from the config change; the prompt
cache did the rest.

---

## 6. Corrections to earlier analysis

- **Assumed NVIDIA.** Advice about CUDA sysmem fallback policy and `nvidia-smi`
  was inapplicable. The card is AMD on Vulkan.
- **The VRAM-spilling mechanism is unconfirmed.** The *effect* is real and
  reproducible, but no shared memory use was observed at `-c 20000`, and three
  flags changed together. `-b`/`-ub` shrink a transient compute buffer and may
  account for the whole difference independently of `-c`.
- **A missing capture file was read as an aborted request** on thin evidence.
  The proxy now writes `-response.ABORTED.raw` so this is unambiguous.
- **"Multi-turn conversations do not exist" was wrong.** An earlier version of
  this document said each request is independent. Captures 0003/0004/0005 carry
  4, 6 and 8 messages: `system` plus alternating `user`/`assistant`. Numen keeps
  the conversation in the array and appends two messages per exchange. The
  system message is *rebuilt* each turn (same length, different bytes — the
  scene timestamp), which is why the volatile block matters even mid-conversation.
- **"We have no Memory-chain captures" was wrong** — `0006` is one, captured on
  8 August.
- **The project was initially framed as a latency problem.** It is a context
  ceiling problem; latency is a constraint, not the goal.
- **§7 question 1 was briefly marked "answered" with the wrong conclusion**
  ("the prefix was never actually stable"), by conflating two different
  capture pairs. The pair the question was actually about (0003→0004→0005)
  has a genuinely ~99% stable prefix and, under `--swa-full --cache-reuse
  256`, reuses it fully (`cache_n=9080` on both hops). The low-overlap pairs
  (0002→0003, 0008→0010) are real content divergences in *different*
  captures, not evidence that the flagged pair was unstable. See §2.

---

## 7. Open questions

1. ~~Why is a ~9100-token stable prefix producing `cache_n = 0`?~~ **Answered,
   9 August.** Fixed by `--swa-full --cache-reuse 256` — verified directly on
   the original pair (0003→0004→0005): `cache_n=9080` on both hops,
   reproducing the same ~99% prefix numbers as the original measurement.
   Survived one intervening Memory-chain request in testing (see §2 —
   `total_slots: 1`, so it wasn't guaranteed to). Phase 2 is justified.
   Two separate, real content-drift bugs remain as Phase 2 cleanup: the
   `[Entrances nearby]`/`[Objects nearby]` section-swap family (confirmed
   cause of the 0008→0010 gap), and an unidentified cause behind 0002→0003's
   divergence.
2. **Does the prompt actually approach the context limit over a long save?**
   **Provisionally closed, 9 August — de-risked, not fully answered.**
   Observed 8008 → 9195 → 9320 → 9434 → 9518 tokens, but over ~9 minutes with
   game reloads in between; never measured as a real growth curve over a long
   save, and no plan to run that measurement now. Closing it anyway because
   every major section of the prompt turns out to have a documented bound:
   `[Backstory]` is capped at 8000 chars, `[Glossary]` renders only in-scope
   entries out of a fixed 381, the volatile sections are small and don't
   accumulate, and `[Journal]`/catalogs are prompt-render-windowed (§3 —
   "latest 50" / "out-of-scope keys collapse to names"), the same idea as
   `[Recent Events]`'s own compression. `[Personality]` is the one section
   with no documented render cap, but it grew slowly in the one NPC checked,
   and a specific entry was independently found missing from the real file
   despite the spec saying entries are never evicted (§3) — suggesting it may
   not be truly unbounded in practice either, though the mechanism is unknown.
   **One concrete residual risk, not closed:** `[Recent Events]` is 30% of the
   prompt and its steady-state size (~54–105 events, what's actually been
   observed) is not its worst case. `trigger=100`/`backoff=120000ms` means a
   pass can't fire more than once per 2 minutes — a chaotic session (combat,
   rapid dialogue, multiple NPCs) could push events toward `lossy=200` before
   the next pass catches up, roughly double the observed steady state. Worth
   a spot-check if a session like that happens, not a blocking measurement.
   Can't be stress-tested with synthetic event spam (§3) — needs a long,
   genuinely varied real play session, which is why this is being closed on
   the available evidence rather than held open for one.
3. ~~Do barks evict the slot?~~ **Answered, 9 August. Yes.** Confirmed
   `total_slots: 1` via `GET /slots`, then captured a real Dialog → Bark →
   Dialog sequence and ran a controlled A/B: the same 0001→0003 pair (58.6%
   real prefix overlap) gets `cache_n=4913` with no disruptor and `cache_n=0`
   with the bark sandwiched in — reproduced twice. Unlike the Memory-chain
   case, which survived (see §2), Bark reliably evicts. `-np 1` is **not**
   safely bark-tolerant as-is: Phase 2's cache payoff will be reduced in
   practice by however often barks land mid-conversation.
   `--ctx-checkpoints`/`--checkpoint-min-step` were tested directly as a fix
   and ruled out (no effect, with or without `--swa-full`). The actual fix —
   `--slot-save-path` with the proxy managing save/restore itself — is a
   build, not a flag; not attempted. Splitting barks onto their own proxy
   port (D1) is still worth doing, now to measure real-world frequency and
   impact rather than to detect whether eviction happens at all.
4. **`-c 12000` vs `-c 20000`.** Faster cold requests and ~2700 tokens of
   headroom, versus slower cold requests and ~10700. Cold requests only happen
   on NPC switches, so the trade depends on question 2 (does the ceiling
   actually get approached).
5. **How much does `lossy=200` actually discard in practice?** Still open —
   no batch has approached 200 events yet, so the hard-discard mechanism
   itself remains untested. But the premise underneath this question turned
   out false: compression well inside the 200 ceiling is *already* lossy
   (§3 — a full conversational thread dropped by a normal, in-budget pass;
   `[Personality]` content confirmed twice not surviving to disk). The
   archive's justification no longer rests on `lossy=200` alone.
6. **What causes 0002→0003's 39.3% prefix divergence?** Not the
   `[Entrances nearby]`/`[Objects nearby]` swap — both captures carry the
   same section there. Not investigated; could be a bigger scene/location
   change, a `[Recent Events]` shift, or something else. Worth a quick diff
   pass before Phase 2 is called complete.

**Measurement discipline:** compare only requests where `cache_n` is near zero.
Cache hits complete in ~3s and will mask any config difference if averaged in.

---

## 8. Decisions

**The proxy is the integration point, not the memory file.** It owns the bytes
on the wire, so Numen needs no cooperation and nothing persists that Numen's
compression could clobber. Integration is one line in `Agent.ini`.

**Numen's compression stays.** Not rebuilding consolidation — it already works,
and the memory files show it doing its job (`events 105->54`). "Works" means
produces reasonable output, not lossless — §3 documents a full thread dropped
and `[Personality]` content not persisting, both well inside the `lossy=200`
ceiling. Rebuilding it is still out of scope (idea.md); this just means the
archive (Phase 3) is protecting against more than `lossy=200` alone.

**Cache hygiene before retrieval.** This inverted during the investigation.
Retrieval targets 5.7% of the prompt; the cache fix delivered a measured 10x on
repeat requests.

**Retrieval is deferred** until question 1 is answered. If built, it targets
`[Glossary]` and `[Recent Events]`, not `[Journal]`.

**Route by port, not by heuristic.** Give the Memory chain (and later Bark) its
own `Agent.*` entry pointing at its own proxy port. Classification then costs
nothing and cannot silently misfire.

**Stack: Python + FastAPI + httpx**, SQLite with FTS5 when storage is needed.

**Three tiers, and only the first two are LLM-free.** The "no spare VRAM"
constraint applies to the request path, not to the project:

| Tier | When | LLM? |
|---|---|---|
| Request rewrite | inside a live request, under a 90 s chain timeout | **No.** Deterministic string operations only. |
| Ingest — watch files, hash events, index | while the game runs | **No.** Must not contend for GPU. |
| Distillation — raw events → retrievable memory | game closed | **Yes.** Full VRAM, no latency budget, can run overnight. |

Offline distillation should start from Numen's own compression prompt (§3),
which is already tuned and produces a structured delta format — but without
`trigger=100` / `batch=50` / `lossy=200` forcing its hand.

**Fail safe always.** Any parse or rewrite failure forwards the original request
untouched and logs why. A proxy error costs a 30 s agent cooldown in-game, so
failures must be silent passthroughs, never 5xx.

**Build it Numen-shaped.** Generalising to arbitrary OpenAI-compatible apps
costs the thing that makes this tractable: a known, structured prompt format.

---

## 9. Reproducing the measurements

Prompt captures — point `Agent.ini` at port 8081:

```
cd tools
.venv\Scripts\python.exe logging_proxy.py --reorder
```

Section budget and cache behaviour are read from `tools/captures/`; every
response carries `prompt_n`, `cache_n` and `timings`.

Numen's own resolved config, agent chains, memory policy and full response
bodies are in `Fallout New Vegas\Numen.log`. NPC memory files, including the
`# last-summary:` header, are in `Fallout New Vegas\Numen\NPCContext\`.

Inference benchmarks, with llama-server stopped:

```
llama-bench.exe -m <model>.gguf -ngl 99 -fa 1 -ctk q4_0 -ctv q4_0 ^
  -d 0,4096,9216 -p 512 -n 64 -r 1
```
