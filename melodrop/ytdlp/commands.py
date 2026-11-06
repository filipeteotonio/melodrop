"""Builds yt-dlp command lines. Pure functions of their inputs."""

from __future__ import annotations

from pathlib import Path
from typing import List

from melodrop.domain.formats import DEFAULT_FORMATS, FormatRegistry
from melodrop.domain.options import DownloadOptions

PROGRESS_PREFIX = "PROGRESS "
FILE_PREFIX = "FILE "
OUTPUT_TEMPLATE = "%(artist,creator,uploader|Unknown)s - %(track,title)s.%(ext)s"

# Short pauses and retries make YouTube's bot check trigger less often.
POLITE_ARGS = [
    "--sleep-requests",
    "1",
    "--sleep-interval",
    "2",
    "--max-sleep-interval",
    "5",
    "--retries",
    "5",
    "--extractor-retries",
    "3",
]


class YtDlpCommandBuilder:
    def __init__(self, binary: str = "yt-dlp", formats: FormatRegistry = DEFAULT_FORMATS, polite: bool = True) -> None:
        self.binary = binary
        self.formats = formats
        self.polite = polite

    @staticmethod
    def cookie_args(browser: str) -> List[str]:
        return ["--cookies-from-browser", browser] if browser else []

    def info(self, url: str, browser: str = "") -> List[str]:
        return [self.binary, "--flat-playlist", "-J", "--no-warnings", *self.cookie_args(browser), url]

    def output_template(self, index: int, options: DownloadOptions) -> str:
        prefix = f"{index:02d} - " if options.number_files else ""
        return prefix + OUTPUT_TEMPLATE

    def download(self, url: str, index: int, options: DownloadOptions, folder: Path) -> List[str]:
        cmd = [
            self.binary,
            "--no-playlist",
            "--newline",
            "--no-warnings",
            "--progress-template",
            "download:" + PROGRESS_PREFIX + "%(progress._percent_str)s",
            "--print",
            "after_move:" + FILE_PREFIX + "%(filepath)s",
            "--no-simulate",
            "-o",
            str(folder / self.output_template(index, options)),
            "--embed-metadata",
        ]
        if self.polite:
            cmd += POLITE_ARGS
        cmd += self.cookie_args(options.browser)
        cmd += self.formats.get(options.format).ytdlp_args(options)
        cmd.append(url)
        return cmd
