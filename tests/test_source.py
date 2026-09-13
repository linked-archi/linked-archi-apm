"""The source owner's refusals, which are the only part of this package that reaches the network.

Every other owner reads a graph somebody already trusted. This one resolves caller-supplied
identifiers, opens sockets, and writes into a cache — so its interesting behaviour is not what
it fetches but what it *declines* to fetch, and each refusal below is a way a permissive
implementation would quietly do the wrong thing:

* a plaintext or ``file://`` URL, silently downgrading transport
* credentials in a URL, which then appear in manifests, logs and error text
* a host outside the allow-list, which is the whole point of having one
* a name or literal pointing inside the network the agent happens to run in (SSRF)
* content whose digest does not match what the caller pinned, which is the tamper case
* a repository path escaping the repository

The digest and allow-list groups matter most: those fail *dangerously* rather than merely
failing, so absence of a test is absence of the guarantee.

Almost nothing here needs the network. ``parse_https_url`` is deliberately pure — policy and
syntax are decided before DNS — and ``materialize`` works on a local file, so the tamper path
is exercised for real rather than mocked.
"""
from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

import support  # noqa: F401  - puts the owner packages on sys.path

from linked_archi_source.core import (
    Policy,
    SourceCache,
    is_full_commit,
    normalize_format,
    require_commit,
    require_digest,
    validate_repository_path,
)
from linked_archi_source.errors import SourceError
from linked_archi_source.http import parse_https_url
from linked_archi_source.mcp import request_gitlab

TRIG = b'<https://example.org/s> <https://example.org/p> <https://example.org/o> .\n'


def policy(**overrides) -> Policy:
    """A policy over a scratch cache, with everything else at its documented default."""
    raw = {"cache_dir": overrides.pop("cache_dir"), **overrides}
    return Policy.from_mapping(raw)


class TestTransportIsNotNegotiable(unittest.TestCase):
    """HTTPS only, no credentials, no fragment — decided without touching the network."""

    def setUp(self):
        self.policy = policy(cache_dir=self.enterContext(_tmp()))

    def test_a_plaintext_or_local_scheme_is_refused(self):
        for url in (
            "http://example.org/model.trig",
            "file:///etc/passwd",
            "ftp://example.org/model.trig",
            "gopher://example.org/model.trig",
        ):
            with self.subTest(url=url), self.assertRaises(SourceError) as caught:
                parse_https_url(url, self.policy)
            self.assertIn("HTTPS", str(caught.exception))

    def test_credentials_in_the_url_are_refused_rather_than_carried(self):
        """A URL is echoed into manifests and error text, so userinfo would leak a secret."""
        for url in (
            "https://user:token@example.org/model.trig",
            "https://token@example.org/model.trig",
        ):
            with self.subTest(url=url), self.assertRaises(SourceError) as caught:
                parse_https_url(url, self.policy)
            self.assertIn("userinfo", str(caught.exception))

    def test_a_fragment_is_refused(self):
        """A fragment is not sent to the server, so honouring one would misdescribe the fetch."""
        with self.assertRaises(SourceError):
            parse_https_url("https://example.org/model.trig#graph", self.policy)

    def test_a_missing_host_or_bad_port_is_refused(self):
        for url in ("https:///model.trig", "https://example.org:notaport/model.trig"):
            with self.subTest(url=url), self.assertRaises(SourceError):
                parse_https_url(url, self.policy)

    def test_a_well_formed_https_url_is_accepted(self):
        split = parse_https_url("https://example.org/dist/model.trig", self.policy)
        self.assertEqual(split.hostname, "example.org")


class TestTheAllowListIsEnforced(unittest.TestCase):
    """An allow-list nobody checks is documentation. Checked here, before DNS."""

    def setUp(self):
        self.cache = self.enterContext(_tmp())

    def test_a_host_outside_the_list_is_refused(self):
        allowed = policy(cache_dir=self.cache, allowed_hosts=["models.example.org"])
        with self.assertRaises(SourceError) as caught:
            parse_https_url("https://evil.example.net/model.trig", allowed)
        self.assertIn("allowed_hosts", str(caught.exception))

    def test_a_listed_host_is_accepted(self):
        allowed = policy(cache_dir=self.cache, allowed_hosts=["models.example.org"])
        split = parse_https_url("https://models.example.org/model.trig", allowed)
        self.assertEqual(split.hostname, "models.example.org")

    def test_case_and_a_trailing_dot_do_not_defeat_the_list(self):
        """`Models.Example.ORG.` and `models.example.org` are the same host to DNS."""
        allowed = policy(cache_dir=self.cache, allowed_hosts=["  Models.Example.ORG.  "])
        for spelling in (
            "https://models.example.org/m.trig",
            "https://MODELS.EXAMPLE.ORG/m.trig",
            "https://models.example.org./m.trig",
        ):
            with self.subTest(spelling=spelling):
                self.assertIsNotNone(parse_https_url(spelling, allowed))

    def test_an_empty_list_means_no_host_restriction(self):
        """Documents the default: the list restricts only when it is populated."""
        self.assertIsNotNone(
            parse_https_url("https://anywhere.example.net/m.trig", policy(cache_dir=self.cache))
        )


class TestTheAgentsOwnNetworkIsNotReachable(unittest.TestCase):
    """SSRF: a caller-supplied address must not reach loopback or a private range.

    Only literals are covered here, because that is what can be decided without DNS. The
    resolved-address gate in ``validated_https_transport`` applies the same rule to whatever a
    name resolves to, which is the half that needs a resolver.
    """

    NON_PUBLIC = (
        "https://127.0.0.1/m.trig",            # loopback
        "https://10.0.0.1/m.trig",             # RFC1918
        "https://192.168.1.1/m.trig",          # RFC1918
        "https://172.16.0.1/m.trig",           # RFC1918
        "https://169.254.169.254/m.trig",      # link-local, the cloud metadata endpoint
        "https://100.64.0.1/m.trig",           # CGNAT
        "https://[::1]/m.trig",                # IPv6 loopback
    )

    def setUp(self):
        self.cache = self.enterContext(_tmp())

    def test_a_non_public_literal_is_refused_by_default(self):
        default = policy(cache_dir=self.cache)
        for url in self.NON_PUBLIC:
            with self.subTest(url=url), self.assertRaises(SourceError) as caught:
                parse_https_url(url, default)
            self.assertIn("non-public", str(caught.exception))

    def test_the_refusal_names_the_flag_that_lifts_it(self):
        """A refusal an operator can act on, rather than a dead end."""
        with self.assertRaises(SourceError) as caught:
            parse_https_url("https://169.254.169.254/m.trig", policy(cache_dir=self.cache))
        self.assertIn("allow-private-network", str(caught.exception))

    def test_an_explicit_opt_in_permits_it(self):
        """Reaching a private host is a legitimate deployment, but never the default."""
        opted_in = policy(cache_dir=self.cache, allow_private_network=True)
        for url in self.NON_PUBLIC:
            with self.subTest(url=url):
                self.assertIsNotNone(parse_https_url(url, opted_in))


class TestContentIsVerifiedAgainstWhatTheCallerPinned(unittest.TestCase):
    """The tamper case, on a real file rather than a mock.

    ``materialize`` is where every acquisition path converges, so this is the single gate that
    decides whether "verified" means anything.
    """

    def setUp(self):
        support.requires_pyoxigraph(self)
        self.cache_dir = self.enterContext(_tmp())
        self.cache = SourceCache(policy(cache_dir=self.cache_dir))
        self.artifact = Path(self.cache_dir) / "incoming.trig"
        self.artifact.write_bytes(TRIG)
        self.digest = hashlib.sha256(TRIG).hexdigest()

    def test_matching_content_is_accepted_and_content_addressed(self):
        result = self.cache.materialize(self.artifact, "trig", self.digest)
        self.assertEqual(result["sha256"], self.digest)
        self.assertIn(self.digest, result["path"])

    def test_a_digest_mismatch_is_refused(self):
        """Substituted content with a caller-pinned digest: the case the digest exists for."""
        with self.assertRaises(SourceError) as caught:
            self.cache.materialize(self.artifact, "trig", "0" * 64)
        message = str(caught.exception)
        self.assertIn("SHA-256 mismatch", message)
        self.assertIn(self.digest, message, "name the digest received, not only the expected one")

    def test_content_that_is_not_the_declared_format_is_refused(self):
        """Bytes that hash correctly can still be the wrong thing entirely."""
        junk = Path(self.cache_dir) / "junk.trig"
        junk.write_bytes(b"this is not RDF at all {{{\n")
        with self.assertRaises(SourceError):
            self.cache.materialize(junk, "trig", hashlib.sha256(junk.read_bytes()).hexdigest())

    def test_content_above_the_size_ceiling_is_refused(self):
        bounded = SourceCache(policy(cache_dir=self.cache_dir, max_bytes=8))
        with self.assertRaises(SourceError) as caught:
            bounded.materialize(self.artifact, "trig", self.digest)
        self.assertIn("max_bytes", str(caught.exception))

    def test_an_unknown_format_is_refused(self):
        with self.assertRaises(SourceError):
            self.cache.materialize(self.artifact, "sparql-results", self.digest)


class TestPinnedIdentifiersMustBeExact(unittest.TestCase):
    """An abbreviation or a loose digest is not a pin, and is refused as though it were absent."""

    def test_a_digest_must_be_exactly_64_hex_characters(self):
        for value in ("", "abc", "0" * 63, "0" * 65, "g" * 64, "0" * 32, None, 12345):
            with self.subTest(value=value), self.assertRaises(SourceError):
                require_digest(value)

    def test_a_digest_is_accepted_case_insensitively_and_normalised(self):
        self.assertEqual(require_digest("A" * 64), "a" * 64)

    def test_an_abbreviated_commit_is_refused(self):
        """`git rev-parse --short` output is ambiguous, so it cannot be a pin."""
        for value in ("abc1234", "a" * 39, "a" * 41, "z" * 40, ""):
            with self.subTest(value=value), self.assertRaises(SourceError):
                require_commit(value)

    def test_full_sha1_and_sha256_commits_are_accepted(self):
        self.assertTrue(is_full_commit(require_commit("A" * 40)))
        self.assertTrue(is_full_commit(require_commit("b" * 64)))


class TestARepositoryPathCannotEscape(unittest.TestCase):
    """The path is caller-supplied and becomes a filesystem name, so traversal is refused."""

    def test_traversal_absolute_and_odd_paths_are_refused(self):
        for value in (
            "../secrets.trig",
            "dist/../../secrets.trig",
            "/etc/passwd",
            "./model.trig",
            "dist//model.trig",
            "dist/",
            "",
            "dist\\model.trig",
            None,
        ):
            with self.subTest(value=value), self.assertRaises(SourceError):
                validate_repository_path(value)

    def test_a_normalised_relative_path_is_accepted(self):
        self.assertEqual(validate_repository_path("dist/model.trig"), "dist/model.trig")


class TestFormatIsResolvedNotGuessed(unittest.TestCase):
    def test_the_extension_decides_when_nothing_is_declared(self):
        self.assertEqual(normalize_format(None, "model.trig"), "trig")
        self.assertEqual(normalize_format(None, "model.ttl"), "turtle")

    def test_an_unknown_extension_is_refused_rather_than_assumed(self):
        with self.assertRaises(SourceError):
            normalize_format(None, "model.xlsx")

    def test_an_explicit_format_overrides_the_extension(self):
        self.assertEqual(normalize_format("turtle", "model.trig"), "turtle")

    def test_an_unsupported_explicit_format_is_refused(self):
        with self.assertRaises(SourceError):
            normalize_format("csv", "model.trig")


class TestPolicyRefusesWhatItCannotHonour(unittest.TestCase):
    """A misspelled policy key must fail loudly, not silently leave a bound at its default."""

    def setUp(self):
        self.cache = self.enterContext(_tmp())

    def test_an_unknown_key_is_refused(self):
        """The dangerous typo: `allow_private_networks` would read as no opt-in at all."""
        with self.assertRaises(SourceError) as caught:
            Policy.from_mapping({"cache_dir": self.cache, "allow_private_networks": True})
        self.assertIn("unknown", str(caught.exception).lower())

    def test_a_non_boolean_flag_is_refused(self):
        """`"false"` is truthy in Python, so accepting a string would invert the intent."""
        for value in ("false", 0, 1, None, []):
            with self.subTest(value=value), self.assertRaises(SourceError):
                Policy.from_mapping({"cache_dir": self.cache, "allow_private_network": value})

    def test_a_non_positive_or_non_integer_bound_is_refused(self):
        for key in ("max_bytes", "timeout_ms"):
            for value in (0, -1, "100", 1.5, None):
                with self.subTest(key=key, value=value), self.assertRaises(SourceError):
                    Policy.from_mapping({"cache_dir": self.cache, key: value})

    def test_allowed_hosts_must_be_a_string_array(self):
        for value in ("example.org", [""], [None], [1], {}):
            with self.subTest(value=value), self.assertRaises(SourceError):
                Policy.from_mapping({"cache_dir": self.cache, "allowed_hosts": value})

    def test_the_contract_reports_the_bounds_it_will_apply(self):
        """What `doctor` and the manifests publish, so an operator can check the policy."""
        contract = policy(
            cache_dir=self.cache, allowed_hosts=["b.example.org", "a.example.org"]
        ).public_contract()
        self.assertEqual(contract["allowed_hosts"], ["a.example.org", "b.example.org"])
        self.assertFalse(contract["allow_private_network"])


class TestTheGitLabHandoffValidatesBeforeItAsksForAnything(unittest.TestCase):
    """Phase one of the two-phase handoff. It contacts nothing — it emits a request.

    No MCP client exists here by design: the agent calls its own approved server, and this
    owner supplies the request and later verifies the bytes. So the only thing phase one can
    get wrong is accepting a request it should have refused.
    """

    def setUp(self):
        self.policy = policy(cache_dir=self.enterContext(_tmp()))

    def valid(self, **overrides) -> dict:
        source = {
            "kind": "gitlab-mcp",
            "project_id": "group/models",
            "revision": "a" * 40,
            "path": "dist/model.trig",
            "format": "trig",
            "expected_sha256": hashlib.sha256(TRIG).hexdigest(),
            "server_id": "approved-gitlab",
        }
        source.update(overrides)
        return source

    def test_an_unknown_field_is_refused(self):
        """Silently ignoring a field means silently ignoring what the caller asked for."""
        with self.assertRaises(SourceError) as caught:
            request_gitlab(self.valid(token="hunter2"), self.policy)
        self.assertIn("unknown", str(caught.exception).lower())

    def test_a_url_as_project_id_is_refused(self):
        """A project path is not a URL; accepting one would pick the server for the agent."""
        with self.assertRaises(SourceError) as caught:
            request_gitlab(self.valid(project_id="https://gitlab.example.org/group/models"),
                           self.policy)
        self.assertIn("not a URL", str(caught.exception))

    def test_a_missing_or_malformed_digest_is_refused(self):
        """The digest is the only thing that will verify the agent's bytes, so it is required."""
        for value in (None, "", "abc"):
            with self.subTest(value=value), self.assertRaises(SourceError):
                request_gitlab(self.valid(expected_sha256=value), self.policy)

    def test_a_traversing_path_is_refused(self):
        with self.assertRaises(SourceError):
            request_gitlab(self.valid(path="../../etc/passwd"), self.policy)

    def test_a_valid_request_names_what_the_agent_must_fetch(self):
        """The response is an instruction to the caller, not a fetch."""
        result = request_gitlab(self.valid(), self.policy)
        rendered = repr(result)
        self.assertIn("group/models", rendered)
        self.assertIn("dist/model.trig", rendered)
        self.assertIn("approved-gitlab", rendered)


def _tmp():
    """A scratch directory as a context manager, for ``enterContext``."""
    import tempfile

    return tempfile.TemporaryDirectory()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
