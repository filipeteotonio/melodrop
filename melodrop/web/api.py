"""The JSON API, independent of HTTP so it can be unit-tested directly."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import quote

from melodrop import __version__
from melodrop.domain.errors import MelodropError
from melodrop.domain.formats import DEFAULT_FORMATS, FormatRegistry
from melodrop.domain.models import Track
from melodrop.domain.options import AUDIO_BITRATES, BROWSERS, VIDEO_HEIGHTS, DownloadOptions
from melodrop.services.downloads import DownloadManager, JobSnapshot
from melodrop.services.folders import FolderOpener
from melodrop.services.library import PlaylistService


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Mapping[str, Any] = field(default_factory=dict)


def _error(status: int, message: str) -> ApiResponse:
    return ApiResponse(status, {"error": message})


class MelodropApi:
    def __init__(
        self,
        library: PlaylistService,
        downloads: DownloadManager,
        folders: FolderOpener,
        formats: FormatRegistry = DEFAULT_FORMATS,
    ) -> None:
        self._library = library
        self._downloads = downloads
        self._folders = folders
        self._formats = formats

    @property
    def download_root(self) -> Path:
        return self._downloads.download_root

    def config(self) -> ApiResponse:
        return ApiResponse(
            200,
            {
                "version": __version__,
                "formats": [f.describe() for f in self._formats],
                "bitrates": list(AUDIO_BITRATES),
                "heights": list(VIDEO_HEIGHTS),
                "browsers": list(BROWSERS),
                "download_root": str(self.download_root),
            },
        )

    def inspect(self, body: Mapping[str, Any]) -> ApiResponse:
        browser = body.get("browser") if body.get("browser") in BROWSERS else ""
        try:
            playlist = self._library.fetch(str(body.get("url") or ""), browser)
        except MelodropError as exc:
            return _error(400, str(exc))
        return ApiResponse(200, playlist.to_dict())

    def start_job(self, body: Mapping[str, Any]) -> ApiResponse:
        raw_tracks = body.get("tracks")
        if not isinstance(raw_tracks, list) or not raw_tracks:
            return _error(400, "Pick at least one track.")
        try:
            tracks = [Track.from_dict(t) for t in raw_tracks if isinstance(t, Mapping)]
        except ValueError as exc:
            return _error(400, str(exc))
        raw_options = body.get("options")
        options = DownloadOptions.from_dict(
            raw_options if isinstance(raw_options, Mapping) else {}, self._formats.keys()
        )
        try:
            job = self._downloads.start(tracks, options, str(body.get("folder") or "Download"))
        except MelodropError as exc:
            return _error(400, str(exc))
        return ApiResponse(201, self._job_body(job.snapshot()))

    def job(self, job_id: str) -> ApiResponse:
        job = self._downloads.get(job_id)
        if job is None:
            return _error(404, "Unknown job.")
        return ApiResponse(200, self._job_body(job.snapshot()))

    def cancel(self, job_id: str) -> ApiResponse:
        if not self._downloads.cancel(job_id):
            return _error(404, "Unknown job.")
        return ApiResponse(200, {"ok": True})

    def open_folder(self, job_id: Optional[str] = None) -> ApiResponse:
        job = self._downloads.get(job_id) if job_id else None
        self._folders.open(job.folder if job else self.download_root)
        return ApiResponse(200, {"ok": True})

    def resolve_file(self, relative: str) -> Optional[Path]:
        """Map a /files/ path to a real file, refusing anything outside the download root."""
        root = self.download_root.resolve()
        target = (root / relative).resolve()
        if root not in target.parents or not target.is_file():
            return None
        return target

    def _job_body(self, snap: JobSnapshot) -> dict:
        root = self.download_root.resolve()
        tracks = []
        for item in snap.items:
            entry = {
                "id": item.track.id,
                "title": item.track.title,
                "status": item.status.value,
                "percent": round(item.percent, 1),
                "error": item.error,
            }
            if item.file_path:
                path = Path(item.file_path).resolve()
                entry["file_name"] = path.name
                if root in path.parents:
                    entry["file_url"] = "/files/" + quote(path.relative_to(root).as_posix())
            tracks.append(entry)
        return {
            "id": snap.id,
            "folder": str(snap.folder),
            "finished": snap.finished,
            "cancelled": snap.cancelled,
            "tracks": tracks,
        }
