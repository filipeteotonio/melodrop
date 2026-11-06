"""`melodrop` command: checks dependencies, starts the server, opens the browser."""

from __future__ import annotations

import shutil
import sys
import threading
import webbrowser
from typing import Callable, List, Optional, Sequence

from melodrop import __version__
from melodrop.app import build_api
from melodrop.config import parse_settings
from melodrop.web.server import create_server

REQUIRED_TOOLS = ("yt-dlp", "ffmpeg")
RECOMMENDED_TOOLS = ("deno",)  # yt-dlp needs a JS runtime for YouTube


def missing_tools(tools: Sequence[str], which: Callable[[str], Optional[str]] = shutil.which) -> List[str]:
    return [tool for tool in tools if not which(tool)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    settings = parse_settings(argv)

    missing = missing_tools(REQUIRED_TOOLS)
    if missing:
        print(f"Missing: {', '.join(missing)}\nInstall with:  brew install {' '.join(missing)}")
        return 1
    for tool in missing_tools(RECOMMENDED_TOOLS):
        print(f"Warning: {tool} is not installed; YouTube downloads may fail. brew install {tool}")

    settings.download_dir.mkdir(parents=True, exist_ok=True)
    try:
        server = create_server(build_api(settings), settings.host, settings.port)
    except OSError as exc:
        print(f"Couldn't start on port {settings.port} ({exc}). Try: melodrop --port {settings.port + 1}")
        return 1

    print(f"Melodrop {__version__} running at {settings.url}")
    print(f"Saving files to {settings.download_dir}")
    print("Press Ctrl+C to stop.")
    if settings.open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(settings.url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
