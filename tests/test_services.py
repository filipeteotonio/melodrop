import json
import tempfile
import threading
import unittest
from pathlib import Path

from melodrop.domain.errors import ErrorTranslator, MelodropError
from melodrop.domain.models import Track, TrackStatus
from melodrop.domain.options import DownloadOptions
from melodrop.services.downloads import DownloadJob, DownloadManager, TrackDownloader
from melodrop.services.folders import FolderOpener
from melodrop.services.library import PlaylistService
from melodrop.ytdlp.commands import YtDlpCommandBuilder
from melodrop.ytdlp.process import ProcessResult
from tests.fakes import FakeProcess, FakeRunner

WAIT = 5  # seconds; jobs in these tests finish in milliseconds
BOT_ERROR = "ERROR: [youtube] x: Sign in to confirm you’re not a bot."


def tracks(n):
    return [Track(id=f"t{i}", title=f"Track {i}", url=f"https://youtu.be/t{i}", position=i) for i in range(1, n + 1)]


class PlaylistServiceTest(unittest.TestCase):
    def service(self, runner):
        return PlaylistService(runner, YtDlpCommandBuilder(), ErrorTranslator(), timeout=3)

    def test_fetch_parses_yt_dlp_json(self):
        payload = {"title": "Mix", "entries": [{"id": "a", "title": "A", "url": "https://youtu.be/a"}]}
        runner = FakeRunner(result=ProcessResult(0, json.dumps(payload), ""))
        playlist = self.service(runner).fetch("  https://music.youtube.com/playlist?list=PL1  ", "safari")
        self.assertEqual(playlist.title, "Mix")
        self.assertEqual(
            runner.run_calls[0][-3:],
            ["--cookies-from-browser", "safari", "https://music.youtube.com/playlist?list=PL1"],
        )

    def test_rejects_non_links_without_running_anything(self):
        runner = FakeRunner()
        with self.assertRaisesRegex(MelodropError, "Paste a YouTube"):
            self.service(runner).fetch("hello")
        self.assertEqual(runner.run_calls, [])

    def test_translates_yt_dlp_errors(self):
        runner = FakeRunner(result=ProcessResult(1, "", BOT_ERROR))
        with self.assertRaisesRegex(MelodropError, "Use browser login"):
            self.service(runner).fetch("https://youtu.be/x")

    def test_generic_failure_message_when_stderr_is_empty(self):
        with self.assertRaisesRegex(MelodropError, "could not read that link"):
            self.service(FakeRunner(result=ProcessResult(1, "", ""))).fetch("https://youtu.be/x")

    def test_timeout_missing_binary_and_bad_json(self):
        cases = [
            (FakeRunner(run_error=TimeoutError()), "too long"),
            (FakeRunner(run_error=FileNotFoundError()), "not installed"),
            (FakeRunner(result=ProcessResult(0, "not json", "")), "unexpected"),
            (FakeRunner(result=ProcessResult(0, json.dumps({"entries": []}), "")), "No playable tracks"),
        ]
        for runner, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(MelodropError, message):
                self.service(runner).fetch("https://youtu.be/x")


class DownloadJobTest(unittest.TestCase):
    def test_snapshot_is_a_stable_copy(self):
        job = DownloadJob("j", Path("/tmp"), DownloadOptions(), tracks(2))
        before = job.snapshot()
        job.update(0, status=TrackStatus.DONE, percent=100.0)
        self.assertEqual(before.items[0].status, TrackStatus.QUEUED)
        after = job.snapshot()
        self.assertEqual(after.count(TrackStatus.DONE), 1)
        self.assertEqual(after.count(TrackStatus.QUEUED), 1)

    def test_attaching_after_cancel_terminates_immediately(self):
        job = DownloadJob("j", Path("/tmp"), DownloadOptions(), tracks(1))
        job.cancel()
        process = FakeProcess()
        job.attach(process)
        self.assertTrue(process.terminated)

    def test_wait_reports_finish(self):
        job = DownloadJob("j", Path("/tmp"), DownloadOptions(), tracks(1))
        self.assertFalse(job.wait(0.01))
        job.mark_finished()
        self.assertTrue(job.wait(0.01))
        self.assertTrue(job.finished)


class DownloadManagerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def manager(self, runner, parallel=2):
        downloader = TrackDownloader(runner, YtDlpCommandBuilder(polite=False), ErrorTranslator())
        ids = iter(f"job{i}" for i in range(100))
        return DownloadManager(downloader, self.root, parallel=parallel, id_factory=lambda: next(ids))

    def test_successful_downloads_report_progress_and_files(self):
        def start(cmd):
            name = cmd[-1].rsplit("/", 1)[-1]
            return FakeProcess(
                ["[download] noise", "PROGRESS 50.0%", "PROGRESS 100%", f"FILE {self.root}/Artist - {name}.mp3"]
            )

        runner = FakeRunner(start=start)
        job = self.manager(runner).start(tracks(3), DownloadOptions(), "My: Mix")
        self.assertTrue(job.wait(WAIT))

        snap = job.snapshot()
        self.assertEqual(snap.id, "job0")
        self.assertEqual(snap.folder, self.root / "My_ Mix")
        self.assertTrue(snap.folder.is_dir())
        self.assertEqual([i.status for i in snap.items], [TrackStatus.DONE] * 3)
        self.assertEqual([i.percent for i in snap.items], [100.0] * 3)
        self.assertEqual(
            sorted(Path(i.file_path).name for i in snap.items),
            ["Artist - t1.mp3", "Artist - t2.mp3", "Artist - t3.mp3"],
        )
        self.assertEqual(len(runner.start_calls), 3)

    def test_failed_track_gets_a_friendly_error_and_others_continue(self):
        def start(cmd):
            if cmd[-1].endswith("t2"):
                return FakeProcess(returncode=1, stderr=BOT_ERROR)
            return FakeProcess(["PROGRESS 100%"])

        job = self.manager(FakeRunner(start=start)).start(tracks(3), DownloadOptions(), "x")
        self.assertTrue(job.wait(WAIT))
        items = job.snapshot().items
        self.assertEqual([i.status for i in items], [TrackStatus.DONE, TrackStatus.ERROR, TrackStatus.DONE])
        self.assertIn("Use browser login", items[1].error)

    def test_numbering_uses_playlist_position_not_batch_index(self):
        runner = FakeRunner()
        retry = [Track(id="t9", title="T9", url="https://youtu.be/t9", position=9)]
        job = self.manager(runner).start(retry, DownloadOptions(number_files=True), "x")
        self.assertTrue(job.wait(WAIT))
        output = runner.start_calls[0][runner.start_calls[0].index("-o") + 1]
        self.assertTrue(Path(output).name.startswith("09 - "))

    def test_missing_yt_dlp(self):
        job = self.manager(FakeRunner(start_error=FileNotFoundError())).start(tracks(1), DownloadOptions(), "x")
        self.assertTrue(job.wait(WAIT))
        self.assertEqual(job.snapshot().items[0].error, "yt-dlp is not installed.")

    def test_unexpected_exception_marks_track_failed_without_stalling(self):
        job = self.manager(FakeRunner(start_error=RuntimeError("kaboom"))).start(tracks(2), DownloadOptions(), "x")
        self.assertTrue(job.wait(WAIT))
        self.assertTrue(all("kaboom" in i.error for i in job.snapshot().items))

    def test_cancel_stops_running_and_queued_tracks(self):
        gate = threading.Event()
        started = threading.Event()

        def start(cmd):
            started.set()
            return FakeProcess(["PROGRESS 10%"], gate=gate)

        manager = self.manager(FakeRunner(start=start), parallel=1)
        job = manager.start(tracks(3), DownloadOptions(), "x")
        self.assertTrue(started.wait(WAIT))
        self.assertTrue(manager.cancel(job.id))
        self.assertTrue(job.wait(WAIT))
        snap = job.snapshot()
        self.assertTrue(snap.cancelled)
        self.assertEqual([i.status for i in snap.items], [TrackStatus.CANCELLED] * 3)

    def test_parallelism_is_respected(self):
        running = []
        peak = []
        lock = threading.Lock()

        class Tracking(FakeProcess):
            def lines(self):
                with lock:
                    running.append(1)
                    peak.append(len(running))
                threading.Event().wait(0.05)
                with lock:
                    running.pop()
                return iter(())

        job = self.manager(FakeRunner(start=lambda cmd: Tracking()), parallel=2).start(
            tracks(6), DownloadOptions(), "x"
        )
        self.assertTrue(job.wait(WAIT))
        self.assertLessEqual(max(peak), 2)

    def test_requires_tracks_and_finds_jobs(self):
        manager = self.manager(FakeRunner())
        with self.assertRaises(MelodropError):
            manager.start([], DownloadOptions(), "x")
        self.assertIsNone(manager.get("nope"))
        self.assertFalse(manager.cancel("nope"))
        job = manager.start(tracks(1), DownloadOptions(), "x")
        self.assertIs(manager.get(job.id), job)
        job.wait(WAIT)


class FolderOpenerTest(unittest.TestCase):
    def test_platform_commands(self):
        folder = Path("/music")
        self.assertEqual(FolderOpener("darwin").command(folder), ["open", "/music"])
        self.assertEqual(FolderOpener("win32").command(folder)[0], "explorer")
        self.assertEqual(FolderOpener("linux").command(folder)[0], "xdg-open")

    def test_open_creates_folder_and_launches(self):
        launched = []
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "new"
            FolderOpener("darwin", launcher=launched.append).open(folder)
            self.assertTrue(folder.is_dir())
        self.assertEqual(launched, [["open", str(folder)]])


if __name__ == "__main__":
    unittest.main()
