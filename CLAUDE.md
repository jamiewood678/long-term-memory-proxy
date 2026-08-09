# CLAUDE.md

## What this is

A transparent proxy between **Numen** (an AI NPC mod for Fallout: New Vegas) and
**llama-server**, on an OpenAI-compatible endpoint. The goal is to raise the
ceiling on how much an NPC can remember — **not** to make requests faster.
Latency is a constraint, not the objective.

Feasibility stage. More has been measured than built.

## Read before working

| File | Why |
|---|---|
| [docs/findings.md](docs/findings.md) | Measured facts. **Authoritative** — where it disagrees with idea.md, it wins |
| [docs/plan.md](docs/plan.md) | Phases, open decisions (D1–D9), gating questions |
| [docs/idea.md](docs/idea.md) | Intent and scope |
| [docs/numen/prompts/](docs/numen/prompts/) | Numen's actual prompt templates, extracted from captures |
| `Numen.log` (game dir) | Resolved agent chains, memory policy, full response bodies |
| `D:\MO2 - TTW 3.4\mods\Numen - AI NPCs for FNV` | Numen's mod files, includes all npcs backstories, .esp file, menus, numen.dll, scripts, tts, lipgenerator
| `D:\MO2 - TTW 3.4\mods\Numen - AI NPCs for FNV.ini` | Numen.ini and Agent.ini, includes all settings for Numen and Agent.

## Working style

**Measure, don't assume.** This project has already been burned by confident
wrong claims — assumed NVIDIA when the card is AMD, assumed requests were
single-turn when they are not, read a missing capture file as an aborted
request. If something has not been measured, say so explicitly.

**Token budget is a real constraint.** Captured requests are ~37 KB each. Never
bulk-read `tools/captures/`. Write a small script that prints only the summary
needed, and run that.

**Correct the record.** When a finding turns out wrong, update findings.md and
say what changed. Don't quietly drop it — the corrections section exists so the
surviving claims aren't flattered by omission.

## Environment

- Windows 11, PowerShell primary
- **GPU: AMD Radeon RX 6750 XT, Vulkan backend.** Not NVIDIA — CUDA advice,
  `nvidia-smi`, and sysmem-fallback settings do not apply
- Model: `gemma-4-12B-it-heretic-Q4_K_M.gguf`
- llama-server `:8080`, proxy `:8081`
- Python venv at `.venv` (repo root; `numen_proxy` package lives at `src/numen_proxy/`)
- Numen install: `C:\Steam\steamapps\common\Fallout New Vegas`
  - `Numen.log` — config and responses
  - `Numen\NPCContext\{Plugin}\{FormID:6}.txt` — per-NPC memory files
  - `Data\NVSE\Plugins\Numen\` is **not** readable — MO2 virtualises it

## Hard constraints

- **The proxy must never return 5xx.** A proxy error benches that agent for 30 s
  in-game (`iAgentCooldownSeconds=30`)
- Anything added must fit inside `iChainTimeoutSeconds=90`
- Any parse or rewrite failure **forwards the original bytes untouched** and logs
  why. Failing open is always correct here
- Do not modify Memory-chain requests — that is Numen's core loop (decision D3)
- Do not write to Numen's memory files; Numen owns them (decision D4)
- `tools/captures/` and `docs/numen/examples/` hold playthrough content. Gitignored.
  Never commit them and never paste them wholesale into a document

## CODE GEN

[CRITICAL] follow SOLID principles
[CRITICAL] by following SOLID code should be easy to test in isolation
[CRITICAL] all new code must be unit tested
[CRITICAL] create integration tests between units
[CRITICAL] try to write clean, readable and well maintable code
[CRITICAL] follow best practices

## Testing

The **golden corpus** — real captured request bodies, scrubbed — is the core test
asset. Replay against `tools/echo_upstream.py` as a fake upstream. Without it,
"does this break Numen" can only be answered by playing the game.

Every prompt rewrite must be:

- **lossless** — identical line multiset before and after
- **idempotent** — `rewrite(rewrite(x)) == rewrite(x)`
- **structure-preserving** — same sections, same user message, same sampling params
- **fail-safe** — a missing or renamed section forwards the original untouched

Cache effectiveness is a regression test, not a metric: assert median `cache_n`
stays above a threshold. That is what catches a Numen prompt-format change.

Do not write tests that assert LLM output quality. Judge distillation by reading
it.

## Verifying a change worked

Read `cache_n` and `prompt_n` from the response `timings` block. Compare only
requests where `cache_n` is near zero — cache hits finish in ~3 s and will mask
any real difference if averaged in.
