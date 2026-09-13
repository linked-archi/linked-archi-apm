"""Execute against an HTTP SPARQL query endpoint, using the standard library only.

Deliberately no ``requests`` dependency: the whole package should install and run with nothing but
Python and, for local files, pyoxigraph.

Two things this does that the original did not:

* **Credentials never reach the envelope.** ``dataset_id`` is the endpoint with
  userinfo and query string stripped, so a saved result can be shared without
  leaking a token that was embedded in the URL.
* **A bearer token is read from the environment, not an argument.** Passing a
  secret on a command line puts it in shell history and in process listings.

Client-side read-only checking is a guard, not a boundary. Point this at a
read-only endpoint or a read-only credential as well.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base import Adapter, AdapterError, RawResult

#: Environment variable holding a bearer token, if the endpoint needs one.
TOKEN_ENV = "LINKED_ARCHI_SPARQL_TOKEN"

_ACCEPT = (
    "application/sparql-results+json;q=1.0, "
    "text/turtle;q=0.9, "
    "application/n-triples;q=0.8"
)
_SPARQL_JSON = "application/sparql-results+json"
_ASK_TEXT = "text/boolean"
_RDF_RESULTS = frozenset({"text/turtle", "application/n-triples"})
_HOST_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def _valid_host(hostname: str) -> bool:
    """Accept IP literals and DNS host names, including IDNA names."""
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    try:
        ascii_name = hostname.rstrip(".").encode("idna").decode("ascii")
    except UnicodeError:
        return False
    return (
        bool(ascii_name)
        and len(ascii_name) <= 253
        and all(_HOST_LABEL.fullmatch(label) for label in ascii_name.split("."))
    )


def validate_endpoint_url(endpoint: str) -> urllib.parse.SplitResult:
    """Parse an endpoint URL or fail with an adapter-owned diagnostic."""
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise AdapterError("Endpoint must be a non-empty http or https URL")
    if endpoint != endpoint.strip() or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in endpoint
    ):
        raise AdapterError("Endpoint URL must not contain whitespace or control characters")
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"Endpoint is not a valid URL: {endpoint!r}") from exc
    if parsed.scheme not in {"http", "https"}:
        raise AdapterError(
            f"Endpoint must be an http or https URL, got {endpoint!r}"
        )
    if not hostname or not _valid_host(hostname):
        raise AdapterError(f"Endpoint URL must include a valid host, got {endpoint!r}")
    if port == 0:
        raise AdapterError(f"Endpoint URL has an invalid port, got {endpoint!r}")
    return parsed


def _public_id(parsed: urllib.parse.SplitResult) -> str:
    """The endpoint, stripped of anything secret, for recording in an envelope."""
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _valid_binding_term(term: Any) -> bool:
    """Whether one SPARQL Results JSON term has a coherent field shape."""
    if not isinstance(term, dict):
        return False
    term_type = term.get("type")
    if term_type not in {"uri", "bnode", "literal", "typed-literal"}:
        return False
    if not isinstance(term.get("value"), str):
        return False

    keys = set(term)
    if term_type in {"uri", "bnode"}:
        return keys == {"type", "value"}
    if term_type == "typed-literal":
        return (
            keys == {"type", "value", "datatype"}
            and isinstance(term.get("datatype"), str)
            and bool(term["datatype"].strip())
        )

    allowed = {"type", "value", "datatype", "xml:lang"}
    if not keys.issubset(allowed):
        return False
    has_datatype = "datatype" in term
    has_language = "xml:lang" in term
    if has_datatype and has_language:
        return False
    if has_datatype and (
        not isinstance(term["datatype"], str) or not term["datatype"].strip()
    ):
        return False
    if has_language and (
        not isinstance(term["xml:lang"], str) or not term["xml:lang"].strip()
    ):
        return False
    return True


class EndpointAdapter(Adapter):
    """A read-only SPARQL query endpoint reached over HTTP."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_ms: int = 30000,
        token: str | None = None,
    ) -> None:
        parsed = validate_endpoint_url(endpoint)
        if (
            not isinstance(timeout_ms, int)
            or isinstance(timeout_ms, bool)
            or timeout_ms <= 0
        ):
            raise AdapterError("timeout_ms must be a positive integer")
        if token is not None and (
            not isinstance(token, str) or not token.strip()
        ):
            raise AdapterError("token must be a non-empty string or null")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            # Not refused: a lab or an internal network may legitimately be plain
            # HTTP. Stated, because the query and its results cross the wire.
            self._insecure = True
        else:
            self._insecure = False

        self.endpoint = endpoint
        self.dataset_id = _public_id(parsed)
        self.default_timeout_ms = timeout_ms
        self._token = token or os.environ.get(TOKEN_ENV)
        # Unknown until something is queried; the connect skill reports it.
        self.named_graphs_present = None

    # -- internals ----------------------------------------------------------

    def _post(self, query: str, timeout_ms: int | None) -> tuple[bytes, str]:
        body = urllib.parse.urlencode({"query": query}).encode("utf-8")
        headers = {
            "Accept": _ACCEPT,
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "linked-archi-apm/0.1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        request = urllib.request.Request(
            self.endpoint, data=body, headers=headers, method="POST"
        )
        timeout = (timeout_ms or self.default_timeout_ms) / 1000
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(), response.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise AdapterError(
                f"Endpoint returned HTTP {exc.code} for a read-only query. "
                f"{detail.strip()}"
            ) from exc
        except urllib.error.URLError as exc:
            raise AdapterError(
                f"Could not reach {self.dataset_id}: {exc.reason}. If the graph is a "
                "local file, use the local adapter instead."
            ) from exc
        except TimeoutError as exc:
            raise AdapterError(
                f"Query exceeded {timeout:.0f}s against {self.dataset_id}. Narrow the "
                "scope or lower the row limit rather than raising the timeout."
            ) from exc

    def _execute_raw(self, query: str, timeout_ms: int | None = None) -> RawResult:
        payload, content_type = self._post(query, timeout_ms)

        if content_type == _SPARQL_JSON:
            try:
                document = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise AdapterError(
                    f"Endpoint claimed {content_type} but returned unparseable JSON"
                ) from exc
            if not isinstance(document, dict):
                raise AdapterError("Endpoint returned a malformed SPARQL JSON result")

            has_boolean = "boolean" in document
            has_results = "results" in document
            if has_boolean == has_results:
                raise AdapterError("Endpoint returned an ambiguous SPARQL JSON result")
            if has_boolean:
                if not isinstance(document["boolean"], bool):
                    raise AdapterError("Endpoint returned a non-boolean ASK result")
                if "head" in document and not isinstance(document["head"], dict):
                    raise AdapterError("Endpoint returned a malformed ASK result")
                return RawResult(form="ASK", boolean=document["boolean"])

            head = document.get("head")
            results = document.get("results")
            if not isinstance(head, dict) or not isinstance(results, dict):
                raise AdapterError("Endpoint returned a malformed SELECT result")
            variables = head.get("vars")
            bindings = results.get("bindings")
            if (
                not isinstance(variables, list)
                or any(not isinstance(name, str) or not name for name in variables)
                or len(set(variables)) != len(variables)
                or not isinstance(bindings, list)
                or any(not isinstance(binding, dict) for binding in bindings)
            ):
                raise AdapterError("Endpoint returned a malformed SELECT result")
            variable_names = set(variables)
            for binding in bindings:
                if not set(binding).issubset(variable_names):
                    raise AdapterError("Endpoint returned an unknown SELECT binding")
                for term in binding.values():
                    if not _valid_binding_term(term):
                        raise AdapterError("Endpoint returned a malformed SELECT binding")
            rows = [
                {name: _binding(binding.get(name)) for name in variables}
                for binding in bindings
            ]
            return RawResult(form="SELECT", variables=variables, rows=rows)

        text = payload.decode("utf-8", errors="replace")
        if content_type == _ASK_TEXT:
            value = text.strip().lower()
            if value not in {"true", "false"}:
                raise AdapterError("Endpoint returned a malformed text ASK result")
            return RawResult(form="ASK", boolean=value == "true")
        if content_type not in _RDF_RESULTS:
            raise AdapterError(
                f"Endpoint returned unsupported result media type {content_type!r}"
            )
        return RawResult(form="CONSTRUCT", triples=text)

    # -- reporting ----------------------------------------------------------

    def describe(self) -> str:
        lines = [f"SPARQL endpoint: {self.dataset_id}"]
        if self._token:
            lines.append(f"  auth: bearer token from ${TOKEN_ENV}")
        if self._insecure:
            lines.append(
                "  warning: plain HTTP. The query and its results cross the network "
                "in the clear."
            )
        lines.append(f"  timeout: {self.default_timeout_ms} ms")
        lines.append(
            "  reminder: enforce read-only server-side too. This client refuses "
            "updates and SERVICE, but a client-side check is a guard, not a boundary."
        )
        return "\n".join(lines)


def _binding(term: dict[str, Any] | None) -> str:
    """Render one SPARQL-JSON binding, keeping blank nodes distinguishable."""
    if not term:
        return ""
    if term.get("type") == "bnode":
        return f"_:{term.get('value', '')}"
    return str(term.get("value", ""))


def connect(endpoint: str, **kwargs: Any) -> EndpointAdapter:
    return EndpointAdapter(endpoint, **kwargs)
