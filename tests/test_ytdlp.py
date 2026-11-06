import sys
import unittest
from pathlib import Path

from melodrop.domain.options import DownloadOptions
from melodrop.ytdlp.commands import OUTPUT_TEMPLATE, POLITE_ARGS, YtDlpCommandBuilder
from melodrop.ytdlp.parsing import (
    FileSavedEvent,
    ProgressEvent,
    entry_url,
    last_error_message,
    parse_output_line,
    parse_playlist,
    pick_thumbnail,
)
from melodrop.ytdlp.process import SubprocessRunner

FOLDER = Path("/music/My Playlist")
URL = "https://music.youtube.com/watch?v=abc"


class CommandBuilderTest(unittest.TestCase):
    def setUp(self):
        self.builder = YtDlpCommandBuilder()

    def test_info_command_reads_playlist_flat_as_json(self):
        self.assertEqual(self.builder.info(URL), ["yt-dlp", "--flat-playlist", "-J", "--no-warnings", URL])

    def test_info_command_can_use_browser_cookies(self):
        cmd = self.builder.info(URL, "chrome")
        self.assertEqual(cmd[-3:], ["--cookies-from-browser", "chrome", URL])

    def test_download_mp3_command(self):
        cmd = self.builder.download(URL, 1, DownloadOptions(), FOLDER)
        self.assertEqual(cmd[0], "yt-dlp")
        self.assertEqual(cmd[-1], URL)
        self.assertEqual(cmd[cmd.index("-o") + 1], str(FOLDER / OUTPUT_TEMPLATE))
        self.assertEqual(cmd[cmd.index("--audio-format") + 1], "mp3")
        self.assertEqual(cmd[cmd.index("--audio-quality") + 1], "320K")
        for flag in ("--no-playlist", "--embed-metadata", "--newline", "--no-simulate"):
            self.assertIn(flag, cmd)
        self.assertNotIn("--cookies-from-browser", cmd)

    def test_download_numbers_files_by_playlist_position(self):
        cmd = self.builder.download(URL, 7, DownloadOptions(number_files=True), FOLDER)
        self.assertEqual(Path(cmd[cmd.index("-o") + 1]).name, "07 - " + OUTPUT_TEMPLATE)

    def test_download_with_browser_login(self):
        cmd = self.builder.download(URL, 1, DownloadOptions(browser="firefox"), FOLDER)
        self.assertEqual(cmd[cmd.index("--cookies-from-browser") + 1], "firefox")

    def test_polite_pacing_is_on_by_default_and_optional(self):
        polite = self.builder.download(URL, 1, DownloadOptions(), FOLDER)
        fast = YtDlpCommandBuilder(polite=False).download(URL, 1, DownloadOptions(), FOLDER)
        self.assertIn("--sleep-interval", polite)
        self.assertEqual(len(polite) - len(fast), len(POLITE_ARGS))

    def test_custom_binary(self):
        self.assertEqual(YtDlpCommandBuilder(binary="/opt/yt-dlp").info(URL)[0], "/opt/yt-dlp")

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(KeyError):
            self.builder.download(URL, 1, DownloadOptions(format="exe"), FOLDER)


class OutputParsingTest(unittest.TestCase):
    def test_progress_lines(self):
        self.assertEqual(parse_output_line("PROGRESS  42.5%"), ProgressEvent(42.5))
        self.assertEqual(parse_output_line("PROGRESS 100.0%\n"), ProgressEvent(100.0))
        self.assertEqual(parse_output_line("PROGRESS 140%"), ProgressEvent(100.0))

    def test_progress_without_percentage_is_ignored(self):
        self.assertIsNone(parse_output_line("PROGRESS   N/A"))

    def test_file_lines(self):
        self.assertEqual(parse_output_line("FILE /music/A - B.mp3"), FileSavedEvent("/music/A - B.mp3"))

    def test_other_lines_are_ignored(self):
        self.assertIsNone(parse_output_line("[youtube] abc: Downloading webpage"))
        self.assertIsNone(parse_output_line(""))

    def test_last_error_prefers_error_lines(self):
        stderr = "WARNING: slow\nERROR: [youtube] x: Video unavailable\nsome trailing noise\n"
        self.assertEqual(last_error_message(stderr), "[youtube] x: Video unavailable")

    def test_last_error_falls_back_to_last_line(self):
        self.assertEqual(last_error_message("first\nlast\n"), "last")
        self.assertEqual(last_error_message(""), "")


class PlaylistParsingTest(unittest.TestCase):
    def test_parses_flat_playlist(self):
        data = {
            "title": "Road Trip",
            "uploader": "Filipe",
            "thumbnails": [{"url": "https://img/big", "width": 900}, {"url": "https://img/mid", "width": 300}],
            "entries": [
                {
                    "id": "a1",
                    "title": "Song A",
                    "url": "https://music.youtube.com/watch?v=a1",
                    "channel": "Artist A",
                    "duration": 200,
                },
                {"id": "gone", "title": "[Deleted video]", "url": "https://youtu.be/gone"},
                {"id": "b2", "title": "Song B", "artist": "Artist B", "duration": 180.5},
                None,
            ],
        }
        playlist = parse_playlist(data)
        self.assertEqual(playlist.title, "Road Trip")
        self.assertEqual(playlist.uploader, "Filipe")
        self.assertEqual(playlist.thumbnail, "https://img/mid")
        self.assertTrue(playlist.is_playlist)
        self.assertEqual([t.id for t in playlist.tracks], ["a1", "b2"])
        self.assertEqual([t.position for t in playlist.tracks], [1, 2])
        self.assertEqual(playlist.tracks[0].artist, "Artist A")
        self.assertEqual(playlist.tracks[1].url, "https://www.youtube.com/watch?v=b2")

    def test_single_video_becomes_one_track(self):
        playlist = parse_playlist(
            {
                "id": "x",
                "title": "Me at the zoo",
                "uploader": "jawed",
                "webpage_url": "https://www.youtube.com/watch?v=x",
                "thumbnail": "https://img/x",
            }
        )
        self.assertFalse(playlist.is_playlist)
        self.assertEqual(playlist.title, "Me at the zoo")
        self.assertEqual(len(playlist.tracks), 1)
        self.assertEqual(playlist.tracks[0].artist, "jawed")
        self.assertEqual(playlist.thumbnail, "https://img/x")

    def test_empty_playlist(self):
        playlist = parse_playlist({"entries": []})
        self.assertEqual((playlist.title, playlist.tracks), ("Download", ()))

    def test_thumbnail_choice(self):
        self.assertEqual(pick_thumbnail({"thumbnails": [{"url": "s", "width": 50}, {"url": "m", "width": 120}]}), "m")
        self.assertEqual(pick_thumbnail({"thumbnails": [{"width": 500}], "thumbnail": "t"}), "t")
        self.assertIsNone(pick_thumbnail({}))

    def test_entry_url_fallbacks(self):
        self.assertEqual(entry_url({"url": "https://a"}), "https://a")
        self.assertEqual(entry_url({"url": "a1", "id": "a1"}), "https://www.youtube.com/watch?v=a1")
        self.assertEqual(entry_url({}), "")


class SubprocessRunnerTest(unittest.TestCase):
    """Runs the real Python interpreter, so these exercise the actual subprocess plumbing."""

    def setUp(self):
        self.runner = SubprocessRunner()

    def test_run_captures_output(self):
        result = self.runner.run([sys.executable, "-c", "import sys; print('hi'); sys.stderr.write('err')"], 10)
        self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, "hi", "err"))

    def test_run_timeout_becomes_timeout_error(self):
        with self.assertRaises(TimeoutError):
            self.runner.run([sys.executable, "-c", "import time; time.sleep(5)"], 0.2)

    def test_missing_binary_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.runner.run(["definitely-not-a-real-binary-xyz"], 5)

    def test_start_streams_lines_and_collects_stderr(self):
        code = "import sys\nfor i in range(3): print('line', i, flush=True)\nsys.stderr.write('oops')\nsys.exit(3)"
        process = self.runner.start([sys.executable, "-c", code])
        self.assertEqual(list(process.lines()), ["line 0", "line 1", "line 2"])
        self.assertEqual(process.wait(), 3)
        self.assertEqual(process.stderr_text(), "oops")

    def test_terminate_stops_a_running_process(self):
        process = self.runner.start([sys.executable, "-c", "import time; time.sleep(30)"])
        process.terminate()
        self.assertNotEqual(process.wait(), 0)
        process.terminate()  # second call is a no-op


if __name__ == "__main__":
    unittest.main()
