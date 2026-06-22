# Night Road Narrator

A local, offline AI **voice narrator** for the Steam game
*Vampire: The Masquerade — Night Road*. It reads the game aloud as you play,
with a distinct voice for the narrator and a different, consistent voice for
each character. Everything runs on your own PC — no cloud, no API keys, no
account.

> **Not affiliated** with Choice of Games or Paradox Interactive. You must own
> *Night Road* on Steam. This project does **not** include or modify any game
> files — it only reads the on-screen story text and plays audio alongside it.

---

## Features

- **Reads the game aloud, fully offline.** All the AI runs locally on your machine.
- **Separate voices for narrator and characters.** The narrator has one voice;
  each character is automatically given their own, and keeps it for the session.
- **Gender-matched casting.** Male characters get male voices and female
  characters get female voices, worked out from pronouns and names in the text.
- **Never loses text.** The story is split locally and the AI only labels *who*
  speaks — so long passages are never cut off or skipped.
- **Knows dialogue from emphasis.** Quoted *terms* (like a "consideration") stay
  in the narrator's voice; only real spoken lines get a character voice.
- **Skips stat and level-up screens** automatically, while still reading any
  story text on the same page.
- **Natural pacing.** Proper pauses after sentences, between paragraphs, and at
  parentheses and em-dashes — no rushing or run-ons.
- **Pronunciation dictionary** for *Vampire: The Masquerade* terms (clan names,
  jargon) so they're said correctly.
- **Audio caching** so repeated lines play instantly.
- **Voice auditioning tool** to browse the ~900 available voices and pick favourites.

---

## How it works

Four small parts working together:

1. **The game** runs as normal, with one extra Steam launch option that lets
   other programs read its text.
2. **A watcher** (`narrator-capture.js`) is injected into the game and notices
   when new story text appears, sending it to the pipeline.
3. **The pipeline** (`nightroad.py`) splits the text, asks a **local AI model**
   (via Ollama) only *who speaks each quote*, then…
4. **…synthesises speech** with **Piper** in the right voice and plays it.

---

## Requirements

- **Windows 10/11** (the one-click launcher is Windows-only; the Python parts
  themselves are cross-platform if you want to adapt them).
- ***Night Road*** owned and installed on Steam.
- **A reasonably modern PC.** The speaker-attribution AI and the speech run
  locally. A dedicated GPU is strongly recommended — this was built and tested
  on an RTX 2080 Ti (11 GB). It will run on CPU only, but with more delay.
- **~10 GB free disk** for the AI model and the voice model.
- **Python 3.10 or newer.**
- **Ollama** (the local AI runner).
- **Piper** (the local text-to-speech engine).

---

## Installation

Work through these once. Commands use `py`, the Windows Python launcher.

### 1. Get the files

Download this project (green **Code** button → **Download ZIP**, then unzip) into
a folder of your choice — for example `C:\NightRoadNarrator`. Everything lives in
that one folder.

### 2. Install Python

Get it from [python.org](https://www.python.org/downloads/) and, during install,
**tick "Add Python to PATH."** Confirm it works by opening Command Prompt and
running `py --version`.

### 3. Install the Python packages

In Command Prompt, from inside the project folder:

```
py -m pip install flask websocket-client piper-tts
```

### 4. Install Ollama and pull the AI model

Install Ollama from [ollama.com](https://ollama.com). Then pull the model that
decides who is speaking:

```
ollama pull qwen2.5:7b
```

(There's a smaller, faster option, `llama3.2:3b` — see **Tuning** below.)

### 5. Download the voice

```
py get-voices.py
```

This fetches the single voice model the pipeline uses
(`en_US-libritts_r-medium`) into a `voices` folder. If it fails repeatedly with
rate-limit errors and you're on a VPN, turn the VPN off and run it again.

### 6. Build the voice gender map

```
py make_gender_map.py
```

This needs an internet connection. It looks up which voices are male and which
are female and writes `voices_gender.json`. You only do this once.

### 7. Turn on the game's debug port

In Steam, right-click **Vampire: The Masquerade — Night Road** →
**Properties** → **General** → **Launch Options**, and paste:

```
--remote-debugging-port=9222
```

This is what lets the watcher read the game's text. It does nothing else.

You're done installing.

---

## Running it

The easy way — double-click **`start-nightroad.bat`**. It opens the pipeline,
launches the game through Steam, waits for it to load, and injects the watcher,
each in its own window.

Then just **play**. When new text appears, you'll hear it. The very first line
of a session is slow (the AI is waking up); after that it keeps pace.

> **Pause narration** any time with **Ctrl+Alt+N** inside the game (press again
> to resume) — handy if you want a quiet moment while recording.

### Running it manually (if you prefer)

1. In one window: `py nightroad.py` (leave it running).
2. Launch *Night Road* from Steam.
3. Once the game is showing story text, in a second window: `py inject.py`.

### Test it without the game

With `nightroad.py` running, open a second window and run `py test_passage.py`.
You should hear a short sample with narrator, a character, and "your" voice.

---

## Tuning

- **Speed & pacing:** near the top of `nightroad.py`, `LENGTH_SCALE` sets the
  speaking speed (1.0 = normal, higher = slower), `SENTENCE_SILENCE` is the pause
  after each sentence, and `SEGMENT_GAP` is the gap between paragraphs and voice
  changes. Nudge them to taste and restart — lower the last two together if it
  feels too stop-start.
- **Faster AI (less delay):** pull the smaller model with
  `ollama pull llama3.2:3b`, then change the `OLLAMA_MODEL` line near the top of
  `nightroad.py` to `"llama3.2:3b"` and restart. Slightly less accurate at
  working out speakers, noticeably quicker.
- **Pronunciations:** the `PRONUNCIATIONS` dictionary near the top of
  `nightroad.py` respells tricky words how they should sound. Add your own as
  `"Word": "Respelling"`.
- **Recasting voices:** characters are remembered in `voices.json`. Delete that
  file and restart to recast everyone from scratch.
- **Auditioning voices:** run `py audition_voices.py` to listen through the
  voices in batches and find ones you like (`py audition_voices.py F` for female,
  and so on — it prints the next command each time).

---

## Troubleshooting

- **No audio at all.** Make sure `nightroad.py` is running, the launch option in
  step 7 is set, and the game is actually showing story text before `inject.py`
  runs. Advancing a page in the game and re-running `py inject.py` usually fixes it.
- **"Couldn't find the game."** The debug port isn't set or the game isn't
  running yet. Re-check step 7 and that the game has finished loading.
- **Long delay before speech.** First line of a session is always slow. If every
  dialogue line drags, switch to `llama3.2:3b` (see Tuning) — most likely your
  graphics memory is tight and the bigger model keeps reloading.
- **Repeated download errors (429).** You're being rate-limited — usually a VPN.
  Turn it off and run `py get-voices.py` again; it resumes where it left off.
- **A word is mispronounced.** Add it to `PRONUNCIATIONS` in `nightroad.py`.

---

## Credits

- Speech: [Piper](https://github.com/OHF-Voice/piper1-gpl) with the
  `libritts_r` voice (built from the LibriTTS / LibriSpeech datasets).
- Local AI: [Ollama](https://ollama.com).
- Game: *Vampire: The Masquerade — Night Road* by Kyle Marquis / Choice of Games.

This is a fan-made accessibility/immersion tool, shared as-is.
