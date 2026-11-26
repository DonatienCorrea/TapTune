(() => {
  "use strict";
  const t = JSON.parse(document.getElementById("maintenance-text").textContent);
  const el = (id) => document.getElementById(id);
  const buttons = document.querySelectorAll("[data-system-action]");
  const dialog = el("maintenance-confirm");
  const wait = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

  function say(message, tone = "") {
    const status = el("maintenance-status");
    status.hidden = !message;
    status.textContent = message;
    status.dataset.tone = tone;
  }

  function setBusy(busy) {
    buttons.forEach((button) => { button.disabled = busy; });
  }

  async function getSystem() {
    const response = await fetch("/api/system", { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    el("system-version").textContent = data.version || t.unknown_version;
    el("update-log-text").textContent = data.update?.log || "";
    el("update-log").hidden = !data.update?.log;
    return data;
  }

  function showResult(data) {
    if (data.update?.state === "failed") {
      say(t.update_failed, "error");
      el("update-log").open = true;
    } else {
      say(`${t.updated} Version ${data.version || t.unknown_version}`, "success");
    }
  }

  // TapTune restarts itself at the end of an update, so failed polls are expected.
  async function followUpdate() {
    setBusy(true);
    say(t.updating);
    for (let failures = 0; failures < 60;) {
      await wait(3000);
      let data;
      try {
        data = await getSystem();
      } catch {
        failures += 1;
        say(t.restarting);
        continue;
      }
      failures = 0;
      if (data.update?.state !== "running") {
        showResult(data);
        setBusy(false);
        return;
      }
      say(t.updating);
    }
    say(t.not_back, "error");
    setBusy(false);
  }

  // Reload once TapTune answers again, after it went down or the grace period passed.
  async function waitForReturn(message, graceAttempts) {
    setBusy(true);
    say(message);
    let down = false;
    for (let attempt = 1; attempt <= graceAttempts + 40; attempt += 1) {
      await wait(3000);
      try {
        const response = await fetch("/health", { cache: "no-store" });
        if (response.ok && (down || attempt > graceAttempts)) {
          window.location.reload();
          return;
        }
        down = down || !response.ok;
      } catch {
        down = true;
      }
    }
    say(t.not_back, "error");
    setBusy(false);
  }

  function confirmAction(action) {
    const [title, note, label] = t.confirm[action];
    if (typeof dialog.showModal !== "function") {
      return Promise.resolve(window.confirm(`${title}\n\n${note}`));
    }
    el("confirm-title").textContent = title;
    el("confirm-note").textContent = note;
    el("confirm-action").textContent = label;
    dialog.returnValue = "";
    dialog.showModal();
    return new Promise((resolve) => {
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
    });
  }

  async function run(action) {
    if (!(await confirmAction(action))) return;
    setBusy(true);
    let response;
    try {
      response = await fetch(`/api/system/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
        body: "{}",
      });
    } catch {
      response = null;
    }
    if (action === "update" && response?.status === 409) {
      say(t.update_running);
      return followUpdate();
    }
    if (!response?.ok) {
      say(t.error, "error");
      setBusy(false);
      return undefined;
    }
    if (action === "update") return followUpdate();
    if (action === "poweroff") {
      say(t.powered_off, "success");
      return undefined;
    }
    return waitForReturn(t.rebooting, 20);
  }

  buttons.forEach((button) => {
    button.addEventListener("click", () => run(button.dataset.systemAction));
  });

  getSystem().then((data) => {
    if (data.update?.state === "running") followUpdate();
    else if (data.update?.state === "failed") showResult(data);
  }).catch(() => {
    el("system-version").textContent = t.unknown_version;
  });
})();
