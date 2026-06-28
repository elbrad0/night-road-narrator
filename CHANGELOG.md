# Changelog

All notable changes to **Night Road Narrator**.

## [1.3.0]

### New
- **Choices are read aloud.** Selecting a decision reads it in the narrator's
  voice; picking a different option cuts the old one off and reads the new. Stat
  tags like `[STR+Athletics]` are stripped so only the choice text is spoken.
- **Numbers, times and dates read naturally.** Digits are spelled out before
  synthesis, British style, so "650" is read "six hundred and fifty" instead of
  the old clipped "six-hundredfifty". Clock times ("6:05 a.m." becomes "six oh
  five"), ordinals ("3rd" to "third") and interstate signs ("I-10" to "I ten")
  are handled too.
- **Consistent comma pacing.** Every comma, semicolon and colon now gets the same
  short pause, so long sentences no longer rush some clauses and breathe on
  others. The length is one setting (`COMMA_SILENCE`) near the top of
  `nightroad.py`; set it to 0 to switch it off.
- **Characters keep the right gender across pages.** Each character's gender is
  remembered from any passage that makes it clear, and the previous page is fed
  in as context, so a character whose only he/she cue was on an earlier page is no
  longer mis-cast on their first spoken line. If an early guess does land wrong,
  the voice re-casts to the correct one as soon as the gender becomes clear.
- **Ctrl+Alt+D** dumps the choice area to the pipeline console — a diagnostic for
  when the game's right-click inspector is disabled.

### Reading quality
- **Faster speech.** The voice model is now kept resident in memory instead of
  reloaded for every line, so narration starts noticeably sooner. It falls back
  to the old per-line method automatically if anything goes wrong.
- **More pronunciations fixed:** Assamite ("ASS-uh-mite"), Larvae, courier,
  carrying, misdirection, teenagers and Instagram.

### Fixed
- **Mis-clicks no longer skip the dialogue.** A re-focus click (clicking off the
  window and back to use the hotkeys), an accidental click, or clicking **Next**
  used to jump to reading the pre-selected top option. A choice is now only read
  when you click that specific option, so stray clicks are ignored.

---

## [1.2.0]

### New
- **Volume hotkeys.** **Ctrl+Up** / **Ctrl+Down** adjust the narration volume in
  10% steps, live — the change is heard on the line that's already playing, not
  just the next one. **0% is a true mute.** The level is remembered between
  sessions. Only this app's volume in the Windows mixer is touched, so the game
  and OBS are left alone. (Needs `pycaw` — see the install step.)
- The console prints the **hotkey list** on startup.

### Fixed
- **Continued dialogue no longer slips into the narrator's voice.** When a
  character's speech runs across more than one quote in a turn (split by a tag
  like "Julian says." or a sentence of narration), every quote now keeps that
  character's voice instead of the continuation sometimes being read by the
  narrator.

---

## [1.1.0]

### Reading control
- **Advancing the page now interrupts narration.** Clicking **Next**, making a
  choice, or opening and closing the menu stops the current line immediately and
  reads the new text, instead of finishing the old page first — so skipping ahead
  feels responsive.

### Reading quality
- **Hyphenated compounds read correctly.** Phrases like "long-dead" no longer get
  a false full stop in the middle; a true em-dash clause break still gets its pause.
- **"Caitiff" fixed** — now a crisp "KAY-tiff" instead of slurring toward "Kate".

---

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
