"""Download jobs: a batch of tracks downloaded in parallel with live progress."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from melodrop.domain.errors import ErrorTranslator, MelodropError
from melodrop.domain.models import Track, TrackStatus
from melodrop.domain.naming import safe_filename
from melodrop.domain.options import DownloadOptions
from melodrop.ytdlp.commands import YtDlpCommandBuilder
from melodrop.ytdlp.parsing import FileSavedEvent, ProgressEvent, last_error_message, parse_output_line
from melodrop.ytdlp.process import ProcessRunner, RunningProcess


@dataclass(frozen=True)
class TrackProgress:
    track: Track
    status: TrackStatus = TrackStatus.QUEUED
    percent: float = 0.0
    file_path: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class JobSnapshot:
    id: str
    folder: Path
    finished: bool
    cancelled: bool
    items: Tuple[TrackProgress, ...]

    def count(self, status: TrackStatus) -> int:
        return sum(1 for item in self.items if item.status is status)


class DownloadJob:
    """Thread-safe state of one batch. Workers update it; the API reads snapshots."""

    def __init__(self, job_id: str, folder: Path, options: DownloadOptions, tracks: Sequence[Track]) -> None:
        self.id = job_id
        self.folder = folder
        self.options = options
        self._items: List[TrackProgress] = [TrackProgress(track=t) for t in tracks]
        self._lock = threading.Lock()
        self._finished = threading.Event()
        self._cancelled = False
        self._processes: Set[RunningProcess] = set()

    def __len__(self) -> int:
        return len(self._items)

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def item(self, index: int) -> TrackProgress:
        with self._lock:
            return self._items[index]

    def update(self, index: int, **changes: object) -> None:
        with self._lock:
            self._items[index] = replace(self._items[index], **changes)

    def attach(self, process: RunningProcess) -> None:
        with self._lock:
            self._processes.add(process)
            stop = self._cancelled
        if stop:
            process.terminate()

    def detach(self, process: RunningProcess) -> None:
        with self._lock:
            self._processes.discard(process)

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            running = list(self._processes)
        for process in running:
            process.terminate()

    def mark_finished(self) -> None:
        self._finished.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._finished.wait(timeout)

    def snapshot(self) -> JobSnapshot:
        with self._lock:
            return JobSnapshot(self.id, self.folder, self.finished, self._cancelled, tuple(self._items))


class TrackDownloader:
    """Downloads one track of a job and reports progress back to the job."""

    def __init__(self, runner: ProcessRunner, commands: YtDlpCommandBuilder, translator: ErrorTranslator) -> None:
        self._runner = runner
        self._commands = commands
        self._translator = translator

    def download(self, job: DownloadJob, index: int) -> None:
        if job.cancelled:
            job.update(index, status=TrackStatus.CANCELLED)
            return

        track = job.item(index).track
        job.update(index, status=TrackStatus.DOWNLOADING)
        cmd = self._commands.download(track.url, track.position or index + 1, job.options, job.folder)
        try:
            process = self._runner.start(cmd)
        except FileNotFoundError:
            job.update(index, status=TrackStatus.ERROR, error="yt-dlp is not installed.")
            return

        job.attach(process)
        try:
            for line in process.lines():
                self._apply(job, index, line)
            code = process.wait()
        finally:
            job.detach(process)

        if code == 0:
            job.update(index, status=TrackStatus.DONE, percent=100.0)
        elif job.cancelled:
            job.update(index, status=TrackStatus.CANCELLED)
        else:
            raw = last_error_message(process.stderr_text())
            message = self._translator.translate(raw, job.options.browser) or "Download failed."
            job.update(index, status=TrackStatus.ERROR, error=message)

    @staticmethod
    def _apply(job: DownloadJob, index: int, line: str) -> None:
        event = parse_output_line(line)
        if isinstance(event, ProgressEvent):
            status = TrackStatus.CONVERTING if event.percent >= 100 else TrackStatus.DOWNLOADING
            job.update(index, percent=event.percent, status=status)
        elif isinstance(event, FileSavedEvent):
            job.update(index, file_path=event.path)


def _new_job_id() -> str:
    return uuid.uuid4().hex[:12]


class DownloadManager:
    def __init__(
        self,
        downloader: TrackDownloader,
        download_root: Path,
        parallel: int = 2,
        id_factory: Callable[[], str] = _new_job_id,
    ) -> None:
        self._downloader = downloader
        self.download_root = download_root
        self._parallel = max(1, parallel)
        self._id_factory = id_factory
        self._jobs: Dict[str, DownloadJob] = {}
        self._lock = threading.Lock()

    def start(self, tracks: Sequence[Track], options: DownloadOptions, folder_name: str) -> DownloadJob:
        if not tracks:
            raise MelodropError("Pick at least one track.")
        folder = self.download_root / safe_filename(folder_name)
        folder.mkdir(parents=True, exist_ok=True)
        job = DownloadJob(self._id_factory(), folder, options, tracks)
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), name="melodrop-job-" + job.id, daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[DownloadJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None:
            return False
        job.cancel()
        return True

    def _run(self, job: DownloadJob) -> None:
        try:
            with ThreadPoolExecutor(max_workers=min(self._parallel, len(job))) as pool:
                list(pool.map(lambda i: self._download_safely(job, i), range(len(job))))
        finally:
            job.mark_finished()

    def _download_safely(self, job: DownloadJob, index: int) -> None:
        try:
            self._downloader.download(job, index)
        except Exception as exc:  # one broken track must not stall the whole batch
            job.update(index, status=TrackStatus.ERROR, error=f"Unexpected error: {exc}")
