"""json_file InjectionProtocol — schema, primitives, file protocol."""

from dimensions.protocols.json_file.file_protocol import JsonFileProtocol
from dimensions.protocols.json_file.primitives import (
    file_size,
    file_subject_dict,
    hash_file,
    walk_json,
)
from dimensions.protocols.json_file.schema import FileSubject, JsonFileEnvelope
from dimensions.protocols.json_file.spec import SpecError, compile_spec

__all__ = [
    "FileSubject",
    "JsonFileEnvelope",
    "JsonFileProtocol",
    "SpecError",
    "compile_spec",
    "file_size",
    "file_subject_dict",
    "hash_file",
    "walk_json",
]
