import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from melodrop import cli
from melodrop.config import DEFAULT_PARALLEL, DEFAULT_PORT, default_download_dir, parse_settings


class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        settings = parse_settings([], env={})
        self.assertEqual(settings.port, DEFAULT_PORT)
        self.assertEqual(settings.parallel, DEFAULT_PARALLEL)
        self.assertEqual(settings.download_dir, default_download_dir())
        self.assertTrue(settings.open_browser)
        self.assertEqual(settings.url, "http://127.0.0.1:8765")

    def test_environment_variables(self):
        settings = parse_settings(
            [], env={"MELODROP_PORT": "9000", "MELODROP_PARALLEL": "4", "MELODROP_DOWNLOAD_DIR": "/tmp/music"}
        )
        self.assertEqual((settings.port, settings.parallel, settings.download_dir), (9000, 4, Path("/tmp/music")))

    def test_flags_override_environment(self):
        settings = parse_settings(
            ["--port", "9100", "--download-dir", "~/Songs", "--no-browser"], env={"MELODROP_PORT": "9000"}
        )
        self.assertEqual(settings.port, 9100)
        self.assertEqual(settings.download_dir, Path.home() / "Songs")
        self.assertFalse(settings.open_browser)

    def test_parallel_is_bounded(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_settings(["--parallel", "50"], env={})


class CliTest(unittest.TestCase):
    def test_missing_tools(self):
        installed = {"yt-dlp": "/bin/yt-dlp"}
        self.assertEqual(cli.missing_tools(["yt-dlp", "ffmpeg"], installed.get), ["ffmpeg"])

    def test_main_exits_when_required_tools_are_missing(self):
        out = io.StringIO()
        with mock.patch.object(cli, "missing_tools", return_value=["ffmpeg"]), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["--no-browser"]), 1)
        self.assertIn("brew install ffmpeg", out.getvalue())

    def _run_main(self, server=None, error=None):
        out = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmp,
            contextlib.redirect_stdout(out),
            mock.patch.object(cli, "missing_tools", return_value=[]),
            mock.patch.object(cli, "create_server", return_value=server, side_effect=error) as create,
        ):
            code = cli.main(["--no-browser", "--download-dir", tmp, "--port", "9999"])
        return code, out.getvalue(), create

    def test_main_serves_until_ctrl_c(self):
        server = mock.Mock()
        server.serve_forever.side_effect = KeyboardInterrupt
        code, out, create = self._run_main(server=server)
        self.assertEqual(code, 0)
        self.assertIn("running at http://127.0.0.1:9999", out)
        self.assertIn("Stopped.", out)
        server.server_close.assert_called_once()
        self.assertEqual(create.call_args[0][1:], ("127.0.0.1", 9999))

    def test_main_reports_busy_port(self):
        code, out, _ = self._run_main(error=OSError("Address already in use"))
        self.assertEqual(code, 1)
        self.assertIn("--port 10000", out)


if __name__ == "__main__":
    unittest.main()
