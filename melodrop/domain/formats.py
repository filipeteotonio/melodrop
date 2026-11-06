"""Output formats as strategies.

Each format knows which yt-dlp arguments it needs. Adding a format means
adding one entry to DEFAULT_FORMATS; nothing else has to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, Iterable, Iterator, List

if TYPE_CHECKING:
    from melodrop.domain.options import DownloadOptions

# Crops YouTube's 16:9 thumbnails to a square so they look like album covers.
SQUARE_COVER_PPA = "ThumbnailsConvertor+ffmpeg_o:-c:v mjpeg -vf crop=\"'if(gt(ih,iw),iw,ih)':'if(gt(iw,ih),ih,iw)'\""


class MediaFormat(ABC):
    kind = "media"

    def __init__(self, key: str, label: str) -> None:
        self.key = key
        self.label = label

    @abstractmethod
    def ytdlp_args(self, options: DownloadOptions) -> List[str]:
        """yt-dlp arguments that select, convert and tag this format."""

    def describe(self) -> dict:
        return {"key": self.key, "label": self.label, "kind": self.kind}


class AudioFormat(MediaFormat):
    kind = "audio"

    def __init__(self, key: str, label: str, *, lossy: bool = True, supports_cover: bool = True) -> None:
        super().__init__(key, label)
        self.lossy = lossy
        self.supports_cover = supports_cover

    def ytdlp_args(self, options: DownloadOptions) -> List[str]:
        args = ["-f", "bestaudio/best", "-x", "--audio-format", self.key]
        if self.lossy:
            args += ["--audio-quality", f"{options.bitrate}K"]
        if options.embed_cover and self.supports_cover:
            args += ["--embed-thumbnail", "--convert-thumbnails", "jpg"]
            if options.square_cover:
                args += ["--ppa", SQUARE_COVER_PPA]
        return args

    def describe(self) -> dict:
        return dict(super().describe(), lossy=self.lossy, supports_cover=self.supports_cover)


class VideoFormat(MediaFormat):
    kind = "video"

    def ytdlp_args(self, options: DownloadOptions) -> List[str]:
        h = options.height
        args = [
            "-f",
            f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/b[height<={h}]/b",
            "--merge-output-format",
            self.key,
        ]
        if options.embed_cover:
            args.append("--embed-thumbnail")
        return args

    def describe(self) -> dict:
        return dict(super().describe(), lossy=True, supports_cover=True)


class FormatRegistry:
    def __init__(self, formats: Iterable[MediaFormat]) -> None:
        self._formats: Dict[str, MediaFormat] = {}
        for fmt in formats:
            if fmt.key in self._formats:
                raise ValueError(f"Duplicate format: {fmt.key}")
            self._formats[fmt.key] = fmt

    def get(self, key: str) -> MediaFormat:
        try:
            return self._formats[key]
        except KeyError:
            raise KeyError(f"Unknown format: {key}") from None

    def keys(self) -> List[str]:
        return list(self._formats)

    def __contains__(self, key: object) -> bool:
        return key in self._formats

    def __iter__(self) -> Iterator[MediaFormat]:
        return iter(self._formats.values())


DEFAULT_FORMATS = FormatRegistry(
    [
        AudioFormat("mp3", "MP3"),
        AudioFormat("m4a", "M4A / AAC"),
        AudioFormat("opus", "Opus"),
        AudioFormat("flac", "FLAC (lossless)", lossy=False),
        AudioFormat("wav", "WAV (lossless)", lossy=False, supports_cover=False),
        VideoFormat("mp4", "MP4 video"),
    ]
)
