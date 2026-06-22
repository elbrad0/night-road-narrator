"""
nightroad.py — the full local pipeline in one file.

Receives game text, works out who speaks each part, reads it aloud with Piper
in different voices, caching as it goes. Only the CONFIG block needs touching.
"""

import hashlib
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
SEGMENT_GAP = 0.35                   # pause between chunks (a breath between lines)
LENGTH_SCALE = 1.1                   # speaking speed: 1.0 = normal, higher = slower

# Everything runs off the one libritts_r model. The number after "#" is the
# speaker index — the value in PARENTHESES on the samples page.
MODEL = "en_US-libritts_r-medium.onnx"
VOICES = {
    "narrator":    f"{MODEL}#899",
    "protagonist": f"{MODEL}#885",
    "unknown":     f"{MODEL}#899",
}
# Characters are cast from gender-matched pools built from voices_gender.json
# (produced by make_gender_map.py): a male character draws a male voice, etc.
GENDER_FILE = "voices_gender.json"
RESERVED_INDICES = {899, 885}            # narrator + protagonist, kept out of pools


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
    "Caitiff": "Kaytiff",
    "Salubri": "Sahloobree",
    "Cappadocian": "Cappadohseean",
    "Banu Haqim": "Bahnoo Hahkeem",
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


def attribute_quotes(passage: str, quotes: list[str], known: list[str]) -> list[tuple]:
    """Ask the model who speaks each quote and their gender.
    Returns a list of (name, gender) in quote order; gender is 'm'/'f'/'?'."""
    qlist = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(quotes))
    chars = ", ".join(sorted(known)) or "(none yet)"
    user = f"KNOWN CHARACTERS: {chars}\n\nPASSAGE:\n{passage}\n\nQUOTES:\n{qlist}"
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


def segment_passage(text: str) -> list[dict]:
    """Split locally; the model only labels real dialogue. Text is never lost."""
    spans = split_quotes(text)
    dialogue = [s for s in spans if is_quote(s) and not is_emphasis(s)]
    if not dialogue:                       # no real speech -> all narration
        return [{"speaker": "narrator", "gender": "?", "text": text}]

    labels = attribute_quotes(text, dialogue, list(KNOWN))
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
def clean_for_speech(text: str) -> str:
    for ch in SYMBOL_STRIP:
        text = text.replace(ch, " ")
    text = text.replace("(", " , ").replace(")", " , ")   # parentheses -> brief pause
    # em / en dash -> a real sentence break. Capitalise the following word so
    # the engine treats it as a true full stop and gives a full-length pause
    # (a lowercase word after a period is NOT treated as a sentence end).
    text = re.sub(r"[\u2012-\u2015\u2e3a\u2e3b]\s*([A-Za-z])",
                  lambda m: ". " + m.group(1).upper(), text)
    text = re.sub(r"[\u2012-\u2015\u2e3a\u2e3b]", ". ", text)   # dash before non-letter
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
    if speaker not in vmap:
        used = set(vmap.values())
        pool = FEMALE_POOL if gender == "f" else MALE_POOL   # '?' defaults to male
        nxt = next((v for v in pool if v not in used), None)
        if nxt is None:                    # pool exhausted -> borrow from the other
            other = MALE_POOL if pool is FEMALE_POOL else FEMALE_POOL
            nxt = next((v for v in other if v not in used),
                       pool[0] if pool else VOICES["unknown"])
        vmap[speaker] = nxt
        json.dump(vmap, open(VOICE_FILE, "w"), indent=2)
        tag = {"m": "male", "f": "female"}.get(gender, "gender unknown -> male")
        print(f"[voice] new character '{speaker}' ({tag}) -> {nxt}")
    return vmap[speaker]


# ============================================================================
# VOICE QUEUE
# ============================================================================
os.makedirs(CACHE_DIR, exist_ok=True)
seg_q: "queue.Queue" = queue.Queue()
play_q: "queue.Queue" = queue.Queue()


def cache_path(voice: str, text: str) -> str:
    key = hashlib.sha1(
        (voice + "\x00" + text + "\x00" + str(SENTENCE_SILENCE)
         + "\x00" + str(LENGTH_SCALE)).encode("utf-8")
    ).hexdigest()
    return os.path.join(CACHE_DIR, key + ".wav")


def synth(voice: str, text: str) -> str:
    out = cache_path(voice, text)
    if os.path.exists(out):
        return out
    model_file, _, speaker = voice.partition("#")
    model = os.path.join(VOICES_DIR, model_file)
    cmd = PIPER_CMD + ["-m", model]
    if speaker:
        cmd += ["-s", speaker]
    if SENTENCE_SILENCE:
        cmd += ["--sentence-silence", str(SENTENCE_SILENCE)]
    cmd += ["--length-scale", str(LENGTH_SCALE)]
    cmd += ["-f", out, "--", text]
    try:
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print("[synth] piper failed:", e)
        return ""
    return out


def play(wav: str) -> None:
    if not wav or not os.path.exists(wav):
        return
    if platform.system() == "Windows":
        import winsound
        winsound.PlaySound(wav, winsound.SND_FILENAME)
    else:
        player = "afplay" if platform.system() == "Darwin" else "aplay"
        subprocess.run([player, wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def synth_worker():
    while True:
        voice, text = seg_q.get()
        play_q.put(synth(voice, text))
        seg_q.task_done()


def play_worker():
    while True:
        wav = play_q.get()
        play(wav)
        if wav:
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
    text = (request.get_json(force=True) or {}).get("text", "").strip()
    if not text:
        return jsonify({"segments": []})

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
                seg_q.put((vf, spoken))
                out_segments.append(seg)
    return jsonify({"segments": out_segments})


def prewarm():
    """Load the model into memory at startup so the first page isn't slow."""
    attribute_quotes('"Hello," she said.', ['"Hello,"'], [])
    synth(VOICES["narrator"], "Ready.")          # warm the speech engine too
    print("[prewarm] model loaded and ready")


if __name__ == "__main__":
    threading.Thread(target=synth_worker, daemon=True).start()
    threading.Thread(target=play_worker, daemon=True).start()
    threading.Thread(target=prewarm, daemon=True).start()
    print(f"Pipeline ready (v1.0.0) on http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT)
