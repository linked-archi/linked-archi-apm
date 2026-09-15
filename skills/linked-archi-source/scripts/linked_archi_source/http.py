"""HTTPS RDF acquisition with pinned peers, bounded redirects, and one deadline."""

from __future__ import annotations

import http.client
import ipaddress
import os
import queue
import re
import socket
import ssl
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from .core import (
    Policy,
    SourceCache,
    canonical_digest,
    normalize_format,
    optional_digest,
    require_text,
    EXTENSIONS,
    MEDIA_TYPES,
)
from .errors import SourceError

MAX_REDIRECTS = 5
USER_AGENT = "linked-archi-source/0.1"

#: The fallback header: everything this client can parse, weighted. Weights state a
#: preference correctly and are not sufficient on their own - the server measured here
#: ignores them completely - which is why they are the LAST attempt rather than the only
#: one. See :func:`negotiation_sequence` for the narrow attempts that come first.
#:
#: Turtle leads because that is what these documents are. An ontology, a SKOS taxonomy
#: and a SHACL shape set are single-graph, so TriG buys nothing, and Turtle is the
#: smallest serialisation published: 94 kB for the core ontology against 129 kB of
#: RDF/XML and 141 kB of JSON-LD, all three measured.
#:
#: A quad dataset is the case where leading with Turtle would be wrong - a server
#: offering the same dataset as both would hand back flattened triples, losing graph
#: identity exactly as `fixtures/flat.ttl` documents. That is what `--format trig`
#: is for, and why an explicit format now reaches this header: see :func:`accept_header`.
ACCEPT_WEIGHTS: tuple[tuple[str, str], ...] = (
    ("text/turtle", "1.0"),
    ("application/trig", "0.9"),
    ("application/n-quads", "0.8"),
    ("application/n-triples", "0.8"),
    ("application/rdf+xml", "0.7"),
    ("application/ld+json", "0.7"),
    ("text/n3", "0.5"),
)
ACCEPT = ", ".join(f"{media};q={weight}" for media, weight in ACCEPT_WEIGHTS)

#: Which media type to ask for first when the caller named a format. Derived from the
#: format table rather than restated, so a new format cannot be requestable and
#: unparseable at the same time.
_MEDIA_FOR_FORMAT = {value: key for key, value in MEDIA_TYPES.items()}


#: Content types that mean "this is a page about the RDF", not the RDF. Named rather
#: than inferred, so an unfamiliar type is still allowed through to format detection
#: instead of being refused on a guess.
_DOCUMENTATION_TYPES = frozenset(
    {"text/html", "application/xhtml+xml", "text/plain", "application/json"}
)


def is_documentation(content_type: str) -> bool:
    """Whether a response carries a page about the RDF rather than the RDF."""
    media_type = content_type.partition(";")[0].strip().lower()
    return bool(media_type) and media_type in _DOCUMENTATION_TYPES


def reject_non_rdf(content_type: str, url: str, asked_for: str = ACCEPT) -> None:
    """Refuse a 200 that carries documentation instead of RDF.

    Content negotiation can fail without failing: asked for `application/trig`,
    meta.linked.archi answers 200 with 254 kB of `text/html`, and a 406 would have been
    the honest reply. Status alone therefore proves nothing about what arrived.

    Worth refusing here rather than at the parser, for the one case where the parser
    would not object either. A URL ending `.ttl` that serves an HTML error page takes its
    format from the extension, so the bytes reach a Turtle parser that reports a syntax
    error at line 1 - which reads as "the vocabulary is malformed" rather than "the
    server sent you a web page".
    """
    media_type = content_type.partition(";")[0].strip().lower()
    if not media_type or media_type not in _DOCUMENTATION_TYPES:
        return
    if media_type == "application/json":
        # JSON-LD is served as application/ld+json. Plain application/json may still be
        # JSON-LD from a server that does not distinguish them, so say what to pass.
        raise SourceError(
            f"{public_url(url)} returned Content-Type {media_type!r}. If this really is "
            "JSON-LD, request it with --format json-ld; otherwise the endpoint is not "
            "serving RDF"
        )
    raise SourceError(
        f"{public_url(url)} returned Content-Type {media_type!r}, not RDF, in answer to "
        f"Accept: {asked_for}. A namespace IRI commonly serves human documentation unless "
        "RDF is negotiated for, and some publishers answer 404 or a web page rather than "
        "406 for a type they do not hold - so a narrower request can succeed where a "
        "broader one fails. Try --format with a serialisation the publisher offers"
    )


def accept_header(rdf_format: str | None = None) -> str:
    """The Accept header, with ``rdf_format`` promoted to first preference.

    Asking for what you intend to parse is the point. `--format turtle` used to be
    applied only when interpreting the response, never when requesting it, so a server
    holding several serialisations could answer JSON-LD to a Turtle request and the
    download then failed to parse - a confusing way to be told about content negotiation.
    """
    if rdf_format is None or rdf_format not in _MEDIA_FOR_FORMAT:
        return ACCEPT
    wanted = _MEDIA_FOR_FORMAT[rdf_format]
    rest = [
        f"{media};q={weight if media != wanted else '0.9'}"
        for media, weight in ACCEPT_WEIGHTS
        if media != wanted
    ]
    return ", ".join([f"{wanted};q=1.0", *rest])


def negotiation_sequence(rdf_format: str | None, path: str) -> list[str]:
    """Accept headers to try, in order, because weights are not always honoured.

    A weighted list is the correct way to state a preference and it is not sufficient.
    meta.linked.archi ignores q entirely: it answers JSON-LD whenever JSON-LD appears
    anywhere in the list, at any weight, and serves Turtle only when JSON-LD is absent.
    Measured across four headers - Turtle at q=1.0 beside JSON-LD at q=0.7 still returns
    141 kB of JSON-LD, while Turtle alone returns 94 kB of Turtle. A server like that can
    only be asked one type at a time.

    So the first attempt is narrow and the last is the full list, which is both a real
    preference and a fallback for a publisher who offers something else entirely.

    A path with an RDF extension gets no narrow attempt: `/dataset.trig` is a document,
    not a negotiated namespace, and its extension already says what it is. That is also
    what keeps a quad dataset from being asked for as Turtle and silently flattened.
    """
    if rdf_format is not None:
        media = _MEDIA_FOR_FORMAT.get(rdf_format)
        # No fallback when a format was named. Answering a Turtle request with JSON-LD
        # and parsing it as Turtle is how you get "syntax error at line 1" instead of
        # "this server does not publish Turtle".
        return [media] if media else [accept_header(rdf_format)]
    if Path(path).suffix.lower() in EXTENSIONS:
        return [ACCEPT]
    return ["text/turtle", ACCEPT]
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceError("HTTPS acquisition exceeded its total timeout")
    return remaining


def _normalize_host(host: str) -> str:
    try:
        return host.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise SourceError(f"source host is not valid IDNA: {host!r}") from exc


def public_url(url: str) -> str:
    """Remove credentials, query, and fragment before recording a URL."""
    split = urllib.parse.urlsplit(url)
    host = _normalize_host(split.hostname or "")
    try:
        port = split.port
    except ValueError:
        port = None
    netloc = host
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urllib.parse.urlunsplit((split.scheme.lower(), netloc, split.path, "", ""))


def parse_https_url(url: Any, policy: Policy) -> urllib.parse.SplitResult:
    """Validate HTTPS syntax and policy without DNS or network access."""
    value = require_text(url, "source uri")
    split = urllib.parse.urlsplit(value)
    if split.scheme.lower() != "https":
        raise SourceError("RDF document acquisition requires HTTPS")
    if split.username is not None or split.password is not None:
        raise SourceError("source URI must not contain userinfo; use external credentials")
    if split.fragment:
        raise SourceError("source URI must not contain a fragment")
    host = _normalize_host(split.hostname or "")
    if not host:
        raise SourceError("source URI requires a host")
    try:
        split.port
    except ValueError as exc:
        raise SourceError(f"source URI has an invalid port: {exc}") from exc
    if policy.allowed_hosts and host not in policy.allowed_hosts:
        raise SourceError(f"source host {host!r} is not in policy allowed_hosts")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not policy.allow_private_network and not literal.is_global:
        raise SourceError(
            f"source host {host!r} is a non-public address; use --allow-private-network only for an explicitly trusted host"
        )
    return split


def _resolve(host: str, port: int, deadline: float) -> list[tuple]:
    result: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except BaseException as exc:  # daemon reports into the caller's error domain
            result.put((False, exc))
        else:
            result.put((True, addresses))

    thread = threading.Thread(target=worker, name="linked-archi-dns", daemon=True)
    thread.start()
    thread.join(_remaining(deadline))
    if thread.is_alive():
        raise SourceError("source DNS resolution exceeded its total timeout")
    ok, value = result.get_nowait()
    if not ok:
        if isinstance(value, socket.gaierror):
            raise SourceError(f"could not resolve source host {host!r}: {value}") from value
        raise SourceError(f"source DNS resolution failed: {value}") from value
    if not value:
        raise SourceError(f"source host {host!r} resolved to no addresses")
    return value


def validated_https_transport(
    url: Any,
    policy: Policy,
    deadline: float | None = None,
) -> tuple[urllib.parse.SplitResult, list[tuple]]:
    """Resolve an HTTPS URL once and return only policy-vetted addresses."""
    split = parse_https_url(url, policy)
    host = _normalize_host(split.hostname or "")
    port = split.port or 443
    effective_deadline = deadline or (time.monotonic() + policy.timeout_ms / 1000)
    addresses = _resolve(host, port, effective_deadline)
    if not policy.allow_private_network:
        refused: set[str] = set()
        for address in addresses:
            raw = address[4][0]
            try:
                parsed = ipaddress.ip_address(raw)
            except ValueError:
                refused.add(raw)
                continue
            if not parsed.is_global:
                refused.add(str(parsed))
        if refused:
            raise SourceError(
                f"source host {host!r} resolves to non-public address(es): "
                + ", ".join(sorted(refused))
                + "; use --allow-private-network only for an explicitly trusted host"
            )
    return split, addresses


def validate_https_url(url: Any, policy: Policy) -> urllib.parse.SplitResult:
    """Validate and resolve a remote HTTPS identity."""
    split, _addresses = validated_https_transport(url, policy)
    return split


def _origin(split: urllib.parse.SplitResult) -> tuple[str, str, int]:
    return (
        split.scheme.lower(),
        _normalize_host(split.hostname or ""),
        split.port or 443,
    )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a vetted address while retaining the original TLS hostname."""

    def __init__(
        self,
        host: str,
        port: int,
        addresses: list[tuple],
        deadline: float,
    ) -> None:
        self._addresses = addresses
        self._deadline = deadline
        super().__init__(
            host,
            port=port,
            timeout=_remaining(deadline),
            context=ssl.create_default_context(),
        )

    def connect(self) -> None:
        last_error: OSError | None = None
        for family, socktype, proto, _canonname, sockaddr in self._addresses:
            raw: socket.socket | None = None
            try:
                raw = socket.socket(family, socktype, proto)
                raw.settimeout(_remaining(self._deadline))
                raw.connect(sockaddr)
                wrapped = self._context.wrap_socket(raw, server_hostname=self.host)
                raw = None  # ownership transferred to the TLS socket
                wrapped.settimeout(_remaining(self._deadline))
                self.sock = wrapped
                return
            except OSError as exc:
                last_error = exc
                if raw is not None:
                    raw.close()
            except BaseException:
                if raw is not None:
                    raw.close()
                raise
        raise SourceError(f"could not connect to a vetted source address: {last_error}")


def acquire_url(source: dict[str, Any], policy: Policy) -> dict[str, Any]:
    allowed = {"kind", "uri", "format", "expected_sha256", "token_env"}
    unknown = set(source).difference(allowed)
    if unknown:
        raise SourceError("url source contains unknown fields: " + ", ".join(sorted(unknown)))
    uri = require_text(source.get("uri"), "source uri")
    initial_split = parse_https_url(uri, policy)
    initial_origin = _origin(initial_split)
    expected = optional_digest(source.get("expected_sha256"))
    token_env = source.get("token_env")
    if token_env is not None:
        token_env = require_text(token_env, "source token_env")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
            raise SourceError("source token_env must be an environment variable name")
    explicit_format = source.get("format")
    normalized_explicit = (
        normalize_format(explicit_format, initial_split.path)
        if explicit_format is not None
        else None
    )
    request_key = canonical_digest(
        {
            "kind": "url",
            "uri": uri,
            "format": normalized_explicit,
            "expected_sha256": expected,
            "token_env": token_env,
            "lenient": policy.lenient,
        }
    )
    cache = SourceCache(policy)
    if policy.offline:
        cached = cache.find(request_key)
        if cached is None:
            raise SourceError("offline mode has no exact cached result for this URL request")
        return cached

    token: str | None = None
    if token_env is not None:
        token = os.environ.get(token_env)
        if not token:
            raise SourceError(f"source credential environment variable is not set: {token_env}")

    deadline = time.monotonic() + policy.timeout_ms / 1000
    current = uri
    redirect_chain: list[str] = []
    temporary: Path | None = None
    # Content negotiation is a sequence here, not one header - see negotiation_sequence.
    # Redirects are counted separately from attempts so that renegotiating does not
    # spend the redirect budget, and the whole thing stays bounded by the deadline.
    candidates = negotiation_sequence(normalized_explicit, initial_split.path)
    attempt = 0
    redirects_used = 0
    try:
        for _iteration in range(len(candidates) * (MAX_REDIRECTS + 1)):
            split, addresses = validated_https_transport(current, policy, deadline)
            current_origin = _origin(split)
            if token is not None and current_origin != initial_origin:
                raise SourceError("credentialled source redirect to a different origin is refused")
            host, port = current_origin[1], current_origin[2]
            connection = _PinnedHTTPSConnection(host, port, addresses, deadline)
            path = urllib.parse.urlunsplit(("", "", split.path or "/", split.query, ""))
            headers = {
                "Accept": candidates[attempt],
                "Accept-Encoding": "identity",
                "User-Agent": USER_AGENT,
            }
            if token is not None:
                headers["Authorization"] = f"Bearer {token}"
            try:
                connection.connect()
                if connection.sock is not None:
                    connection.sock.settimeout(_remaining(deadline))
                connection.request("GET", path, headers=headers)
                _remaining(deadline)
                if connection.sock is not None:
                    connection.sock.settimeout(_remaining(deadline))
                response = connection.getresponse()
                _remaining(deadline)
                if response.status in _REDIRECTS:
                    location = response.getheader("Location")
                    if not location:
                        raise SourceError(f"source returned HTTP {response.status} without Location")
                    if redirects_used >= MAX_REDIRECTS:
                        raise SourceError(f"source exceeded {MAX_REDIRECTS} HTTPS redirects")
                    redirects_used += 1
                    current = urllib.parse.urljoin(current, location)
                    redirected = parse_https_url(current, policy)
                    if token is not None and _origin(redirected) != initial_origin:
                        raise SourceError("credentialled source redirect to a different origin is refused")
                    redirect_chain.append(public_url(current))
                    continue
                if response.status != 200:
                    raise SourceError(f"source returned HTTP {response.status}: {response.reason}")
                encoding = response.getheader("Content-Encoding", "identity").lower()
                if encoding not in {"", "identity"}:
                    raise SourceError(
                        f"source returned Content-Encoding {encoding!r}; compressed responses are refused"
                    )
                content_length = response.getheader("Content-Length")
                if content_length is not None:
                    try:
                        declared = int(content_length)
                    except ValueError as exc:
                        raise SourceError("source returned an invalid Content-Length") from exc
                    if declared < 0 or declared > policy.max_bytes:
                        raise SourceError(
                            f"source declares {declared} bytes, above max_bytes={policy.max_bytes}"
                        )
                content_type = response.getheader("Content-Type", "")
                if is_documentation(content_type) and attempt + 1 < len(candidates):
                    # Negotiation failed without failing: 200, but a web page. Ask again
                    # with the next header rather than reporting a parse error later.
                    attempt += 1
                    current = uri
                    redirect_chain.clear()
                    redirects_used = 0
                    continue
                reject_non_rdf(content_type, current, candidates[attempt])
                rdf_format = normalize_format(normalized_explicit, split.path, content_type)
                temporary = cache.temporary_path()
                received = 0
                with temporary.open("wb") as output:
                    while True:
                        if connection.sock is not None:
                            connection.sock.settimeout(_remaining(deadline))
                        limit = min(64 * 1024, policy.max_bytes + 1 - received)
                        reader = getattr(response, "read1", None) or response.read
                        block = reader(limit)
                        _remaining(deadline)
                        if not block:
                            break
                        received += len(block)
                        if received > policy.max_bytes:
                            raise SourceError(
                                f"source exceeded max_bytes={policy.max_bytes} while downloading"
                            )
                        output.write(block)
                final_url = current
                break
            except SourceError:
                raise
            except (OSError, http.client.HTTPException, TimeoutError) as exc:
                raise SourceError(f"could not fetch RDF source: {exc}") from exc
            finally:
                connection.close()
        else:  # pragma: no cover - bounded loop always exits or raises
            raise SourceError(
                f"source exhausted {len(candidates)} content-negotiation attempt(s) "
                f"within {MAX_REDIRECTS} redirects each"
            )

        artifact = cache.materialize(temporary, rdf_format, expected)
        warnings: list[str] = []
        if expected is None:
            warnings.append(
                "source was not pinned by --sha256; record the observed digest for reproducible reuse"
            )
        source_manifest = {
            "kind": "url",
            "request_key": request_key,
            "requested_identity": public_url(uri),
            "resolved_identity": public_url(final_url),
            "redirect_chain": redirect_chain,
            "expected_sha256": expected,
            "credential_env": token_env,
            "content_type": content_type.partition(";")[0].strip().lower() or None,
        }
        return cache.write_manifest(source_manifest, [artifact], warnings)
    finally:
        if temporary is not None:
            cache.discard(temporary)
