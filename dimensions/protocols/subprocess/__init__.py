"""Subprocess InjectionProtocol — schema, primitives, real + fixture impls."""

from dimensions.protocols.subprocess.injection import (
    CommandState,
    SubprocessProtocol,
)
from dimensions.protocols.subprocess.primitives import (
    command_subject_dict,
    emit_command,
)
from dimensions.protocols.subprocess.schema import (
    CommandSubject,
    SubprocessEnvelope,
)

__all__ = [
    "CommandState",
    "CommandSubject",
    "SubprocessEnvelope",
    "SubprocessProtocol",
    "command_subject_dict",
    "emit_command",
]
