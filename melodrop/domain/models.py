"""Value objects shared by every layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Tuple


class TrackStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"

    @property
    def is_final(self) -> bool:
        return self in (TrackStatus.DONE, TrackStatus.ERROR, TrackStatus.CANCELLED)


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    url: str
    artist: str = ""
    duration: Optional[float] = None
    thumbnail: Optional[str] = None
    position: Optional[int] = None  # 1-based position in the playlist

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Track:
        """Build a track from untrusted client input."""
        url = str(data.get("url") or "")
        if not url.startswith(("http://", "https://")):
            raise ValueError("Every track needs an http(s) URL.")
        track_id = str(data.get("id") or url)
        position = data.get("position")
        valid_position = isinstance(position, int) and not isinstance(position, bool) and position > 0
        return cls(
            id=track_id,
            title=str(data.get("title") or track_id),
            url=url,
            position=position if valid_position else None,
        )


@dataclass(frozen=True)
class Playlist:
    title: str
    tracks: Tuple[Track, ...]
    uploader: str = ""
    thumbnail: Optional[str] = None
    is_playlist: bool = True

    @property
    def total_duration(self) -> float:
        return sum(t.duration or 0 for t in self.tracks)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "uploader": self.uploader,
            "thumbnail": self.thumbnail,
            "is_playlist": self.is_playlist,
            "total_duration": self.total_duration,
            "tracks": [t.to_dict() for t in self.tracks],
        }
