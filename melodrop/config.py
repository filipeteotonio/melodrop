"""Runtime settings from command-line flags and environment variables."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence

from melodrop import __version__

DEFAULT_PORT = 8765
DEFAULT_PARALLEL = 2


def default_download_dir() -> Path:
    return Path.home() / "Downloads" / "YouTube Music"


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    download_dir: Path = field(default_factory=default_download_dir)
    parallel: int = DEFAULT_PARALLEL
    open_browser: bool = True
    ytdlp_binary: str = "yt-dlp"

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def parse_settings(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(
        prog="melodrop",
        description="Download YouTube and YouTube Music playlists from a local web UI.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(env.get("MELODROP_PORT", DEFAULT_PORT)),
        help="port for the local web UI (default: %(default)s)",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path(env["MELODROP_DOWNLOAD_DIR"]) if env.get("MELODROP_DOWNLOAD_DIR") else default_download_dir(),
        help="where files are saved (default: %(default)s)",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=int(env.get("MELODROP_PARALLEL", DEFAULT_PARALLEL)),
        help="tracks downloaded at the same time (default: %(default)s)",
    )
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser on start")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args = parser.parse_args(argv)
    if not 1 <= args.parallel <= 8:
        parser.error("--parallel must be between 1 and 8")
    return Settings(
        port=args.port,
        download_dir=args.download_dir.expanduser(),
        parallel=args.parallel,
        open_browser=not args.no_browser,
    )
