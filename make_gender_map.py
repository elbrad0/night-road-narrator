"""
make_gender_map.py — works out each libritts_r voice's gender AND a rough
quality signal, saving the result to voices_gender.json.

The libritts_r model is built from the LibriTTS / LibriSpeech speech dataset,
which ships, for every reader: gender, which subset they're in ("clean" = the
clearer, easier-to-recognise speakers; "other" = messier), and how many minutes
of their speech was used. We map each Piper voice number back to its reader and
copy those across. No audio analysis needed.

Run once (the game pipeline doesn't need to be running):
    py make_gender_map.py

Output: voices_gender.json  ->  { "899": {"g":"M","clean":true,"min":25.2}, ... }
"""

import json
import os
import sys
import urllib.request

MODEL_JSON = os.path.join("voices", "en_US-libritts_r-medium.onnx.json")
SPEAKERS_URL = (
    "https://raw.githubusercontent.com/oscarknagg/voicemap/"
    "master/data/LibriSpeech/SPEAKERS.TXT"
)
OUT_FILE = "voices_gender.json"


def load_speaker_id_map() -> dict:
    if not os.path.exists(MODEL_JSON):
        sys.exit(f"ERROR: can't find {MODEL_JSON}\n"
                 f"Make sure the libritts_r voice (.onnx AND .onnx.json) is in "
                 f"the 'voices' folder.")
    cfg = json.load(open(MODEL_JSON, encoding="utf-8"))
    sid = cfg.get("speaker_id_map") or {}
    if not sid:
        sys.exit("ERROR: no speaker_id_map in the model settings file.")
    return {str(reader): int(idx) for reader, idx in sid.items()}


def fetch_reader_meta() -> dict:
    """reader_id -> {'g': 'M'/'F', 'subset': str, 'min': float}"""
    print("Fetching the LibriSpeech speaker list...")
    with urllib.request.urlopen(SPEAKERS_URL, timeout=60) as r:
        text = r.read().decode("utf-8", "replace")
    meta = {}
    for line in text.splitlines():
        if line.startswith(";") or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4 and parts[1] in ("M", "F"):
            try:
                minutes = float(parts[3])
            except ValueError:
                minutes = 0.0
            meta[parts[0]] = {"g": parts[1], "subset": parts[2], "min": minutes}
    print(f"  got metadata for {len(meta)} readers")
    return meta


def main() -> None:
    id_map = load_speaker_id_map()
    meta = fetch_reader_meta()

    out, missing = {}, []
    for reader, idx in id_map.items():
        m = meta.get(reader)
        if m:
            out[str(idx)] = {
                "g": m["g"],
                "clean": "clean" in m["subset"].lower(),
                "min": round(m["min"], 1),
            }
        else:
            missing.append(reader)

    json.dump(out, open(OUT_FILE, "w"), indent=2, sort_keys=True)

    males = sum(1 for v in out.values() if v["g"] == "M")
    females = sum(1 for v in out.values() if v["g"] == "F")
    clean_m = sum(1 for v in out.values() if v["g"] == "M" and v["clean"])
    clean_f = sum(1 for v in out.values() if v["g"] == "F" and v["clean"])
    print(f"\nWrote {OUT_FILE}: {len(out)} voices")
    print(f"  male:   {males:3}  ({clean_m} from the clearer 'clean' set)")
    print(f"  female: {females:3}  ({clean_f} from the clearer 'clean' set)")
    if missing:
        print(f"  ({len(missing)} voice(s) had no match and were skipped)")


if __name__ == "__main__":
    main()
