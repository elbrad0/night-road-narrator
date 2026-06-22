"""
test_passage.py — sends one sample passage to the running pipeline so you can
hear it work before touching the game.

Run this in a SECOND command window (leave nightroad.py running in the first).
"""

import json
import urllib.request

# A made-up Night Road-flavoured passage with narration, a character (Dove),
# and one of "your" lines — so you hear all three voice types at once.
PASSAGE = (
    "The motel sign buzzed red against the dark. Dove was already leaning on "
    "your car when you pulled in. \"You took your time,\" she said, not looking "
    "up. You tell her the road was watched. \"It's always watched,\" she "
    "muttered. \"Now get in.\""
)

req = urllib.request.Request(
    "http://127.0.0.1:8765/passage",
    data=json.dumps({"text": PASSAGE}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)

print("Sending the passage... (the first one is slow while the model wakes up)\n")
with urllib.request.urlopen(req, timeout=180) as r:
    segments = json.loads(r.read())["segments"]

print("How the model split it up:\n")
for s in segments:
    print(f"  [{s.get('speaker', '?'):>11}]  {s['text']}")
print("\nYou should be hearing this read aloud now, in the other window.")
