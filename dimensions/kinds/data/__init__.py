"""Data dimension — schema, primitives, and reference plugin."""

from dimensions.kinds.data.primitives import (
    file_size,
    file_subject_dict,
    hash_file,
    walk_json,
)
from dimensions.kinds.data.file_protocol import JsonFileProtocol
from dimensions.kinds.data.schema import DataEnvelope, FileSubject
from dimensions.kinds.data.spec import SpecError, compile_spec

__all__ = [
    "DataEnvelope",
    "FileSubject",
    "JsonFileProtocol",
    "SpecError",
    "compile_spec",
    "file_size",
    "file_subject_dict",
    "hash_file",
    "walk_json",
]
