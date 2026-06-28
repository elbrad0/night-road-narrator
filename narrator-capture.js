// narrator-capture.js  (v7 — story capture, page-change flush, choice reading, hotkeys)
// Watches the game's text and sends new story text to the local pipeline.
// On a new page it flags a replace so the pipeline stops the old page's audio.
// When a decision is selected (its radio button), it reads that choice aloud;
// picking a different one cuts the old off and reads the new.
// v7: a choice is only read when the click lands on one specific option row, so
// refocus clicks, Next, and stray clicks no longer skip to the top option.
// Press Ctrl+Alt+N to pause/resume narration (handy on stat / level-up screens).
// Press Ctrl+Up / Ctrl+Down to raise / lower the narration volume (10% steps).
// Press Ctrl+Alt+D to dump the choice DOM to the pipeline console (diagnostic).

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
  let lastChoice = "";

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
      lastChoice = "";                       // new page -> new choices may repeat text
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

  // --- read the selected decision (radio button gets the blue dot) ----------
  const choiceEndpoint = CONFIG.endpoint.replace("/passage", "/choice");
  function sendChoice(text) {
    log("choice:", text.slice(0, 80) + (text.length > 80 ? "…" : ""));
    fetch(choiceEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    }).then(() => log("choice POST ok")).catch((e) => log("choice failed:", e.message));
  }

  function choiceTextFrom(radio) {
    // the choice text lives in the enclosing label (or list item / parent)
    const host = radio.closest("label") || radio.closest("li") || radio.parentElement;
    return host ? (host.innerText || host.textContent || "").replace(/\s+/g, " ").trim() : "";
  }

  function findChoiceRadio(target) {
    // Only treat a click as a *selection* when it lands on one specific option
    // row. The old version walked up and grabbed the first radio under any
    // ancestor, so a refocus click, a Next click, or a stray click on the
    // choice container all matched the top (pre-selected) option and read it.
    if (!target || !target.closest) return null;
    if (target.matches && target.matches('input[type="radio"]')) return target;
    let n = target;
    for (let i = 0; n && n !== document.body && i < 6; i++) {
      if (n.matches && n.matches("label, li")) {
        const radios = n.querySelectorAll('input[type="radio"]');
        if (radios.length === 1) return radios[0];   // exactly one = a real option
        if (radios.length > 1) return null;           // a container, not a choice
      }
      n = n.parentElement;
    }
    return null;                                       // empty space / Next / button
  }

  // Listen on the CAPTURE phase: ChoiceScript sets the radio with .checked in its
  // own click handler (which fires no 'change' event), so we catch the click first.
  document.addEventListener("click", (e) => {
    if (paused) return;
    const radio = findChoiceRadio(e.target);
    if (!radio) return;
    const txt = choiceTextFrom(radio);
    if (txt && txt !== lastChoice) {            // a different decision was picked
      lastChoice = txt;
      sendChoice(txt);                          // pipeline flushes -> old audio cuts off
    }
  }, true);

  // Diagnostic: dump the choice DOM to the PIPELINE console (Ctrl+Alt+D), since
  // right-click inspect is disabled in the game window.
  function dumpChoiceDom() {
    const radios = document.querySelectorAll('input[type="radio"]');
    let target = radios.length
      ? (radios[0].closest("ul, ol, form, fieldset, div") || radios[0].parentElement)
      : (document.querySelector("form, ul.choices, .choices") || document.body);
    const html = (target && target.outerHTML ? target.outerHTML : "").slice(0, 4000);
    fetch(CONFIG.endpoint.replace("/passage", "/debug"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ radios: radios.length, info: html }),
    }).then(() => log("dumped choice DOM to pipeline console")).catch(() => {});
  }

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.altKey && (e.key === "n" || e.key === "N")) {
      e.preventDefault();
      setPaused(!paused);                      // Ctrl+Alt+N -> pause / resume
    } else if (e.ctrlKey && e.altKey && (e.key === "d" || e.key === "D")) {
      e.preventDefault();
      dumpChoiceDom();                         // Ctrl+Alt+D -> dump choice DOM to console
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
