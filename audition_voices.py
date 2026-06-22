"""
audition_voices.py — listen through the libritts_r voices to find ones you like.

It speaks a sample line in each voice and says the voice number first, so you
can note the numbers you want. Goes in batches so you're not stuck hearing all
900 in one sitting. The game pipeline does NOT need to be running.

Usage:
    py audition_voices.py                 # first 20 male voices
    py audition_voices.py F               # first 20 female voices
    py audition_voices.py M 20            # male voices, skipping the first 20
    py audition_voices.py F 40 15         # female, skip 40, play 15
    py audition_voices.py all 0 30        # any gender, first 30

So to work through them, keep the same gender and bump the "skip" number by the
batch size each run (0, then 20, then 40...).
"""

import json
import os
import platform
import subprocess
import sys

MODEL = "en_US-libritts_r-medium.onnx"
VOICES_DIR = "voices"
GENDER_FILE = "voices_gender.json"
SAMPLE = "The night is long, and every road leads back to blood."
OUT = "audition.wav"

# ---- args: [gender] [skip] [count] ----
gender = (sys.argv[1].upper() if len(sys.argv) > 1 else "M")
skip = int(sys.argv[2]) if len(sys.argv) > 2 else 0
count = int(sys.argv[3]) if len(sys.argv) > 3 else 20


def load_indices() -> list[int]:
    gmap = json.load(open(GENDER_FILE))
    out = []
    for k, v in gmap.items():
        g = v["g"] if isinstance(v, dict) else v
        if gender in ("ALL", "A") or g == gender:
            out.append(int(k))
    return sorted(out)


def play(wav: str) -> None:
    if platform.system() == "Windows":
        import winsound
        winsound.PlaySound(wav, winsound.SND_FILENAME)
    else:
        player = "afplay" if platform.system() == "Darwin" else "aplay"
        subprocess.run([player, wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def synth(idx: int, text: str) -> None:
    cmd = [sys.executable, "-m", "piper", "-m", os.path.join(VOICES_DIR, MODEL),
           "-s", str(idx), "-f", OUT, "--", text]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    if not os.path.exists(GENDER_FILE):
        sys.exit(f"ERROR: {GENDER_FILE} not found — run make_gender_map.py first.")
    idxs = load_indices()
    batch = idxs[skip:skip + count]
    if not batch:
        sys.exit(f"Nothing to play — only {len(idxs)} {gender} voices exist "
                 f"(you asked to skip {skip}).")
    label = {"M": "male", "F": "female"}.get(gender, "any-gender")
    print(f"Auditioning {len(batch)} {label} voices "
          f"({skip + 1}-{skip + len(batch)} of {len(idxs)}).")
    print("Note the numbers you like.\n")
    for idx in batch:
        print(f"  voice #{idx}")
        synth(idx, f"Voice {idx}. {SAMPLE}")
        play(OUT)
    nxt = skip + count
    print(f"\nDone. For the next batch:  py audition_voices.py {gender} {nxt} {count}")


if __name__ == "__main__":
    main()
