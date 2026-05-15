"""SubprocessProtocol — the InjectionProtocol for the CLI dimension.

Drives a real subprocess via ``asyncio.subprocess``. Surfaces every
failure mode (timeout, missing binary, non-zero exit) as a structured
``CommandState`` rather than raising — the plugin always produces an
envelope so the framework's diff / render machinery has something to
work with.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from dimensions.injection import BaseInjectionProtocol


@dataclass(frozen=True)
class CommandState:
    """Frozen state returned by every SubprocessProtocol implementation.

    Mirrors PageState / DataState: structured, optional, comparable.
    """

    available:   bool
    completed:   bool
    exit_code:   int
    stdout:      str
    stderr:      str
    duration_ms: int
    argv:        List[str] = field(default_factory=list)
    cwd:         Optional[str] = None
    error:       Optional[str] = None


class SubprocessProtocol(BaseInjectionProtocol):
    """Run shell commands and return a CommandState."""

    name = "subprocess"
    engine = "asyncio"

    def __init__(
        self,
        *,
        default_timeout_s: float = 30.0,
        max_output_bytes: int = 64 * 1024,
    ) -> None:
        self.default_timeout_s = float(default_timeout_s)
        self.max_output_bytes = int(max_output_bytes)

    async def __aenter__(self) -> "SubprocessProtocol":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run(
        self,
        argv: Union[str, List[str]],
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        stdin: Optional[bytes] = None,
        timeout_s: Optional[float] = None,
    ) -> CommandState:
        if isinstance(argv, str):
            argv_list = shlex.split(argv)
        else:
            argv_list = list(argv)
        if not argv_list:
            return CommandState(
                available=False, completed=False, exit_code=-1,
                stdout="", stderr="", duration_ms=0,
                error="empty argv",
            )

        merged_env = dict(os.environ)
        if env:
            merged_env.update({str(k): str(v) for k, v in env.items()})

        timeout = timeout_s if timeout_s is not None else self.default_timeout_s
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                cwd=cwd,
                env=merged_env,
            )
        except FileNotFoundError as exc:
            return CommandState(
                available=False, completed=False, exit_code=-1,
                stdout="", stderr="", duration_ms=int((time.monotonic() - t0) * 1000),
                argv=argv_list, cwd=cwd,
                error=f"executable not found: {exc.filename!r}",
            )
        except Exception as exc:  # noqa: BLE001
            return CommandState(
                available=False, completed=False, exit_code=-1,
                stdout="", stderr="", duration_ms=int((time.monotonic() - t0) * 1000),
                argv=argv_list, cwd=cwd,
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=stdin), timeout=timeout,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return CommandState(
                available=True, completed=False, exit_code=-1,
                stdout="", stderr="", duration_ms=int(timeout * 1000),
                argv=argv_list, cwd=cwd,
                error=f"timed out after {timeout}s",
            )

        duration = int((time.monotonic() - t0) * 1000)
        return CommandState(
            available=True,
            completed=True,
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=self._truncate(stdout_b),
            stderr=self._truncate(stderr_b),
            duration_ms=duration,
            argv=argv_list,
            cwd=cwd,
        )

    def _truncate(self, b: bytes) -> str:
        if len(b) > self.max_output_bytes:
            head = b[: self.max_output_bytes].decode("utf-8", "replace")
            return head + f"\n…[truncated, {len(b)} bytes total]"
        return b.decode("utf-8", "replace")
