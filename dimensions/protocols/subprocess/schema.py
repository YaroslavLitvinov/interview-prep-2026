"""Pydantic schema for the subprocess InjectionProtocol.

Owns the envelope + subject shape produced by any SubprocessProtocol
implementation. A command is launched; exit code, stdout, stderr,
and duration become observations.
"""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict

from dimensions.schema.envelope import _EnvelopeBase, register_envelope


class CommandSubject(BaseModel):
    """Subject schema for subprocess captures — a single command run."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["command"]
    argv: List[str]
    cwd: Optional[str] = None
    env: Dict[str, str] = {}     # only vars explicitly set by the scenario


@register_envelope
class SubprocessEnvelope(_EnvelopeBase):
    """Envelope variant for the subprocess InjectionProtocol."""

    protocol: Literal["subprocess"]
    subject: CommandSubject
    dimension_version: int = 1
