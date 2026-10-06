from flask import Flask, jsonify, redirect, render_template_string, request, url_for

from .config import settings
from .db import get_tag_by_uid, list_tags, record_event, upsert_tag
from .spotify_service import dispatch_tag_value, get_tag_type

HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>TapTune</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --paper: #f4f1e8;
      --paper-deep: #e8e3d5;
      --ink: #182027;
      --muted: #5c635f;
      --line: #c9c5b9;
      --blue: #1945e8;
      --blue-dark: #1232aa;
      --orange: #f06328;
      --green: #20734f;
      --white: #fbfaf5;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      padding: 0 0 88px;
      font-family: "DM Sans", sans-serif;
      line-height: 1.55;
      background: var(--paper);
      color: var(--ink);
      -webkit-font-smoothing: antialiased;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 32 32'%3E%3Cpath d='M0 31.5h32M31.5 0v32' stroke='%23c9c5b9' stroke-opacity='.22' stroke-width='1'/%3E%3C/svg%3E");
    }

    .app-shell {
      width: min(1160px, calc(100% - 64px));
      margin: 0 auto;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 0;
      min-width: 0;
    }

    .app-shell > *,
    .header > *,
    .assignment-heading > *,
    .form-grid > *,
    .tag-card > * { min-width: 0; }

    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      min-height: 112px;
      padding: 20px 0;
      border-bottom: 1px solid var(--line);
    }

    .skip-link {
      position: absolute;
      left: 20px;
      top: -60px;
      z-index: 2;
      padding: 12px 16px;
      background: var(--ink);
      color: var(--white);
    }

    .skip-link:focus { top: 20px; }
    a, button { touch-action: manipulation; }
    a:focus-visible, button:focus-visible, input:focus-visible {
      outline: 3px solid var(--orange);
      outline-offset: 4px;
    }
    h1, h2, h3 { scroll-margin-top: 28px; }

    .title {
      display: flex;
      align-items: center;
      gap: 11px;
      font-family: "Space Grotesk", sans-serif;
      font-size: clamp(1.75rem, 3vw, 2.25rem);
      line-height: 1;
      font-weight: 600;
      letter-spacing: -0.035em;
      margin: 6px 0 0;
      overflow-wrap: anywhere;
    }

    .logo-mark {
      width: 32px;
      height: 32px;
      flex: 0 0 auto;
      fill: none;
      stroke: var(--orange);
      stroke-width: 2;
    }

    .logo-mark circle:nth-child(2) { fill: var(--orange); stroke: none; }
    .brand-tune { color: var(--blue); }
    .assignment-heading {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(220px, .7fr);
      align-items: end;
      gap: 28px;
      margin-bottom: 34px;
    }

    .assignment-heading .section-title { margin: 12px 0 0; }
    .assignment-heading > p { max-width: 310px; margin: 0 0 5px; color: var(--muted); }

    .subtitle {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: .9rem;
      max-width: 500px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 0;
      border-radius: 0;
      background: transparent;
      color: var(--blue);
      font: 500 11px "DM Mono", monospace;
      letter-spacing: .13em;
      text-transform: uppercase;
    }

    .panel {
      background: transparent;
      border: 0;
      border-radius: 0;
      box-shadow: none;
      backdrop-filter: none;
    }

    .form-panel {
      padding: 92px 0 110px;
      border-bottom: 1px solid var(--line);
    }

    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 18px 28px;
      max-width: 780px;
    }

    .field {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .field:last-child {
      grid-column: 1 / -1;
    }

    .field label {
      font-size: 0.88rem;
      font-weight: 700;
      color: var(--muted);
      font: 500 11px "DM Mono", monospace;
      letter-spacing: .08em;
      text-transform: uppercase;
    }

    input {
      width: 100%;
      padding: 0.9rem 0.85rem;
      border-radius: 0;
      border: 1px solid var(--ink);
      background: var(--white);
      color: var(--ink);
      font: 500 13px "DM Mono", monospace;
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }

    input:focus-visible {
      outline: none;
      border-color: var(--blue);
      box-shadow: 4px 4px 0 var(--orange);
    }

    .helper-row {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin: 0 0 30px;
    }

    .helper-label, .record-label {
      color: var(--muted);
      font: 500 10px "DM Mono", monospace;
      letter-spacing: .08em;
      text-transform: uppercase;
    }

    .helper-label { align-self: center; margin-right: 4px; }

    .helper-button {
      border: 1px solid var(--ink);
      background: transparent;
      color: var(--ink);
      border-radius: 0;
      min-height: 44px;
      padding: 0.65rem 0.8rem;
      font: 600 12px "DM Sans", sans-serif;
      cursor: pointer;
      transition: transform .2s ease, background-color .2s ease, color .2s ease;
    }

    .helper-button:hover {
      transform: translateY(-2px);
      background: var(--ink);
      color: var(--white);
    }

    .actions {
      display: flex;
      justify-content: flex-end;
      margin-top: 28px;
    }

    .save-button {
      border: 1px solid transparent;
      background: var(--blue);
      color: var(--white);
      min-height: 48px;
      padding: 14px 18px;
      border-radius: 0;
      font: 700 13px "DM Sans", sans-serif;
      cursor: pointer;
      transition: transform .2s ease, background-color .2s ease;
    }

    .save-button:hover {
      transform: translateY(-2px);
      background: var(--blue-dark);
    }

    .success-banner {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0.85rem 1rem;
      border: 1px solid var(--green);
      border-radius: 0;
      background: transparent;
      color: var(--green);
      font: 500 12px "DM Mono", monospace;
      margin-bottom: 26px;
    }

    .tags-panel {
      padding: 80px 0 0;
    }

    .section-title {
      margin: 0 0 24px;
      font: 600 clamp(2rem, 4vw, 3.4rem)/.95 "Space Grotesk", sans-serif;
      letter-spacing: -.04em;
      overflow-wrap: anywhere;
    }

    .tag-list {
      display: grid;
      grid-template-columns: 1fr;
      gap: 0;
      list-style: none;
      margin: 0;
      padding: 0;
    }

    .tag-card {
      display: grid;
      grid-template-columns: 150px minmax(130px, .7fr) minmax(0, 1.5fr) minmax(120px, .7fr);
      align-items: center;
      gap: 18px;
      padding: 18px 0;
      border-radius: 0;
      background: transparent;
      border-top: 1px solid var(--line);
    }

    .tag-meta {
      display: flex;
      justify-content: flex-start;
      align-items: center;
      gap: 8px;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      font-family: "DM Mono", monospace;
    }

    .tag-meta > span:last-child { overflow-wrap: anywhere; }

    .pill {
      display: inline-flex;
      align-items: center;
      padding: 0.28rem 0.45rem;
      border-radius: 0;
      font: 500 10px "DM Mono", monospace;
      letter-spacing: 0.04em;
    }

    .pill.content {
      background: transparent;
      color: var(--green);
      border: 1px solid var(--green);
    }

    .pill.action {
      background: transparent;
      color: var(--orange);
      border: 1px solid var(--orange);
    }

    .tag-uid {
      font: 600 16px "Space Grotesk", sans-serif;
      font-size: 1rem;
      word-break: break-all;
    }

    .tag-value {
      font-size: 0.95rem;
      color: var(--ink);
      overflow-wrap: anywhere;
      font: 12px "DM Mono", monospace;
      line-height: 1.5;
    }

    .tag-label {
      color: var(--muted);
      font-size: 0.9rem;
      overflow-wrap: anywhere;
    }

    .record-label { display: block; margin-bottom: 5px; }

    .empty-state {
      padding: 1.2rem 0.5rem;
      text-align: center;
      color: var(--muted);
      background: var(--paper-deep);
      border-radius: 0;
      border: 1px dashed var(--line);
      grid-column: 1 / -1;
    }

    @media (max-width: 640px) {
      .app-shell { width: calc(100% - 32px); }
      .assignment-heading { grid-template-columns: 1fr; gap: 14px; }
      .header {
        flex-direction: column;
        align-items: flex-start;
        justify-content: center;
        padding: 24px 0;
      }

      .actions {
        justify-content: stretch;
      }

      .save-button {
        width: 100%;
      }

      .tag-card {
        grid-template-columns: 1fr;
        gap: 8px;
      }

      .tag-meta {
        justify-content: space-between;
      }
    }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        transition-duration: .01ms !important;
        animation-duration: .01ms !important;
        animation-iteration-count: 1 !important;
      }
    }
  </style>
</head>
<body>
  <a class="skip-link" href="#assignment">Skip to tag assignment</a>
  <div class="app-shell">
    <header class="header">
      <div>
        <span class="badge">Tag assignment / field guide</span>
        <h1 class="title"><svg class="logo-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false"><circle cx="16" cy="16" r="13"></circle><circle cx="16" cy="16" r="5"></circle><path d="M16 3v7M16 22v7"></path></svg><span>Tap<span class="brand-tune">Tune</span></span></h1>
        <p class="subtitle">Assign playlists and shortcuts to your NFC tags.</p>
      </div>
      <span class="badge">Physical input → playback</span>
    </header>

    <main id="assignment" class="panel form-panel">
      {% if saved %}
        <div class="success-banner" role="status" aria-live="polite">✓ Tag saved successfully.</div>
      {% endif %}

      <div class="assignment-heading">
        <div>
          <span class="badge">01 / Map a physical input</span>
          <h2 class="section-title">Give a tag a job.</h2>
        </div>
        <p>Enter the UID printed by the reader, then point it at a Spotify URI or a playback action.</p>
      </div>
      <div class="helper-row">
        <span class="helper-label">Quick fill</span>
        <button type="button" class="helper-button" data-value="spotify:playlist:37i9dQZF1DXcBWIGoYBM5M">Spotify playlist</button>
        <button type="button" class="helper-button" data-value="action:play_pause">Play / pause</button>
        <button type="button" class="helper-button" data-value="action:next_track">Next track</button>
      </div>

      <form method="post" action="/assign">
        <div class="form-grid">
          <div class="field">
            <label for="uid">Tag UID</label>
            <input id="uid" name="uid" required autocomplete="off" spellcheck="false" inputmode="text" placeholder="Example: 04A7B2F1…">
          </div>

          <div class="field">
            <label for="label">Friendly label</label>
            <input id="label" name="label" autocomplete="off" placeholder="Example: Morning playlist…">
          </div>

          <div class="field">
            <label for="value">Spotify URI / Action</label>
            <input id="value" name="value" required autocomplete="off" spellcheck="false" placeholder="spotify:playlist:… or action:play_pause">
          </div>
        </div>

        <div class="actions">
          <button class="save-button" type="submit">Save tag</button>
        </div>
      </form>
    </main>

    <section class="panel tags-panel">
      <h2 class="section-title">Assigned tags</h2>
      <ul class="tag-list">
        {% for tag in tags %}
          <li class="tag-card">
            <div class="tag-meta">
              <span class="pill {{ tag.tag_type }}">{{ tag.tag_type }}</span>
              <span>{{ tag.uid }}</span>
            </div>
            <div class="tag-uid">{{ tag.uid }}</div>
            <div><span class="record-label">Target</span><div class="tag-value">{{ tag.value }}</div></div>
            <div class="tag-label">{% if tag.label %}<span class="record-label">Label</span>{{ tag.label }}{% else %}<span class="record-label">Label</span>Unlabeled{% endif %}</div>
          </li>
        {% else %}
          <li class="empty-state">No tags assigned yet.</li>
        {% endfor %}
      </ul>
    </section>
  </div>

  <script>
    document.querySelectorAll('[data-value]').forEach((button) => {
      button.addEventListener('click', () => {
        const input = document.getElementById('value');
        input.value = button.dataset.value;
        input.focus();
      });
    });
  </script>
</body>
</html>
"""


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template_string(HTML, tags=list_tags(), saved=request.args.get("saved") == "1")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "app": "TapTune"})

    @app.post("/assign")
    def assign_tag():
        uid = (request.form.get("uid") or "").strip()
        value = (request.form.get("value") or "").strip()
        label = (request.form.get("label") or "").strip() or None

        if not uid or not value:
            return jsonify({"error": "uid and value are required"}), 400

        tag_type = get_tag_type(value)
        if tag_type is None:
            return jsonify({
                "error": (
                    "Unsupported value. Use a Spotify track, playlist, or album URI, "
                    "or action:play_pause, action:next, or action:next_track."
                )
            }), 400

        upsert_tag(uid=uid, value=value, tag_type=tag_type, label=label)
        return redirect(url_for("index", saved=1))

    @app.post("/dispatch")
    def dispatch_tag():
        uid = (request.form.get("uid") or "").strip()
        value = (request.form.get("value") or "").strip()

        if not uid and not value:
            return jsonify({"error": "uid or value required"}), 400

        if uid:
            tag = get_tag_by_uid(uid)
            if not tag:
                return jsonify({"error": "Unknown tag"}), 404
            value = tag["value"]

        record_event(uid or "simulated", "content" if value.startswith("spotify:") else "action", value, source="web")
        result = dispatch_tag_value(value)
        if isinstance(result, dict) and result.get("status") == "error":
            return jsonify({"status": "error", "result": result}), 502
        return jsonify({"status": "ok", "result": result})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=settings.APP_HOST, port=settings.APP_PORT, debug=False)
