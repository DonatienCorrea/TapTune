(() => {
  "use strict";
  const t = JSON.parse(document.getElementById("music-translations").textContent);
  const el = (id) => document.getElementById(id);
  const results = el("music-results");
  let collection = "albums";
  let query = "";
  let kind = "album";
  let nextPage = null;
  let requestNumber = 0;
  let selected = null;
  let available = false;
  let activeJob = null;
  let writePending = false;
  let pollTimer = null;
  let pollFailures = 0;
  const shown = new Set();

  function message(id, text, error = false) {
    el(id).textContent = text;
    el(id).classList.toggle("is-error", error);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { cache: "no-store", ...options });
    if (!response.headers.get("content-type")?.includes("application/json")) {
      throw new Error("error_network");
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "error_network");
    return data;
  }

  function errorText(error) {
    return t[error.message] || t.error_network;
  }

  function connection(title, note, error = false) {
    message("connection-title", title, error);
    el("connection-note").textContent = note;
  }

  function updateControls() {
    const busy = writePending || activeJob !== null;
    el("write-tag").disabled = !selected || !available || busy;
    el("use-assignment").disabled = !selected;
    el("cancel-write").hidden = activeJob === null;
    el("cancel-write").disabled = writePending;
    el("change-music").disabled = busy;
    results.querySelectorAll("button").forEach((button) => { button.disabled = busy; });
  }

  function updateSelection() {
    results.querySelectorAll("button[data-uri]").forEach((button) => {
      const chosen = button.dataset.uri === selected?.uri;
      button.setAttribute("aria-pressed", String(chosen));
      button.textContent = chosen ? t.selected_music : t.select_music;
      button.setAttribute("aria-label", `${button.textContent}: ${button.dataset.name}`);
      button.closest("li").classList.toggle("is-selected", chosen);
    });
  }

  function select(item, focus = true) {
    selected = item;
    el("selection-hint").hidden = true;
    el("write-selection").hidden = false;
    el("selected-name").textContent = item.name;
    el("selected-detail").textContent = [t[item.kind], item.detail].filter(Boolean).join(" · ");
    el("selected-uri").textContent = item.uri;
    updateSelection();
    updateControls();
    if (focus) {
      el("selection-heading").tabIndex = -1;
      el("selection-heading").focus();
      el("write-step").scrollIntoView({ block: "start" });
    }
  }

  function addItem(item) {
    if (shown.has(item.uri)) return;
    shown.add(item.uri);
    const row = document.createElement("li");
    row.className = "music-row";
    const art = document.createElement("div");
    art.className = "music-art";
    if (item.image) {
      const image = document.createElement("img");
      image.src = item.image;
      image.alt = "";
      image.width = 240;
      image.height = 240;
      image.loading = "lazy";
      image.referrerPolicy = "no-referrer";
      art.append(image);
    } else {
      const placeholder = document.createElement("span");
      placeholder.className = "music-art-placeholder";
      placeholder.setAttribute("aria-hidden", "true");
      const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      icon.setAttribute("viewBox", "0 0 64 64");
      icon.setAttribute("width", "64");
      icon.setAttribute("height", "64");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", "M25 44V19l27-6v25M25 25l27-6M25 44c0 4-4 7-9 7s-8-2-8-6 4-7 9-7 8 2 8 6Zm27-6c0 4-4 7-9 7s-8-2-8-6 4-7 9-7 8 2 8 6Z");
      icon.append(path);
      placeholder.append(icon);
      art.append(placeholder);
    }
    const info = document.createElement("div");
    info.className = "music-info";
    const name = document.createElement("strong");
    name.textContent = item.name;
    const detail = document.createElement("span");
    detail.textContent = [t[item.kind], item.detail].filter(Boolean).join(" · ");
    info.append(name, detail);
    const link = document.createElement("a");
    link.href = item.url;
    link.textContent = t.open_spotify;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    info.append(link);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "helper-button";
    button.textContent = t.select_music;
    button.dataset.uri = item.uri;
    button.dataset.name = item.name;
    button.setAttribute("aria-label", `${t.select_music}: ${item.name}`);
    button.setAttribute("aria-pressed", String(selected?.uri === item.uri));
    button.addEventListener("click", () => select(item));
    row.append(art, info, button);
    results.append(row);
  }

  async function loadMusic(append = false) {
    const number = ++requestNumber;
    const page = append ? nextPage : null;
    if (!append) {
      results.replaceChildren();
      shown.clear();
    }
    nextPage = null;
    el("load-more").hidden = true;
    el("authorization-guide").hidden = true;
    el("retry-music").hidden = true;
    el("music-search").hidden = collection !== "search";
    el("music-view-heading").textContent = t[collection];
    el("recent-note").hidden = collection !== "recent";
    results.setAttribute("aria-busy", "true");
    message("music-status", t.loading);
    document.querySelectorAll("[data-collection]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.collection === collection));
    });
    const params = new URLSearchParams({ collection, q: query, kind, ...page });
    try {
      const data = await api(`/api/music?${params}`);
      if (number !== requestNumber) return;
      if (data.mode === "fake") {
        connection(t.demo_title, t.demo_music);
        el("connection-help").textContent = t.demo_help;
      } else {
        connection(t.connection_live, t.connection_live_note);
        el("connection-help").textContent = t.connection_saved;
      }
      data.items.forEach(addItem);
      updateSelection();
      nextPage = data.next;
      el("load-more").hidden = !nextPage;
      message("music-status", shown.size ? "" : (t[`empty_${collection}`] || t.empty_music));
      updateControls();
    } catch (error) {
      if (number !== requestNumber) return;
      const permissions = error.message === "spotify_permissions";
      const auth = error.message === "spotify_auth_error";
      if (permissions || auth) {
        connection(permissions ? t.connection_permissions : t.connection_auth,
          permissions ? t.connection_permissions_note : t.spotify_auth_error, true);
        message("music-status", "");
        el("connection-help").textContent = t.connection_saved;
      } else {
        message("music-status", error.message === "invalid_music_request" ? errorText(error) : "", true);
        if (error.message !== "invalid_music_request") {
          connection(t.connection_blocked, errorText(error), true);
        }
      }
      el("authorization-guide").hidden = !permissions && !auth;
      el("retry-music").hidden = false;
      // Keep the failed page retryable without losing already loaded music.
      nextPage = page;
      el("load-more").hidden = !nextPage;
    } finally {
      if (number === requestNumber) results.setAttribute("aria-busy", "false");
    }
  }

  function showJob(job) {
    clearTimeout(pollTimer);
    if (job.status === "waiting") {
      activeJob = job.id;
      if (!selected || selected.uri !== job.value) {
        select({ name: t.pending_selection, uri: job.value }, false);
      }
      message("write-status", t.waiting);
      pollTimer = setTimeout(pollJob, 750);
    } else {
      activeJob = null;
      const text = job.status === "success" ? t.write_success
        : job.status === "cancelled" ? t.cancelled : (t[job.error] || t.tag_write_failed);
      message("write-status", `${text}${job.uid ? ` UID: ${job.uid}` : ""}`, job.status === "error");
    }
    updateControls();
  }

  async function pollJob() {
    if (!activeJob) return;
    try {
      const job = await api(`/api/tag-writes/${encodeURIComponent(activeJob)}`);
      pollFailures = 0;
      showJob(job);
    } catch (error) {
      message("write-status", errorText(error), true);
      pollFailures += 1;
      if (pollFailures < 3) pollTimer = setTimeout(pollJob, 2000);
    }
  }

  async function refreshReader() {
    el("refresh-reader").disabled = true;
    try {
      const state = await api("/api/tag-writes");
      available = state.available;
      writePending = false;
      pollFailures = 0;
      message("reader-status", available ? t.writer_ready : t.writer_disabled, !available);
      if (state.job) showJob(state.job);
      else {
        activeJob = null;
        clearTimeout(pollTimer);
      }
      updateControls();
    } catch (error) {
      available = false;
      message("reader-status", errorText(error), true);
      updateControls();
    } finally {
      el("refresh-reader").disabled = false;
    }
  }

  document.querySelectorAll("[data-collection]").forEach((button) => {
    button.addEventListener("click", () => {
      collection = button.dataset.collection;
      if (collection === "search" && !query) {
        requestNumber += 1;
        results.replaceChildren();
        shown.clear();
        nextPage = null;
        el("load-more").hidden = true;
        el("recent-note").hidden = true;
        el("retry-music").hidden = true;
        el("authorization-guide").hidden = true;
        results.setAttribute("aria-busy", "false");
        document.querySelectorAll("[data-collection]").forEach((tab) => {
          tab.setAttribute("aria-pressed", String(tab === button));
        });
        el("music-search").hidden = false;
        el("music-view-heading").textContent = t.search;
        message("music-status", t.search_prompt);
      } else {
        loadMusic();
      }
      if (collection === "search") el("music-query").focus();
    });
  });
  el("music-search").addEventListener("submit", (event) => {
    event.preventDefault();
    query = el("music-query").value.trim();
    if (!query) {
      message("music-status", t.invalid_music_request, true);
      return;
    }
    kind = el("music-kind").value;
    collection = "search";
    loadMusic();
  });
  el("load-more").addEventListener("click", () => loadMusic(true));
  el("retry-music").addEventListener("click", () => loadMusic());
  el("change-music").addEventListener("click", () => {
    el("choose-heading").focus();
    el("choose-heading").scrollIntoView({ block: "start" });
  });
  el("refresh-reader").addEventListener("click", refreshReader);
  el("use-assignment").addEventListener("click", () => {
    if (!selected) return;
    el("value").value = selected.uri;
    el("label").value = selected.name;
    el("advanced-options").open = true;
    el("uid").focus();
  });
  el("write-tag").addEventListener("click", async () => {
    if (!selected || writePending || activeJob) return;
    writePending = true;
    updateControls();
    try {
      const job = await api("/api/tag-writes", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: selected.uri }),
      });
      pollFailures = 0;
      showJob(job);
    } catch (error) {
      message("write-status", errorText(error), true);
      // A lost response can still mean the Pi accepted the write.
      await refreshReader();
    } finally {
      writePending = false;
      updateControls();
    }
  });
  el("cancel-write").addEventListener("click", async () => {
    if (!activeJob || writePending) return;
    clearTimeout(pollTimer);
    writePending = true;
    updateControls();
    try {
      const job = await api(`/api/tag-writes/${encodeURIComponent(activeJob)}/cancel`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      showJob(job);
    } catch (error) {
      message("write-status", errorText(error), true);
      pollTimer = setTimeout(pollJob, 2000);
    } finally {
      writePending = false;
      updateControls();
    }
  });
  loadMusic();
  refreshReader();
})();
