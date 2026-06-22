"""
get-voices.py — downloads the single Piper voice the pipeline uses
(en_US-libritts_r-medium), retrying politely if the download host rate-limits
you (HTTP 429). Skips the download if the voice is already present.

    py get-voices.py
"""

import os
import subprocess
import sys
import time

VOICE = "en_US-libritts_r-medium"
MAX_TRIES = 6


def have() -> bool:
    return os.path.exists(os.path.join("voices", VOICE + ".onnx"))


def main() -> None:
    if have():
        print(f"{VOICE} is already in the 'voices' folder — nothing to do.")
        return
    for attempt in range(1, MAX_TRIES + 1):
        print(f"Downloading {VOICE}  (attempt {attempt}/{MAX_TRIES})...")
        rc = subprocess.run(
            [sys.executable, "-m", "piper.download_voices",
             "--data-dir", "voices", VOICE]
        ).returncode
        if rc == 0 and have():
            print("Done. The voice model and its .onnx.json are in 'voices'.")
            return
        wait = 30 * attempt
        print(f"  failed or rate-limited — waiting {wait}s, then retrying...\n")
        time.sleep(wait)
    print("Couldn't finish the download. If you're on a VPN, turn it off and "
          "run this again — that's the usual cause of repeated 429 errors.")


if __name__ == "__main__":
    main()
