"""Parses yt-dlp's JSON and line output into domain objects and events."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, List, Mapping, Optional, Union

from melodrop.domain.models import Playlist, Track
from melodrop.ytdlp.commands import FILE_PREFIX, PROGRESS_PREFIX

UNPLAYABLE_TITLES = {"[Private video]", "[Deleted video]"}
LIST_THUMB_MIN_WIDTH = 200
_PERCENT = re.compile(r"([\d.]+)%")


@dataclass(frozen=True)
class ProgressEvent:
    percent: float


@dataclass(frozen=True)
class FileSavedEvent:
    path: str


OutputEvent = Union[ProgressEvent, FileSavedEvent]


def parse_output_line(line: str) -> Optional[OutputEvent]:
    line = line.strip()
    if line.startswith(PROGRESS_PREFIX):
        match = _PERCENT.search(line)
        if match:
            return ProgressEvent(min(100.0, float(match.group(1))))
    elif line.startswith(FILE_PREFIX):
        return FileSavedEvent(line[len(FILE_PREFIX) :])
    return None


def last_error_message(stderr: str) -> str:
    """The most relevant line of yt-dlp's stderr, without the ERROR: prefix."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("ERROR")]
    picked = (errors or lines or [""])[-1]
    return re.sub(r"^ERROR:\s*", "", picked)


def pick_thumbnail(entry: Mapping[str, Any]) -> Optional[str]:
    """A medium-size thumbnail: big enough to look sharp in the list, not huge."""
    thumbs: List[Mapping[str, Any]] = [t for t in entry.get("thumbnails") or [] if t.get("url")]
    if thumbs:
        thumbs.sort(key=lambda t: t.get("width") or 0)
        for thumb in thumbs:
            if (thumb.get("width") or 0) >= LIST_THUMB_MIN_WIDTH:
                return thumb["url"]
        return thumbs[-1]["url"]
    return entry.get("thumbnail")


def entry_url(entry: Mapping[str, Any]) -> str:
    url = entry.get("url") or entry.get("webpage_url") or ""
    if str(url).startswith("http"):
        return url
    if entry.get("id"):
        return "https://www.youtube.com/watch?v=" + entry["id"]
    return str(url)


def parse_track(entry: Mapping[str, Any]) -> Optional[Track]:
    title = entry.get("title") or ""
    if title in UNPLAYABLE_TITLES:
        return None
    url = entry_url(entry)
    if not url:
        return None
    track_id = entry.get("id") or url
    return Track(
        id=track_id,
        title=title or track_id,
        url=url,
        artist=entry.get("artist") or entry.get("channel") or entry.get("uploader") or "",
        duration=entry.get("duration"),
        thumbnail=pick_thumbnail(entry),
    )


def _tracks(entries: Iterable[Any]) -> List[Track]:
    tracks: List[Track] = []
    for entry in entries:
        if isinstance(entry, Mapping):
            track = parse_track(entry)
            if track:
                tracks.append(replace(track, position=len(tracks) + 1))
    return tracks


def parse_playlist(data: Mapping[str, Any]) -> Playlist:
    """Parse `yt-dlp --flat-playlist -J` output. A single video becomes a one-track playlist."""
    is_playlist = data.get("entries") is not None
    tracks = _tracks(data["entries"] if is_playlist else [data])
    first = tracks[0] if tracks else None
    return Playlist(
        title=data.get("title") or (first.title if first else "Download"),
        uploader=data.get("uploader") or data.get("channel") or "",
        thumbnail=pick_thumbnail(data) or (first.thumbnail if first else None),
        is_playlist=is_playlist,
        tracks=tuple(tracks),
    )
