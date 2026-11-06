"""Reads a playlist, album or song link into a Playlist."""

from __future__ import annotations

import json

from melodrop.domain.errors import ErrorTranslator, MelodropError
from melodrop.domain.models import Playlist
from melodrop.ytdlp.commands import YtDlpCommandBuilder
from melodrop.ytdlp.parsing import last_error_message, parse_playlist
from melodrop.ytdlp.process import ProcessRunner

DEFAULT_TIMEOUT = 180.0


class PlaylistService:
    def __init__(
        self,
        runner: ProcessRunner,
        commands: YtDlpCommandBuilder,
        translator: ErrorTranslator,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._runner = runner
        self._commands = commands
        self._translator = translator
        self._timeout = timeout

    def fetch(self, url: str, browser: str = "") -> Playlist:
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise MelodropError("Paste a YouTube or YouTube Music link.")

        try:
            result = self._runner.run(self._commands.info(url, browser), self._timeout)
        except TimeoutError:
            raise MelodropError("YouTube took too long to answer. Try again.") from None
        except FileNotFoundError:
            raise MelodropError("yt-dlp is not installed. Run: brew install yt-dlp") from None

        if result.returncode != 0:
            message = self._translator.translate(last_error_message(result.stderr), browser)
            raise MelodropError(message or "yt-dlp could not read that link.")

        try:
            data = json.loads(result.stdout)
        except ValueError:
            raise MelodropError("yt-dlp returned something unexpected. Try updating it.") from None

        playlist = parse_playlist(data)
        if not playlist.tracks:
            raise MelodropError("No playable tracks found at that link.")
        return playlist
