import threading
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, request, url_for

from .config import settings
from .db import get_tag_by_uid, list_tags, record_event, upsert_tag
from .spotify_service import dispatch_tag_value, get_tag_type, is_live_spotify_configured
from . import spotify_service
from .spotify_browser import browse_music
from .tag_writer import TagWriter, WriterBusy
from .activity import ACTIVITY_LIMIT, list_activity, record_activity, record_playback

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
        "saved": "Tag saved.",
        "badge_step": "01 / Map a physical input",
        "section_title": "Assign a UID",
        "intro": "Enter the UID printed by the reader, then point it at a Spotify URI or a playback action.",
        "quick_fill": "Quick fill",
        "uid_label": "Tag UID",
        "uid_placeholder": "Example: 04A7B2F1…",
        "label_label": "Friendly label",
        "label_placeholder": "Example: Morning playlist…",
        "value_label": "Spotify URI / Action",
        "value_placeholder": "spotify:playlist:… / spotify:show:… or action:play_pause",
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
        "error_unsupported": "Unsupported value. Use a Spotify track, playlist, album or show URI, or action:play_pause, action:next, action:next_track, action:volume_up, or action:volume_down.",
        "helper_playlist": "Spotify playlist",
        "helper_pause": "Play / pause",
        "helper_next": "Next track",
        "helper_volume_up": "Volume +10%",
        "helper_volume_down": "Volume -10%",
        "browse_title": "Make a tag",
        "browse_intro": "Choose an album, playlist, song or podcast show. Then write it to a tag using the reader on your Pi.",
        "choose_title": "Choose music",
        "write_title": "Write tag",
        "albums": "My albums",
        "playlists": "My playlists",
        "recent": "Recent albums",
        "search": "Search Spotify",
        "search_label": "Search Spotify",
        "search_placeholder": "Search Spotify…",
        "group_album": "Albums",
        "group_playlist": "Playlists",
        "group_track": "Songs",
        "group_show": "Podcasts",
        "album": "Album",
        "playlist": "Playlist",
        "track": "Track",
        "show": "Podcast show",
        "search_button": "Search",
        "load_more": "Load more",
        "loading": "Loading music…",
        "empty_music": "No results for this search. Try another name.",
        "empty_albums": "No saved albums. Try Search.",
        "empty_playlists": "No playlists. Try Search.",
        "empty_recent": "No recent albums. Try Search.",
        "demo_title": "Demo — sample music only",
        "demo_music": "No Spotify account is configured here. Open TapTune on your Pi for your library.",
        "demo_help": "Your token on the Pi is not available in this computer's preview. Open TapTune on your Pi to use its saved Spotify connection. You do not need to paste the token into this page.",
        "connection_checking": "Checking Spotify…",
        "connection_saved": "Uses this device’s saved Spotify connection.",
        "connection_live": "Spotify connected",
        "connection_live_note": "Uses this device’s saved Spotify connection.",
        "connection_help": "About this connection",
        "connection_blocked": "Spotify needs attention",
        "connection_permissions": "Spotify needs permission for this view",
        "connection_permissions_note": "Your saved token is being used, but Spotify refused access. A playback-only token needs a one-time approval for saved albums, private playlists and listening history. You can also try Search Spotify.",
        "connection_auth": "Spotify did not accept the saved connection",
        "spotify_auth_error": "The saved Spotify token is invalid or expired. Follow the setup guide to authorize TapTune again, then restart it.",
        "retry_music": "Try again",
        "search_prompt": "",
        "recent_note": "Albums from your last 50 tracks.",
        "select_music": "Choose",
        "selected_music": "Selected",
        "open_spotify": "Open in Spotify",
        "selection_hint": "Choose music first.",
        "write_tag": "Write tag",
        "write_another": "Write another tag",
        "write_instruction": "Place the tag on the Pi reader, not your phone.",
        "write_warning": "Replaces existing tag content.",
        "tag_help": "Reader help",
        "tag_help_note": "Use an unlocked NTAG213/215/216, a supported Feiju 144-byte Type 2 tag, or a writable NFC Type 4 NDEF tag. On the Pi, enable NFC_READER_ENABLED and run python -m app.main (or the TapTune service).",
        "writer_disabled": "Reader unavailable · See Reader help",
        "writer_ready": "Reader ready",
        "check_reader": "Check reader",
        "check_write": "Check status",
        "write_preparing_title": "Preparing reader…",
        "write_waiting_title": "Place tag on Pi reader",
        "write_success_title": "Tag written",
        "write_error_title": "Write failed",
        "write_uncertain_title": "Write status unknown",
        "write_cancelled_title": "Cancelled",
        "waiting": "Keep it still until confirmation. Expires after 60 seconds; playback scanning is paused.",
        "write_success": "Verified. Remove the tag, then tap to play.",
        "cancel": "Cancel",
        "cancelled": "Remove the tag from the reader.",
        "use_assignment": "Use in manual setup",
        "selection_details": "Spotify link / manual setup",
        "change_music": "Change music",
        "pending_selection": "Restored selection",
        "advanced_options": "Manual setup",
        "assigned_note": "UID mappings only, not tags written above.",
        "manual_assignment": "Manual UID assignment",
        "manual_note": "Map a tag UID to music or a playback shortcut.",
        "error_network": "Cannot reach TapTune. Check the connection and status. Pending writes expire after 60 seconds; remove the tag before retrying.",
        "spotify_permissions": "Spotify access is missing or expired. Re-authorize with library, private playlist and recently played permissions, then update the Pi's refresh token and restart TapTune.",
        "spotify_rate_limit": "Spotify is limiting requests. Wait a little before retrying.",
        "spotify_unavailable": "Spotify is unavailable. Check the Pi's internet connection and Spotify configuration, then retry.",
        "invalid_music_request": "Enter a search between 1 and 200 characters.",
        "reader_unavailable": "The Pi's reader is unavailable. Check its connection and restart TapTune if needed.",
        "writer_busy": "Another tag write is pending. Wait for it to finish or expire.",
        "write_timeout": "No tag was written within 60 seconds. Remove any tag and try again.",
        "tag_changed": "The tag was removed or changed. Keep one tag on the reader and try again.",
        "unsupported_tag": "Unsupported tag. See Reader help for compatible tags, or use manual UID setup.",
        "tag_locked": "This tag is locked or protected. Use an unlocked tag.",
        "tag_too_small": "This tag does not have enough writable space for the link.",
        "tag_read_failed": "The reader could not inspect the tag. Reposition it and try again.",
        "tag_write_failed": "Writing failed; the tag may be incomplete. Keep it on the reader and retry.",
        "tag_verify_failed": "The written link could not be verified. The tag may be incomplete; write it again.",
        "write_not_found": "This write session is no longer available. Remove the tag, then start a new write.",
        "invalid_write": "Choose a Spotify album, playlist, track or podcast show before writing.",
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
        "saved": "Tag enregistré.",
        "badge_step": "01 / Associer une entrée physique",
        "section_title": "Associer un UID",
        "intro": "Saisissez le UID affiché par le lecteur, puis pointez vers une URI Spotify ou une action de lecture.",
        "quick_fill": "Remplissage rapide",
        "uid_label": "UID du tag",
        "uid_placeholder": "Exemple : 04A7B2F1…",
        "label_label": "Étiquette conviviale",
        "label_placeholder": "Exemple : Playlist du matin…",
        "value_label": "URI Spotify / Action",
        "value_placeholder": "spotify:playlist:… / spotify:show:… ou action:play_pause",
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
        "error_unsupported": "Valeur non prise en charge. Utilisez une URI Spotify de morceau, playlist, album ou podcast, ou action:play_pause, action:next, action:next_track, action:volume_up, ou action:volume_down.",
        "helper_playlist": "Playlist Spotify",
        "helper_pause": "Lecture / pause",
        "helper_next": "Piste suivante",
        "helper_volume_up": "Volume +10 %",
        "helper_volume_down": "Volume -10 %",
        "browse_title": "Créer un tag",
        "browse_intro": "Choisissez un album, une playlist, un morceau ou un podcast. Écrivez-le ensuite sur un tag avec le lecteur de votre Pi.",
        "choose_title": "Choisir la musique",
        "write_title": "Écrire le tag",
        "albums": "Mes albums",
        "playlists": "Mes playlists",
        "recent": "Albums récents",
        "search": "Rechercher sur Spotify",
        "search_label": "Rechercher sur Spotify",
        "search_placeholder": "Rechercher sur Spotify…",
        "group_album": "Albums",
        "group_playlist": "Playlists",
        "group_track": "Morceaux",
        "group_show": "Podcasts",
        "album": "Album",
        "playlist": "Playlist",
        "track": "Morceau",
        "show": "Podcast",
        "search_button": "Rechercher",
        "load_more": "Charger la suite",
        "loading": "Chargement de la musique…",
        "empty_music": "Aucun résultat. Essayez un autre nom.",
        "empty_albums": "Aucun album enregistré. Essayez la recherche.",
        "empty_playlists": "Aucune playlist. Essayez la recherche.",
        "empty_recent": "Aucun album récent. Essayez la recherche.",
        "demo_title": "Démo — musique fictive",
        "demo_music": "Aucun compte Spotify configuré ici. Ouvrez TapTune sur votre Pi pour retrouver votre bibliothèque.",
        "demo_help": "Le jeton de votre Pi n’est pas disponible dans l’aperçu de cet ordinateur. Ouvrez TapTune sur votre Pi pour utiliser sa connexion Spotify enregistrée. Aucun jeton à coller dans cette page.",
        "connection_checking": "Vérification de Spotify…",
        "connection_saved": "Utilise la connexion Spotify enregistrée sur cet appareil.",
        "connection_live": "Spotify connecté",
        "connection_live_note": "Utilise la connexion Spotify enregistrée sur cet appareil.",
        "connection_help": "À propos de cette connexion",
        "connection_blocked": "Vérifiez la connexion Spotify",
        "connection_permissions": "Spotify demande une autorisation pour cette vue",
        "connection_permissions_note": "Votre jeton enregistré est utilisé, mais Spotify refuse l’accès. Un jeton limité à la lecture musicale nécessite une nouvelle approbation pour les albums enregistrés, les playlists privées et l’historique. Vous pouvez aussi essayer Rechercher sur Spotify.",
        "connection_auth": "Spotify refuse la connexion enregistrée",
        "spotify_auth_error": "Le jeton Spotify enregistré est invalide ou expiré. Suivez le guide pour autoriser TapTune à nouveau, puis redémarrez-le.",
        "retry_music": "Réessayer",
        "search_prompt": "",
        "recent_note": "Albums des 50 derniers morceaux écoutés.",
        "select_music": "Choisir",
        "selected_music": "Sélection",
        "open_spotify": "Ouvrir dans Spotify",
        "selection_hint": "Choisissez d’abord la musique.",
        "write_tag": "Écrire le tag",
        "write_another": "Écrire un autre tag",
        "write_instruction": "Posez le tag sur le lecteur du Pi, pas sur votre téléphone.",
        "write_warning": "Remplace le contenu existant du tag.",
        "tag_help": "Aide du lecteur",
        "tag_help_note": "Utilisez un NTAG213/215/216 non verrouillé, un tag Feiju Type 2 de 144 octets pris en charge ou un tag NFC Type 4 NDEF accessible en écriture. Sur le Pi, activez NFC_READER_ENABLED et lancez python -m app.main (ou le service TapTune).",
        "writer_disabled": "Lecteur indisponible · Voir Aide du lecteur",
        "writer_ready": "Lecteur prêt",
        "check_reader": "Vérifier le lecteur",
        "check_write": "Vérifier l’état",
        "write_preparing_title": "Préparation du lecteur…",
        "write_waiting_title": "Posez le tag sur le lecteur du Pi",
        "write_success_title": "Tag écrit",
        "write_error_title": "Échec de l’écriture",
        "write_uncertain_title": "État de l’écriture inconnu",
        "write_cancelled_title": "Annulé",
        "waiting": "Gardez-le immobile jusqu’à confirmation. Expire après 60 secondes ; la détection pour la lecture est suspendue.",
        "write_success": "Vérifié. Retirez le tag, puis présentez-le pour écouter.",
        "cancel": "Annuler",
        "cancelled": "Retirez le tag du lecteur.",
        "use_assignment": "Utiliser dans la configuration manuelle",
        "selection_details": "Lien Spotify / configuration manuelle",
        "change_music": "Changer la musique",
        "pending_selection": "Sélection restaurée",
        "advanced_options": "Configuration manuelle",
        "assigned_note": "Associations par UID uniquement, pas les tags écrits ci-dessus.",
        "manual_assignment": "Assignation manuelle par UID",
        "manual_note": "Associez un UID à la musique ou à un raccourci de lecture.",
        "error_network": "TapTune est inaccessible. Vérifiez la connexion et l’état. Une écriture expire après 60 secondes ; retirez le tag avant de réessayer.",
        "spotify_permissions": "L’accès Spotify est absent ou expiré. Autorisez à nouveau l’accès à la bibliothèque, aux playlists privées et à l’historique, puis mettez à jour le jeton du Pi et redémarrez TapTune.",
        "spotify_rate_limit": "Spotify limite les requêtes. Patientez avant de réessayer.",
        "spotify_unavailable": "Spotify est indisponible. Vérifiez la connexion Internet et la configuration Spotify du Pi, puis réessayez.",
        "invalid_music_request": "Saisissez une recherche de 1 à 200 caractères.",
        "reader_unavailable": "Le lecteur du Pi est indisponible. Vérifiez sa connexion et redémarrez TapTune si nécessaire.",
        "writer_busy": "Une autre écriture est en attente. Attendez sa fin ou son expiration.",
        "write_timeout": "Aucun tag écrit dans les 60 secondes. Retirez tout tag et réessayez.",
        "tag_changed": "Le tag a été retiré ou remplacé. Gardez un seul tag sur le lecteur et réessayez.",
        "unsupported_tag": "Tag non compatible. Consultez Aide du lecteur ou utilisez une association par UID.",
        "tag_locked": "Ce tag est verrouillé ou protégé. Utilisez un tag non verrouillé.",
        "tag_too_small": "Ce tag ne dispose pas d’assez de mémoire accessible pour le lien.",
        "tag_read_failed": "Impossible d’inspecter le tag. Repositionnez-le et réessayez.",
        "tag_write_failed": "L’écriture a échoué ; le tag peut être incomplet. Gardez-le sur le lecteur et réessayez.",
        "tag_verify_failed": "Le lien écrit n’a pas pu être vérifié. Le tag peut être incomplet ; réécrivez-le.",
        "write_not_found": "Cette session d’écriture n’est plus disponible. Retirez le tag et recommencez.",
        "invalid_write": "Choisissez un album, une playlist, un morceau ou un podcast Spotify avant l’écriture.",
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
                query=request.args.get("q", ""), kind=request.args.get("kind", "all"),
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

    @app.get("/logs")
    @app.get("/fr/logs")
    def logs():
        locale = "fr" if request.path.startswith("/fr/") else "en"
        query = request.args.get("q", "").strip()
        kind = request.args.get("kind", "")
        level = request.args.get("level", "")
        try:
            page = int(request.args.get("page", "1"))
            entries, more = list_activity(query, kind, level, page)
        except ValueError:
            return jsonify({"error": "Invalid activity filters or page"}), 400
        response = app.make_response(render_template(
            "logs.html", locale=locale, entries=entries, more=more, page=page,
            query=query, kind=kind, level=level, limit=ACTIVITY_LIMIT,
            home_url="/fr/" if locale == "fr" else "/",
            switch_url="/logs" if locale == "fr" else "/fr/logs",
        ))
        response.headers["Cache-Control"] = "no-store"
        return response

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
                record_activity("playback", "WARNING", "web", "Unknown tag UID.", uid=uid)
                return jsonify({"error": "Unknown tag"}), 404
            value = tag["value"]

        record_event(uid or "simulated", "content" if value.startswith("spotify:") else "action", value, source="web")
        try:
            result = dispatch_tag_value(value)
        except Exception:
            record_activity(
                "playback", "ERROR", "web", "Tag dispatch failed; check the service logs and try again.",
                uid=uid or "simulated", value=value,
            )
            raise
        record_playback(uid or "simulated", value, "web", result)
        if isinstance(result, dict) and result.get("status") == "error":
            return jsonify({"status": "error", "result": result}), 502
        return jsonify({"status": "ok", "result": result})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=settings.APP_HOST, port=settings.APP_PORT, debug=False)
