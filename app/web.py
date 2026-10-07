from flask import Flask, jsonify, redirect, render_template, request, url_for

from .config import settings
from .db import get_tag_by_uid, list_tags, record_event, upsert_tag
from .spotify_service import dispatch_tag_value, get_tag_type

TRANSLATIONS = {
    "en": {
        "switch_label": "Français",
        "switch_url": "/fr/",
        "page_title": "TapTune",
        "badge_top": "Tag assignment / field guide",
        "badge_right": "Physical input → playback",
        "subtitle": "Assign playlists and shortcuts to your NFC tags.",
        "saved": "✓ Tag saved successfully.",
        "badge_step": "01 / Map a physical input",
        "section_title": "Give a tag a job.",
        "intro": "Enter the UID printed by the reader, then point it at a Spotify URI or a playback action.",
        "quick_fill": "Quick fill",
        "uid_label": "Tag UID",
        "uid_placeholder": "Example: 04A7B2F1…",
        "label_label": "Friendly label",
        "label_placeholder": "Example: Morning playlist…",
        "value_label": "Spotify URI / Action",
        "value_placeholder": "spotify:playlist:… or action:play_pause",
        "save": "Save tag",
        "assigned_tags": "Assigned tags",
        "target": "Target",
        "label": "Label",
        "unlabeled": "Unlabeled",
        "empty": "No tags assigned yet.",
        "skip": "Skip to tag assignment",
        "error_required": "uid and value are required",
        "error_unknown": "Unknown tag",
        "error_missing": "uid or value required",
        "error_unsupported": "Unsupported value. Use a Spotify track, playlist, or album URI, or action:play_pause, action:next, or action:next_track.",
        "helper_playlist": "Spotify playlist",
        "helper_pause": "Play / pause",
        "helper_next": "Next track",
    },
    "fr": {
        "switch_label": "English",
        "switch_url": "/",
        "page_title": "TapTune",
        "badge_top": "Assignation de tags / guide de terrain",
        "badge_right": "Entrée physique → lecture",
        "subtitle": "Assignez des playlists et des raccourcis à vos tags NFC.",
        "saved": "✓ Tag enregistré avec succès.",
        "badge_step": "01 / Associer une entrée physique",
        "section_title": "Donnez un rôle à un tag.",
        "intro": "Saisissez le UID affiché par le lecteur, puis pointez vers une URI Spotify ou une action de lecture.",
        "quick_fill": "Remplissage rapide",
        "uid_label": "UID du tag",
        "uid_placeholder": "Exemple : 04A7B2F1…",
        "label_label": "Étiquette conviviale",
        "label_placeholder": "Exemple : Playlist du matin…",
        "value_label": "URI Spotify / Action",
        "value_placeholder": "spotify:playlist:… ou action:play_pause",
        "save": "Enregistrer le tag",
        "assigned_tags": "Tags assignés",
        "target": "Cible",
        "label": "Étiquette",
        "unlabeled": "Sans étiquette",
        "empty": "Aucun tag assigné pour le moment.",
        "skip": "Aller à l’assignation du tag",
        "error_required": "uid et value sont requis",
        "error_unknown": "Tag inconnu",
        "error_missing": "uid ou value requis",
        "error_unsupported": "Valeur non prise en charge. Utilisez une URI Spotify de morceau, playlist ou album, ou action:play_pause, action:next, ou action:next_track.",
        "helper_playlist": "Playlist Spotify",
        "helper_pause": "Lecture / pause",
        "helper_next": "Piste suivante",
    },
}


def create_app() -> Flask:
    app = Flask(__name__)

    def render_index(locale: str, saved: bool = False):
        translations = TRANSLATIONS[locale]
        return render_template(
            "index.html",
            tags=list_tags(),
            saved=saved,
            locale=locale,
            translations=translations,
            switch_url=translations["switch_url"],
            form_action=url_for("assign_tag_fr" if locale == "fr" else "assign_tag_en"),
        )

    @app.get("/")
    def index_en():
        return render_index("en", saved=request.args.get("saved") == "1")

    @app.get("/fr/")
    def index_fr():
        return render_index("fr", saved=request.args.get("saved") == "1")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "app": "TapTune"})

    @app.post("/assign")
    def assign_tag_en():
        return _assign_tag("en")

    @app.post("/fr/assign")
    def assign_tag_fr():
        return _assign_tag("fr")

    def _assign_tag(locale: str):
        uid = (request.form.get("uid") or "").strip()
        value = (request.form.get("value") or "").strip()
        label = (request.form.get("label") or "").strip() or None

        if not uid or not value:
            error = TRANSLATIONS[locale]["error_required"]
            return jsonify({"error": error}), 400

        tag_type = get_tag_type(value)
        if tag_type is None:
            return jsonify({"error": TRANSLATIONS[locale]["error_unsupported"]}), 400

        upsert_tag(uid=uid, value=value, tag_type=tag_type, label=label)
        target = "index_fr" if locale == "fr" else "index_en"
        return redirect(url_for(target, saved=1))

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
