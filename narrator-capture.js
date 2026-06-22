// narrator-capture.js  (v3 — diff-based capture + pause hotkey)
// Watches the game's text and sends new story text to the local pipeline.
// Press Ctrl+Alt+N to pause/resume narration (handy on stat / level-up screens).

(() => {
  "use strict";

  const CONFIG = {
    endpoint: "http://127.0.0.1:8765/passage",
    debounceMs: 250,
    textSelector: "#text",
    debug: true,
  };

  const log = (...a) => CONFIG.debug && console.log("[capture]", ...a);

  function storyText() {
    const el = document.querySelector(CONFIG.textSelector);
    return el ? (el.innerText || el.textContent || "") : "";
  }

  let lastText = storyText().replace(/\u00a0/g, " ").trim();
  let timer = null;
  let paused = false;

  function diffAndSend() {
    timer = null;
    const current = storyText().replace(/\u00a0/g, " ").trim();
    if (paused) { lastText = current; return; }     // stay in sync, send nothing
    if (!current || current === lastText) { log("tick — no new text"); return; }

    let fresh;
    if (lastText && current.startsWith(lastText)) {
      fresh = current.slice(lastText.length).trim();
    } else {
      fresh = current;
    }
    lastText = current;

    if (!fresh) { log("tick — nothing new after diff"); return; }
    log("sending:", fresh.slice(0, 100) + (fresh.length > 100 ? "…" : ""));
    fetch(CONFIG.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: fresh, ts: Date.now() }),
    }).then(() => log("POST ok")).catch((e) => log("POST failed:", e.message));
  }

  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(diffAndSend, CONFIG.debounceMs);
  }

  const observer = new MutationObserver(() => schedule());
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });

  function setPaused(p) {
    paused = p;
    lastText = storyText().replace(/\u00a0/g, " ").trim();   // don't replay backlog
    log(paused ? "PAUSED (Ctrl+Alt+N to resume)" : "RESUMED");
  }

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.altKey && (e.key === "n" || e.key === "N")) {
      e.preventDefault();
      setPaused(!paused);
    }
  });

  log("observing body; initial #text length =", lastText.length, "| Ctrl+Alt+N pauses");

  window.__narratorCapture = {
    stop: () => { observer.disconnect(); log("stopped"); },
    pause: () => setPaused(true),
    resume: () => setPaused(false),
    resync: () => { lastText = storyText().replace(/\u00a0/g, " ").trim(); log("resynced"); },
    sendNow: () => { lastText = ""; schedule(); },
    config: CONFIG,
  };
})();
