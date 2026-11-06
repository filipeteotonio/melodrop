"""User-selected download options, validated from untrusted input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Mapping

BROWSERS = ("chrome", "safari", "firefox", "edge", "brave")
AUDIO_BITRATES = (320, 256, 192, 128)
VIDEO_HEIGHTS = (2160, 1440, 1080, 720, 480, 360)


def _pick(value: Any, allowed: Collection[Any], default: Any) -> Any:
    return value if value in allowed else default


def _as_int(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class DownloadOptions:
    format: str = "mp3"
    bitrate: int = 320
    height: int = 1080
    browser: str = ""
    embed_cover: bool = True
    square_cover: bool = True
    number_files: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], known_formats: Collection[str]) -> DownloadOptions:
        """Lenient parsing: anything invalid falls back to the default."""
        default = cls()
        return cls(
            format=_pick(data.get("format"), known_formats, default.format),
            bitrate=_pick(_as_int(data.get("bitrate")), AUDIO_BITRATES, default.bitrate),
            height=_pick(_as_int(data.get("height")), VIDEO_HEIGHTS, default.height),
            browser=_pick(data.get("browser"), BROWSERS, ""),
            embed_cover=bool(data.get("embed_cover", default.embed_cover)),
            square_cover=bool(data.get("square_cover", default.square_cover)),
            number_files=bool(data.get("number_files", default.number_files)),
        )
