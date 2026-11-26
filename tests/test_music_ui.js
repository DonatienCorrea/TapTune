const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = readFileSync(join(__dirname, "../app/static/music.js"), "utf8");

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    const classes = new Set();
    this.classList = {
      toggle(name, enabled) {
        if (enabled) classes.add(name);
        else classes.delete(name);
      },
    };
  }
  append(...children) {
    children.forEach((child) => { child.parent = this; });
    this.children.push(...children);
  }
  replaceChildren() { this.children = []; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  click() {
    if (!this.disabled) return this.listeners.click?.({});
  }
  focus() {}
  scrollIntoView() {}
  closest(tag) { return this.tag === tag ? this : this.parent?.closest(tag); }
  querySelectorAll(selector) {
    const all = this.children.flatMap((child) => [child, ...child.querySelectorAll("*")]);
    if (selector === "*") return all;
    return all.filter((child) => child.tag === "button"
      && (selector === "button" || child.dataset.uri));
  }
}

async function picker(job = null, items = []) {
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  ["write-status", "write-selection", "cancel-write", "retry-write", "check-write",
    "write-another", "write-feedback-actions"].forEach((id) => { el(id).hidden = true; });
  el("music-translations").textContent = JSON.stringify({
    write_waiting_title: "Place tag on Pi reader",
    write_success_title: "Tag written",
    write_error_title: "Write failed",
    write_uncertain_title: "Write status unknown",
    write_cancelled_title: "Cancelled",
    write_preparing_title: "Preparing reader",
    tag_locked: "Use an unlocked tag.",
    tag_write_failed: "Writing failed.",
    error_network: "Check status before retrying.",
    write_not_found: "Remove the tag, then start a new write.",
    reader_unavailable: "Reader unavailable.",
    writer_disabled: "Reader unavailable.",
    writer_ready: "Reader ready",
    waiting: "Keep it still.",
    write_success: "Verified. Remove the tag.",
    cancelled: "Remove the tag.",
    select_music: "Choose",
    selected_music: "Selected",
    pending_selection: "Restored music",
  });
  const scenario = { available: true, job, items, failPoll: false, failState: false, failStart: false };
  const categories = ["recent", "music", "podcasts"].map((name) => {
    const button = el(name);
    button.dataset.collection = name;
    return button;
  });
  el("music-source-select").value = "albums";
  const opened = [];
  const timers = new Map();
  let timerId = 0;
  let jobId = 0;
  vm.runInNewContext(script, {
    document: {
      getElementById: el,
      querySelectorAll: (selector) => selector === "[data-collection]" ? categories : [],
      createElement: (tag) => new Element(tag),
      createElementNS: (_, tag) => new Element(tag),
    },
    window: { open: (...args) => opened.push(args) },
    URLSearchParams,
    setTimeout: (callback) => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: (id) => timers.delete(id),
    fetch: async (path, options = {}) => {
      let data;
      let ok = true;
      if (path.startsWith("/api/music")) {
        scenario.musicPaths = [...(scenario.musicPaths || []), path];
        data = { items: scenario.items, next: null };
      } else if (path === "/api/tag-writes" && options.method === "POST") {
        if (scenario.failStart) throw new TypeError("Failed to fetch");
        if (scenario.startError) {
          ok = false;
          data = { error: scenario.startError };
        } else {
          scenario.job = { id: `new-${++jobId}`, status: "waiting",
            value: JSON.parse(options.body).value, uid: null };
          data = scenario.job;
        }
      } else if (path.endsWith("/cancel")) {
        scenario.job = { ...scenario.job, status: "cancelled" };
        data = scenario.job;
      } else if (path === "/api/tag-writes") {
        if (scenario.failState) throw new TypeError("Failed to fetch");
        data = { available: scenario.available, job: scenario.job };
      } else {
        if (scenario.failPoll) throw new TypeError("Failed to fetch");
        data = scenario.job;
      }
      return { ok, headers: { get: () => "application/json" }, json: async () => data };
    },
  });
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  await settle();
  return {
    el, scenario, opened,
    async poll() {
      const [id, callback] = timers.entries().next().value;
      timers.delete(id);
      await callback();
    },
  };
}

const waiting = { id: "restored", status: "waiting", value: "spotify:album:abc", uid: null };

test("credential-free search opens Spotify to find a podcast to share", async () => {
  const ui = await picker();
  ui.el("podcasts").click();
  ui.el("spotify-search-query").value = "science & stories";
  ui.el("spotify-external-search").listeners.submit({ preventDefault() {} });
  assert.deepEqual(ui.opened[0], [
    "https://open.spotify.com/search/science%20%26%20stories/podcasts", "_blank", "noopener,noreferrer",
  ]);
});

test("waiting and verified success use distinct structured feedback", async () => {
  const ui = await picker(waiting);
  assert.equal(ui.el("write-status").dataset.state, "waiting");
  assert.equal(ui.el("write-tag").disabled, true);
  assert.equal(ui.el("cancel-write").hidden, false);
  const waitingIcon = ui.el("write-icon-path").attributes.d;
  ui.scenario.job = { ...waiting, status: "success", uid: "040102" };
  await ui.poll();
  assert.equal(ui.el("write-status").dataset.state, "success");
  assert.equal(ui.el("write-status-title").textContent, "Tag written");
  assert.notEqual(ui.el("write-icon-path").attributes.d, waitingIcon);
  assert.equal(ui.el("write-uid").textContent, "040102");
  assert.equal(ui.el("write-status-uid").hidden, false);
  assert.equal(ui.el("write-tag").disabled, false);
  assert.equal(ui.el("write-tag").hidden, true);
  assert.equal(ui.el("write-another").hidden, false);
  assert.equal(ui.el("write-instruction").hidden, true);
  assert.equal(ui.el("cancel-write").hidden, true);
  await ui.el("write-another").click();
  assert.equal(ui.el("write-status").dataset.state, "waiting");
});

test("write errors show the specific recovery and retry starts another job", async () => {
  const ui = await picker(waiting);
  ui.scenario.job = { ...waiting, status: "error", error: "tag_locked", uid: "040102" };
  await ui.poll();
  assert.equal(ui.el("write-status").dataset.state, "error");
  assert.equal(ui.el("write-status-detail").textContent, "Use an unlocked tag.");
  assert.equal(ui.el("retry-write").hidden, false);
  await ui.el("retry-write").click();
  assert.equal(ui.el("write-status").dataset.state, "waiting");
  await ui.el("cancel-write").click();
  assert.equal(ui.el("write-status").dataset.state, "cancelled");
  assert.equal(ui.el("cancel-write").hidden, true);
});

test("lost polling disables new writes until status is reconciled", async () => {
  const ui = await picker(waiting);
  ui.scenario.failPoll = true;
  await ui.poll();
  assert.equal(ui.el("write-status").dataset.state, "uncertain");
  assert.equal(ui.el("write-tag").disabled, true);
  assert.equal(ui.el("check-write").hidden, false);
  ui.scenario.failState = true;
  await ui.el("check-write").click();
  assert.equal(ui.el("write-status").dataset.state, "uncertain");
  assert.equal(ui.el("write-tag").disabled, true);
  ui.scenario.failState = false;
  ui.scenario.failPoll = false;
  await ui.el("check-write").click();
  assert.equal(ui.el("write-status").dataset.state, "waiting");
  ui.scenario.job = { ...waiting, status: "success" };
  await ui.poll();
  assert.equal(ui.el("write-status").dataset.state, "success");
});

test("a different completed job cannot unlock an unresolved write", async () => {
  const ui = await picker(waiting);
  ui.scenario.failPoll = true;
  await ui.poll();
  assert.equal(ui.el("write-status").dataset.state, "uncertain");
  assert.equal(ui.el("write-tag").disabled, true);

  ui.scenario.failPoll = false;
  ui.scenario.job = {
    id: "another-client", status: "success",
    value: "spotify:album:other", uid: "OTHER",
  };
  await ui.el("check-write").click();

  assert.equal(ui.el("write-status").dataset.state, "error");
  assert.equal(ui.el("write-status-detail").textContent, "Remove the tag, then start a new write.");
  assert.equal(ui.el("write-tag").hidden, true);
  assert.equal(ui.el("retry-write").hidden, false);
});

test("a previous success cannot confirm a failed new request", async () => {
  const ui = await picker({ ...waiting, status: "success", uid: "old-card" });
  ui.scenario.failStart = true;
  await ui.el("write-tag").click();
  assert.equal(ui.el("write-status").dataset.state, "error");
  assert.equal(ui.el("write-status-title").textContent, "Write failed");
  assert.equal(ui.el("write-status-uid").hidden, true);
});

test("a lost start response and failed status check keep new writes blocked", async () => {
  const ui = await picker({ ...waiting, status: "success" });
  ui.scenario.failStart = true;
  ui.scenario.failState = true;
  await ui.el("write-another").click();
  assert.equal(ui.el("write-status").dataset.state, "uncertain");
  assert.equal(ui.el("write-tag").disabled, true);
  assert.equal(ui.el("retry-write").hidden, true);
  assert.equal(ui.el("check-write").hidden, false);
  ui.scenario.failState = false;
  await ui.el("check-write").click();
  assert.equal(ui.el("write-status").dataset.state, "error");
  assert.equal(ui.el("write-tag").disabled, false);
});

test("changing selection clears old feedback and reader checks do not restore it", async () => {
  const ui = await picker({ ...waiting, status: "success" }, [
    { uri: "spotify:album:new", name: "New music", kind: "album", detail: "", url: "" },
  ]);
  const choose = ui.el("music-results").querySelectorAll("button[data-uri]")[0];
  choose.click();
  assert.equal(ui.el("selected-name").textContent, "New music");
  assert.equal(ui.el("write-status").hidden, true);
  await ui.el("refresh-reader").click();
  assert.equal(ui.el("write-status").hidden, true);
});

test("reader failures offer status checking rather than a disabled retry", async () => {
  const ui = await picker({ ...waiting, status: "success" });
  ui.scenario.startError = "reader_unavailable";
  await ui.el("write-tag").click();
  assert.equal(ui.el("write-status").dataset.state, "error");
  assert.equal(ui.el("retry-write").hidden, true);
  assert.equal(ui.el("check-write").hidden, false);
  await ui.el("check-write").click();
  assert.equal(ui.el("write-status").dataset.state, "error");
  assert.equal(ui.el("retry-write").hidden, false);
});

test("library views only request a collection from the API", async () => {
  const ui = await picker();
  assert.deepEqual(ui.scenario.musicPaths, ["/api/music?collection=recent"]);
  ui.el("music").click();
  ui.el("music-source-select").value = "playlists";
  ui.el("music-source-select").listeners.change();
  ui.el("podcasts").click();
  assert.deepEqual(ui.scenario.musicPaths.slice(1), [
    "/api/music?collection=albums", "/api/music?collection=playlists", "/api/music?collection=podcasts",
  ]);
});

const maintenanceScript = readFileSync(join(__dirname, "../app/static/maintenance.js"), "utf8");

async function maintenance(system) {
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  el("maintenance-text").textContent = JSON.stringify({
    confirm: { update: ["Update?", "", "Update"], restart: ["Restart?", "", "Restart"] },
    updating: "Updating…", restarting: "Restarting…", updated: "Update finished.",
    update_failed: "Update failed.", error: "Could not start.", not_back: "Still down.",
    unknown_version: "unknown",
  });
  const buttons = ["update", "restart"].map((action) => {
    const button = new Element("button");
    button.dataset.systemAction = action;
    return button;
  });
  const scenario = { system, down: false, posts: [], reloaded: false };
  const timers = [];
  vm.runInNewContext(maintenanceScript, {
    document: { getElementById: el, querySelectorAll: () => buttons },
    window: { confirm: () => true, location: { reload: () => { scenario.reloaded = true; } } },
    setTimeout: (callback) => timers.push(callback),
    fetch: async (path, options = {}) => {
      if (options.method === "POST") {
        scenario.posts.push(path);
        return { ok: true, status: 202, json: async () => ({ status: "started" }) };
      }
      if (scenario.down) throw new TypeError("Failed to fetch");
      return { ok: true, status: 200, json: async () => scenario.system };
    },
  });
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  await settle();
  return {
    el, buttons, scenario, settle,
    async tick() {
      timers.shift()();
      await settle();
    },
  };
}

test("update keeps polling through the restart and reports the new version", async () => {
  const ui = await maintenance({ version: "old", update: { state: "idle", log: "" } });
  assert.equal(ui.el("system-version").textContent, "old");
  ui.buttons[0].listeners.click();
  await ui.settle();
  assert.deepEqual(ui.scenario.posts, ["/api/system/update"]);
  assert.equal(ui.buttons[1].disabled, true);
  ui.scenario.down = true;
  await ui.tick();
  assert.equal(ui.el("maintenance-status").textContent, "Restarting…");
  ui.scenario.down = false;
  ui.scenario.system = { version: "new", update: { state: "succeeded", log: "done" } };
  await ui.tick();
  assert.equal(ui.el("maintenance-status").dataset.tone, "success");
  assert.match(ui.el("maintenance-status").textContent, /new/);
  assert.equal(ui.el("update-log").hidden, false);
  assert.equal(ui.buttons[1].disabled, false);
});

test("restart reloads the page once TapTune answers again", async () => {
  const ui = await maintenance({ version: "v1", update: { state: "idle", log: "" } });
  ui.buttons[1].listeners.click();
  await ui.settle();
  assert.deepEqual(ui.scenario.posts, ["/api/system/restart"]);
  ui.scenario.down = true;
  await ui.tick();
  assert.equal(ui.scenario.reloaded, false);
  ui.scenario.down = false;
  await ui.tick();
  assert.equal(ui.scenario.reloaded, true);
});
