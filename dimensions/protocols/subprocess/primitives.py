"""Framework primitives for the CLI dimension.

Plugins delegate to these functions to push CommandState observations
onto an envelope. The plugin only configures which command to run; the
primitives own the observation IDs and shapes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from dimensions.api import EnvelopeBuilder
    from dimensions.protocols.subprocess.injection import CommandState


def command_subject_dict(
    argv: Union[List[str], str],
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build a CommandSubject dict for ``ctx.envelope(subject=...)``."""
    if isinstance(argv, str):
        import shlex
        argv = shlex.split(argv)
    subject: Dict[str, Any] = {"kind": "command", "argv": list(argv)}
    if cwd is not None:
        subject["cwd"] = cwd
    if env:
        subject["env"] = {str(k): str(v) for k, v in env.items()}
    return subject


def emit_command(env: "EnvelopeBuilder", state: "CommandState") -> None:
    """Emit the canonical CLI-dim observations from a CommandState."""
    env.boolean(
        "cli.available",
        "Executable launched (binary found, no early failure)",
        bool(state.available),
    )
    env.boolean(
        "cli.completed",
        "Process completed without timing out",
        bool(state.completed),
    )
    env.scalar(
        "cli.exit_code", "Process exit code",
        int(state.exit_code),
    )
    env.boolean(
        "cli.exit_ok", "Exit code is zero",
        state.exit_code == 0,
    )
    env.scalar(
        "cli.duration_ms", "Wall-clock duration",
        int(state.duration_ms), unit="ms",
    )
    env.scalar(
        "cli.stdout_bytes", "Captured stdout size",
        len(state.stdout.encode("utf-8")), unit="bytes",
    )
    env.scalar(
        "cli.stderr_bytes", "Captured stderr size",
        len(state.stderr.encode("utf-8")), unit="bytes",
    )
    env.payload(
        "cli.stdout", "Captured stdout (truncated)",
        payload_schema="text",
        data={"text": state.stdout},
    )
    env.payload(
        "cli.stderr", "Captured stderr (truncated)",
        payload_schema="text",
        data={"text": state.stderr},
    )
    if state.error:
        env.payload(
            "cli.error", "Protocol-level error (timeout, exec failure)",
            payload_schema="text",
            data={"text": state.error},
        )
