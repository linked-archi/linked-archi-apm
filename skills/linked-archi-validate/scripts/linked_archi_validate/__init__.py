"""SHACL validation and report-reading owner.

Self-contained: SHACL runs in-process through pyshacl, so no converter, Java runtime or
network access is involved. Shape documents are never bundled here - they are published
separately under their own licence - so callers pass local files, or acquire the published
ones once through the source owner and pass the cached paths.
"""

from .coverage import Coverage, measure
from .errors import ValidateError
from .report import Finding, Summary, summarise

__all__ = [
    "Coverage",
    "Finding",
    "Summary",
    "ValidateError",
    "measure",
    "summarise",
]
