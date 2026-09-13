"""Regression tests for the subprocess and transport ownership boundaries."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import support  # noqa: F401 - installs the three owner script paths

from linked_archi_connect import cli as connect_cli
from linked_archi_connect.adapters import (
    AdapterError, EndpointAdapter, open_adapter,
)
from linked_archi_connect.adapters.base import RawResult
from linked_archi_profile import cli as profile_cli
from linked_archi_profile.profile import load_profile, verify_against_dataset
from linked_archi_query import cli as query_cli


class TestPublicTransportSafety(unittest.TestCase):
    def test_direct_endpoint_update_is_refused_before_http(self):
        adapter = EndpointAdapter("https://graph.example/query")
        with mock.patch.object(adapter, "_post") as post:
            with self.assertRaisesRegex(AdapterError, "SPARQL Update"):
                adapter.execute("DELETE WHERE { ?s ?p ?o }")
        post.assert_not_called()

    def test_mixed_batch_is_fully_refused_before_any_http(self):
        adapter = EndpointAdapter("https://graph.example/query")
        with mock.patch.object(adapter, "_post") as post:
            with self.assertRaisesRegex(AdapterError, "SPARQL Update"):
                adapter.execute_many([
                    "ASK { ?s ?p ?o }",
                    "INSERT DATA { <urn:s> <urn:p> <urn:o> }",
                ])
        post.assert_not_called()

    def test_machine_lints_before_opening_local_data(self):
        request = {
            "schema_version": 1,
            "target": {"data": ["graph.trig"], "timeout_ms": 30000},
            "query": "DELETE WHERE { ?s ?p ?o }",
        }
        with mock.patch.object(
            connect_cli.sys, "stdin", io.StringIO(json.dumps(request))
        ), mock.patch.object(
            connect_cli,
            "validate_queries_readonly",
            side_effect=AdapterError("query refused"),
        ) as validate, mock.patch.object(connect_cli, "_open") as opened:
            with self.assertRaisesRegex(AdapterError, "query refused"):
                connect_cli.cmd_machine_execute(argparse.Namespace())
        validate.assert_called_once_with([request["query"]])
        opened.assert_not_called()

    def test_machine_rejects_malformed_target_before_lint_or_open(self):
        requests = [
            {
                "schema_version": 1,
                "target": {"data": {"fixtures/base.trig": "not-a-list"}},
                "query": "ASK { ?s ?p ?o }",
            },
            {
                "schema_version": 1,
                "target": {"endpoint": "https://", "data": []},
                "query": "ASK { ?s ?p ?o }",
            },
        ]
        for request in requests:
            with self.subTest(target=request["target"]):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with mock.patch.object(
                    connect_cli.sys, "stdin", io.StringIO(json.dumps(request))
                ), mock.patch.object(
                    connect_cli, "validate_queries_readonly"
                ) as validate, mock.patch.object(
                    connect_cli, "_open"
                ) as opened, redirect_stdout(stdout), redirect_stderr(stderr):
                    result = connect_cli.main(["_machine", "execute"])
                self.assertEqual(result, 2)
                self.assertEqual(stdout.getvalue(), "")
                validate.assert_not_called()
                opened.assert_not_called()

    def test_endpoint_rejects_non_boolean_ask_payload(self):
        adapter = EndpointAdapter("https://graph.example/query")
        with mock.patch.object(
            adapter,
            "_post",
            return_value=(
                b'{"boolean":"false"}',
                "application/sparql-results+json",
            ),
        ):
            with self.assertRaisesRegex(AdapterError, "non-boolean ASK"):
                adapter._execute_raw("ASK { ?s ?p ?o }")

    def test_endpoint_rejects_unsupported_and_contradictory_results(self):
        adapter = EndpointAdapter("https://graph.example/query")
        cases = [
            (b"<html>login</html>", "text/html", "media type"),
            (
                b'{"head":{"vars":[]},"results":{"bindings":[]}}',
                "application/json",
                "media type",
            ),
            (
                b'{"head":{},"boolean":false,"results":{"bindings":[]}}',
                "application/sparql-results+json",
                "ambiguous",
            ),
            (
                b'{"head":{"vars":["s"]},"results":{"bindings":'
                b'[{"s":{"type":"bogus","value":"urn:s"}}]}}',
                "application/sparql-results+json",
                "SELECT binding",
            ),
            (
                b'{"head":{"vars":["s"]},"results":{"bindings":'
                b'[{"s":{"type":"uri","value":"urn:s",'
                b'"datatype":"http://www.w3.org/2001/XMLSchema#string"}}]}}',
                "application/sparql-results+json",
                "SELECT binding",
            ),
            (
                b'{"head":{"vars":["s"]},"results":{"bindings":'
                b'[{"s":{"type":"literal","value":"x","xml:lang":"en",'
                b'"datatype":"http://www.w3.org/2001/XMLSchema#string"}}]}}',
                "application/sparql-results+json",
                "SELECT binding",
            ),
            (
                b'{"head":{"vars":["s"]},"results":{"bindings":'
                b'[{"s":{"type":"typed-literal","value":"x"}}]}}',
                "application/sparql-results+json",
                "SELECT binding",
            ),
        ]
        for payload, content_type, message in cases:
            with self.subTest(content_type=content_type, payload=payload):
                with mock.patch.object(
                    adapter, "_post", return_value=(payload, content_type)
                ):
                    with self.assertRaisesRegex(AdapterError, message):
                        adapter._execute_raw("ASK { ?s ?p ?o }")

    def test_endpoint_accepts_coherent_sparql_json_terms(self):
        payload = json.dumps({
            "head": {"vars": ["u", "b", "l", "d", "t"]},
            "results": {"bindings": [{
                "u": {"type": "uri", "value": "urn:u"},
                "b": {"type": "bnode", "value": "b1"},
                "l": {"type": "literal", "value": "hello", "xml:lang": "en"},
                "d": {
                    "type": "literal",
                    "value": "1",
                    "datatype": "http://www.w3.org/2001/XMLSchema#integer",
                },
                "t": {
                    "type": "typed-literal",
                    "value": "1",
                    "datatype": "http://www.w3.org/2001/XMLSchema#integer",
                },
            }]},
        }).encode()
        adapter = EndpointAdapter("https://graph.example/query")
        with mock.patch.object(
            adapter,
            "_post",
            return_value=(payload, "application/sparql-results+json"),
        ):
            result = adapter._execute_raw("SELECT * WHERE { ?s ?p ?o }")
        self.assertEqual(result.form, "SELECT")
        self.assertEqual(result.rows[0]["b"], "_:b1")

    def test_open_adapter_rejects_malformed_endpoint_options(self):
        for endpoint, options in (
            ("https://graph.example/query", {"timeout_ms": True}),
            ("https://graph.example/query", {"timeout_ms": "30000"}),
            ("https://graph.example/query", {"token": 123}),
            ("https://graph.example/query", {"timeot_ms": 1}),
            ("https://", {}),
            ("https://graph.example:bad/query", {}),
            ("https://graph.example:70000/query", {}),
            ("https://bad host:443/query", {}),
        ):
            with self.subTest(endpoint=endpoint, options=options):
                with self.assertRaises(AdapterError):
                    open_adapter(endpoint=endpoint, **options)
        with self.assertRaisesRegex(AdapterError, "unknown adapter options"):
            open_adapter(data=["graph.trig"], surprise=True)

    def test_execution_timeout_override_is_validated_before_lint_or_http(self):
        adapter = EndpointAdapter("https://graph.example/query")
        for timeout_ms in (True, 0, -1, "1000"):
            with self.subTest(timeout_ms=timeout_ms), mock.patch(
                "linked_archi_connect.adapters.base.validate_queries_readonly"
            ) as validate, mock.patch.object(adapter, "_post") as post:
                with self.assertRaisesRegex(AdapterError, "timeout_ms"):
                    adapter.execute("ASK { ?s ?p ?o }", timeout_ms=timeout_ms)
                validate.assert_not_called()
                post.assert_not_called()

    def test_malformed_lint_decision_never_reaches_http(self):
        malformed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "schema_version": 1,
                "decisions": [{"accepted": "yes"}],
            }),
            stderr="",
        )
        adapter = EndpointAdapter("https://graph.example/query")
        with mock.patch(
            "linked_archi_connect.adapters.base.subprocess.run",
            return_value=malformed,
        ), mock.patch.object(adapter, "_post") as post:
            with self.assertRaisesRegex(AdapterError, "malformed decision"):
                adapter.execute("ASK { ?s ?p ?o }")
        post.assert_not_called()


class TestBatchLifetime(unittest.TestCase):
    def test_profile_verification_submits_exactly_one_probe_batch(self):
        class Probe:
            calls = 0
            query_count = 0

            def execute_many(self, queries):
                self.calls += 1
                self.query_count = len(queries)
                results = []
                for query in queries:
                    if "COUNT(DISTINCT ?g)" in query:
                        results.append({
                            "form": "SELECT", "variables": ["n"],
                            "rows": [{"n": "12"}],
                        })
                    else:
                        results.append({"form": "ASK", "boolean": False})
                return results

        probe = Probe()
        verify_against_dataset(load_profile("linked-archi-default"), probe)
        self.assertEqual(probe.calls, 1)
        self.assertGreater(probe.query_count, 40)

    def test_connect_execute_many_opens_target_once(self):
        class FakeAdapter:
            enters = 0
            calls = 0

            def __enter__(self):
                self.enters += 1
                return self

            def __exit__(self, *_exc):
                return None

            def execute_many(self, queries, timeout_ms=None):
                self.calls += 1
                return [RawResult(form="ASK", boolean=True) for _ in queries]

        request = {
            "schema_version": 1,
            "target": {"data": ["graph.trig"], "timeout_ms": 30000},
            "queries": ["ASK { ?s ?p ?o }", "ASK { ?a ?b ?c }"],
        }
        adapter = FakeAdapter()
        with mock.patch.object(connect_cli.sys, "stdin", io.StringIO(json.dumps(request))), \
                mock.patch.object(connect_cli, "_open", return_value=adapter) as opened, \
                redirect_stdout(io.StringIO()):
            result = connect_cli.cmd_machine_execute_many(argparse.Namespace())
        self.assertEqual(result, 0)
        # The whole normalised target, not a subset: every field the contract fills in
        # is asserted, so a new one cannot appear on the wire without a test saying so.
        # `store` is null here because the request omitted it, which means "defer to
        # $LINKED_ARCHI_STORE in this process" rather than "memory".
        opened.assert_called_once_with({
            "data": ["graph.trig"],
            "endpoint": None,
            "timeout_ms": 30000,
            "lenient": False,
            "store": None,
        })
        self.assertEqual(adapter.enters, 1)
        self.assertEqual(adapter.calls, 1)


class TestRawResultContracts(unittest.TestCase):
    def test_query_rejects_partial_result_without_emitting_evidence(self):
        profile = query_cli.ResolvedProfile(
            load_profile("linked-archi-default").resolved_snapshot()
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(query_cli, "_profile", return_value=profile), \
                mock.patch.object(
                    query_cli, "_machine", return_value={"schema_version": 1}
                ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = query_cli.main([
                "query", "literal", "--query", "ASK { ?s ?p ?o }",
                "--data", "graph.trig",
            ])
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("malformed raw result", stderr.getvalue())
        self.assertNotIn("(no rows)", stdout.getvalue())

    def test_both_consumers_reject_non_normalized_select_bindings(self):
        malformed = {
            "schema_version": 1,
            "form": "SELECT",
            "variables": ["s"],
            "rows": [{"unexpected": {"nested": "value"}}],
            "boolean": None,
            "triples": None,
            "elapsed_ms": 1,
            "dataset_id": "fixture.trig",
            "named_graphs_present": True,
            "description": "fixture",
        }
        for validator, error in (
            (query_cli._validate_raw_result, query_cli.CompanionError),
            (profile_cli._validate_raw_result, profile_cli.CompanionError),
        ):
            with self.subTest(validator=validator.__module__):
                with self.assertRaisesRegex(error, "SELECT bindings"):
                    validator(malformed)

    def test_query_rejects_malformed_profile_snapshots_without_output(self):
        valid = load_profile("linked-archi-default").resolved_snapshot()
        malformed = [
            {"schema_version": 1},
            {**valid, "roles": "not-an-object"},
            {
                **valid,
                "roles": {
                    key: value for key, value in valid["roles"].items()
                    if key != "label"
                },
            },
            {
                **valid,
                "roles": {**valid["roles"], "label": ["relative/label"]},
            },
            {
                **valid,
                "roles": {
                    **valid["roles"],
                    "label": ["https://example.org/label with space"],
                },
            },
            {
                **valid,
                "roles": {**valid["roles"], "label": ["https://example.org/a#b#c"]},
            },
            {
                **valid,
                "roles": {**valid["roles"], "label": ["https://example.org/["]},
            },
            {
                **valid,
                "namespaces": {**valid["namespaces"], "bad": "  "},
            },
            {
                **valid,
                "capabilities": {
                    **valid["capabilities"],
                    "direct_rel_triples": "yes",
                },
            },
            {
                **valid,
                "graphs": {
                    **valid["graphs"],
                    "roles": {
                        **valid["graphs"]["roles"],
                        "semantic": "",
                    },
                },
            },
            {
                **valid,
                "graphs": {
                    **valid["graphs"],
                    "layout": "single",
                    "named_graphs": True,
                },
            },
            {
                **valid,
                "graphs": {
                    **valid["graphs"],
                    "layout": "explicit",
                    "roles": {"semantic": "relative/graph"},
                },
            },
            {
                **valid,
                "graphs": {
                    **valid["graphs"],
                    "layout": "explicit",
                    "roles": {"semantic": "https://example.org/graph with space"},
                },
            },
        ]
        commands = [
            ["catalog", "list", "--profile", "custom-profile"],
            ["catalog", "show", "core/inventory", "--profile", "custom-profile"],
        ]
        for snapshot in malformed:
            for command in commands:
                with self.subTest(snapshot=snapshot, command=command):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with mock.patch.object(
                        query_cli, "_machine", return_value=snapshot
                    ), redirect_stdout(stdout), redirect_stderr(stderr):
                        result = query_cli.main(command)
                    self.assertEqual(result, 2)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn("snapshot", stderr.getvalue())

    def test_profile_rejects_partial_batch_result_without_findings(self):
        def malformed_batch(*_args, **kwargs):
            request = json.loads(kwargs["input"])
            return subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({
                    "schema_version": 1,
                    "results": [
                        {"schema_version": 1} for _ in request["queries"]
                    ],
                }),
                stderr="",
            )

        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(
            profile_cli.subprocess, "run", side_effect=malformed_batch
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = profile_cli.main([
                "verify", "--profile", "linked-archi-default",
                "--data", "graph.trig",
            ])
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("malformed raw result", stderr.getvalue())


class TestSchemaVersions(unittest.TestCase):
    def test_machine_commands_reject_boolean_schema_versions_without_output(self):
        cases = [
            (
                query_cli,
                ["_machine", "lint"],
                {"schema_version": True, "query": "ASK { ?s ?p ?o }"},
            ),
            (
                connect_cli,
                ["_machine", "execute"],
                {
                    "schema_version": True,
                    "target": {"data": ["graph.trig"]},
                    "query": "ASK { ?s ?p ?o }",
                },
            ),
            (
                profile_cli,
                ["_machine", "resolve"],
                {"schema_version": True, "profile": "linked-archi-default"},
            ),
        ]
        for module, argv, request in cases:
            with self.subTest(module=module.__name__):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with mock.patch.object(
                    module.sys, "stdin", io.StringIO(json.dumps(request))
                ), redirect_stdout(stdout), redirect_stderr(stderr):
                    result = module.main(argv)
                self.assertEqual(result, 2)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("schema_version=1", stderr.getvalue())

    def test_profile_resolve_rejects_present_falsy_reference_without_output(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        request = {"schema_version": 1, "profile": False}
        with mock.patch.object(
            profile_cli.sys, "stdin", io.StringIO(json.dumps(request))
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = profile_cli.main(["_machine", "resolve"])
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("non-empty string", stderr.getvalue())

    def test_query_rejects_boolean_companion_schema_version(self):
        malformed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"schema_version": True}), stderr="",
        )
        with mock.patch.object(query_cli.subprocess, "run", return_value=malformed):
            with self.assertRaisesRegex(query_cli.CompanionError, "schema_version"):
                query_cli._machine(
                    "linked-archi-profile", "la-profile", "resolve",
                    {"schema_version": 1, "profile": "linked-archi-default"},
                )

    def test_connect_rejects_boolean_lint_schema_version_before_http(self):
        malformed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "schema_version": True,
                "decisions": [{"accepted": True}],
            }),
            stderr="",
        )
        adapter = EndpointAdapter("https://graph.example/query")
        with mock.patch(
            "linked_archi_connect.adapters.base.subprocess.run",
            return_value=malformed,
        ), mock.patch.object(adapter, "_post") as post:
            with self.assertRaisesRegex(AdapterError, "schema_version"):
                adapter.execute("ASK { ?s ?p ?o }")
        post.assert_not_called()

    def test_profile_rejects_boolean_batch_schema_version(self):
        malformed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"schema_version": True, "results": []}),
            stderr="",
        )
        with mock.patch.object(
            profile_cli.subprocess, "run", return_value=malformed
        ):
            with self.assertRaisesRegex(profile_cli.CompanionError, "schema_version"):
                profile_cli._execute_many(
                    {"data": ["graph.trig"], "timeout_ms": 30000},
                    ["ASK { ?s ?p ?o }"],
                )


class TestCompanionTimeouts(unittest.TestCase):
    def test_local_execution_has_a_finite_parent_process_deadline(self):
        """Reversed deliberately. This test used to assert the opposite.

        Both owners used to pass no deadline for local execution, reasoning that
        pyoxigraph has no query timeout so a parent deadline would kill valid long
        queries. The reasoning was fair and the conclusion was wrong: it traded a bounded
        failure for an unbounded one. One `core/dependents-qualified` against a 21 MB
        estate graph ran 49 minutes to 20 GB resident with no message and no ceiling.

        The bound can only live at the process boundary, because the query is a blocking
        call into Rust that nothing inside that process can interrupt. See
        `tests/test_local_bounds.py` for the ceilings themselves.
        """
        request = {
            "schema_version": 1,
            "target": {"data": ["graph.trig"], "timeout_ms": 30000},
            "query": "ASK { ?s ?p ?o }",
        }
        self.assertIsNotNone(query_cli._companion_deadline(request))
        self.assertIsNotNone(profile_cli._companion_deadline(request["target"], 50))

    def test_query_deadline_honors_backend_timeout_and_translates_expiry(self):
        request = {
            "schema_version": 1,
            "target": {"endpoint": "https://graph.example/query", "timeout_ms": 180000},
            "query": "ASK { ?s ?p ?o }",
        }
        with mock.patch.object(
            query_cli.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["la-connect"], 210),
        ) as run:
            with self.assertRaisesRegex(query_cli.CompanionError, "companion deadline"):
                query_cli._machine(
                    "linked-archi-connect", "la-connect", "execute", request
                )
        self.assertGreater(run.call_args.kwargs["timeout"], 180)

    def test_profile_batch_deadline_honors_each_backend_timeout(self):
        target = {"endpoint": "https://graph.example/query", "timeout_ms": 180000}
        queries = ["ASK { ?s ?p ?o }", "ASK { ?a ?b ?c }"]
        with mock.patch.object(
            profile_cli.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["la-connect"], 390),
        ) as run:
            with self.assertRaisesRegex(profile_cli.CompanionError, "companion deadline"):
                profile_cli._execute_many(target, queries)
        self.assertGreater(run.call_args.kwargs["timeout"], 360)


if __name__ == "__main__":
    unittest.main()
