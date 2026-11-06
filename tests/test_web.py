import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from melodrop.app import build_api
from melodrop.config import Settings
from melodrop.web.router import Router
from melodrop.web.server import create_server, is_local_host
from melodrop.ytdlp.process import ProcessResult
from tests.fakes import FakeFolderOpener, FakeProcess, FakeRunner

PLAYLIST_JSON = json.dumps(
    {
        "title": "Chill Mix",
        "uploader": "DJ",
        "entries": [
            {"id": "a", "title": "Song A", "url": "https://youtu.be/a", "duration": 100},
            {"id": "b", "title": "Song B", "url": "https://youtu.be/b", "duration": 50},
        ],
    }
)


class ApiTestCase(unittest.TestCase):
    """Builds the real object graph with fake process + folder adapters."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.runner = FakeRunner(result=ProcessResult(0, PLAYLIST_JSON, ""), start=self.fake_download)
        self.folders = FakeFolderOpener()
        self.api = build_api(Settings(download_dir=self.root, parallel=2), self.runner, self.folders)

    def tearDown(self):
        self._tmp.cleanup()

    def fake_download(self, cmd):
        folder = Path(cmd[cmd.index("-o") + 1]).parent
        path = folder / (cmd[-1].rsplit("/", 1)[-1] + ".mp3")
        path.write_bytes(b"ID3fake")
        return FakeProcess(["PROGRESS 100%", f"FILE {path}"])

    def wait_for_job(self, job_id, timeout=5.0):
        """Poll the public API, exactly like the browser does."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            body = self.api.job(job_id).body
            if body["finished"]:
                return body
            time.sleep(0.01)
        self.fail(f"job {job_id} did not finish")


class ApiTest(ApiTestCase):
    def test_config_lists_formats_and_choices(self):
        body = self.api.config().body
        self.assertEqual(body["formats"][0]["key"], "mp3")
        self.assertIn(320, body["bitrates"])
        self.assertIn("chrome", body["browsers"])
        self.assertEqual(body["download_root"], str(self.root))

    def test_inspect_returns_playlist(self):
        response = self.api.inspect({"url": "https://youtube.com/playlist?list=x", "browser": "chrome"})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["title"], "Chill Mix")
        self.assertEqual(response.body["total_duration"], 150)
        self.assertEqual([t["position"] for t in response.body["tracks"]], [1, 2])

    def test_inspect_ignores_unknown_browser(self):
        self.api.inspect({"url": "https://youtube.com/x", "browser": "; rm -rf /"})
        self.assertNotIn("--cookies-from-browser", self.runner.run_calls[0])

    def test_inspect_error_is_400(self):
        response = self.api.inspect({"url": "nope"})
        self.assertEqual(response.status, 400)
        self.assertIn("error", response.body)

    def test_start_job_and_follow_it_to_completion(self):
        response = self.api.start_job(
            {
                "folder": "Chill Mix",
                "options": {"format": "mp3", "bitrate": 192},
                "tracks": [{"id": "a", "title": "Song A", "url": "https://youtu.be/a", "position": 1}],
            }
        )
        self.assertEqual(response.status, 201)
        body = self.wait_for_job(response.body["id"])
        self.assertTrue(body["finished"])
        track = body["tracks"][0]
        self.assertEqual(track["status"], "done")
        self.assertEqual(track["file_url"], "/files/Chill%20Mix/a.mp3")
        self.assertEqual(self.api.resolve_file("Chill Mix/a.mp3"), self.root / "Chill Mix" / "a.mp3")
        self.assertIn("192K", self.runner.start_calls[0])

    def test_start_job_validation(self):
        bad_bodies = [
            {},
            {"tracks": []},
            {"tracks": "all"},
            {"tracks": [{"url": "javascript:alert(1)"}]},
        ]
        for body in bad_bodies:
            with self.subTest(body=body):
                self.assertEqual(self.api.start_job(body).status, 400)

    def test_unknown_jobs_are_404(self):
        self.assertEqual(self.api.job("missing").status, 404)
        self.assertEqual(self.api.cancel("missing").status, 404)

    def test_cancel_known_job(self):
        response = self.api.start_job({"tracks": [{"url": "https://youtu.be/a"}]})
        self.assertEqual(self.api.cancel(response.body["id"]).status, 200)
        self.wait_for_job(response.body["id"])

    def test_open_folder_for_job_or_root(self):
        self.api.open_folder()
        response = self.api.start_job({"folder": "Mine", "tracks": [{"url": "https://youtu.be/a"}]})
        self.api.open_folder(response.body["id"])
        self.assertEqual(self.folders.opened, [self.root, self.root / "Mine"])
        self.wait_for_job(response.body["id"])

    def test_resolve_file_blocks_path_traversal(self):
        outside = self.root.parent / "secret.txt"
        for attempt in ("../secret.txt", "/etc/passwd", "a/../../secret.txt", "missing.mp3", ""):
            with self.subTest(attempt=attempt):
                self.assertIsNone(self.api.resolve_file(attempt))
        self.assertFalse(outside.exists())


class RouterTest(unittest.TestCase):
    def test_matches_method_and_extracts_params(self):
        router = Router()
        router.add("GET", r"/items/(?P<item>\d+)", lambda body, item: item)
        handler, params = router.match("get", "/items/42")
        self.assertEqual(handler(None, **params), "42")
        self.assertIsNone(router.match("POST", "/items/42"))
        self.assertIsNone(router.match("GET", "/items/abc"))
        self.assertTrue(router.allows("/items/42"))
        self.assertFalse(router.allows("/other"))


class LocalHostTest(unittest.TestCase):
    def test_accepts_only_loopback_hosts(self):
        for host in ("127.0.0.1:8765", "localhost", "LOCALHOST:1", "[::1]:8765"):
            self.assertTrue(is_local_host(host), host)
        for host in (None, "", "evil.com", "127.0.0.1.evil.com:8765", "192.168.0.10:8765"):
            self.assertFalse(is_local_host(host), host)


class HttpServerTest(ApiTestCase):
    """End-to-end through a real socket, with fakes only at the process boundary."""

    def setUp(self):
        super().setUp()
        self.server = create_server(self.api, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body).encode() if body is not None else None
        final_headers = {"Content-Type": "application/json"} if payload is not None else {}
        final_headers.update(headers or {})
        conn.request(method, path, body=payload, headers=final_headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response, data

    def test_serves_the_ui_and_assets(self):
        for path, kind in (
            ("/", "text/html"),
            ("/app.js", "text/javascript"),
            ("/styles.css", "text/css"),
            ("/logo.svg", "image/svg+xml"),
        ):
            with self.subTest(path=path):
                response, data = self.request("GET", path)
                self.assertEqual(response.status, 200)
                self.assertTrue(response.getheader("Content-Type").startswith(kind))
                self.assertTrue(data)

    def test_static_files_cannot_escape_their_folder(self):
        response, _ = self.request("GET", "/../../server.py")
        self.assertEqual(response.status, 404)

    def test_full_flow_inspect_download_fetch_file(self):
        response, data = self.request("POST", "/api/playlist", {"url": "https://youtube.com/playlist?list=x"})
        self.assertEqual(response.status, 200)
        playlist = json.loads(data)

        response, data = self.request(
            "POST",
            "/api/jobs",
            {
                "folder": playlist["title"],
                "options": {"format": "mp3"},
                "tracks": playlist["tracks"],
            },
        )
        self.assertEqual(response.status, 201)
        job_id = json.loads(data)["id"]
        self.wait_for_job(job_id)

        response, data = self.request("GET", "/api/jobs/" + job_id)
        job = json.loads(data)
        self.assertEqual([t["status"] for t in job["tracks"]], ["done", "done"])

        response, data = self.request("GET", job["tracks"][0]["file_url"])
        self.assertEqual(response.status, 200)
        self.assertEqual(data, b"ID3fake")
        self.assertIn("attachment", response.getheader("Content-Disposition"))

    def test_rejects_requests_for_other_hosts(self):
        response, _ = self.request("GET", "/api/config", headers={"Host": "evil.example:8765"})
        self.assertEqual(response.status, 403)

    def test_post_requires_json_content_type(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/jobs", body=b"{}", headers={"Content-Type": "text/plain"})
        self.assertEqual(conn.getresponse().status, 415)
        conn.close()

    def test_bad_json_unknown_route_and_wrong_method(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/jobs", body=b"{nope", headers={"Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()
        self.assertEqual(self.request("GET", "/api/nothing")[0].status, 404)
        self.assertEqual(self.request("GET", "/api/playlist")[0].status, 405)
        self.assertEqual(self.request("GET", "/files/../../etc/passwd")[0].status, 404)

    def test_open_folder_endpoint(self):
        response, _ = self.request("POST", "/api/open-folder", {})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.folders.opened, [self.root])


if __name__ == "__main__":
    unittest.main()
