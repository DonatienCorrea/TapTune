import threading
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, request, url_for

from .config import settings
from .db import get_tag_by_uid, list_tags, record_event, upsert_tag
from .spotify_service import dispatch_tag_value, get_tag_type, is_live_spotify_configured
from . import spotify_service
from .spotify_browser import browse_music
from .tag_writer import TagWriter, WriterBusy

SPOTIFY_BROWSER_ERRORS = spotify_service.NETWORK_ERRORS + (RuntimeError,) + tuple(
    error for error in (spotify_service.SpotifyException, spotify_service.SpotifyOauthError)
    if error is not None
)

TRANSLATIONS = {
    "en": {
        "switch_label": "Français",
        "switch_url": "/fr/",
        "page_title": "TapTune",
        "badge_top": "Tag assignment / field guide",
        "badge_right": "Physical input → playback",
        "subtitle": "Your music, one tap away.",
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
        "error_unsupported": "Unsupported value. Use a Spotify track, playlist, or album URI, or action:play_pause, action:next, action:next_track, action:volume_up, or action:volume_down.",
        "helper_playlist": "Spotify playlist",
        "helper_pause": "Play / pause",
        "helper_next": "Next track",
        "helper_volume_up": "Volume +10%",
        "helper_volume_down": "Volume -10%",
        "browse_title": "Make a music tag",
        "browse_intro": "Choose an album, playlist or song. Then write it to a tag using the reader on your Pi.",
        "choose_title": "1. Choose your music",
        "write_title": "2. Write your tag",
        "albums": "My albums",
        "playlists": "My playlists",
        "recent": "Recent albums",
        "search": "Search Spotify",
        "search_label": "What do you want to find?",
        "search_placeholder": "An artist, album, playlist or song…",
        "search_kind": "Search for",
        "album": "Album",
        "playlist": "Playlist",
        "track": "Track",
        "search_button": "Search",
        "load_more": "Load more",
        "loading": "Loading music…",
        "empty_music": "No results for this search. Try another name or music type.",
        "empty_albums": "No saved albums found. Save an album in Spotify, or use Search Spotify to find music.",
        "empty_playlists": "No playlists found. Try My albums or Search Spotify.",
        "empty_recent": "No recent albums found. Play some music in Spotify, or use Search Spotify.",
        "demo_title": "Demo preview — not your Spotify library",
        "demo_music": "This copy of TapTune has no Spotify credentials. Open the page on your Pi to use its saved connection. The music below is only an example.",
        "demo_help": "Your token on the Pi is not available in this computer's preview. Open TapTune on your Pi to use its saved Spotify connection. You do not need to paste the token into this page.",
        "connection_checking": "Checking your saved Spotify connection…",
        "connection_saved": "TapTune uses the Spotify token already saved on this device. No separate login or token entry is needed here.",
        "connection_live": "Spotify connected",
        "connection_live_note": "Using your saved Spotify connection. Choose music below; your token stays on the device running TapTune.",
        "connection_help": "About this connection",
        "connection_blocked": "Spotify needs attention",
        "connection_permissions": "Spotify needs permission for this view",
        "connection_permissions_note": "Your saved token is being used, but Spotify refused access. A playback-only token needs a one-time approval for saved albums, private playlists and listening history. You can also try Search Spotify.",
        "connection_auth": "Spotify did not accept the saved connection",
        "spotify_auth_error": "The saved Spotify token is invalid or expired. Follow the setup guide to authorize TapTune again, then restart it.",
        "retry_music": "Try again",
        "search_prompt": "Enter a name above, choose a music type, then select Search.",
        "recent_note": "Albums from your last 50 played tracks, newest first. Load more to look further back.",
        "select_music": "Choose",
        "selected_music": "Selected",
        "open_spotify": "Open in Spotify",
        "selection_hint": "Choose music above first. You do not need to enter a tag number or copy a Spotify link.",
        "write_tag": "Start writing",
        "write_instruction": "Select Start writing, then place your tag on the Pi's reader — not against your iPhone. Leave it there until you see confirmation.",
        "write_warning": "Any music or other content already on the tag will be replaced.",
        "tag_help": "Compatible tags and reader setup",
        "tag_help_note": "Use an unlocked NTAG213/215/216, a supported Feiju 144-byte Type 2 tag, or a writable NFC Type 4 NDEF tag. On the Pi, enable NFC_READER_ENABLED and run python -m app.main (or the TapTune service).",
        "writer_disabled": "The Pi's tag reader is not ready. You can still browse music. Check its connection; setup help is below.",
        "writer_ready": "Pi reader ready",
        "check_reader": "Check reader",
        "waiting": "Hold your tag against the Pi's reader within 60 seconds. Playback scanning is paused.",
        "write_success": "Tag written and verified. Remove it from the Pi's reader, then tap again to play.",
        "cancel": "Cancel write",
        "cancelled": "Write cancelled. Remove any tag from the Pi's reader.",
        "use_assignment": "Fill the advanced form with this music",
        "selection_details": "Spotify link and advanced options",
        "change_music": "Choose different music",
        "pending_selection": "Music from the pending write",
        "advanced_options": "Advanced: manual tag setup & playback shortcuts",
        "assigned_note": "These are manual assignments saved on this Pi, not a list of tags written above.",
        "manual_assignment": "Manual UID assignment",
        "manual_note": "Use a UID mapping instead of writing a tag, or assign a playback shortcut.",
        "error_network": "Cannot reach TapTune. Check your connection, then retry. If a write was pending, it expires after 60 seconds; remove the tag before retrying.",
        "spotify_permissions": "Spotify access is missing or expired. Re-authorize with library, private playlist and recently played permissions, then update the Pi's refresh token and restart TapTune.",
        "spotify_rate_limit": "Spotify is limiting requests. Wait a little before retrying.",
        "spotify_unavailable": "Spotify is unavailable. Check the Pi's internet connection and Spotify configuration, then retry.",
        "invalid_music_request": "Enter a search between 1 and 200 characters and choose a supported music type.",
        "reader_unavailable": "The Pi's reader is unavailable. Check its connection and restart TapTune if needed.",
        "writer_busy": "Another tag write is pending. Wait for it to finish or expire.",
        "write_timeout": "No tag was written within 60 seconds. Remove any tag and try again.",
        "tag_changed": "The tag was removed or changed. Keep one tag on the reader and try again.",
        "unsupported_tag": "This tag's chip or memory layout is not supported. Use an NTAG213/215/216, a supported Feiju 144-byte Type 2 tag, a supported NFC Type 4 NDEF tag, or a manual UID assignment.",
        "tag_locked": "This tag is locked or protected. Use an unlocked tag.",
        "tag_too_small": "This tag does not have enough writable space for the link.",
        "tag_read_failed": "The reader could not inspect the tag. Reposition it and try again.",
        "tag_write_failed": "Writing failed; the tag may be incomplete. Keep it on the reader and retry.",
        "tag_verify_failed": "The written link could not be verified. The tag may be incomplete; write it again.",
        "write_not_found": "This write session is no longer available. Remove the tag, then start a new write.",
        "invalid_write": "Choose a Spotify album, playlist or track before writing.",
        "invalid_origin": "Writing must be started from this TapTune page. Reload the page and retry.",
        "authorization_guide": "Spotify authorization guide",
    },
    "fr": {
        "switch_label": "English",
        "switch_url": "/",
        "page_title": "TapTune",
        "badge_top": "Assignation de tags / guide de terrain",
        "badge_right": "Entrée physique → lecture",
        "subtitle": "Votre musique à portée de tag.",
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
        "error_unsupported": "Valeur non prise en charge. Utilisez une URI Spotify de morceau, playlist ou album, ou action:play_pause, action:next, action:next_track, action:volume_up, ou action:volume_down.",
        "helper_playlist": "Playlist Spotify",
        "helper_pause": "Lecture / pause",
        "helper_next": "Piste suivante",
        "helper_volume_up": "Volume +10 %",
        "helper_volume_down": "Volume -10 %",
        "browse_title": "Créez un tag musical",
        "browse_intro": "Choisissez un album, une playlist ou un morceau. Écrivez-le ensuite sur un tag avec le lecteur de votre Pi.",
        "choose_title": "1. Choisissez votre musique",
        "write_title": "2. Écrivez votre tag",
        "albums": "Mes albums",
        "playlists": "Mes playlists",
        "recent": "Albums récents",
        "search": "Rechercher sur Spotify",
        "search_label": "Que souhaitez-vous trouver ?",
        "search_placeholder": "Un artiste, un album, une playlist ou un morceau…",
        "search_kind": "Rechercher un",
        "album": "Album",
        "playlist": "Playlist",
        "track": "Morceau",
        "search_button": "Rechercher",
        "load_more": "Charger la suite",
        "loading": "Chargement de la musique…",
        "empty_music": "Aucun résultat. Essayez un autre nom ou type de musique.",
        "empty_albums": "Aucun album enregistré. Enregistrez un album dans Spotify ou utilisez Rechercher sur Spotify.",
        "empty_playlists": "Aucune playlist trouvée. Essayez Mes albums ou Rechercher sur Spotify.",
        "empty_recent": "Aucun album récent. Écoutez de la musique dans Spotify ou utilisez Rechercher sur Spotify.",
        "demo_title": "Aperçu de démonstration — pas votre bibliothèque Spotify",
        "demo_music": "Cette copie de TapTune n’a pas d’identifiants Spotify. Ouvrez la page sur votre Pi pour utiliser sa connexion enregistrée. La musique ci-dessous est fictive.",
        "demo_help": "Le jeton de votre Pi n’est pas disponible dans l’aperçu de cet ordinateur. Ouvrez TapTune sur votre Pi pour utiliser sa connexion Spotify enregistrée. Aucun jeton à coller dans cette page.",
        "connection_checking": "Vérification de votre connexion Spotify enregistrée…",
        "connection_saved": "TapTune utilise le jeton Spotify déjà enregistré sur cet appareil. Aucune connexion séparée ni saisie de jeton n’est nécessaire ici.",
        "connection_live": "Spotify connecté",
        "connection_live_note": "Votre connexion Spotify enregistrée est utilisée. Choisissez la musique ci-dessous ; le jeton reste sur l’appareil qui exécute TapTune.",
        "connection_help": "À propos de cette connexion",
        "connection_blocked": "Vérifiez la connexion Spotify",
        "connection_permissions": "Spotify demande une autorisation pour cette vue",
        "connection_permissions_note": "Votre jeton enregistré est utilisé, mais Spotify refuse l’accès. Un jeton limité à la lecture musicale nécessite une nouvelle approbation pour les albums enregistrés, les playlists privées et l’historique. Vous pouvez aussi essayer Rechercher sur Spotify.",
        "connection_auth": "Spotify refuse la connexion enregistrée",
        "spotify_auth_error": "Le jeton Spotify enregistré est invalide ou expiré. Suivez le guide pour autoriser TapTune à nouveau, puis redémarrez-le.",
        "retry_music": "Réessayer",
        "search_prompt": "Saisissez un nom ci-dessus, choisissez un type de musique, puis sélectionnez Rechercher.",
        "recent_note": "Albums des 50 derniers morceaux écoutés, du plus récent au plus ancien. Chargez la suite pour remonter plus loin.",
        "select_music": "Choisir",
        "selected_music": "Sélection",
        "open_spotify": "Ouvrir dans Spotify",
        "selection_hint": "Choisissez d’abord la musique ci-dessus. Aucun numéro de tag à saisir ni lien Spotify à copier.",
        "write_tag": "Commencer l’écriture",
        "write_instruction": "Sélectionnez Commencer l’écriture, puis posez le tag sur le lecteur du Pi — pas contre votre iPhone. Laissez-le en place jusqu’à confirmation.",
        "write_warning": "La musique ou tout autre contenu déjà présent sur le tag sera remplacé.",
        "tag_help": "Tags compatibles et configuration du lecteur",
        "tag_help_note": "Utilisez un NTAG213/215/216 non verrouillé, un tag Feiju Type 2 de 144 octets pris en charge ou un tag NFC Type 4 NDEF accessible en écriture. Sur le Pi, activez NFC_READER_ENABLED et lancez python -m app.main (ou le service TapTune).",
        "writer_disabled": "Le lecteur de tags du Pi n’est pas prêt. Vous pouvez parcourir la musique. Vérifiez sa connexion ; l’aide est ci-dessous.",
        "writer_ready": "Lecteur du Pi prêt",
        "check_reader": "Vérifier le lecteur",
        "waiting": "Posez votre tag sur le lecteur du Pi dans les 60 secondes. La détection pour la lecture musicale est suspendue.",
        "write_success": "Tag écrit et vérifié. Retirez-le du lecteur du Pi, puis présentez-le à nouveau pour écouter.",
        "cancel": "Annuler l’écriture",
        "cancelled": "Écriture annulée. Retirez tout tag du lecteur du Pi.",
        "use_assignment": "Remplir le formulaire avancé avec cette musique",
        "selection_details": "Lien Spotify et options avancées",
        "change_music": "Choisir une autre musique",
        "pending_selection": "Musique de l’écriture en attente",
        "advanced_options": "Avancé : configuration manuelle et raccourcis",
        "assigned_note": "Il s’agit des assignations manuelles enregistrées sur ce Pi, pas des tags écrits ci-dessus.",
        "manual_assignment": "Assignation manuelle par UID",
        "manual_note": "Associez un UID sans écrire sur le tag, ou assignez un raccourci de lecture.",
        "error_network": "TapTune est inaccessible. Vérifiez la connexion et réessayez. Une écriture en attente expire après 60 secondes ; retirez le tag avant de réessayer.",
        "spotify_permissions": "L’accès Spotify est absent ou expiré. Autorisez à nouveau l’accès à la bibliothèque, aux playlists privées et à l’historique, puis mettez à jour le jeton du Pi et redémarrez TapTune.",
        "spotify_rate_limit": "Spotify limite les requêtes. Patientez avant de réessayer.",
        "spotify_unavailable": "Spotify est indisponible. Vérifiez la connexion Internet et la configuration Spotify du Pi, puis réessayez.",
        "invalid_music_request": "Saisissez une recherche de 1 à 200 caractères et choisissez un type de musique pris en charge.",
        "reader_unavailable": "Le lecteur du Pi est indisponible. Vérifiez sa connexion et redémarrez TapTune si nécessaire.",
        "writer_busy": "Une autre écriture est en attente. Attendez sa fin ou son expiration.",
        "write_timeout": "Aucun tag écrit dans les 60 secondes. Retirez tout tag et réessayez.",
        "tag_changed": "Le tag a été retiré ou remplacé. Gardez un seul tag sur le lecteur et réessayez.",
        "unsupported_tag": "La puce ou la disposition mémoire de ce tag n’est pas prise en charge. Utilisez un NTAG213/215/216, un tag Feiju Type 2 de 144 octets compatible, un tag NFC Type 4 NDEF compatible ou une assignation par UID.",
        "tag_locked": "Ce tag est verrouillé ou protégé. Utilisez un tag non verrouillé.",
        "tag_too_small": "Ce tag ne dispose pas d’assez de mémoire accessible pour le lien.",
        "tag_read_failed": "Impossible d’inspecter le tag. Repositionnez-le et réessayez.",
        "tag_write_failed": "L’écriture a échoué ; le tag peut être incomplet. Gardez-le sur le lecteur et réessayez.",
        "tag_verify_failed": "Le lien écrit n’a pas pu être vérifié. Le tag peut être incomplet ; réécrivez-le.",
        "write_not_found": "Cette session d’écriture n’est plus disponible. Retirez le tag et recommencez.",
        "invalid_write": "Choisissez un album, une playlist ou un morceau Spotify avant l’écriture.",
        "invalid_origin": "L’écriture doit être lancée depuis cette page TapTune. Rechargez la page et réessayez.",
        "authorization_guide": "Guide d’autorisation Spotify",
    },
}


def create_app() -> Flask:
    app = Flask(__name__)
    writer = TagWriter()
    app.config["TAG_WRITER"] = writer

    def reader_available():
        thread = app.config.get("NFC_READER_THREAD")
        ready = getattr(thread, "reader_ready", None)
        return bool(
            settings.NFC_READER_ENABLED and thread is not None and thread.is_alive()
            and isinstance(ready, threading.Event) and ready.is_set()
        )

    def api_response(data, status=200):
        response = jsonify(data)
        response.status_code = status
        response.headers["Cache-Control"] = "no-store"
        return response

    def api_error(code, status):
        return api_response({"error": code}, status)

    @app.get("/api/music")
    def music():
        try:
            result = browse_music(
                request.args.get("collection", "albums"),
                query=request.args.get("q", ""), kind=request.args.get("kind", "album"),
                offset=int(request.args.get("offset", "0")),
                before=int(request.args["before"]) if "before" in request.args else None,
            )
        except ValueError:
            return api_error("invalid_music_request", 400)
        except SPOTIFY_BROWSER_ERRORS as error:
            if spotify_service.SpotifyException and isinstance(error, spotify_service.SpotifyException):
                status = error.http_status
                app.logger.warning("Spotify browsing failed (HTTP %s).", status)
                if status == 401:
                    return api_error("spotify_auth_error", 403)
                if status == 403:
                    return api_error("spotify_permissions", 403)
                if status == 429:
                    response = api_error("spotify_rate_limit", 429)
                    retry = (error.headers or {}).get("Retry-After")
                    if retry and str(retry).isdigit():
                        response.headers["Retry-After"] = str(retry)
                    return response
            elif spotify_service.SpotifyOauthError and isinstance(error, spotify_service.SpotifyOauthError):
                app.logger.warning("Spotify browsing authorization failed.")
                return api_error("spotify_auth_error", 403)
            app.logger.warning("Spotify browsing is unavailable (%s).", type(error).__name__)
            return api_error("spotify_unavailable", 502)
        return api_response(result)

    @app.get("/api/tag-writes")
    def write_status():
        return api_response({"available": reader_available(), "job": writer.snapshot()})

    def valid_write_request():
        origin = request.headers.get("Origin")
        return (
            request.is_json
            and request.headers.get("Sec-Fetch-Site") != "cross-site"
            and (not origin or urlsplit(origin)[:2] == urlsplit(request.host_url)[:2])
        )

    @app.post("/api/tag-writes")
    def start_write():
        if not valid_write_request():
            return api_error("invalid_origin", 403)
        data = request.get_json()
        value = data.get("value") if isinstance(data, dict) else None
        if not isinstance(value, str) or len(value) > 200 or get_tag_type(value) != "content":
            return api_error("invalid_write", 400)
        if not reader_available():
            return api_error("reader_unavailable", 503)
        try:
            job = writer.start(value)
        except WriterBusy:
            return api_error("writer_busy", 409)
        return api_response(job, 202)

    @app.get("/api/tag-writes/<job_id>")
    def get_write(job_id):
        job = writer.snapshot(job_id)
        return api_response(job) if job else api_error("write_not_found", 404)

    @app.post("/api/tag-writes/<job_id>/cancel")
    def cancel_write(job_id):
        if not valid_write_request():
            return api_error("invalid_origin", 403)
        job = writer.cancel(job_id)
        return api_response(job) if job else api_error("write_not_found", 404)

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
            spotify_configured=is_live_spotify_configured(),
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

    @app.get("/ready")
    def ready():
        reader = app.config.get("NFC_READER_THREAD")
        reader_event = getattr(reader, "reader_ready", None)
        reader_ready = not settings.NFC_READER_ENABLED or (
            reader is not None and reader.is_alive()
            and (not isinstance(reader_event, threading.Event) or reader_event.is_set())
        )
        live = is_live_spotify_configured()
        ready = bool(reader_ready and live)
        return jsonify({
            "status": "ready" if ready else "not_ready",
            "app": "TapTune",
            "reader_ready": bool(reader_ready),
            "spotify_mode": "spotify" if live else "fake",
        }), 200 if ready else 503

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
