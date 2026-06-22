"""
test_pronunciations.py — reads every word we've respelled (plus a few we left
alone) aloud through the running pipeline, so you can hear how each lands.

Have nightroad.py running, then in a second window:
    py test_pronunciations.py

It prints each word as it speaks it, so you can note which ones sound wrong.
"""

import json
import time
import urllib.request

ENDPOINT = "http://127.0.0.1:8765/passage"

# Original spellings — the pipeline applies the respellings, so you hear the
# real in-game result. The last group is NOT corrected yet: judge those.
WORDS = [
    "Tucson",
    # clans (corrected)
    "Tzimisce", "Tremere", "Brujah", "Lasombra", "Ravnos", "Malkavian",
    "Ventrue", "Giovanni", "Hecata", "Caitiff", "Salubri", "Cappadocian",
    "Banu Haqim",
    # terms (corrected)
    "Camarilla", "Kine", "Cainite", "Vitae", "Primogen", "diablerie",
    "Vinculum", "Vaulderie", "antitribu", "Methuselah",
    # NOT corrected yet — decide if Piper says these acceptably as-is
    "Toreador", "Nosferatu", "Gangrel", "Antediluvian", "Elysium",
]


def say(word: str) -> None:
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"text": word + "."}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=60).read()


print("Reading each word aloud. Listen and note any that sound wrong.\n")
for i, w in enumerate(WORDS, 1):
    print(f"  {i:2}. {w}")
    say(w)
    time.sleep(2.5)
print("\nDone. Tell me the words (or their numbers) that need tweaking.")
