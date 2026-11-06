"""Process execution behind small interfaces, so services can be tested with fakes."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from typing import Iterator, List, Protocol, Sequence


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class RunningProcess(Protocol):
    def lines(self) -> Iterator[str]:
        """Yield stdout lines as they are printed."""

    def wait(self) -> int:
        """Wait for exit and return the exit code."""

    def stderr_text(self) -> str:
        """Everything written to stderr (call after wait)."""

    def terminate(self) -> None:
        """Ask the process to stop."""


class ProcessRunner(Protocol):
    def run(self, cmd: Sequence[str], timeout: float) -> ProcessResult:
        """Run to completion. Raises TimeoutError or FileNotFoundError."""

    def start(self, cmd: Sequence[str]) -> RunningProcess:
        """Start a process and stream its output. Raises FileNotFoundError."""


class _PopenProcess:
    def __init__(self, cmd: Sequence[str]) -> None:
        self._proc = subprocess.Popen(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
        self._stderr: List[str] = []
        # Drain stderr on a side thread so a chatty process can't block on a full pipe.
        self._stderr_reader = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_reader.start()

    def _drain_stderr(self) -> None:
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            self._stderr.append(line)

    def lines(self) -> Iterator[str]:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            yield line.rstrip("\n")

    def wait(self) -> int:
        code = self._proc.wait()
        self._stderr_reader.join(timeout=2)
        for stream in (self._proc.stdout, self._proc.stderr):
            if stream is not None:
                stream.close()
        return code

    def stderr_text(self) -> str:
        return "".join(self._stderr)

    def terminate(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()


class SubprocessRunner:
    def run(self, cmd: Sequence[str], timeout: float) -> ProcessResult:
        try:
            proc = subprocess.run(
                list(cmd), capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(str(exc)) from exc
        return ProcessResult(proc.returncode, proc.stdout, proc.stderr)

    def start(self, cmd: Sequence[str]) -> RunningProcess:
        return _PopenProcess(cmd)
