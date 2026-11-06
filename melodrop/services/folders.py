"""Opens a folder in the system file manager."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Sequence


class FolderOpener:
    def __init__(
        self, platform: str = sys.platform, launcher: Callable[[Sequence[str]], object] = subprocess.Popen
    ) -> None:
        self._platform = platform
        self._launcher = launcher

    def command(self, folder: Path) -> List[str]:
        if self._platform == "darwin":
            return ["open", str(folder)]
        if self._platform.startswith("win"):
            return ["explorer", str(folder)]
        return ["xdg-open", str(folder)]

    def open(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self._launcher(self.command(folder))
