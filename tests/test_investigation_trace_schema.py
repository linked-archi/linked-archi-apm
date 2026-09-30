"""Check the observational trace contract without adding a runtime dependency."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest


try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas/investigation-trace-v1.schema.json")
                    .read_text(encoding="utf-8"))
DIGEST = "a" * 64


def example_trace():
    return {
        "schema_version": 1,
        "scenario_id": "bounded-name-lookup",
        "scenario_contract_sha256": DIGEST,
        "snapshot_manifest_sha256": DIGEST,
        "dataset_sha256": DIGEST,
        "profile_sha256": DIGEST,
        "apm_source_sha256": DIGEST,
        "agent": {"client": "test-client", "model": "test-model", "settings_sha256": DIGEST},
        "prompt_sha256": DIGEST,
        "started_at": "2026-09-30T00:00:00Z",
        "finished_at": "2026-09-30T00:00:01Z",
        "elapsed_ms": 1000,
        "agent_exit_code": 0,
        "events": [{
            "sequence": 1, "offset_ms": 100, "phase": "resolution", "kind": "owner_call",
            "owner": "query", "argv": ["la-query", "query", "run", "core/resolve-element"],
            "exit_code": 0, "wall_ms": 200, "stdout_bytes": 50, "stderr_bytes": 0,
            "visible_bytes": 50, "visible_sha256": DIGEST,
        }],
        "raw_events": {"path": "events.jsonl", "sha256": DIGEST, "bytes": 1000},
        "saved_artifacts": [{"path": "steps/resolve.json", "sha256": DIGEST, "bytes": 500}],
        "final_answer": {"path": "answer.md", "sha256": DIGEST, "bytes": 100},
        "token_usage": {"status": "unmeasured", "reason": "Client telemetry was unavailable"},
    }


class InvestigationTraceSchemaTests(unittest.TestCase):
    def test_trace_is_observational_and_token_usage_cannot_be_estimated(self):
        self.assertEqual(SCHEMA["$id"], "urn:linked-archi:apm:investigation-trace:1")
        self.assertEqual(SCHEMA["properties"]["schema_version"]["const"], 1)
        self.assertIn("events", SCHEMA["required"])
        self.assertIn("token_usage", SCHEMA["required"])
        self.assertNotIn("query", SCHEMA["properties"])

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is not an APM runtime dependency")
    def test_valid_trace_and_all_event_kinds(self):
        Draft202012Validator.check_schema(SCHEMA)
        trace = example_trace()
        trace["events"].extend([
            {
                "sequence": 2, "offset_ms": 350, "phase": "resolution", "kind": "artifact_read",
                "path": "steps/resolve.json", "read_bytes": 500, "visible_bytes": 100,
                "visible_sha256": DIGEST,
            },
            {
                "sequence": 3, "offset_ms": 500, "phase": "answer", "kind": "review",
                "reviewed_events": [1, 2], "outcome": "continue", "summary": "Evidence was inspected",
            },
            {
                "sequence": 4, "offset_ms": None, "phase": "investigation", "kind": "tool_call",
                "command": "jq . steps/resolve.json", "argv": ["jq", ".", "steps/resolve.json"],
                "exit_code": 0, "wall_ms": None,
                "visible_bytes": 10, "visible_sha256": DIGEST,
            },
        ])
        Draft202012Validator(SCHEMA).validate(trace)
        trace["events"][0].update(offset_ms=None, wall_ms=None, stdout_bytes=None, stderr_bytes=None)
        trace["elapsed_ms"] = None
        Draft202012Validator(SCHEMA).validate(trace)
        trace["events"] = []
        trace["final_answer"] = None
        trace["agent_exit_code"] = 1
        Draft202012Validator(SCHEMA).validate(trace)
        trace["token_usage"] = {
            "status": "measured", "source": "client telemetry", "input_tokens": 10,
            "output_tokens": 5, "cached_input_tokens": 2,
        }
        Draft202012Validator(SCHEMA).validate(trace)

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is not an APM runtime dependency")
    def test_estimates_and_unowned_execution_are_rejected(self):
        validator = Draft202012Validator(SCHEMA)
        trace = example_trace()
        for change in (
            lambda document: document["token_usage"].update(status="estimated"),
            lambda document: document["token_usage"].update(input_tokens=100),
            lambda document: document["events"][0].update(owner="benchmark"),
            lambda document: document["events"][0].update(visible_bytes=-1),
            lambda document: document.update(query="SELECT * WHERE {}"),
        ):
            with self.subTest(change=change):
                invalid = copy.deepcopy(trace)
                change(invalid)
                self.assertFalse(validator.is_valid(invalid))


if __name__ == "__main__":
    unittest.main()
