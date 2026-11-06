"""Test doubles for the process layer."""

from __future__ import annotations

import threading
from typing import Callable, Iterator, List, Optional, Sequence

from melodrop.ytdlp.process import ProcessResult


class FakeProcess:
    def __init__(
        self, lines: Sequence[str] = (), returncode: int = 0, stderr: str = "", gate: Optional[threading.Event] = None
    ) -> None:
        self._lines = list(lines)
        self._returncode = returncode
        self._stderr = stderr
        self._gate = gate  # when set, output pauses until the gate opens or terminate() is called
        self.terminated = False
        self._stopped = threading.Event()

    def lines(self) -> Iterator[str]:
        yield from self._lines
        if self._gate is not None:
            while not (self._gate.is_set() or self._stopped.is_set()):
                self._stopped.wait(0.01)

    def wait(self) -> int:
        return -15 if self.terminated else self._returncode

    def stderr_text(self) -> str:
        return self._stderr

    def terminate(self) -> None:
        self.terminated = True
        self._stopped.set()


class FakeRunner:
    def __init__(
        self,
        result: Optional[ProcessResult] = None,
        run_error: Optional[Exception] = None,
        start: Optional[Callable[[List[str]], FakeProcess]] = None,
        start_error: Optional[Exception] = None,
    ) -> None:
        self.result = result or ProcessResult(0, "{}", "")
        self.run_error = run_error
        self._start = start or (lambda cmd: FakeProcess())
        self.start_error = start_error
        self.run_calls: List[List[str]] = []
        self.start_calls: List[List[str]] = []
        self._lock = threading.Lock()

    def run(self, cmd: Sequence[str], timeout: float) -> ProcessResult:
        self.run_calls.append(list(cmd))
        if self.run_error:
            raise self.run_error
        return self.result

    def start(self, cmd: Sequence[str]) -> FakeProcess:
        with self._lock:
            self.start_calls.append(list(cmd))
        if self.start_error:
            raise self.start_error
        return self._start(list(cmd))


class FakeFolderOpener:
    def __init__(self) -> None:
        self.opened: List[object] = []

    def open(self, folder: object) -> None:
        self.opened.append(folder)
