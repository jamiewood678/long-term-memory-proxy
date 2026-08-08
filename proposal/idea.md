# Project Goal: Long-Term Memory Middleware for LLMs

I want to build a transparent middleware/proxy that lets a local LLM application
hold an unbounded amount of long-term memory while keeping its active context
small, without requiring changes to the application itself.

## The problem

The immediate target is Numen, an AI NPC system for Fallout: New Vegas. Numen
maintains NPC memories and sends them to the LLM as part of every prompt. I
cannot easily modify Numen's internal memory storage or retrieval.

Numen currently sends the **entire** NPC memory with each request. It compresses
that memory to keep it manageable, and that helps — but compression has a floor.
You can only summarise so far before you start destroying the detail that makes
an NPC feel like it remembers anything. Past roughly 20k tokens, quality and
performance deteriorate rapidly on my hardware, and raising the context window
is not affordable on a consumer GPU.

So there is a hard ceiling on how long an NPC's life can get. Compression alone
cannot lift it, because the whole memory is always in the prompt.

**This is not a project about making requests faster.** Latency is a constraint
to respect, not the goal. The goal is to raise the ceiling on how much an NPC
can remember.

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
with something that already works.

What Numen does not have is **retrieval**. Its journal is flat and chronological;
nothing pulls an old entry back into context when it becomes relevant again.
That gap is the actual contribution of this project, and it is a much smaller
piece of work than a full memory pipeline.

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

**2. Select memory per situation**
- Choose which archived material goes into the prompt based on what is currently
  happening, not on a fixed window.
- Strip the memory Numen sent and substitute the selection. Adding without
  removing does not reduce anything.

**3. Keep identity intact**
- Small, identity-critical sections (`[State]`, `[Trust Log]`, `[Romance Log]`,
  `[Personality]`, `[Personal goals]`, backstory) always go in. They are bounded
  and cheap.
- Recent conversation always goes in, faithfully.
- Only the unbounded, entity-keyed sections (`[Journal]`, `[Personas]`,
  `[Locations]`, `[Threads]`) are selected from.

**4. Hold a fixed context budget**
- Target roughly 10–15k active tokens regardless of archive size.
- Note the floor: system instructions, world glossary and backstory are fixed
  costs the middleware cannot touch, likely 4–6k tokens. The realistic outcome
  is "stops growing, forever", not "20k down to 5k".

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
.\llama-server.exe -m "gemma-4-12B-it-heretic-Q4_K_M.gguf" -ngl 99 -fa on ^
  -ctk q4_0 -ctv q4_0 -c 20000 -b 4096 -ub 1024 -np 1 ^
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
