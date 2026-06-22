# Changelog

All notable changes to **Night Road Narrator**.

## [1.0.0] — first public release

A local, offline voice narrator for *Vampire: The Masquerade — Night Road*.

### Narration & attribution
- Reads the game aloud with a separate **narrator voice** and a distinct,
  remembered voice for each **character**.
- **Local text splitting** — the AI only labels *who speaks each quote*, so story
  text is never truncated or dropped, even on long passages.
- Tells **spoken dialogue from quoted emphasis** (terms like a "consideration"
  stay in the narrator's voice).
- **Gender-matched casting** — characters are voiced by gender, inferred from the
  pronouns and names around them.
- Voice pools **ordered by a quality signal** (clearer dataset speakers, and those
  with more source audio, are used first).

### Reading quality
- Natural pacing: pauses after sentences, between paragraphs, and at parentheses
  and em-dashes.
- **Adjustable speaking speed and pause lengths** via simple settings at the top
  of `nightroad.py`.
- **Pronunciation dictionary** for *Vampire: The Masquerade* terms (clan names and
  jargon), tuned against the phoneme engine so they're said correctly.
- **Automatic skipping of stat / level-up screens**, per line — surrounding story
  text on the same page is still read.

### Performance
- The local AI model is **kept warm and pre-loaded** to minimise the wait before
  speech.
- Synthesised audio is **cached** so repeated lines play instantly.

### Tools
- One-click Windows **launcher** (`start-nightroad.bat`).
- **Voice gender-map generator** (`make_gender_map.py`).
- **Voice auditioning tool** (`audition_voices.py`).
- **Test scripts** for the pipeline (`test_passage.py`) and pronunciations
  (`test_pronunciations.py`).

### Notes
- Optional **faster AI model** (`llama3.2:3b`) selectable in `nightroad.py`.
- **Ctrl+Alt+N** pauses and resumes narration.

---

## Development history (pre-1.0)

The 1.0 release came together through a lot of play-testing. The main milestones:

- Moved from an early cloud-API prototype to a **fully local** pipeline
  (Ollama + Piper).
- Consolidated from many separate voice models down to a **single multi-speaker
  model** selected by speaker index.
- Reworked attribution so the AI **never reproduces the story text** — fixing
  passages that previously cut off mid-sentence.
- Added **stat-screen detection**, the **emphasis-vs-dialogue** rule, and the
  **pacing pauses**.
- Tackled **latency** with a kept-warm model and start-up pre-warm.
- Built the **pronunciation dictionary** and verified every entry against the
  espeak phoneme output.
- Added **gender-aware casting** and **voice-quality ordering** using the speech
  dataset's own metadata.
