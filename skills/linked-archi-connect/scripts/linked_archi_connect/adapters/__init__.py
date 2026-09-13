"""Execution backends behind one interface.

``open_adapter`` is what the skills call. It takes whatever the user supplied -
files, an endpoint, or nothing - and either returns something executable or explains
what is missing.

The refusal path matters as much as the success path. An investigation that cannot
execute should stop and say so, having produced candidate queries clearly labelled
unexecuted, rather than describe what the answer would probably have been.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .base import (
    Adapter, AdapterError, RawResult, term_to_string, validate_queries_readonly,
)
from .endpoint import EndpointAdapter, TOKEN_ENV, validate_endpoint_url
from .local import FORMATS, LocalAdapter
from .store_cache import MODES as STORE_MODES, StoreCacheError

__all__ = [
    "Adapter",
    "AdapterError",
    "RawResult",
    "term_to_string",
    "validate_queries_readonly",
    "LocalAdapter",
    "EndpointAdapter",
    "TOKEN_ENV",
    "validate_endpoint_url",
    "FORMATS",
    "STORE_MODES",
    "StoreCacheError",
    "open_adapter",
]


def open_adapter(
    data: Sequence[str | Path] | None = None,
    endpoint: str | None = None,
    **kwargs: Any,
) -> Adapter:
    """Open the backend implied by the arguments.

    Passing both is refused rather than silently preferring one: a result recorded
    against the wrong dataset identity is worse than an error, because it looks
    reproducible.
    """
    if data is not None and (
        isinstance(data, (str, bytes))
        or not isinstance(data, Sequence)
        or any(
            not isinstance(path, (str, Path)) or not str(path).strip()
            for path in data
        )
    ):
        raise AdapterError("data must be a sequence of non-empty paths")
    if endpoint is not None and (
        not isinstance(endpoint, str) or not endpoint.strip()
    ):
        raise AdapterError("endpoint must be a non-empty string")
    unknown = set(kwargs).difference({"lenient", "timeout_ms", "token", "store"})
    if unknown:
        raise AdapterError(
            "unknown adapter options: " + ", ".join(sorted(unknown))
        )
    if "lenient" in kwargs and not isinstance(kwargs["lenient"], bool):
        raise AdapterError("lenient must be a boolean")
    # Validated here rather than left to the local adapter so that passing a bad mode
    # alongside --endpoint is still refused. A silently ignored option reads as a
    # setting that had no effect, which is the hardest kind to notice.
    if "store" in kwargs and kwargs["store"] is not None and (
        not isinstance(kwargs["store"], str) or kwargs["store"].strip().lower() not in STORE_MODES
    ):
        raise AdapterError(
            "store must be null or one of: " + ", ".join(STORE_MODES)
        )
    if "timeout_ms" in kwargs and (
        not isinstance(kwargs["timeout_ms"], int)
        or isinstance(kwargs["timeout_ms"], bool)
        or kwargs["timeout_ms"] <= 0
    ):
        raise AdapterError("timeout_ms must be a positive integer")
    if "token" in kwargs and kwargs["token"] is not None and (
        not isinstance(kwargs["token"], str) or not kwargs["token"].strip()
    ):
        raise AdapterError("token must be a non-empty string or null")
    data_list = list(data) if data is not None else []
    if data_list and endpoint:
        raise AdapterError(
            "Give either --data or --endpoint, not both. Two datasets would make the "
            "recorded dataset identity wrong, and a result that cites the wrong "
            "source is worse than no result."
        )
    if endpoint:
        allowed = {"timeout_ms", "token"}
        return EndpointAdapter(endpoint, **{k: v for k, v in kwargs.items() if k in allowed})
    if data_list:
        return LocalAdapter(
            data_list,
            lenient=kwargs.get("lenient", False),
            store=kwargs.get("store"),
        )
    raise AdapterError(
        "No graph to query. Pass --data with one or more RDF files, or --endpoint "
        "with a read-only SPARQL URL.\n"
        "If neither is available, stop after producing candidate queries and label "
        "them unexecuted - do not describe results you have not seen."
    )
