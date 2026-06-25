// narrator-capture.js  (v5 — diff capture, page-change flush, pause + volume hotkeys)
// Watches the game's text and sends new story text to the local pipeline.
// On a new page it flags a replace so the pipeline stops the old page's audio.
// Press Ctrl+Alt+N to pause/resume narration (handy on stat / level-up screens).
// Press Ctrl+Up / Ctrl+Down to raise / lower the narration volume (10% steps).

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

    let fresh, replace;
    if (lastText && current.startsWith(lastText)) {
      fresh = current.slice(lastText.length).trim();
      replace = false;                      // text added to the same page
    } else {
      fresh = current;
      replace = true;                       // new page -> tell pipeline to flush
    }
    lastText = current;

    if (!fresh) { log("tick — nothing new after diff"); return; }
    log((replace ? "new page: " : "sending: ") + fresh.slice(0, 100) + (fresh.length > 100 ? "…" : ""));
    fetch(CONFIG.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: fresh, replace: replace, ts: Date.now() }),
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

  const volumeEndpoint = CONFIG.endpoint.replace("/passage", "/volume");
  function nudgeVolume(delta) {
    fetch(volumeEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ delta: delta }),
    })
      .then((r) => r.json())
      .then((d) => log("volume", d.volume + "%"))
      .catch((e) => log("volume failed:", e.message));
  }

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.altKey && (e.key === "n" || e.key === "N")) {
      e.preventDefault();
      setPaused(!paused);                      // Ctrl+Alt+N -> pause / resume
    } else if (e.ctrlKey && !e.altKey && !e.shiftKey && e.key === "ArrowUp") {
      e.preventDefault();
      nudgeVolume(10);                         // Ctrl+Up -> louder
    } else if (e.ctrlKey && !e.altKey && !e.shiftKey && e.key === "ArrowDown") {
      e.preventDefault();
      nudgeVolume(-10);                        // Ctrl+Down -> quieter
    }
  });

  log("observing body; initial #text length =", lastText.length,
      "| Ctrl+Alt+N pauses, Ctrl+Up/Down volume");

  window.__narratorCapture = {
    stop: () => { observer.disconnect(); log("stopped"); },
    pause: () => setPaused(true),
    resume: () => setPaused(false),
    louder: () => nudgeVolume(10),
    quieter: () => nudgeVolume(-10),
    resync: () => { lastText = storyText().replace(/\u00a0/g, " ").trim(); log("resynced"); },
    sendNow: () => { lastText = ""; schedule(); },
    config: CONFIG,
  };
})();
