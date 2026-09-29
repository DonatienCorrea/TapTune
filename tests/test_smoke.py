import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, db, nfc_reader, spotify_service
from app.db import clear_all_tags, get_tag_by_uid
from app.simulate import dispatch_simulated_value
from app.web import create_app


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = str(Path(self.temporary_directory.name) / "taptune.db")
        self.original_database_path = config.settings.DATABASE_PATH
        config.settings.DATABASE_PATH = self.database_path
        spotify_credentials = patch.multiple(
            config.settings,
            SPOTIFY_CLIENT_ID="",
            SPOTIFY_CLIENT_SECRET="",
            SPOTIFY_REFRESH_TOKEN="",
        )
        spotify_credentials.start()
        self.addCleanup(spotify_credentials.stop)
        spotify_service._fake_spotify_client = None
        clear_all_tags()
        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        config.settings.DATABASE_PATH = self.original_database_path
        spotify_service._fake_spotify_client = None
        self.temporary_directory.cleanup()

    def test_health(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'ok')

    def test_assign_and_dispatch_playlist(self):
        assign = self.client.post('/assign', data={
            'uid': 'UID-001',
            'value': 'spotify:playlist:123abc',
            'label': 'Morning mix'
        }, follow_redirects=True)
        self.assertEqual(assign.status_code, 200)

        dispatch = self.client.post('/dispatch', data={'uid': 'UID-001'})
        self.assertEqual(dispatch.status_code, 200)
        payload = dispatch.get_json()
        self.assertEqual(payload['status'], 'ok')
        self.assertIn('mode', payload['result'])

    def test_invalid_assignment_is_rejected_and_not_persisted(self):
        response = self.client.post('/assign', data={
            'uid': 'UID-INVALID',
            'value': 'not-a-supported-value',
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn('Unsupported value', response.get_json()['error'])
        self.assertIsNone(get_tag_by_uid('UID-INVALID'))

    def test_play_pause_action(self):
        first = self.client.post('/dispatch', data={'value': 'action:play_pause'})
        second = self.client.post('/dispatch', data={'value': 'action:play_pause'})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()['result']['status'], 'ok')
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()['result']['paused'])

    def test_next_track_alias(self):
        dispatch = self.client.post('/dispatch', data={'value': 'action:next_track'})

        self.assertEqual(dispatch.status_code, 200)
        self.assertEqual(dispatch.get_json()['result']['action'], 'next')

    def test_invalid_simulated_value_is_not_persisted(self):
        with self.assertRaisesRegex(ValueError, "Unsupported simulated tag value"):
            dispatch_simulated_value("UID-INVALID", "action:unsupported")

        self.assertIsNone(get_tag_by_uid("UID-INVALID"))

    def test_invalid_spotify_uri_does_not_start_playback(self):
        result = spotify_service.dispatch_tag_value("spotify:playlist:not-an-id")

        self.assertEqual(result, {"status": "unsupported_uri", "uri": "spotify:playlist:not-an-id"})
        self.assertIsNone(spotify_service._fake_spotify_client)

    def test_invalid_playback_position_is_rejected(self):
        result = spotify_service.play_content("spotify:track:123abc", -1)

        self.assertEqual(result, {"status": "invalid_position", "position_ms": -1})
        self.assertIsNone(spotify_service._fake_spotify_client)

    def test_rc522_reader_uses_the_value_assigned_to_the_scanned_uid(self):
        class FakeReader:
            MI_OK = 0
            PICC_REQIDL = 0

            def MFRC522_Request(self, request):
                return self.MI_OK, None

            def MFRC522_Anticoll(self):
                return self.MI_OK, [4, 167, 178, 241, 224]

        class FakeGPIO:
            BOARD = 10
            OUT = 0
            HIGH = 1

            def __init__(self):
                self.mode = None
                self.setup_calls = []

            def getmode(self):
                return self.mode

            def setmode(self, mode):
                self.mode = mode

            def setup(self, pin, direction, initial):
                self.setup_calls.append((pin, direction, initial))

        dispatch_simulated_value("04A7B2F1", "action:next")
        gpio = FakeGPIO()
        with patch.object(nfc_reader, "GPIO", gpio):
            with patch.object(nfc_reader, "MFRC522", return_value=FakeReader()) as reader_class:
                event = nfc_reader.RC522Reader().read_once()

        reader_class.assert_called_once_with(pin_mode=gpio.BOARD, pin_rst=22)
        self.assertEqual(gpio.setup_calls, [(22, gpio.OUT, gpio.HIGH)])
        self.assertIsNotNone(event)
        self.assertEqual(event.uid, "04A7B2F1")
        self.assertEqual(event.payload, "action:next")

    def test_read_uid_from_hardware_polls_until_a_tag_is_present(self):
        class FakeHardwareReader:
            def __init__(self):
                self.calls = 0

            def read_once(self):
                self.calls += 1
                if self.calls < 3:
                    return None
                return nfc_reader.NFCEvent(uid="04A7B2F1", payload="04A7B2F1")

        fake_reader = FakeHardwareReader()
        with patch.object(nfc_reader, "RC522Reader", return_value=fake_reader):
            with patch.object(nfc_reader.time, "sleep") as mock_sleep:
                uid = nfc_reader.read_uid_from_hardware()

        self.assertEqual(uid, "04A7B2F1")
        self.assertEqual(fake_reader.calls, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_missing_schema_fails_at_connection_setup(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            missing_schema = Path(temp_directory) / "schema.sql"
            with patch.object(db, "SCHEMA_PATH", missing_schema):
                with self.assertRaisesRegex(FileNotFoundError, "Database schema not found"):
                    db.get_connection()

    def test_missing_spotify_dependency_uses_fake_client(self):
        from app import spotify_service

        original_spotify = spotify_service.Spotify
        original_oauth = spotify_service.SpotifyOAuth
        spotify_service.Spotify = None
        spotify_service.SpotifyOAuth = None

        try:
            client = spotify_service.build_spotify_client()
            self.assertIsInstance(client, spotify_service.FakeSpotifyClient)
            self.assertEqual(spotify_service.dispatch_tag_value('spotify:track:demo')['status'], 'ok')
        finally:
            spotify_service.Spotify = original_spotify
            spotify_service.SpotifyOAuth = original_oauth


class ConfigurationTests(unittest.TestCase):
    def test_parse_port_accepts_valid_boundary_values(self):
        self.assertEqual(config.parse_port("1"), 1)
        self.assertEqual(config.parse_port("65535"), 65535)

    def test_parse_port_rejects_invalid_values_with_configuration_name(self):
        for value in ("", "not-a-port", "0", "65536"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "APP_PORT"):
                    config.parse_port(value)


if __name__ == '__main__':
    unittest.main()
