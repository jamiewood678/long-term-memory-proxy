# Project Goal: Long-Term Memory Middleware for LLMs

I want to build a transparent middleware/proxy that lets a local LLM application
hold an unbounded amount of long-term memory while keeping its active context
small, without requiring changes to the application itself.

## The problem

The immediate target is Numen, an AI NPC system for Fallout: New Vegas. Numen
maintains NPC memories and sends them to the LLM as part of every prompt. I
cannot easily modify Numen's internal memory storage or retrieval.

**Original premise, now corrected.** This project started from the assumption
that Numen sends the entire NPC memory every request and that token budget is
the binding constraint — past roughly 20k tokens, quality and performance
deteriorate, so there'd be a hard ceiling on how long an NPC's life could get.
Measurement (findings.md §7 Q2) showed this is wrong. Numen already bounds
almost everything: `[Recent Events]` is actively compressed
(trigger/batch/lossy), and `[Journal]` and the catalogs
(`[Locations]`/`[Personas]`/`[Threads]`) are rendered through a fixed window
— latest entries, pinned entries, and whatever Numen's own tagging judges
relevant to the current scene — regardless of how large the underlying store
gets. Real prompts have run 8-9.5k tokens against a ~20k budget. Token ceiling
is not the constraint.

**The real problem is recall, not capacity.** Numen's journal is append-only
on disk — nothing is deleted (verified directly: 11 entries in, 14 out, zero
removed, across two real compression passes) — but only a small, fixed slice
of it ever reaches the model on a given turn. An entry that ages out of the
latest-50 window and isn't pinned or re-tagged as relevant is invisible to
the NPC from then on, even though the raw fact still exists in the file. From
the player's side, "preserved but never shown again" and "forgotten" look
identical. Numen's own relevance-picking is crude — tag/catalog-key matching,
not real situational judgement — and demonstrably misses things: a whole
conversational thread was dropped by an ordinary, well-inside-budget
compression pass (findings.md §3).

One place has *real*, permanent loss, not just a windowing gap:
`[Personality]` entries, documented as "never evicted," were confirmed
missing from the persisted file in two independent cases. That's a genuine
bug worth guarding against separately from the recall problem.

**This is not a project about making requests faster, and it turned out not
to be a project about fitting more tokens into a small context either.** The
goal is to make sure an NPC can still act on something it learned a long time
ago, once Numen's own short window has moved past it.

## The core idea

Separate **lifetime memory** from **active context**.

Instead of sending all accumulated memory every time, dynamically select the
subset that is relevant to the current situation and send only that. The archive
can then grow without bound — hundreds of thousands of tokens — while the prompt
stays at a fixed, comfortable size forever.

> Don't force all of an LLM's long-term memory into its context window. Give it
> an external memory it can selectively recall from.

## What Numen already does, and what I'm adding

Numen already handles compression and consolidation. Its memory files are
structured into `[Journal]`, `[Personas]`, `[Locations]`, `[Threads]`,
`[Personality]`, `[Trust Log]`, `[State]` and `[Recent Events]`, and it
summarises events down as they accumulate.

**I am keeping that.** Rebuilding it is not the point and would be competing
with something that already works — imperfectly, but well enough that a
parallel effort isn't justified (see findings.md §3 for the specific gaps
found so far).

What Numen does not have is **retrieval**. Its journal is rendered through a
fixed recency/pinning/tag-match window; nothing pulls an old, non-recent,
non-pinned, non-tag-matched entry back into context when it becomes relevant
again. That gap is confirmed, not assumed, and it is the actual contribution
of this project — a much smaller piece of work than a full memory pipeline.

## Proposed solution

```
Numen → Long-Term Memory Middleware → llama.cpp/llama-server → LLM
```

The middleware sits on the OpenAI-compatible endpoint, so integration is a
single line in Numen's `Agent.ini` and is trivially reversible.

It should:

**1. Archive everything, permanently**
- Watch Numen's memory files and snapshot them as they change.
- Preserve the raw, pre-compression detail that Numen discards when it
  summarises. This is the safety net — lossy compression must never be
  irreversible.

**2. Select memory per situation, injected as a new `[Old Memories]` section**
- Choose which archived material goes into the prompt based on what is currently
  happening, not on a fixed window.
- **Augment, don't substitute.** Inject as a new `[Old Memories]` block rather
  than stripping and replacing anything Numen sends. Originally ruled out
  ("adding without removing does not reduce anything") under the assumption
  that token budget was the binding constraint — it isn't (see The problem,
  above). Augmenting is safer: it can only add recall Numen's own window
  wouldn't otherwise surface, and a bad selection can't break Numen's existing
  working memory the way a bad substitution could.
- **A named section, not a raw append, matters.** Numen's whole system prompt
  is built from `^\[Name\]` blocks the model has thousands of tokens of
  consistent exposure to before it ever reaches this one; a block in the same
  shape reads as "more structured memory," not a foreign insertion.
- **Dedup by construction.** Selection excludes anything already present in
  Numen's own render this turn — the current `[Journal]` window, in-scope
  catalog descriptions, `[Recent Events]`. `[Old Memories]` can only ever
  contain things nowhere else in the prompt.
- **Placement: stable zone, near the volatile tail.** Grouped with
  `[Journal]`/catalogs/`[Personality]`, before the volatile block Phase 2
  already moved to the end — pinned per conversation so it never fragments
  the cache mid-conversation, but close enough to the generation point that
  it isn't attention-diluted by ~9k tokens of everything ahead of it. Worth
  measuring rather than guessing where exactly.
- **Give it explicit usage instructions**, the same way `[Voice]`/`[Command
  rules]` already steer other sections — something like *"things you
  genuinely know from further back; treat as established fact, weave in only
  if relevant, don't feel obligated to use one every turn."* An unexplained
  new section risks the model either ignoring it or over-using it because
  it's novel.
- **Omit the header entirely when nothing qualifies** — cheaper than an empty
  section, and consistent with the fail-safe discipline the rest of the
  proxy already follows.

**3. Keep identity intact**
- Small, identity-critical sections (`[State]`, `[Trust Log]`, `[Romance Log]`,
  `[Personality]`, `[Personal goals]`, backstory) always go in. They are bounded
  and cheap.
- Recent conversation always goes in, faithfully.
- Only the entity-keyed sections (`[Journal]`, `[Personas]`, `[Locations]`,
  `[Threads]`) are selected from — their persisted store can grow without
  bound even though Numen's own render window keeps what reaches the prompt
  small; that gap between "stored" and "visible" is what selection targets.

**4. Hold a bounded retrieval budget**
- Not a shrink target — Numen's own prompt already runs comfortably under the
  context limit (see The problem). Instead, cap how many *additional* tokens
  the middleware is willing to inject per turn, so a bad retrieval can't blow
  the latency budget even though there's no hard ceiling forcing it.
- A few hundred to ~1-2k tokens of augmentation is the likely right order of
  magnitude; tune against measured `prompt_n` headroom once Phase 5 is
  underway, not a number picked in advance.

## Constraints

**Cache stability.** llama-server reuses the KV cache for whatever prefix is
unchanged between requests. Rewriting the middle of the prompt every turn
invalidates it and forces full reprocessing. So the selected memory set should
be pinned when a conversation opens and held byte-identical across turns,
re-selected only on a real trigger — conversation start, location change, or a
clear topic shift. This is also better behaviourally: memory that churns
mid-conversation gives the NPC selective amnesia between one line and the next.

**Retrieval keys.** What the player types is often contentless ("aye aye
captain"). The useful query is situational: current location, NPCs present,
active quest entries, recent events — all of which are already in the prompt.

**No spare VRAM.** The model plus KV cache plus the game leaves nothing for a
second GPU model. Any embedding work runs on CPU. Given how entity-dense the
memory is, plain keyword/entity search may be sufficient and should be tried
before anything heavier.

**Latency.** Selection happens per conversation, not per turn, and must add no
more than a second or so. Building the archive can be as expensive as it likes —
it runs out of game.

## Hardware

- 12 GB VRAM consumer GPU, Ryzen 3800X, 32 GB RAM
- Model loaded fully on GPU, not split with CPU
- Fallout: New Vegas uses 512 MB–1 GB VRAM and 2–4 GB RAM; Windows 11 another 1 GB
- CPU utilisation is not a concern
- Model: `gemma-4-12B-it-heretic-Q4_K_M.gguf`

```
.\llama-server.exe  -m "gemma-4-12B-it-heretic-Q4_K_M.gguf" -ngl 99 -fa on ^
  -ctk q4_0 -ctv q4_0 --swa-full -c 20000 -b 4096 -ub 1024 -np 1 ^
  --host 127.0.0.1 --port 8080 --repeat-penalty 1.0 ^
  --top-p 0.95 --top-k 64 --min-p 0.0 --reasoning off
```

## Out of scope for v1

- **Building my own consolidation/summarisation pipeline.** Numen's compression
  stays. Revisit only if the archive shows it losing something that matters.
- **Importance scoring, memory decay, relationship graphs.** Each needs to be
  justified by an observed failure of something simpler.
- **Semantic embeddings**, until keyword and entity retrieval is shown to be
  insufficient.

## Long-term goal

Numen is the initial use case, but I would like the middleware to eventually
work with any application talking to a local LLM over an OpenAI-compatible API —
a general-purpose long-term memory layer that sits transparently between an
application and its inference server.

This is explicitly secondary. Generalising early costs the thing that makes the
Numen case tractable: a known, structured, on-disk memory format. Build it
Numen-shaped first; generalise only if it earns it.
