(() => {
  const text = JSON.parse(document.getElementById("speaker-text").textContent);
  const status = document.getElementById("speaker-status");
  const pairing = document.getElementById("speaker-pairing");
  const scan = document.getElementById("speaker-scan");
  const list = document.getElementById("speaker-list");
  const change = document.getElementById("speaker-change");
  const testAfter = document.getElementById("speaker-test-after");
  let busy = false;

  const say = (message) => { status.textContent = message; };
  const fill = (template, name) => template.replace("{name}", name);
  const errorText = (code) => text.errors[code] || text.errors.unknown;

  async function post(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await response.json(); } catch (error) { /* keep empty */ }
    if (!response.ok) throw new Error(data.error || "unknown");
    return data;
  }

  function setBusy(value) {
    busy = value;
    document.querySelectorAll("#speaker-setup button").forEach((button) => { button.disabled = value; });
  }

  async function run(task) {
    if (busy) return;
    setBusy(true);
    try { await task(); } catch (error) { say(errorText(error.message)); } finally { setBusy(false); }
  }

  function show(speakers) {
    list.replaceChildren();
    if (!speakers.length) { say(text.none); return; }
    say(text.pick);
    for (const speaker of speakers) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "helper-button";
      button.textContent = speaker.paired ? `${speaker.name} (${text.paired})` : speaker.name;
      button.addEventListener("click", () => pair(speaker));
      item.append(button);
      list.append(item);
    }
  }

  function pair(speaker) {
    run(async () => {
      say(fill(text.connecting, speaker.name));
      const data = await post("/api/setup/speaker/pair", { mac: speaker.mac });
      list.replaceChildren();
      const saved = fill(text.saved, data.speaker.name);
      say(data.receiver === "failed" ? `${saved} ${text.receiver_failed}` : saved);
      testAfter.hidden = false;
    }).then(() => { if (!testAfter.hidden) testAfter.focus(); });
  }

  scan.addEventListener("click", () => run(async () => {
    list.replaceChildren();
    say(text.scanning);
    show((await post("/api/setup/speaker/scan")).speakers);
  }));

  if (change) {
    change.addEventListener("click", () => {
      pairing.hidden = false;
      scan.focus();
    });
  }

  document.querySelectorAll("[data-speaker-test]").forEach((button) => {
    button.addEventListener("click", () => run(async () => {
      say(text.testing);
      say((await post("/api/setup/speaker/test")).played ? text.played : text.not_played);
    }));
  });
})();
