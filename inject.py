"""
inject.py — pushes narrator-capture.js into the running game automatically.
It waits both for the game window AND for the story text to actually load
before injecting, so it doesn't matter how fast or slow the game starts.

One-time install:
    py -m pip install websocket-client

Each session (or just use the launcher):
    py inject.py
"""

import json
import time
import urllib.request

try:
    from websocket import create_connection
except ImportError:
    raise SystemExit("Missing dependency. Run:  py -m pip install websocket-client")

CAPTURE_FILE = "narrator-capture.js"
DEBUG_PORT = 9222
WAIT_FOR_GAME = 60        # seconds to wait for the game window to appear
WAIT_FOR_TEXT = 60        # seconds to wait for the story text to load
TEXT_SELECTOR = "#text"


def find_game_page():
    try:
        raw = urllib.request.urlopen(f"http://localhost:{DEBUG_PORT}/json", timeout=3).read()
    except Exception:
        return None
    targets = json.loads(raw)
    pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    return pages[0] if pages else None


class CDP:
    """Tiny Chrome DevTools Protocol client over the websocket."""
    def __init__(self, ws_url):
        self.ws = create_connection(ws_url, timeout=10)
        self._id = 0

    def evaluate(self, expression):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                                 "params": {"expression": expression, "returnByValue": True}}))
        while True:                      # skip any event messages, wait for our reply
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                return msg

    def close(self):
        self.ws.close()


def main():
    print("Looking for Night Road on the debug port...")
    page = None
    for _ in range(WAIT_FOR_GAME):
        page = find_game_page()
        if page:
            break
        time.sleep(1)

    if not page:
        print("Couldn't find the game. Check that it's running and that")
        print("  --remote-debugging-port=9222  is set in Steam's launch options.")
        return

    print(f"Found it: {page.get('title', '(page)')}")
    cdp = CDP(page["webSocketDebuggerUrl"])

    print("Waiting for the story text to load...")
    check = (f"(document.querySelector('{TEXT_SELECTOR}') ? "
             f"document.querySelector('{TEXT_SELECTOR}').innerText.trim().length : 0)")
    ready = False
    for _ in range(WAIT_FOR_TEXT):
        res = cdp.evaluate(check)
        length = res.get("result", {}).get("result", {}).get("value", 0) or 0
        if length > 20:
            ready = True
            break
        time.sleep(1)

    if not ready:
        print("Story text didn't appear in time — injecting anyway. If there's no")
        print("audio, advance a page in the game and run this again.")

    src = open(CAPTURE_FILE, encoding="utf-8").read()
    res = cdp.evaluate(src)
    cdp.close()

    if res.get("result", {}).get("exceptionDetails"):
        print("Injected, but the script reported an error:")
        print(res["result"]["exceptionDetails"].get("text", res))
    else:
        print("Watcher injected and the story is loaded. Advance a page to hear it.")


if __name__ == "__main__":
    main()
