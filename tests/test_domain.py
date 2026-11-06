import unittest

from melodrop.domain.errors import ErrorRule, ErrorTranslator
from melodrop.domain.formats import DEFAULT_FORMATS, AudioFormat, FormatRegistry, VideoFormat
from melodrop.domain.models import Playlist, Track, TrackStatus
from melodrop.domain.naming import safe_filename
from melodrop.domain.options import DownloadOptions

KNOWN = DEFAULT_FORMATS.keys()


class SafeFilenameTest(unittest.TestCase):
    def test_replaces_characters_forbidden_on_any_os(self):
        self.assertEqual(safe_filename('AC/DC: "Back" <in> Black?'), "AC_DC_ _Back_ _in_ Black_")

    def test_trims_dots_and_spaces_and_collapses_whitespace(self):
        self.assertEqual(safe_filename("  ..My   Mix.. "), "My Mix")

    def test_falls_back_when_nothing_is_left(self):
        self.assertEqual(safe_filename(" ... "), "Download")
        self.assertEqual(safe_filename("", fallback="X"), "X")

    def test_limits_length(self):
        self.assertEqual(len(safe_filename("a" * 500)), 120)

    def test_keeps_unicode(self):
        self.assertEqual(safe_filename("Olhe Nós Dois"), "Olhe Nós Dois")


class TrackTest(unittest.TestCase):
    def test_from_dict_requires_http_url(self):
        with self.assertRaises(ValueError):
            Track.from_dict({"id": "x", "url": "file:///etc/passwd"})

    def test_from_dict_keeps_only_safe_fields(self):
        track = Track.from_dict(
            {"id": "abc", "title": "Song", "url": "https://youtu.be/abc", "position": 3, "thumbnail": "ignored"}
        )
        self.assertEqual(track, Track(id="abc", title="Song", url="https://youtu.be/abc", position=3))

    def test_from_dict_ignores_invalid_position(self):
        for bad in (0, -1, "2", 1.5, True, None):
            self.assertIsNone(Track.from_dict({"url": "https://x", "position": bad}).position)

    def test_from_dict_defaults_id_and_title_to_url(self):
        track = Track.from_dict({"url": "https://x"})
        self.assertEqual((track.id, track.title), ("https://x", "https://x"))


class PlaylistTest(unittest.TestCase):
    def test_total_duration_ignores_unknown_durations(self):
        playlist = Playlist(
            "P", (Track("a", "A", "https://a", duration=60), Track("b", "B", "https://b", duration=None))
        )
        self.assertEqual(playlist.total_duration, 60)
        self.assertEqual(playlist.to_dict()["tracks"][0]["title"], "A")


class TrackStatusTest(unittest.TestCase):
    def test_final_statuses(self):
        self.assertEqual(
            {s for s in TrackStatus if s.is_final}, {TrackStatus.DONE, TrackStatus.ERROR, TrackStatus.CANCELLED}
        )


class DownloadOptionsTest(unittest.TestCase):
    def test_defaults_are_mp3_320_with_cover(self):
        options = DownloadOptions.from_dict({}, KNOWN)
        self.assertEqual(options, DownloadOptions())
        self.assertEqual((options.format, options.bitrate, options.embed_cover), ("mp3", 320, True))

    def test_accepts_valid_values_including_numeric_strings(self):
        options = DownloadOptions.from_dict(
            {
                "format": "flac",
                "bitrate": "192",
                "height": 720,
                "browser": "firefox",
                "embed_cover": False,
                "number_files": True,
            },
            KNOWN,
        )
        self.assertEqual(
            (options.format, options.bitrate, options.height, options.browser), ("flac", 192, 720, "firefox")
        )
        self.assertFalse(options.embed_cover)
        self.assertTrue(options.number_files)

    def test_invalid_values_fall_back_to_defaults(self):
        options = DownloadOptions.from_dict(
            {"format": "exe", "bitrate": 9999, "height": "tall", "browser": "netscape"}, KNOWN
        )
        self.assertEqual(options, DownloadOptions())


class FormatsTest(unittest.TestCase):
    def test_lossy_audio_sets_bitrate_and_square_cover(self):
        args = AudioFormat("mp3", "MP3").ytdlp_args(DownloadOptions(bitrate=256))
        self.assertEqual(args[:5], ["-f", "bestaudio/best", "-x", "--audio-format", "mp3"])
        self.assertIn("256K", args)
        self.assertIn("--embed-thumbnail", args)
        self.assertIn("--ppa", args)

    def test_lossless_audio_has_no_bitrate(self):
        args = DEFAULT_FORMATS.get("flac").ytdlp_args(DownloadOptions())
        self.assertNotIn("--audio-quality", args)

    def test_wav_never_embeds_cover(self):
        args = DEFAULT_FORMATS.get("wav").ytdlp_args(DownloadOptions(embed_cover=True))
        self.assertNotIn("--embed-thumbnail", args)

    def test_cover_options_can_be_turned_off(self):
        mp3 = DEFAULT_FORMATS.get("mp3")
        self.assertNotIn("--ppa", mp3.ytdlp_args(DownloadOptions(square_cover=False)))
        self.assertNotIn("--embed-thumbnail", mp3.ytdlp_args(DownloadOptions(embed_cover=False)))

    def test_video_caps_height_and_merges_to_mp4(self):
        args = VideoFormat("mp4", "MP4").ytdlp_args(DownloadOptions(height=720))
        self.assertIn("bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]/b", args)
        self.assertEqual(args[args.index("--merge-output-format") + 1], "mp4")

    def test_describe_exposes_ui_hints(self):
        described = {f["key"]: f for f in (fmt.describe() for fmt in DEFAULT_FORMATS)}
        self.assertEqual(
            described["mp3"], {"key": "mp3", "label": "MP3", "kind": "audio", "lossy": True, "supports_cover": True}
        )
        self.assertEqual(described["mp4"]["kind"], "video")
        self.assertFalse(described["wav"]["supports_cover"])

    def test_registry_rejects_duplicates_and_unknown_keys(self):
        with self.assertRaises(ValueError):
            FormatRegistry([AudioFormat("mp3", "a"), AudioFormat("mp3", "b")])
        with self.assertRaises(KeyError):
            DEFAULT_FORMATS.get("exe")
        self.assertIn("opus", DEFAULT_FORMATS)
        self.assertNotIn("exe", DEFAULT_FORMATS)


class ErrorTranslatorTest(unittest.TestCase):
    BOT = "[youtube] _z4eli7hQVY: Sign in to confirm you’re not a bot. This helps protect our community."

    def setUp(self):
        self.translator = ErrorTranslator()

    def test_bot_check_without_browser_points_to_browser_login(self):
        message = self.translator.translate(self.BOT)
        self.assertIn("Use browser login", message)
        self.assertIn("Retry failed", message)

    def test_bot_check_with_browser_names_it(self):
        self.assertIn("in Chrome", self.translator.translate(self.BOT, "chrome"))

    def test_cookie_problems_are_explained_per_browser(self):
        safari = self.translator.translate("Operation not permitted: Cookies.binarycookies", "safari")
        self.assertIn("Full Disk Access", safari)
        chrome = self.translator.translate("failed to decrypt cookie with keyring", "chrome")
        self.assertIn("Always Allow", chrome)

    def test_cookie_words_without_browser_are_not_cookie_errors(self):
        self.assertEqual(self.translator.translate("cookie jar empty"), "cookie jar empty")

    def test_other_known_errors(self):
        self.assertIn("age-restricted", self.translator.translate("Sign in to confirm your age"))
        self.assertEqual(self.translator.translate("Private video. Sign in"), "This video is private.")
        self.assertIn("isn't available", self.translator.translate("Video unavailable"))

    def test_unknown_errors_pass_through_truncated(self):
        self.assertEqual(self.translator.translate("x" * 1000), "x" * 300)
        self.assertEqual(self.translator.translate(""), "")

    def test_rules_are_pluggable(self):
        custom = ErrorTranslator([ErrorRule(lambda ctx: "boom" in ctx.lower, lambda ctx: "Custom!")])
        self.assertEqual(custom.translate("BOOM"), "Custom!")
        self.assertEqual(custom.translate(self.BOT), self.BOT)


if __name__ == "__main__":
    unittest.main()
