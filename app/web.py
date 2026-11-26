import threading
from urllib.parse import urlsplit

from flask import Flask, jsonify, redirect, render_template, request, url_for

from .config import settings
from .db import get_tag_by_uid, list_tags, upsert_tag
from .spotify_service import dispatch_tag_value, get_tag_type
from . import spotify_service
from .spotify_browser import LinkPreviewUnavailable, browse_music, import_spotify_link
from .nfc_reader import reader_supported
from .tag_writer import TagWriter, WriterBusy
from . import setup as setup_state
from . import speaker_pairing
from . import system
from .activity import ACTIVITY_LIMIT, list_activity, record_activity, record_playback, redact

TRANSLATIONS = {
    "en": {
        "switch_url": "/fr/",
        "saved": "Tag saved.",
        "section_title": "Assign a UID",
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
        "error_required": "uid and value are required",
        "error_unsupported": "Unsupported value. Use a Spotify track, playlist, album or show URI, or action:play_pause, action:next, action:next_track, action:volume_up, or action:volume_down.",
        "helper_playlist": "Spotify playlist",
        "helper_pause": "Play / pause",
        "helper_next": "Next track",
        "helper_volume_up": "Volume +10%",
        "helper_volume_down": "Volume -10%",
        "browse_title": "Make a tag",
        "choose_title": "Choose music",
        "write_title": "Write tag",
        "albums": "My albums",
        "playlists": "My playlists",
        "recent": "Recently played",
        "music": "Music",
        "podcasts": "Podcasts",
        "music_source": "Browse",
        "podcast_query": "Podcast name…",
        "empty_podcasts": "No podcasts added yet. Find a show in Spotify and paste its link above.",
        "playing": "What's playing",
        "link": "Spotify link",
        "spotify_link_label": "Paste a Spotify link",
        "spotify_link_placeholder": "https://open.spotify.com/album/…",
        "spotify_link_button": "Load link",
        "spotify_search_label": "Search Spotify by name",
        "spotify_search_placeholder": "Artist, album, song, or podcast…",
        "spotify_search_button": "Search in Spotify",
        "spotify_search_help": "Opens Spotify in a new tab. Use Share → Copy link, then paste it below.",
        "spotify_link_invalid": "Paste a valid Spotify album, playlist, track, or podcast-show link.",
        "spotify_link_unavailable": "Spotify could not load this link preview. Check the internet connection and try again.",
        "album": "Album",
        "playlist": "Playlist",
        "track": "Track",
        "show": "Podcast show",
        "load_more": "Load more",
        "loading": "Loading music…",
        "empty_albums": "No saved albums. Paste a Spotify link above.",
        "empty_playlists": "No playlists. Paste a Spotify link above.",
        "empty_recent": "No titled plays yet. Choose Music or Podcasts to get started.",
        "empty_playing": "Nothing is playing on TapTune right now. Start Spotify on a phone and select TapTune under Devices.",
        "connection_checking": "Checking Spotify…",
        "connection_live": "Spotify connected",
        "connection_note": "Uses this device’s saved Spotify connection.",
        "connection_blocked": "Spotify needs attention",
        "retry_music": "Try again",
        "recent_note": "Played on this Pi, most recent first. Only items with a known title are shown.",
        "select_music": "Choose",
        "selected_music": "Selected",
        "open_spotify": "Open in Spotify",
        "selection_hint": "Choose music first.",
        "write_tag": "Write tag",
        "write_another": "Write another tag",
        "write_instruction": "Place the tag on the Pi reader, not your phone.",
        "write_warning": "Replaces existing tag content.",
        "tag_help": "Reader help",
        "tag_help_note": "Use an unlocked NTAG213/215/216, a supported Feiju 144-byte Type 2 tag, or a writable NFC Type 4 NDEF tag. If the reader stays unavailable, use Restart TapTune on the Maintenance page.",
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
        "manual_note": "Map a tag UID to music or a playback shortcut.",
        "error_network": "Cannot reach TapTune. Check the connection and status. Pending writes expire after 60 seconds; remove the tag before retrying.",
        "spotify_rate_limit": "Spotify is limiting requests. Wait a little before retrying.",
        "spotify_unavailable": "Spotify is not answering. Check the Pi's internet connection, then try again.",
        "spotify_not_signed_in": "The Pi is not signed in to Spotify yet. Open Spotify on a phone on the same Wi-Fi, tap Devices and choose TapTune once, then retry.",
        "invalid_music_request": "This view could not load. Reload the page.",
        "reader_unavailable": "The Pi's reader is unavailable. Check its cable, then use Restart TapTune on the Maintenance page.",
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
    },
    "fr": {
        "switch_url": "/",
        "saved": "Tag enregistré.",
        "section_title": "Associer un UID",
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
        "error_required": "uid et value sont requis",
        "error_unsupported": "Valeur non prise en charge. Utilisez une URI Spotify de morceau, playlist, album ou podcast, ou action:play_pause, action:next, action:next_track, action:volume_up, ou action:volume_down.",
        "helper_playlist": "Playlist Spotify",
        "helper_pause": "Lecture / pause",
        "helper_next": "Piste suivante",
        "helper_volume_up": "Volume +10 %",
        "helper_volume_down": "Volume -10 %",
        "browse_title": "Créer un tag",
        "choose_title": "Choisir la musique",
        "write_title": "Écrire le tag",
        "albums": "Mes albums",
        "playlists": "Mes playlists",
        "recent": "Écoutés récemment",
        "music": "Musique",
        "podcasts": "Podcasts",
        "music_source": "Parcourir",
        "podcast_query": "Nom du podcast…",
        "empty_podcasts": "Aucun podcast ajouté. Cherchez une émission sur Spotify et collez son lien ci-dessus.",
        "playing": "En cours",
        "link": "Lien Spotify",
        "spotify_link_label": "Coller un lien Spotify",
        "spotify_link_placeholder": "https://open.spotify.com/album/…",
        "spotify_link_button": "Charger le lien",
        "spotify_search_label": "Rechercher un nom sur Spotify",
        "spotify_search_placeholder": "Artiste, album, morceau ou podcast…",
        "spotify_search_button": "Rechercher sur Spotify",
        "spotify_search_help": "Spotify s’ouvre dans un nouvel onglet. Utilisez Partager → Copier le lien, puis collez-le ci-dessous.",
        "spotify_link_invalid": "Collez un lien Spotify valide vers un album, une playlist, un morceau ou un podcast.",
        "spotify_link_unavailable": "Spotify n’a pas pu charger l’aperçu. Vérifiez la connexion Internet et réessayez.",
        "album": "Album",
        "playlist": "Playlist",
        "track": "Morceau",
        "show": "Podcast",
        "load_more": "Charger la suite",
        "loading": "Chargement de la musique…",
        "empty_albums": "Aucun album enregistré. Collez un lien Spotify ci-dessus.",
        "empty_playlists": "Aucune playlist. Collez un lien Spotify ci-dessus.",
        "empty_recent": "Aucune écoute avec un titre connu. Choisissez Musique ou Podcasts pour commencer.",
        "empty_playing": "Aucune musique ne joue sur TapTune. Lancez Spotify sur un téléphone, puis choisissez TapTune dans Appareils.",
        "connection_checking": "Vérification de Spotify…",
        "connection_live": "Spotify connecté",
        "connection_note": "Utilise la connexion Spotify enregistrée sur cet appareil.",
        "connection_blocked": "Vérifiez la connexion Spotify",
        "retry_music": "Réessayer",
        "recent_note": "Écoutes sur ce Pi, de la plus récente à la plus ancienne. Seuls les titres connus sont affichés.",
        "select_music": "Choisir",
        "selected_music": "Sélection",
        "open_spotify": "Ouvrir dans Spotify",
        "selection_hint": "Choisissez d’abord la musique.",
        "write_tag": "Écrire le tag",
        "write_another": "Écrire un autre tag",
        "write_instruction": "Posez le tag sur le lecteur du Pi, pas sur votre téléphone.",
        "write_warning": "Remplace le contenu existant du tag.",
        "tag_help": "Aide du lecteur",
        "tag_help_note": "Utilisez un NTAG213/215/216 non verrouillé, un tag Feiju Type 2 de 144 octets pris en charge ou un tag NFC Type 4 NDEF accessible en écriture. Si le lecteur reste indisponible, utilisez Redémarrer TapTune sur la page Maintenance.",
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
        "manual_note": "Associez un UID à la musique ou à un raccourci de lecture.",
        "error_network": "TapTune est inaccessible. Vérifiez la connexion et l’état. Une écriture expire après 60 secondes ; retirez le tag avant de réessayer.",
        "spotify_rate_limit": "Spotify limite les requêtes. Patientez avant de réessayer.",
        "spotify_unavailable": "Spotify ne répond pas. Vérifiez la connexion Internet du Pi, puis réessayez.",
        "spotify_not_signed_in": "Le Pi n’est pas encore connecté à Spotify. Ouvrez Spotify sur un téléphone connecté au même Wi-Fi, touchez Appareils et choisissez TapTune une fois, puis réessayez.",
        "invalid_music_request": "Cette vue n’a pas pu se charger. Rechargez la page.",
        "reader_unavailable": "Le lecteur du Pi est indisponible. Vérifiez son câble, puis utilisez Redémarrer TapTune sur la page Maintenance.",
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
            thread is not None and thread.is_alive()
            and isinstance(ready, threading.Event) and ready.is_set()
        )

    def api_response(data, status=200):
        response = jsonify(data)
        response.status_code = status
        response.headers["Cache-Control"] = "no-store"
        return response

    def api_error(code, status):
        return api_response({"error": code}, status)

    def rate_limit_response(seconds):
        response = api_error("spotify_rate_limit", 429)
        response.headers["Retry-After"] = str(max(1, int(seconds)))
        return response

    @app.get("/api/music")
    def music():
        try:
            result = browse_music(
                request.args.get("collection", "recent"), offset=int(request.args.get("offset", "0")),
            )
        except ValueError:
            return api_error("invalid_music_request", 400)
        except spotify_service.RateLimited as error:
            return rate_limit_response(error.seconds)
        except spotify_service.NotLoggedIn:
            app.logger.warning("Spotify browsing needs the Pi to be signed in to Spotify (go-librespot).")
            return api_error("spotify_not_signed_in", 409)
        except (spotify_service.LibrespotUnavailable, spotify_service.LibrespotError) as error:
            app.logger.warning("Spotify browsing failed: go-librespot is unavailable (%s).", error)
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

    @app.post("/api/music/link")
    def music_link():
        if not valid_write_request():
            return api_error("invalid_origin", 403)
        data = request.get_json()
        value = data.get("url") if isinstance(data, dict) else None
        try:
            item = import_spotify_link(value)
        except ValueError:
            return api_error("spotify_link_invalid", 400)
        except LinkPreviewUnavailable:
            app.logger.warning("Spotify link preview is unavailable.")
            return api_error("spotify_link_unavailable", 502)
        return api_response({"item": item, "mode": "preview"})

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
        )

    def setup_redirect(locale):
        if setup_state.onboarding_complete():
            return None
        return redirect("/fr/setup" if locale == "fr" else "/setup")

    def render_setup(locale, message=None, status=200):
        steps = setup_state.setup_steps()
        response = app.make_response((render_template(
            "setup.html", locale=locale, steps=steps, message=message,
            complete=setup_state.setup_complete(steps),
            home_url="/fr/" if locale == "fr" else "/",
            switch_url="/setup" if locale == "fr" else "/fr/setup",
            action="/fr/setup" if locale == "fr" else "/setup",
        ), status))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/setup")
    @app.get("/fr/setup")
    def setup_page():
        return render_setup("fr" if request.path.startswith("/fr/") else "en",
                            None)

    @app.get("/api/setup")
    def setup_api():
        steps = setup_state.setup_steps()
        return api_response({"steps": steps, "complete": setup_state.setup_complete(steps)})

    def speaker_call(action):
        if not valid_write_request():
            return api_error("invalid_origin", 403)
        try:
            return action()
        except speaker_pairing.PairingBusy:
            return api_error("bluetooth_busy", 409)
        except speaker_pairing.PairingError as error:
            if error.detail:
                app.logger.warning("Speaker setup failed (%s): %s", error.code, error.detail)
            return api_error(error.code, 400 if error.code == "invalid_mac" else 502)

    @app.post("/api/setup/speaker/scan")
    def speaker_scan():
        return speaker_call(lambda: api_response({"speakers": speaker_pairing.scan_speakers()}))

    @app.post("/api/setup/speaker/pair")
    def speaker_pair():
        def pair():
            data = request.get_json()
            speaker = speaker_pairing.pair_speaker(data.get("mac") if isinstance(data, dict) else None)
            try:
                speaker_pairing.save_speaker(speaker["mac"])
            except (OSError, setup_state.InvalidSetting):
                app.logger.exception("Could not save the Bluetooth speaker.")
                return api_error("save_failed", 500)
            return api_response({"speaker": speaker})
        return speaker_call(pair)

    @app.post("/api/setup/speaker/test")
    def speaker_test():
        def play():
            from .readiness import build_chime_wav, play_ready_sound
            if not settings.BLUETOOTH_SPEAKER_MAC.strip():
                return api_error("no_speaker", 409)
            return api_response({"played": bool(play_ready_sound(build_chime_wav()))})
        return speaker_call(play)

    @app.get("/")
    def index_en():
        return setup_redirect("en") or render_index("en", saved=request.args.get("saved") == "1")

    @app.get("/fr/")
    def index_fr():
        return setup_redirect("fr") or render_index("fr", saved=request.args.get("saved") == "1")

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

    @app.get("/api/system")
    def system_status():
        return api_response({"version": system.code_version(), "update": system.update_status()})

    def system_action(name, action):
        if not valid_write_request():
            return api_error("invalid_origin", 403)
        record_activity("diagnostic", "WARNING", "web", f"{name} requested from the web page.")
        action()
        return api_response({"status": "started"}, 202)

    @app.post("/api/system/update")
    def system_update():
        if not valid_write_request():
            return api_error("invalid_origin", 403)
        try:
            system.start_update()
        except system.UpdateRunning:
            return api_error("update_running", 409)
        except (OSError, KeyError) as error:
            app.logger.error("Could not start the update: %s", error)
            return api_error("update_failed", 500)
        record_activity("diagnostic", "WARNING", "web", "Update requested from the web page.")
        return api_response({"status": "started"}, 202)

    @app.post("/api/system/restart")
    def system_restart():
        return system_action("Restart", system.restart_app)

    @app.post("/api/system/reboot")
    def system_reboot():
        return system_action("Reboot", system.reboot)

    @app.get("/api/system/diagnostics")
    def system_diagnostics():
        entries, _ = list_activity(page=1)
        activity = "\n".join(
            f"{row.get('created_at', '')} {row.get('level', '')} {row.get('kind', '')} {row.get('message', '')}"
            for row in entries
        )
        text = (
            f"TapTune {system.code_version()}\n"
            f"Receiver: {settings.SPOTIFY_DEVICE_NAME}\nSpeaker: {settings.BLUETOOTH_SPEAKER_MAC or '(none)'}\n"
            f"NFC reader: {'ready' if reader_available() else 'not found'}\n"
            f"Setup: {[(step['id'], step['state'], step.get('reason')) for step in setup_state.setup_steps()]}\n\n"
            f"== Last update ==\n{system.update_status()['log']}\n\n"
            f"== Activity (newest first) ==\n{activity}\n\n"
            f"== System journal (this boot) ==\n{system.journal()}"
        )
        response = app.make_response((redact(text, None), 200, {"Content-Type": "text/plain; charset=utf-8"}))
        response.headers["Content-Disposition"] = "attachment; filename=taptune-diagnostics.txt"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "app": "TapTune"})

    @app.get("/ready")
    def ready():
        reader = app.config.get("NFC_READER_THREAD")
        reader_event = getattr(reader, "reader_ready", None)
        # Without the PN532 libraries (not a Pi) no reader thread is started.
        reader_ready = not reader_supported() or (
            reader is not None and reader.is_alive()
            and (not isinstance(reader_event, threading.Event) or reader_event.is_set())
        )
        return jsonify({
            "status": "ready" if reader_ready else "not_ready",
            "app": "TapTune",
            "reader_ready": bool(reader_ready),
        }), 200 if reader_ready else 503

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
