# Numen - AI NPCs for Fallout: New Vegas

## Overview

Numen is an NVSE plugin that gives NPCs in Fallout: New Vegas long-term memory and the ability to have unscripted conversations. NPCs can think, talk, remember, and interact with each other autonomously.

- **Version:** 1.6.0
- **Creator:** Eddoursul
- **License:** ModPub Non-Commercial Private Use License 1.0
- **Language:** English

> **Summary:** AI companions with long-term memory and NPC-to-NPC conversations.

---

## Core Concept

Numen enables unscripted conversations with almost any NPC in the game. You point at an NPC, press the Grab key, type what you want to say, and they answer in character with voice and lip-sync. They remember what happened between you across play sessions, form opinions, and talk to each other.

The plugin sends conversation requests to an LLM of your choice—a free model running locally or a cloud API. The model's response is spoken using neural TTS (with optional voice cloning) and can trigger in-game actions like recruiting, trading, or romance.

**Key advantage:** No subscription, no sign-up. You control the model, where it runs, and what it costs.

---

## What NPCs Can Do

### Core Capabilities

- **Comment** - Voice opinions when entering locations, finishing quests, or trading items (dozen auto-triggers, configurable per trigger)
- **Remember** - Persistent long-term memory across save games: places, people, promises, shared history
- **Think** - Inner voice providing subtext to dialogue
- **Feel** - Evolving trust, romance, and mood based on player interactions
- **Act** - Recruit/dismiss, trade, equip gear, fight, romance, gift-giving (driven by NPC decisions, not player commands)
- **Converse** - Talk to each other with separate contexts; no pre-scripted dialogue
- **Lie** - Can deceive and manipulate
- **Relax** - Auto-sandbox in safe/home locations

### In-Game Actions

NPCs can:
- Join or leave your party (or choose to leave if pushed too far)
- Open trade/share windows or accept/give gifts
- Equip or remove armor and weapons
- Turn hostile if insulted or threatened
- Build relationships with paced, earned trust/romance/mood changes
- Optional intimacy (can be completely ignored)

**Note:** Actions are context-gated and earned gradually—NPCs are not yes-men. No established trust means no loyalty.

---

## Player Interaction

### Starting a Conversation
1. Aim at an NPC
2. Press Grab key (Z by default, rebindable)
3. Text box opens

### During Conversation
- Type your line and press Enter
- World keeps running (no pause)
- NPC reply streams with voice and subtitles
- Animated "thinking" indicator shows the model is working
- Text box reopens automatically
- Press Tab or submit empty line to end

### Quick Commands
```
/hire    Recruit the NPC instantly
/fire    Dismiss the NPC instantly
```

---

## Long-Term Memory System

### How It Works

Every conversation-capable NPC maintains a persistent memory file surviving save games:

- **Journal** - Meetings, promises, conflicts, milestones
- **Catalogs** - Places, people, storylines they know
- **Personality notes** - Personal goals and self-perception
- **Relationship log** - Trust, romance, mood with documented reasons for changes

### Memory Operations

- **Automatic compression** - Background model compresses memory without stalling gameplay
- **Intelligent trimming** - Prompt-time trimming keeps even small models grounded and consistent
- **Overhearing** - NPCs hear and remember conversations around them
- **Persistence** - Memories survive across in-game days; an NPC will remember you after extended absence

### Storage Location

```
{GameDir}\Numen\NPCContext\{PluginName}\{FormID:6}.txt
```

You can manually delete or modify memory files to alter an NPC's history.

---

## Customizing NPC Personalities

### Default Behavior

NPCs automatically improvise personalities from their in-game data (name, faction, location) with **zero setup required**.

### Hand-Authored Backstories

Create plain text files for custom personalities:

```
Data\NVSE\Plugins\Numen\Context\Backstories\english\{ModName}\{FormID:6}.txt
```

**Example:**
```
Data\NVSE\Plugins\Numen\Context\Backstories\english\FalloutNV.esm\104E85.txt
```

**Guidelines:**
- Limit: 8000 characters
- Include: backstory, voice, quirks, secrets, opinions, faction feelings
- This forms the immutable core; in-game learning builds on top

### Included Content

- Backstories for 2800+ vanilla NPCs (spoiler-free)
- Extendable world glossary so NPCs know people, places, and gear without being told
- Add custom .txt files to the glossary to extend it

---

## Model & Hardware Requirements

### Minimum Specifications

- **Model:** Gemma 4 12B or higher
- **Context window:** 
  - 20k tokens: Comfortable for typical endgame NPC (13k token prompt)
  - 30k tokens: Needed for overthinking models (e.g., Qwen)
- **Models to avoid:** Overthinking models increase delay and are not recommended for slow setups

### Performance Example

**Gemma 4 12B (unsloth/gemma-4-12b-it-qat):**
- Response time: ~2 seconds
- Hardware: RTX 5070 Ti (16GB) + 32GB DDR5-6000 RAM

---

## Configuration

Configuration files are located in `Data\NVSE\Plugins\Numen\`:

### Agent.ini
Controls LLM selection and endpoints:
- LLM endpoints (local or cloud API)
- API keys and model names
- Fallback chains and load balancing
- Timeout settings
- Multi-agent configuration (assign multiple models per type)

### Numen.ini
Controls gameplay behavior:
- Talk key binding
- TTS backend selection
- Voice settings
- Companion comment frequency
- NPC-to-NPC conversation chance (default: 0)

### Installation Notes

If misconfigured, Numen shows a single plain-language message at the main menu telling you exactly what to fix.

---

## Choosing Your AI Model

### Option 1: Cloud API (Easiest)

**Setup:**
1. Sign up with a provider
2. Paste API key and model name into Agent.ini
3. No hardware required; costs pennies

**Providers supported:**
- OpenRouter (best for price comparison)
- Hugging Face
- Google AI Studio
- MiniMax
- Any OpenAI or Anthropic-compatible endpoint

**Cost analysis:** Sort models on OpenRouter by price per 1M tokens to estimate usage costs. Chain free offerings for zero cost.

### Option 2: Local Models (Free, Private, Offline)

**Setup:**
1. Install a local server: LM Studio, llama.cpp, Ollama, or vLLM
2. Load a chat model
3. Point Agent.ini at the server address
4. A decent GPU is recommended

**Advantage:** No data leaves your machine; completely free after initial setup.

### Mixing Strategies

Use a cheap, fast model for ambient chatter and a smarter one for important conversations. The mod supports multi-agent configuration:
- Specify multiple models per type
- Automatically balances between them or falls back when overloaded
- Example: Cloud API first, local model fallback if cloud is down

---

## Text-to-Speech Options

### Pocket TTS (Default)
- Fast voice cloning
- Automatic opt-in support
- No additional setup required

### sherpa-onnx
- Multi-engine support: Piper, Kokoro, KittenTTS
- NVIDIA users can install CUDA for significant speedup
- Requires additional configuration

**Note:** The base mod ships ready to talk with Pocket TTS included. Extra voice presets and models are optional downloads.

---

## Getting Started

### Quick Start (3 steps)

1. **Install requirements:**
   - English version of Fallout: New Vegas
   - xNVSE
   - JIP LN NVSE
   - Numen (install via mod manager; MO2 recommended)

2. **Configure your model:**
   - Open `Data\NVSE\Plugins\Numen\Agent.ini`
   - Point to a local model server address OR paste cloud API key and model name

3. **Play:**
   - Launch the game
   - Aim at any NPC
   - Press Grab key (Z by default)
   - Start talking

**Result:** NPCs are voiced out of the box and begin building memories from your first conversation.

### NPC-to-NPC Conversations

The initial release focuses on AI companions. NPC-to-NPC conversation is partially enabled:
- Companions may talk to each other
- Chance of conversation between other NPCs is set to 0 by default (needs more polish)
- To enable: raise `iOnNPCHello` in Numen.ini
- Companions can technically talk to other NPCs but are currently discouraged

---

## Compatibility

### Compatible Mods & Features

- **JIP Companions Command & Control (CCC)** - If installed, Numen uses JIP CCC follow packages
- **Vanilla companions** - Works alongside Boone, Veronica, ED-E, etc. without interfering with their scripted follower systems
- **TTW (Tale of Two Wastelands)** - Fully compatible; recommend telling companions they're heading to the Mojave (they may get confused otherwise)
- **JohnnyGuitar NVSE** (recommended) - Improves spatial awareness via always-loaded Editor IDs

### Installation Notes

- Built around engine hooks in popular NVSE plugins
- Designed for typical FNV or TTW modlists
- Use a mod manager (MO2 recommended) for organization

---

## Limitations

### Model-Dependent
- **Quality varies** - Depends on LLM coherence, hardware speed, and endpoint availability
- **Occasional issues** - Hallucination, forgetting, and lore inconsistencies are inherent to LLM technology; not bugs that can be fully tuned out
- **Model comparison** - A large but lower-tier model (e.g., MiniMax 2.7) shows richer vocabulary, better creative writing, and better nuance than small local models

### Gameplay Constraints
- **No children dialogue** - Cannot talk to child NPCs
- **Humans primarily** - Most creatures and robots cannot converse (exceptions: DC robo-butlers, Fawkes, Lily)
- **English/ASCII only** - Prompts, glossary, and voices are English; game subtitle renderer is ASCII-only (non-English model replies appear garbled)
- **Vanilla companions unchanged** - Boone, Veronica, Arcade Gannon remain on vanilla dialogue; Numen doesn't take over their scripted follower system
- **NPC-to-NPC early** - Companion conversations work; NPC-only conversations off by default pending polish

### Technical
- **Response latency** - Every reply is a round-trip to the model + TTS synthesis. "Thinking" indicator covers the wait, but expect a pause (longer on slow hardware or busy free endpoints)

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| NPCs don't reply or "request failed" | Check Agent.ini endpoint is correct; verify local server is running; confirm API key and model name are correct |
| Subtitles appear but no voice | Check [TTS] section in Numen.ini; verify TTS engine started; review Numen.log |
| Crashes with VRAM/video driver errors | Out of video memory; reduce model size or graphics settings |
| General setup issues | Check `Numen.log` in your game folder—it answers the majority of setup questions |

**First step:** Always check `Numen.log` alongside your Agent.ini settings.

---

## Uninstallation

### Clean Removal (3 steps)

1. **Dismiss companions:**
   - Talk to each companion you recruited through Numen
   - Type `/fire`
   - This returns them to normal game state
   - Skipping this can leave them following you permanently

2. **Disable the plugin:**
   - Locate `NVSE\Plugins\Numen.dll`
   - Delete or hide this file (in mod manager, hide the DLL itself, not the whole mod)
   - The ESP contains no moving parts; without the DLL it does nothing

3. **Keep the ESP:**
   - Leave `Numen.esp` enabled in your load order
   - Removing an ESP from an active save is highly discouraged
   - Only remove the ESP entirely when starting a fresh game

### Why This Order

- The DLL contains all Numen behavior; removing it silences the mod completely
- The ESP is purely a placeholder and does nothing without the DLL
- Keeping the ESP preserves save game integrity

---

## Requirements Summary

### Required
- English version of Fallout: New Vegas
- xNVSE
- JIP LN NVSE
- LLM endpoint (Gemma 4 12B or higher)
  - Local: LM Studio, llama.cpp, Ollama, vLLM
  - Cloud: OpenRouter, Google AI Studio, Hugging Face, MiniMax, etc.

### Recommended
- Mod manager (MO2) for installation and organization
- JohnnyGuitar NVSE for improved spatial awareness
- Decent GPU (if running models locally)
