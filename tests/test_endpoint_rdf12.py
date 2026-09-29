"""HTTP term fidelity and opt-in capability discovery, without a live endpoint."""

from __future__ import annotations

import io
import json
import subprocess
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
from unittest import mock

import support

from linked_archi_connect import cli as connect_cli
from linked_archi_connect.adapters.base import AdapterError, RawResult
from linked_archi_connect.adapters.endpoint import (
    EndpointAdapter, EndpointResponseError, _TRIPLE_TERM_PROBE,
)
from linked_archi_profile import cli as profile_cli


def iri(value: str) -> dict:
    return {"type": "uri", "value": value}


def triple(object_term: dict | None = None) -> dict:
    return {
        "type": "triple",
        "value": {
            "subject": iri("urn:linked-archi:probe:subject"),
            "predicate": iri("urn:linked-archi:probe:predicate"),
            "object": object_term or iri("urn:linked-archi:probe:object"),
        },
    }


def result_payload(bindings: list[dict], variables: list[str] | None = None) -> bytes:
    return json.dumps({
        "head": {"vars": variables or list(bindings[0]), "version": "1.2"},
        "results": {"bindings": bindings},
    }).encode()


def probe_payload() -> bytes:
    return result_payload([{
        "term": triple(),
        "subject": iri("urn:linked-archi:probe:subject"),
        "predicate": iri("urn:linked-archi:probe:predicate"),
        "object": iri("urn:linked-archi:probe:object"),
    }])


class TestEndpointTripleTerms(unittest.TestCase):
    def read(self, term: dict) -> RawResult:
        adapter = EndpointAdapter("https://graph.example/query")
        with mock.patch.object(adapter, "_post", return_value=(
            result_payload([{"term": term}]), "application/sparql-results+json",
        )):
            return adapter._execute_raw("SELECT ?term WHERE { ?resource ?predicate ?term }")

    def test_triple_preserves_iris(self):
        result = self.read(triple())
        self.assertEqual(result.rows, [{
            "term": "<<( <urn:linked-archi:probe:subject> "
            "<urn:linked-archi:probe:predicate> <urn:linked-archi:probe:object> )>>",
        }])

    def test_nested_object_triple_is_preserved(self):
        term = triple(triple({"type": "literal", "value": "hello", "xml:lang": "en"}))
        result = self.read(term)
        self.assertIn('"hello"@en )>> )>>', result.rows[0]["term"])

    def test_blank_node_and_escaped_typed_literal_are_preserved(self):
        term = triple({
            "type": "literal", "value": 'line\n"quoted"\\tail', "datatype": "urn:datatype",
        })
        term["value"]["subject"] = {"type": "bnode", "value": "subject"}
        self.assertEqual(self.read(term).rows[0]["term"],
                         '<<( _:subject <urn:linked-archi:probe:predicate> '
                         '"line\\n\\"quoted\\"\\\\tail"^^<urn:datatype> )>>')

    def test_directional_literal_preserves_language_and_direction(self):
        term = {"type": "literal", "value": "مرحبا", "xml:lang": "ar", "its:dir": "rtl"}
        self.assertEqual(self.read(term).rows[0]["term"], '"مرحبا"@ar--rtl')
        self.assertIn('"مرحبا"@ar--rtl', self.read(triple(term)).rows[0]["term"])

    def test_malformed_triples_are_rejected(self):
        cases = [
            {"type": "triple", "value": "not-an-object"},
            {"type": "triple", "value": {}},
            {"type": "triple", "value": triple()["value"], "datatype": "urn:wrong"},
            {"type": [], "value": "invalid"},
        ]
        for position, invalid in (
            ("subject", {"type": "literal", "value": "not a subject"}),
            ("subject", triple()),
            ("predicate", {"type": "bnode", "value": "not-a-predicate"}),
            ("predicate", triple()),
            ("object", None),
            ("object", {"type": "uri", "value": 23}),
        ):
            term = triple()
            term["value"][position] = invalid
            cases.append(term)
        extra_part = triple()
        extra_part["value"]["graph"] = iri("urn:graph")
        cases.append(extra_part)
        for term in cases:
            with self.subTest(term=term), self.assertRaisesRegex(AdapterError, "SELECT binding"):
                self.read(term)

    def test_malformed_directional_literals_are_rejected(self):
        cases = [
            {"type": "literal", "value": "hello", "its:dir": "ltr"},
            {"type": "literal", "value": "hello", "xml:lang": "en", "its:dir": "up"},
            {"type": "literal", "value": "hello", "xml:lang": "en", "its:dir": []},
        ]
        for term in cases:
            with self.subTest(term=term), self.assertRaisesRegex(AdapterError, "SELECT binding"):
                self.read(term)

    def test_excessive_triple_nesting_is_rejected_cleanly(self):
        term = triple()
        for _depth in range(65):
            term = triple(term)
        with self.assertRaisesRegex(AdapterError, "SELECT binding"):
            self.read(term)


class TestEndpointProtocol(unittest.TestCase):
    def test_versioned_accept_keeps_legacy_fallback_and_query_version_is_optional(self):
        headers = Message()
        headers["Content-Type"] = "application/sparql-results+json; version=1.2"
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.headers = headers
        response.read.return_value = b'{"boolean":true}'
        adapter = EndpointAdapter("https://graph.example/query")
        with mock.patch("urllib.request.urlopen", return_value=response) as opened:
            adapter._post("ASK {}", None)
            request = opened.call_args.args[0]
            self.assertEqual(urllib.parse.parse_qs(request.data.decode()), {"query": ["ASK {}"]})
            self.assertIn("application/sparql-results+json;version=1.2", request.get_header("Accept"))
            self.assertIn("application/sparql-results+json;q=", request.get_header("Accept"))
            adapter._post(_TRIPLE_TERM_PROBE, None)
            request = opened.call_args.args[0]
            self.assertEqual(urllib.parse.parse_qs(request.data.decode())["version"], ["1.2"])
            for query in (
                "ASK { FILTER('<<(' = '<<(') }",
                "ASK {} # <<( not a term",
                "SELECT (<<( <urn:subject> <urn:predicate> <urn:object> )>> AS ?term) {}",
            ):
                adapter._post(query, None)
                request = opened.call_args.args[0]
                self.assertEqual(urllib.parse.parse_qs(request.data.decode()), {"query": [query]})

    def test_http_status_survives_transport_error(self):
        error = urllib.error.HTTPError("https://graph.example/query", 400, "parse", {}, io.BytesIO(b"parse"))
        adapter = EndpointAdapter("https://graph.example/query")
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(EndpointResponseError) as caught:
                adapter._post("ASK {}", None)
        self.assertEqual(caught.exception.status_code, 400)
        error.close()


class TestExplicitEndpointProbe(unittest.TestCase):
    def setUp(self):
        self.adapter = EndpointAdapter("https://graph.example/query")

    def test_constructor_and_ordinary_execution_never_probe(self):
        with mock.patch.object(self.adapter, "_post", return_value=(
            b'{"boolean":true}', "application/sparql-results+json",
        )) as post:
            self.assertFalse(self.adapter.sparql_12)
            self.adapter.execute("ASK {}")
            post.assert_called_once_with("ASK {}", None)
            self.assertFalse(self.adapter.sparql_12)

    def test_structured_triple_result_alone_does_not_advertise_syntax_support(self):
        with mock.patch.object(self.adapter, "_post", return_value=(
            result_payload([{"term": triple()}]), "application/sparql-results+json",
        )):
            self.adapter._execute_raw("SELECT ?term WHERE { ?resource ?predicate ?term }")
        self.assertFalse(self.adapter.sparql_12)

    def test_known_answer_probe_verifies_only_after_query_owner_lint(self):
        with mock.patch.object(self.adapter, "_post", return_value=(
            probe_payload(), "application/sparql-results+json",
        )) as post, mock.patch(
            "linked_archi_connect.adapters.base.validate_queries_readonly"
        ) as lint:
            self.assertTrue(self.adapter.probe_sparql_12())
            self.assertEqual(lint.call_args.args[0], [post.call_args.args[0]])
            self.assertIn("<<( ?nestedSubject ?nestedPredicate ?nestedObject )>>", post.call_args.args[0])
            self.assertIn("FILTER(false)", post.call_args.args[0])
            post.assert_called_once()
        self.assertTrue(self.adapter.sparql_12)
        self.assertIn("probe: verified", self.adapter.describe())

    def test_probe_refusal_never_reaches_endpoint(self):
        with mock.patch("linked_archi_connect.adapters.base.validate_queries_readonly",
                        side_effect=AdapterError("refused")), mock.patch.object(self.adapter, "_post") as post:
            with self.assertRaisesRegex(AdapterError, "refused"):
                self.adapter.probe_sparql_12()
            post.assert_not_called()

    def test_literal_cannot_impersonate_a_structured_triple(self):
        document = json.loads(probe_payload())
        document["results"]["bindings"][0]["term"] = {
            "type": "literal", "value": "<<( <urn:linked-archi:probe:subject> "
            "<urn:linked-archi:probe:predicate> <urn:linked-archi:probe:object> )>>",
        }
        with mock.patch.object(self.adapter, "_post", return_value=(
            json.dumps(document).encode(), "application/sparql-results+json",
        )):
            self.assertFalse(self.adapter.probe_sparql_12())

    def test_unsupported_syntax_returns_false_and_clears_previous_claim(self):
        for status_code in (400, 406, 415, 422):
            with self.subTest(status_code=status_code), mock.patch.object(
                self.adapter, "_post", side_effect=EndpointResponseError(status_code, "unsupported"),
            ):
                self.adapter.sparql_12 = True
                self.assertFalse(self.adapter.probe_sparql_12())
                self.assertFalse(self.adapter.sparql_12)

    def test_wrong_or_empty_answers_do_not_verify(self):
        for payload in (
            b'{"boolean":true}',
            b'{"head":{"vars":["term"]},"results":{"bindings":[]}}',
            probe_payload().replace(b"probe:object", b"probe:wrong"),
        ):
            with self.subTest(payload=payload), mock.patch.object(self.adapter, "_post", return_value=(
                payload, "application/sparql-results+json",
            )):
                self.assertFalse(self.adapter.probe_sparql_12())

    def test_auth_network_and_malformed_response_fail_instead_of_looking_unsupported(self):
        for error in (
            EndpointResponseError(401, "auth"), EndpointResponseError(500, "server"),
            AdapterError("network"), AdapterError("malformed SELECT binding"),
        ):
            with self.subTest(error=error), mock.patch.object(self.adapter, "_post", side_effect=error):
                with self.assertRaises(AdapterError):
                    self.adapter.probe_sparql_12()


class TestCapabilityContract(unittest.TestCase):
    target = {"endpoint": "https://graph.example/query", "timeout_ms": 2000}
    report = {
        "schema_version": 1, "dataset_id": "https://graph.example/query",
        "triple_terms": True, "description": "triple-term probe: verified",
    }

    def test_public_and_machine_commands_have_identical_json(self):
        for arguments in (
            ["capabilities", "--endpoint", self.target["endpoint"]],
            ["_machine", "capabilities"],
        ):
            with self.subTest(arguments=arguments), mock.patch.object(
                EndpointAdapter, "_post", return_value=(probe_payload(), "application/sparql-results+json"),
            ), mock.patch.object(connect_cli.sys, "stdin", io.StringIO(json.dumps({
                "schema_version": 1, "target": self.target,
            }))), redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(connect_cli.main(arguments), 0)
                report = json.loads(stdout.getvalue())
                self.assertEqual(report["schema_version"], 1)
                self.assertEqual(report["dataset_id"], self.target["endpoint"])
                self.assertIs(report["triple_terms"], True)

    def test_capabilities_refuse_local_data_and_extra_machine_fields_before_open(self):
        requests = [
            {"schema_version": 1, "target": {"data": ["graph.trig"]}},
            {"schema_version": 1, "target": self.target, "query": "DELETE WHERE {}"},
        ]
        for request in requests:
            with self.subTest(request=request), mock.patch.object(
                connect_cli.sys, "stdin", io.StringIO(json.dumps(request)),
            ), mock.patch.object(connect_cli, "_open") as opened, \
                    redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()):
                self.assertEqual(connect_cli.main(["_machine", "capabilities"]), 2)
                self.assertEqual(stdout.getvalue(), "")
                opened.assert_not_called()

    def test_profile_probe_is_explicit_and_once_per_operation(self):
        with mock.patch.object(profile_cli, "_endpoint_capabilities", return_value=self.report) as capability:
            ordinary = profile_cli._ConnectProbe(self.target)
            self.assertFalse(ordinary.sparql_12)
            capability.assert_not_called()
            probe = profile_cli._ConnectProbe(self.target, probe_endpoint=True)
            self.assertTrue(probe.sparql_12)
            capability.assert_called_once_with(self.target)
        raw = RawResult(form="ASK", boolean=True, dataset_id=self.target["endpoint"]).as_contract()
        with mock.patch.object(profile_cli, "_execute_many", return_value=[raw]):
            probe.execute_many(["ASK {}"])
        self.assertIn("explicit endpoint triple-term probe: verified", probe.description)

    def test_profile_requires_matching_dataset_identity(self):
        with mock.patch.object(profile_cli, "_endpoint_capabilities", return_value=self.report):
            probe = profile_cli._ConnectProbe(self.target, probe_endpoint=True)
        raw = RawResult(form="ASK", boolean=True, dataset_id="https://different.example/query").as_contract()
        with mock.patch.object(profile_cli, "_execute_many", return_value=[raw]):
            with self.assertRaisesRegex(profile_cli.CompanionError, "identities disagree"):
                probe.execute_many(["ASK {}"])

    def test_profile_local_target_refuses_endpoint_probe_before_calling_companion(self):
        with mock.patch.object(profile_cli, "_endpoint_capabilities") as capability:
            with self.assertRaisesRegex(profile_cli.CompanionError, "requires --endpoint"):
                profile_cli._ConnectProbe({"data": ["graph.trig"]}, probe_endpoint=True)
            capability.assert_not_called()

    def test_profile_capability_wire_contract_is_strict(self):
        invalid = [
            {**self.report, "schema_version": True},
            {**self.report, "triple_terms": "yes"},
            {**self.report, "dataset_id": ""},
            {**self.report, "description": None},
        ]
        for index, report in enumerate([self.report, *invalid]):
            response = subprocess.CompletedProcess([], 0, stdout=json.dumps(report), stderr="")
            with self.subTest(report=report), mock.patch.object(profile_cli.subprocess, "run", return_value=response) as run:
                if index:
                    with self.assertRaisesRegex(profile_cli.CompanionError, "capability result"):
                        profile_cli._endpoint_capabilities(self.target)
                else:
                    self.assertEqual(profile_cli._endpoint_capabilities(self.target), report)
                    self.assertEqual(run.call_args.args[0][-2:], ["_machine", "capabilities"])
                    self.assertEqual(run.call_args.kwargs["timeout"], 62.0)

    def test_profile_flags_are_accepted_only_for_dataset_operations(self):
        for operation in ("recommend", "verify"):
            arguments = profile_cli.build_parser().parse_args([
                operation, "--endpoint", self.target["endpoint"], "--probe-endpoint",
            ])
            self.assertTrue(arguments.probe_endpoint)


if __name__ == "__main__":
    unittest.main()
