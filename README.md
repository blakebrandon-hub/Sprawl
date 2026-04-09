# SPRAWL

> *The city doesn't care about you. GHOST does. Barely.*

---

You are John. Street operator. Neural link active.

Somewhere in the Neon Bazaar, a fixer named Sal has a job that pays too well for how easy it sounds. Somewhere above you, Glassspire Tower's ICE is already scanning. And somewhere in your skull, GHOST — your onboard AI — is watching your vitals tick up and your trace exposure climb.

**Sprawl** is a text RPG powered by a live language model. You type what John does. The city responds. No menus. No loading screens. No hand-holding.

---

## What It Actually Feels Like

You're not clicking through dialogue trees. You're talking to a city.

Tell John to tailgate a CorpSec guard through a security door. Instruct GHOST to blue-snarf the executive's bone-conduction comms. Pick a fight in the Ironworks District and watch your HP, Neural Strain, and Trace all move at once. The AI tracks it all — your inventory, your rep with three factions, your one active job, the augmentations installed in your hardware slots — and the world reacts accordingly.

GHOST speaks out loud. Ads bleed into your UI when you're in commercial zones. The music shifts to combat tracks when things go wrong. If your Neural Strain hits 100%, the link collapses and you die.

It feels like a cyberpunk novel you're writing in real time.

---

## The Setup (It's Quick)

You need Python, a Flask server, and at least one API key — Anthropic, Google, or OpenAI. The narrator model is swappable; Claude, Gemini, and GPT all work. Optional image generation will paint the current scene on demand.

```bash
pip install flask flask-cors anthropic openai google-genai

export ANTHROPIC_API_KEY="your-key"
export NARRATOR_MODEL="claude-sonnet-4-6"

python app.py
```

Open `http://localhost:5000`. Click **ENTER THE SPRAWL**.

That's it.

---

## The World

The Sprawl has four zones, each with its own pressure:

- **Neon Bazaar** — Ad-saturated, loud, civilian cover. Good for meeting Sal.
- **Ironworks District** — Smog and smugglers. Less surveillance, more physical risk.
- **Glassspire Tower** — Full corporate surveillance. Hardened ICE. Don't linger.
- **Shadow Alley Network** — Off-grid. Unstable. High criminal density.

Your reputation with **Ironhand**, **Data Vultures**, and **CorpSec** shifts based on what you do — not what you say you'll do. Burn a contact and their network closes. Complete a job cleanly and doors open.

---

## Your Network

**Sal** — your fixer. Straight shooter. Doesn't oversell the job.

**GHOST** — your neural-link AI. Tactical, slightly distorted, protective. Performs hacks at the cost of your Strain and Trace. Speaks directly to you through a dedicated console.

**Cipher** — a WW3 veteran who taught you the rules. Shows up when he chooses. His stories don't always match between tellings.

**Vex** — black market augments. Ironhand-connected. Prices depend on your standing.

**Luna** — the one person in the Sprawl who sees through your distance. A liability you keep anyway.

---

## Three Ways to Die

Your Neural Strain hits 100% — GHOST's link collapses mid-sentence.

Your Trace hits 100% — CorpSec follows the signal back to you.

Your HP hits 0 — the city wins. It usually does.

---

## The Technical Part (For the Curious)

The narrator communicates game state through structured tags hidden in its prose. A custom Glyph Engine parses them client-side — no extra API calls — updating your inventory, faction rep, job status, augment slots, and stat bars in real time. Every 12 exchanges, a lightweight archiving model compresses the session history so long runs stay coherent without burning tokens.

The backend supports four separate game worlds. Sprawl is one of them.

---

*Built with Flask, Tone.js, the Web Speech API, and whichever LLM you trust most.*
