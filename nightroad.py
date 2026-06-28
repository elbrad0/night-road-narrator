"""
nightroad.py — the full local pipeline in one file.

Receives game text, works out who speaks each part, reads it aloud with Piper
in different voices, caching as it goes. Only the CONFIG block needs touching.
"""

import hashlib
import io
import json
import os
import platform
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request
import wave
from flask import Flask, request, jsonify

# ============================================================================
# CONFIG
# ============================================================================
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:7b"          # for less delay try "llama3.2:3b"
OLLAMA_KEEPALIVE = -1                # -1 = keep the model loaded indefinitely

PIPER_CMD = [sys.executable, "-m", "piper"]
VOICES_DIR = "voices"
SENTENCE_SILENCE = 0.4               # pause after each sentence (period rush fix)
COMMA_SILENCE = 0.18                 # pause at commas/clauses (set 0 to disable)
SEGMENT_GAP = 0.35                   # pause between chunks (a breath between lines)
LENGTH_SCALE = 1.1                   # speaking speed: 1.0 = normal, higher = slower

# Everything runs off the one libritts_r model. The number after "#" is the
# speaker index — the value in PARENTHESES on the samples page.
MODEL = "en_US-libritts_r-medium.onnx"
VOICES = {
    "narrator":    f"{MODEL}#22",
    "protagonist": f"{MODEL}#52",
    "unknown":     f"{MODEL}#22",
}
# Characters are cast from gender-matched pools built from voices_gender.json
# (produced by make_gender_map.py): a male character draws a male voice, etc.
GENDER_FILE = "voices_gender.json"
RESERVED_INDICES = {22, 52}            # narrator + protagonist, kept out of pools


def _build_gender_pools():
    if not os.path.exists(GENDER_FILE):
        print(f"[warn] {GENDER_FILE} not found — run make_gender_map.py. "
              f"Falling back to one mixed pool.")
        mixed = [f"{MODEL}#{i}" for i in
                 (10, 48, 92, 137, 205, 288, 361, 440, 523, 611, 704, 801)]
        return mixed, mixed
    gmap = json.load(open(GENDER_FILE))
    males, females = [], []
    for k, v in gmap.items():
        idx = int(k)
        if idx in RESERVED_INDICES:
            continue
        if isinstance(v, dict):                      # new format: gender + quality
            g, clean, mins = v.get("g"), bool(v.get("clean")), float(v.get("min", 0))
        else:                                        # old format: gender only
            g, clean, mins = v, True, 0.0
        if g == "M":
            males.append((idx, clean, mins))
        elif g == "F":
            females.append((idx, clean, mins))
    # best odds first: clean speakers, then those with the most audio behind them
    key = lambda e: (not e[1], -e[2], e[0])
    males.sort(key=key)
    females.sort(key=key)
    cm = sum(1 for _, c, _ in males if c)
    cf = sum(1 for _, c, _ in females if c)
    print(f"[voices] {len(males)} male ({cm} clean), {len(females)} female ({cf} clean)")
    return ([f"{MODEL}#{i}" for i, _, _ in males],
            [f"{MODEL}#{i}" for i, _, _ in females])


MALE_POOL, FEMALE_POOL = _build_gender_pools()

# Session memory of each character's gender, learned from any passage where the
# model is confident. A name's gender is stable, but a single passage often
# lacks the he/she cue (it was on an earlier page), so we remember it and stop
# guessing wrong. Drives re-casting if an early '?' guess put them in the wrong
# pool. Names are keyed lower-case.
SPEAKER_GENDER: dict = {}
_MALE_SET = set(MALE_POOL)
_FEMALE_SET = set(FEMALE_POOL)
LAST_PASSAGE = ""                       # previous passage text, fed as gender/identity context


def _voice_gender(voice: str) -> str:
    if voice in _FEMALE_SET:
        return "f"
    if voice in _MALE_SET:
        return "m"
    return "?"


def remember_genders(labels: list) -> None:
    """Record confident m/f genders from a passage's attributions."""
    for name, gender in labels:
        nm = str(name).strip().lower()
        if gender in ("m", "f") and nm not in ("narrator", "unknown", ""):
            SPEAKER_GENDER[nm] = gender

# Pronunciation fixes (whole-word, case-insensitive), spelled how they sound.
# These are first-pass guesses — listen and tell me which to tweak or remove.
PRONUNCIATIONS = {
    # place names
    "Tucson": "Tooson",
    # V:TM clans
    "Tzimisce": "Zimeesee",
    "Tremere": "Tremeer",
    "Brujah": "Broohaa",
    "Lasombra": "Lahsombra",
    "Ravnos": "Ravnoss",
    "Malkavian": "Malkayvian",
    "Ventrue": "Ventroo",
    "Giovanni": "Jeeohvahnee",
    "Hecata": "Heckahtaa",
    "Caitiff": "Kay-tiff",
    "Salubri": "Sahloobree",
    "Cappadocian": "Cappadohseean",
    "Banu Haqim": "Bahnoo Hahkeem",
    "Assamite": "Assa-mite",
    "Assamites": "Assa-mites",
    # society & terminology
    "Camarilla": "Cammarilla",
    "Kine": "kyne",
    "Cainite": "Kaynite",
    "Vitae": "Veetay",
    "Primogen": "Primmojen",
    "diablerie": "Dee-abblurree",
    "Methuselah": "Methooselaa",
    "Vinculum": "Vinkewlum",
    "Vaulderie": "Vawlderee",
    "antitribu": "anteetreeboo",
    "Larvae": "Lar-vay",
    # general-English words Piper mishandles (espeak gets them right; Piper diverges)
    "teenagers": "teen agers",
    "teenager": "teen ager",
    "Instagram": "insta gram",
    "courier": "koorier",
    "couriers": "kooriers",
    "carrying": "carreeng",
    "misdirection": "mizdirection",
}

SYMBOL_STRIP = "\u25cf\u25cb\u25c9\u2022\u25e6\u25c6\u25c7\u25aa\u25ab\u25a0\u25a1\u2605\u2606\u2b24\u25b2\u25bc"
STAT_DOTS = "\u25cf\u25cb\u25c9\u2b24"   # ● ○ ◉ ⬤ — only ever on stat screens

CACHE_DIR = "audio_cache"
PORT = 8765
QUOTE_CHARS = "\"\u201c\u201d"
QUOTE_RE = re.compile(r'([\u201c\u201d"][^\u201c\u201d"]*[\u201c\u201d"])')


# ============================================================================
# WHO SPEAKS EACH QUOTE  (the model only returns names — never the text)
# ============================================================================
SPEAKER_PROMPT = """You identify who speaks each quoted line in a passage from a \
Vampire: The Masquerade interactive novel (written in the second person). You \
are given the passage and a numbered list of the quotes within it.

Reply with ONLY JSON: {"speakers": [{"name": "...", "gender": "m"|"f"|"?"}, ...]} \
— exactly one entry per quote, in order.

For "name":
- Not every quoted phrase is dialogue. Quote marks are also used for emphasis, \
nicknames, slang, or a quoted term (e.g. the "kiddie pool", a "consideration"). \
If a quoted item is NOT actually spoken aloud — just an emphasised word or \
phrase inside the narration — use "narrator".
- For real spoken dialogue, use the speaking character's name exactly as it \
appears in the passage.
- Use "protagonist" for the player's own spoken lines (cued by "you say/ask/reply").
- Use "unknown" only if a line is clearly dialogue but you cannot tell who says it.
- Attribute untagged dialogue by turn-taking, and reuse KNOWN CHARACTER names.
- A character's speech may span several quotes in one turn, split by a tag like \
"Julian says." or by a sentence of narration. Every quote in that turn is the \
SAME speaker — never switch to "narrator" partway through someone speaking. Use \
"narrator" only for a short emphasised term, never for a whole spoken sentence.

For "gender": the speaker's gender from context — "m" if referred to with \
he/him or clearly male, "f" if she/her or clearly female, otherwise "?". \
Always use "?" for narrator, protagonist, and unknown."""


def has_quote(text: str) -> bool:
    return any(q in text for q in QUOTE_CHARS)


def is_stat_screen(text: str) -> bool:
    return any(d in text for d in STAT_DOTS)


def split_quotes(text: str) -> list[str]:
    """Split into alternating narration / quoted spans, in order."""
    return [p for p in QUOTE_RE.split(text) if p and p.strip()]


def is_quote(span: str) -> bool:
    return bool(span) and span[0] in QUOTE_CHARS


def attribute_quotes(passage: str, quotes: list[str], known: list[str],
                     context: str = "") -> list[tuple]:
    """Ask the model who speaks each quote and their gender.
    Returns a list of (name, gender) in quote order; gender is 'm'/'f'/'?'."""
    qlist = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(quotes))
    chars = ", ".join(sorted(known)) or "(none yet)"
    ctx = (f"RECENT CONTEXT (earlier text, for working out who a speaker is and "
           f"their gender — do NOT attribute quotes to it):\n{context}\n\n"
           if context.strip() else "")
    user = f"KNOWN CHARACTERS: {chars}\n\n{ctx}PASSAGE:\n{passage}\n\nQUOTES:\n{qlist}"
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "keep_alive": OLLAMA_KEEPALIVE,
        "options": {"temperature": 0, "num_predict": 512},
        "messages": [
            {"role": "system", "content": SPEAKER_PROMPT},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")

    def norm_gender(g) -> str:
        g = str(g).strip().lower()
        return g[0] if g and g[0] in ("m", "f") else "?"

    try:
        req = urllib.request.Request(OLLAMA_URL, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = json.loads(r.read())["message"]["content"]
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        data = json.loads(raw)
        items = data.get("speakers", data) if isinstance(data, dict) else data
        out = []
        for it in items:
            if isinstance(it, dict):
                out.append((str(it.get("name", "unknown")), norm_gender(it.get("gender"))))
            else:
                out.append((str(it), "?"))
        return out
    except Exception as e:
        print("[attribute] failed:", e)
        return []


def quote_inner(span: str) -> str:
    return span.strip(QUOTE_CHARS).strip()


def is_emphasis(span: str) -> bool:
    """A quoted phrase starting lowercase is almost always an emphasised term,
    not spoken dialogue (which starts with a capital). So -> narrator voice."""
    first = next((c for c in quote_inner(span) if c.isalpha()), "")
    return first.islower()


def carry_forward_speakers(labels: list[tuple], quotes: list[str]) -> list[tuple]:
    """Safety net for continued dialogue. Every quote here is real speech (emphasis
    was filtered out before the model saw it), so a quote the model tagged
    narrator/unknown that is clearly a spoken sentence almost certainly continues
    the previous speaker's turn — inherit them so it keeps the right voice. Short
    quoted terms (no sentence shape) are left alone."""
    fixed = list(labels)
    last = None                                  # last identified (name, gender)
    for i, (name, gender) in enumerate(fixed):
        if str(name).strip().lower() not in ("narrator", "unknown", ""):
            last = (name, gender)
        elif last is not None and i < len(quotes):
            inner = quote_inner(quotes[i])
            if len(inner.split()) > 4 or inner.rstrip()[-1:] in "?!":
                fixed[i] = last                  # continuation -> previous speaker
    return fixed


def segment_passage(text: str) -> list[dict]:
    """Split locally; the model only labels real dialogue. Text is never lost."""
    global LAST_PASSAGE
    spans = split_quotes(text)
    dialogue = [s for s in spans if is_quote(s) and not is_emphasis(s)]
    if not dialogue:                       # no real speech -> all narration
        LAST_PASSAGE = text[-500:]         # keep as context for the next passage
        return [{"speaker": "narrator", "gender": "?", "text": text}]

    labels = attribute_quotes(text, dialogue, list(KNOWN), context=LAST_PASSAGE)
    labels = carry_forward_speakers(labels, dialogue)
    remember_genders(labels)               # learn genders so we stop guessing wrong
    LAST_PASSAGE = text[-500:]
    print(f"[attr] {len(dialogue)} line(s) -> {labels}")
    segs, qi = [], 0
    for s in spans:
        if is_quote(s) and not is_emphasis(s):
            name, gender = labels[qi] if qi < len(labels) else ("unknown", "?")
            segs.append({"speaker": name or "unknown", "gender": gender, "text": s})
            qi += 1
        else:                              # narration, or an emphasised quote
            segs.append({"speaker": "narrator", "gender": "?", "text": s})
    # Stitch neighbours that share a voice, so narration around an emphasised
    # quote reads as one smooth unit instead of choppy fragments with gaps.
    merged: list[dict] = []
    for seg in segs:
        if merged and merged[-1]["speaker"] == seg["speaker"]:
            merged[-1]["text"] += " " + seg["text"]
        else:
            merged.append(dict(seg))
    return merged


# ============================================================================
# SPEECH CLEAN-UP
# ============================================================================
# ---------------------------------------------------------------------------
# Numbers -> words. Piper's built-in digit expansion mangles the cadence
# ("650" comes out "six<pause>hundredfifty"), so we spell numbers out as plain
# British-style words before synthesis and let the engine read them normally.
# ---------------------------------------------------------------------------
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]
_SCALES = [(1_000_000_000, "billion"), (1_000_000, "million"),
           (1_000, "thousand"), (100, "hundred")]
_ORDINAL_IRREG = {"one": "first", "two": "second", "three": "third",
                  "five": "fifth", "eight": "eighth", "nine": "ninth",
                  "twelve": "twelfth"}


def _int_to_words(n: int) -> str:
    if n < 0:
        return "minus " + _int_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")
    for value, name in _SCALES:
        if n >= value:
            head, rem = _int_to_words(n // value), n % value
            out = head + " " + name
            if rem:                                   # British 'and' before a sub-100 tail
                out += (" and " if rem < 100 else " ") + _int_to_words(rem)
            return out
    return _ONES[n]


def _ordinal_words(n: int) -> str:
    w = _int_to_words(n)
    last = w.split()[-1].split("-")[-1]
    if last in _ORDINAL_IRREG:
        return w[: len(w) - len(last)] + _ORDINAL_IRREG[last]
    if last.endswith("y"):                            # twenty -> twentieth
        return w[:-1] + "ieth"
    return w + "th"


def numbers_to_words(text: str) -> str:
    text = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b",
                  lambda m: _ordinal_words(int(m.group(1))), text, flags=re.IGNORECASE)

    def card(m):
        whole, frac = m.group(1).replace(",", ""), m.group(2)
        try:
            words = _int_to_words(int(whole))
        except (ValueError, OverflowError):
            return m.group(0)
        if frac:
            words += " point " + " ".join(_ONES[int(d)] for d in frac)
        return words
    return re.sub(r"\b(\d[\d,]*)(?:\.(\d+))?\b", card, text)


def _time_to_words(text: str) -> str:
    """Clock times: '6:05' -> 'six oh five', '6:41' -> 'six forty one', '6:00' -> 'six'.
    Runs before number expansion so the colon never becomes a spurious pause."""
    def repl(m):
        h, mnt = int(m.group(1)), int(m.group(2))
        if not (0 <= h <= 23 and 0 <= mnt <= 59):
            return m.group(0)                     # not a real time -> leave alone
        hw = _int_to_words(h)
        if mnt == 0:
            return hw
        if mnt < 10:
            return f"{hw} oh {_int_to_words(mnt)}"
        return f"{hw} {_int_to_words(mnt)}"
    return re.sub(r"\b(\d{1,2}):(\d{2})\b", repl, text)


def highways_to_words(text: str) -> str:
    """Road designations like 'I-10' read as 'eyeten' because the hyphen welds
    them. Split the letter off so it reads 'I ten'. Single-letter routes only
    (I-10, I-19); multi-letter ones (US-60) can be added if they come up."""
    return re.sub(r"\b([A-Z])-(\d{1,4})\b", r"\1 \2", text)


def clean_for_speech(text: str) -> str:
    for ch in SYMBOL_STRIP:
        text = text.replace(ch, " ")
    text = text.replace("(", " , ").replace(")", " , ")   # parentheses -> brief pause
    # Dash handling. An em-dash (—) is a clause break -> a full sentence pause
    # (capitalise the next word so the engine treats it as a true full stop).
    # An en-dash (–) tucked tight between two words or numbers is a compound or
    # range ("long–dead", "1990–2000") -> read as a hyphen, NOT a sentence break.
    text = re.sub(r"\u2014\s*([A-Za-z])", lambda m: ". " + m.group(1).upper(), text)
    text = re.sub(r"\s+[\u2012\u2013\u2015\u2e3a\u2e3b]\s*([A-Za-z])",
                  lambda m: ". " + m.group(1).upper(), text)        # spaced dash
    text = re.sub(r"(?<=\w)[\u2012\u2013\u2015\u2e3a\u2e3b](?=\w)", "-", text)  # compound
    text = re.sub(r"[\u2012-\u2015\u2e3a\u2e3b]", ". ", text)       # any leftover dash
    text = highways_to_words(text)                                  # I-10 -> I 10 (gap)
    text = _time_to_words(text)                                     # 6:05 -> six oh five
    text = numbers_to_words(text)                                   # 650 -> six hundred and fifty
    for word, say in PRONUNCIATIONS.items():
        text = re.sub(rf"\b{re.escape(word)}\b", say, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.])", r"\1", text)     # no space before comma/period
    text = re.sub(r"(,\s*){2,}", ", ", text)     # collapse repeated commas
    return text.strip(" ,")


# ============================================================================
# VOICE ASSIGNMENT
# ============================================================================
VOICE_FILE = "voices.json"


def load_voice_map() -> dict:
    if os.path.exists(VOICE_FILE):
        return json.load(open(VOICE_FILE))
    return dict(VOICES)


def voice_for(speaker: str, gender: str, vmap: dict) -> str:
    nm = speaker.strip().lower()
    # a remembered, confident gender beats this passage's guess (incl. a bare '?')
    eff = SPEAKER_GENDER.get(nm) or (gender if gender in ("m", "f") else "?")

    cur = vmap.get(speaker)
    recast = False
    if cur is not None and eff in ("m", "f") and _voice_gender(cur) not in ("?", eff):
        cur = None                         # locked to the wrong gender -> re-cast
        recast = True

    if cur is None:
        used = {v for k, v in vmap.items() if k != speaker}
        pool = FEMALE_POOL if eff == "f" else MALE_POOL      # '?' still defaults male
        nxt = next((v for v in pool if v not in used), None)
        if nxt is None:                    # pool exhausted -> borrow from the other
            other = MALE_POOL if pool is FEMALE_POOL else FEMALE_POOL
            nxt = next((v for v in other if v not in used),
                       pool[0] if pool else VOICES["unknown"])
        vmap[speaker] = nxt
        json.dump(vmap, open(VOICE_FILE, "w"), indent=2)
        tag = {"m": "male", "f": "female"}.get(eff, "gender unknown -> male")
        verb = "recast" if recast else "new character"
        print(f"[voice] {verb} '{speaker}' ({tag}) -> {nxt}")
    return vmap[speaker]


# ============================================================================
# VOICE QUEUE
# ============================================================================
os.makedirs(CACHE_DIR, exist_ok=True)
seg_q: "queue.Queue" = queue.Queue()
play_q: "queue.Queue" = queue.Queue()
EPOCH = 0                                # bumped on flush; stale items are skipped

VOL_FILE = "volume.json"                 # remembers the volume between sessions
VOLUME = 100                             # 0-100; applied to every clip as it plays


def flush():
    """A new page arrived — drop everything still queued from the previous one."""
    global EPOCH
    EPOCH += 1
    for q in (seg_q, play_q):
        try:
            while True:
                q.get_nowait()
                q.task_done()
        except queue.Empty:
            pass


def load_volume():
    """Restore the saved volume on startup (defaults to 100%)."""
    global VOLUME
    try:
        with open(VOL_FILE, encoding="utf-8") as f:
            VOLUME = int(json.load(f).get("volume", 100))
    except Exception:
        VOLUME = 100
    VOLUME = max(0, min(100, VOLUME))


def save_volume():
    try:
        with open(VOL_FILE, "w", encoding="utf-8") as f:
            json.dump({"volume": VOLUME}, f)
    except Exception as e:
        print("[volume] could not save:", e)


_vol_session = None                      # ISimpleAudioVolume iface | None (retry) | False (give up)
_vol_last = None                         # last level actually pushed to the mixer
_vol_warned = False


def _acquire_session():
    """Find this process's entry in the Windows volume mixer."""
    from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
    pid = os.getpid()
    for s in AudioUtilities.GetAllSessions():
        if s.Process and s.Process.pid == pid:
            return s._ctl.QueryInterface(ISimpleAudioVolume)
    return None


def apply_volume():
    """Push the current VOLUME to this app's mixer slider, live. Called every poll
    while a clip plays, so a hotkey is heard at once. Cheap once the session is
    cached; retries until the session exists; gives up quietly if pycaw is absent.
    Controls only our process — the game and OBS are untouched."""
    global _vol_session, _vol_last, _vol_warned
    if platform.system() != "Windows" or _vol_session is False:
        return
    if _vol_session is not None and _vol_last == VOLUME:
        return                                       # already at this level
    try:
        if _vol_session is None:
            _vol_session = _acquire_session()        # may be None if not registered yet
        if _vol_session:
            _vol_session.SetMasterVolume(VOLUME / 100.0, None)
            _vol_last = VOLUME
    except Exception:
        try:
            _vol_session = _acquire_session()        # session recreated -> re-acquire once
            if _vol_session:
                _vol_session.SetMasterVolume(VOLUME / 100.0, None)
                _vol_last = VOLUME
        except Exception as e:
            _vol_session = False                     # pycaw unusable -> stop trying
            if not _vol_warned:
                print("[volume] live volume needs pycaw — run:  py -m pip install pycaw comtypes")
                print("        (", e, ")")
                _vol_warned = True


def cache_path(voice: str, text: str) -> str:
    key = hashlib.sha1(
        (voice + "\x00" + text + "\x00" + str(SENTENCE_SILENCE)
         + "\x00" + str(LENGTH_SCALE)).encode("utf-8")
    ).hexdigest()
    return os.path.join(CACHE_DIR, key + ".wav")


_PIPER_VOICES = {}                     # model_path -> loaded PiperVoice (kept resident)
_PIPER_LOCK = threading.Lock()
_PIPER_INPROCESS = True                # flips False if the in-process API isn't usable


def _sentences(text: str) -> list[str]:
    return [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]


def _clauses(sentence: str) -> list[str]:
    """Split a sentence at commas / semicolons / colons so each clause can be
    synthesised on its own and given a uniform short pause. Piper's own comma
    timing is erratic — sometimes a beat, sometimes none — so we take it over."""
    return [c.strip() for c in re.split(r"\s*[,;:]\s+", sentence) if c.strip()]


def _speech_segments(text: str) -> list[tuple]:
    """Yield (clause, trailing_silence_seconds). Full stops get SENTENCE_SILENCE,
    internal commas get the smaller COMMA_SILENCE, the very last clause gets none."""
    segs, sents = [], _sentences(text) or [text]
    for si, sent in enumerate(sents):
        clauses = (_clauses(sent) if COMMA_SILENCE else [sent]) or [sent]
        for ci, clause in enumerate(clauses):
            last_in_sent = ci == len(clauses) - 1
            last_overall = last_in_sent and si == len(sents) - 1
            if last_overall:
                gap = 0.0
            elif last_in_sent:
                gap = SENTENCE_SILENCE
            else:
                gap = COMMA_SILENCE
            segs.append((clause, gap))
    return segs


def _get_voice(model_path: str):
    """Load a Piper voice once and keep it in memory (no per-line model reload)."""
    pv = _PIPER_VOICES.get(model_path)
    if pv is None:
        with _PIPER_LOCK:                          # double-checked: load only once
            pv = _PIPER_VOICES.get(model_path)
            if pv is None:
                from piper import PiperVoice
                pv = PiperVoice.load(model_path)
                _PIPER_VOICES[model_path] = pv
                print(f"[synth] Piper loaded in-process (resident): {os.path.basename(model_path)}")
    return pv


def _synth_inprocess(model_path: str, speaker: str, text: str, out: str) -> None:
    """Synthesize with the resident voice. The in-process API has no
    sentence-silence option, so we synth each sentence and splice the same pause
    between them that the CLI's --sentence-silence gave us."""
    from piper import SynthesisConfig
    pv = _get_voice(model_path)
    cfg = SynthesisConfig(
        speaker_id=int(speaker) if speaker else None,
        length_scale=float(LENGTH_SCALE),
    )
    pieces, params = [], None
    segs = _speech_segments(text) or [(text, 0.0)]
    for clause, gap in segs:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            pv.synthesize_wav(clause, wf, cfg)
        buf.seek(0)
        with wave.open(buf, "rb") as wr:
            if params is None:
                params = wr.getparams()
            pieces.append(wr.readframes(wr.getnframes()))
        if gap > 0 and params is not None:
            pieces.append(b"\x00" * (params.sampwidth * params.nchannels
                                     * int(params.framerate * gap)))
    if params is None:
        raise RuntimeError("no audio produced")
    tmp = out + ".tmp"
    with wave.open(tmp, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(b"".join(pieces))
    os.replace(tmp, out)                            # atomic: out only appears complete


def _synth_cli(model_path: str, speaker: str, text: str, out: str) -> str:
    """Fallback: the original per-call Piper CLI (slower, but always works)."""
    cmd = PIPER_CMD + ["-m", model_path]
    if speaker:
        cmd += ["-s", speaker]
    if SENTENCE_SILENCE:
        cmd += ["--sentence-silence", str(SENTENCE_SILENCE)]
    cmd += ["--length-scale", str(LENGTH_SCALE), "-f", out, "--", text]
    try:
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print("[synth] piper failed:", e)
        return ""
    return out


def synth(voice: str, text: str) -> str:
    out = cache_path(voice, text)
    if os.path.exists(out):
        return out
    model_file, _, speaker = voice.partition("#")
    model_path = os.path.join(VOICES_DIR, model_file)
    global _PIPER_INPROCESS
    if _PIPER_INPROCESS:
        try:
            _synth_inprocess(model_path, speaker, text, out)
            return out
        except Exception as e:
            _PIPER_INPROCESS = False                # API mismatch / load issue -> CLI
            print("[synth] in-process Piper unavailable -> using CLI from now on. Reason:", e)
    return _synth_cli(model_path, speaker, text, out)


def wav_duration(path: str) -> float:
    """Length of a wav in seconds, so async playback knows when it's done."""
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            return w.getnframes() / float(rate) if rate else 0.0
    except Exception:
        return 0.0


def play(wav: str, epoch: int) -> None:
    """Play a clip, but bail out the instant a new page arrives (EPOCH bumped).
    Volume is applied live to the mixer while it plays, so a hotkey is heard at
    once rather than waiting for the next clip."""
    if not wav or not os.path.exists(wav):
        return
    if platform.system() == "Windows":
        # Use the Media Control Interface (winmm) rather than winsound: it has a
        # real 'stop' command and a queryable state, so a new page can cut the
        # current clip off cleanly (winsound's SND_PURGE doesn't reliably stop).
        import ctypes
        winmm = ctypes.windll.winmm

        def mci(cmd: str) -> int:
            return winmm.mciSendStringW(cmd, None, 0, None)

        alias = "nrclip"
        mci(f"close {alias}")                                  # clear any stale handle
        if mci(f'open "{wav}" type waveaudio alias {alias}') != 0:
            import winsound                                    # fallback: plain play
            winsound.PlaySound(wav, winsound.SND_FILENAME)
            return
        try:
            mci(f"play {alias}")
            buf = ctypes.create_unicode_buffer(32)
            deadline = time.time() + wav_duration(wav) + 1.0   # safety cap
            while time.time() < deadline:
                if epoch != EPOCH:                             # Next was clicked
                    break
                apply_volume()                                 # live volume (cheap when unchanged)
                winmm.mciSendStringW(f"status {alias} mode", buf, 32, None)
                if buf.value and buf.value != "playing":       # finished naturally
                    break
                time.sleep(0.02)
        finally:
            mci(f"stop {alias}")
            mci(f"close {alias}")
    else:
        player = "afplay" if platform.system() == "Darwin" else "aplay"
        proc = subprocess.Popen([player, wav],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while proc.poll() is None:
            if epoch != EPOCH:
                proc.terminate()
                return
            time.sleep(0.02)


def synth_worker():
    while True:
        epoch, voice, text = seg_q.get()
        if epoch == EPOCH:
            play_q.put((epoch, synth(voice, text)))
        seg_q.task_done()


def play_worker():
    if platform.system() == "Windows":
        try:
            import comtypes
            comtypes.CoInitialize()              # COM lives in this one thread (for pycaw)
        except Exception:
            pass
    while True:
        epoch, wav = play_q.get()
        if epoch == EPOCH:
            play(wav, epoch)
            if wav and epoch == EPOCH:               # no gap if we were cut off
                time.sleep(SEGMENT_GAP)
        play_q.task_done()


# ============================================================================
# SERVER
# ============================================================================
app = Flask(__name__)
KNOWN: set[str] = set()


@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r


@app.route("/passage", methods=["POST", "OPTIONS"])
def passage():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(force=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"segments": []})
    flush()        # any new text = the player advanced -> stop the old narration first

    print(f"[recv] {len(text)} chars / {text.count(chr(10)) + 1} line(s): {text[:90]!r}")
    vmap = load_voice_map()
    out_segments = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if is_stat_screen(line):
            print("[skip] stat line")
            continue
        for seg in segment_passage(line):
            sp = seg.get("speaker", "narrator")
            if sp not in ("narrator", "protagonist", "unknown"):
                KNOWN.add(sp)
            vf = voice_for(sp, seg.get("gender", "?"), vmap)
            spoken = clean_for_speech(seg["text"])
            if spoken:
                seg_q.put((EPOCH, vf, spoken))
                out_segments.append(seg)
    return jsonify({"segments": out_segments})


@app.route("/volume", methods=["POST", "OPTIONS"])
def volume():
    if request.method == "OPTIONS":
        return ("", 204)
    global VOLUME
    data = request.get_json(force=True) or {}
    if "set" in data:
        VOLUME = int(data["set"])
    else:
        VOLUME = VOLUME + int(data.get("delta", 0))
    VOLUME = max(0, min(100, VOLUME))        # clamp 0-100, in 10% steps from the keys
    save_volume()
    print(f"[volume] {VOLUME}%")
    return jsonify({"volume": VOLUME})


@app.route("/choice", methods=["POST", "OPTIONS"])
def choice():
    """Read a selected decision aloud in the narrator's voice. Selecting a
    different choice flushes first, so the old one is cut off and the new one
    plays — same behaviour as advancing a page. Always narrator: the whole
    choice (quotes and all) is read in one voice, with no speaker attribution."""
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(force=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"ok": True})
    flush()                                  # cut off the previous choice / narration
    print(f"[choice] {text[:90]!r}")
    spoken = re.sub(r"\s*\[[^\]]*\]", "", text).strip() or text   # drop [STR+Athletics] tags
    spoken = clean_for_speech(spoken)
    if spoken:
        seg_q.put((EPOCH, VOICES["narrator"], spoken))
    return jsonify({"ok": True})


@app.route("/debug", methods=["POST", "OPTIONS"])
def debug():
    """Print whatever the watcher sends to the pipeline console — used to capture
    the choice DOM when right-click inspect is unavailable in the game."""
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(force=True) or {}
    print("\n==== [debug] watcher dump | radios found:", data.get("radios"), "====")
    print(data.get("info", "")[:4000])
    print("==== [end debug] ====\n")
    return jsonify({"ok": True})


def prewarm():
    """Warm the model + speech engine so the first line isn't slow, and report
    whether Piper is running in-process (resident) or has fallen back to the CLI.
    Runs a real synth (bypassing the cache) so the status always prints."""
    global _PIPER_INPROCESS
    attribute_quotes('"Hello," she said.', ['"Hello,"'], [])
    if _PIPER_INPROCESS:
        probe = os.path.join(CACHE_DIR, "_prewarm.wav")
        try:
            v = VOICES["narrator"]
            _synth_inprocess(os.path.join(VOICES_DIR, v.partition("#")[0]),
                             v.partition("#")[2], "Ready.", probe)
        except Exception as e:
            _PIPER_INPROCESS = False
            print("[synth] in-process Piper unavailable -> using CLI. Reason:", e)
        finally:
            try:
                os.remove(probe)
            except OSError:
                pass
    if not _PIPER_INPROCESS:
        synth(VOICES["narrator"], "Ready.")      # CLI path: warm + cache the clip
    print("[prewarm] model loaded and ready")


if __name__ == "__main__":
    load_volume()
    threading.Thread(target=synth_worker, daemon=True).start()
    threading.Thread(target=play_worker, daemon=True).start()
    threading.Thread(target=prewarm, daemon=True).start()
    print(f"Pipeline ready (v1.3.0) on http://127.0.0.1:{PORT}  |  volume {VOLUME}%")
    print("  Hotkeys (focus the game window first):")
    print("    Ctrl+Alt+N   pause / resume narration")
    print("    Ctrl+Up      volume up    (+10%)")
    print("    Ctrl+Down    volume down  (-10%)")
    app.run(host="127.0.0.1", port=PORT)
