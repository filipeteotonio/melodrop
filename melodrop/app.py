"""Composition root: the one place where concrete classes are wired together."""

from __future__ import annotations

from typing import Optional

from melodrop.config import Settings
from melodrop.domain.errors import ErrorTranslator
from melodrop.domain.formats import DEFAULT_FORMATS
from melodrop.services.downloads import DownloadManager, TrackDownloader
from melodrop.services.folders import FolderOpener
from melodrop.services.library import PlaylistService
from melodrop.web.api import MelodropApi
from melodrop.ytdlp.commands import YtDlpCommandBuilder
from melodrop.ytdlp.process import ProcessRunner, SubprocessRunner


def build_api(
    settings: Settings, runner: Optional[ProcessRunner] = None, folders: Optional[FolderOpener] = None
) -> MelodropApi:
    runner = runner or SubprocessRunner()
    commands = YtDlpCommandBuilder(binary=settings.ytdlp_binary, formats=DEFAULT_FORMATS)
    translator = ErrorTranslator()
    library = PlaylistService(runner, commands, translator)
    downloads = DownloadManager(
        TrackDownloader(runner, commands, translator), settings.download_dir, parallel=settings.parallel
    )
    return MelodropApi(library, downloads, folders or FolderOpener(), DEFAULT_FORMATS)
