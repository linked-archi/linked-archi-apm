"""Store modes: what each one promises, and what invalidates a cached store.

These tests are about the correctness of the caching decision, not about speed. A
cache that returns a stale store answers a question about a dataset that no longer
exists, and that is the one failure here that produces a wrong answer rather than a
slow one - so the key and the invalidation paths get the most attention.

``memory`` is the default and no test needs to opt out of caching, so nothing here
writes to the user's real cache except through an explicitly redirected root.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests import support


class StoreCacheTestCase(unittest.TestCase):
    """Isolate the cache into a temporary directory for the duration of one test."""

    def setUp(self) -> None:
        support.requires_pyoxigraph(self)
        from linked_archi_connect.adapters import store_cache

        self.store_cache = store_cache
        self._tmp = TemporaryDirectory()
        self.cache = Path(self._tmp.name) / "stores"
        self._saved = {
            name: os.environ.get(name)
            for name in (
                store_cache.ENV_MODE,
                store_cache.ENV_CACHE,
                store_cache.ENV_KEEP,
                store_cache.ENV_MAX_BYTES,
            )
        }
        os.environ[store_cache.ENV_CACHE] = str(self.cache)
        for name in (store_cache.ENV_MODE, store_cache.ENV_KEEP,
                     store_cache.ENV_MAX_BYTES):
            os.environ.pop(name, None)

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self._tmp.cleanup()

    def sources(self, *paths: Path):
        from linked_archi_connect.adapters.local import LocalAdapter

        return LocalAdapter._validate(list(paths or (support.BASE,)))

    def store_dirs(self) -> list[Path]:
        if not self.cache.is_dir():
            return []
        return sorted(
            entry for entry in self.cache.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        )


class TestModeResolution(StoreCacheTestCase):
    def test_memory_is_the_default(self):
        """Caching is opt-in: it makes analytical queries slower, so it cannot be default."""
        self.assertEqual(self.store_cache.resolve_mode(), "memory")
        self.assertEqual(self.store_cache.DEFAULT_MODE, "memory")

    def test_the_environment_selects_a_mode(self):
        os.environ[self.store_cache.ENV_MODE] = "cached"
        self.assertEqual(self.store_cache.resolve_mode(), "cached")

    def test_an_explicit_argument_beats_the_environment(self):
        """An in-process caller has a reason; the environment is only a default."""
        os.environ[self.store_cache.ENV_MODE] = "cached"
        self.assertEqual(self.store_cache.resolve_mode("memory"), "memory")

    def test_an_unknown_mode_is_refused_rather_than_defaulted(self):
        """A typo must not look like a mode that had no effect."""
        with self.assertRaises(self.store_cache.StoreCacheError) as caught:
            self.store_cache.resolve_mode("cahced")
        self.assertIn("cahced", str(caught.exception))
        for mode in self.store_cache.MODES:
            self.assertIn(mode, str(caught.exception))

    def test_a_mode_removed_from_the_set_is_refused_too(self):
        """'auto' existed during development and was withdrawn on the measurements.

        It has to fail loudly rather than be quietly accepted, because anything that
        still passes it is asking for a decision this module deliberately declines to
        make on a caller's behalf.
        """
        with self.assertRaises(self.store_cache.StoreCacheError):
            self.store_cache.resolve_mode("auto")

    def test_blank_settings_fall_back_to_the_default(self):
        os.environ[self.store_cache.ENV_MODE] = "   "
        self.assertEqual(self.store_cache.resolve_mode(), "memory")

    def test_open_adapter_refuses_a_bad_mode_even_with_an_endpoint(self):
        """Validated at the funnel, so a bad option is never silently ignored."""
        from linked_archi_connect.adapters import AdapterError, open_adapter

        with self.assertRaises(AdapterError):
            open_adapter(endpoint="https://example.org/sparql", store="nonsense")


class TestCacheKey(StoreCacheTestCase):
    def test_the_same_inputs_give_the_same_key(self):
        sources = self.sources()
        self.assertEqual(
            self.store_cache.compute_key(sources, False, "0.5.10"),
            self.store_cache.compute_key(sources, False, "0.5.10"),
        )

    def test_lenient_changes_the_key(self):
        """It changes what survives parsing, so it changes what the store contains."""
        sources = self.sources()
        self.assertNotEqual(
            self.store_cache.compute_key(sources, False, "0.5.10"),
            self.store_cache.compute_key(sources, True, "0.5.10"),
        )

    def test_the_pyoxigraph_version_changes_the_key(self):
        """The on-disk format belongs to the library, not to us."""
        sources = self.sources()
        self.assertNotEqual(
            self.store_cache.compute_key(sources, False, "0.5.10"),
            self.store_cache.compute_key(sources, False, "0.6.0"),
        )

    def test_a_changed_mtime_changes_the_key(self):
        """This is the invalidation that matters: a refreshed dataset must rebuild."""
        copy = Path(self._tmp.name) / "data.trig"
        copy.write_bytes(support.BASE.read_bytes())
        before = self.store_cache.compute_key(self.sources(copy), False, "0.5.10")
        os.utime(copy, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
        after = self.store_cache.compute_key(self.sources(copy), False, "0.5.10")
        self.assertNotEqual(before, after)

    def test_a_changed_size_changes_the_key(self):
        copy = Path(self._tmp.name) / "data.trig"
        copy.write_bytes(support.BASE.read_bytes())
        before = self.store_cache.compute_key(self.sources(copy), False, "0.5.10")
        with copy.open("ab") as handle:
            handle.write(b"\n# a trailing comment\n")
        after = self.store_cache.compute_key(self.sources(copy), False, "0.5.10")
        self.assertNotEqual(before, after)

    def test_file_order_is_part_of_the_key(self):
        self.assertNotEqual(
            self.store_cache.compute_key(
                self.sources(support.BASE, support.AUGMENTED), False, "0.5.10"
            ),
            self.store_cache.compute_key(
                self.sources(support.AUGMENTED, support.BASE), False, "0.5.10"
            ),
        )


class TestMemoryMode(StoreCacheTestCase):
    def test_memory_never_touches_the_cache(self):
        loaded = self.store_cache.load(self.sources(), lenient=False, mode="memory")
        self.assertEqual(loaded.origin, "memory")
        self.assertIsNone(loaded.store_path)
        self.assertEqual(self.store_dirs(), [])

    def test_memory_is_what_you_get_without_asking(self):
        loaded = self.store_cache.load(self.sources(), lenient=False)
        self.assertEqual(loaded.origin, "memory")
        self.assertEqual(self.store_dirs(), [])


class TestCachedMode(StoreCacheTestCase):
    def test_it_builds_then_reuses(self):
        first = self.store_cache.load(self.sources(), lenient=False, mode="cached")
        self.assertEqual(first.origin, "cache-built")
        self.assertEqual(len(self.store_dirs()), 1)

        second = self.store_cache.load(self.sources(), lenient=False, mode="cached")
        self.assertIn(second.origin, {"cache-hit-rw", "cache-hit-ro"})
        self.assertEqual(second.quads_loaded, first.quads_loaded)
        self.assertEqual(second.graph_names, first.graph_names)

    def test_it_refuses_rather_than_falling_back(self):
        """So a caller told they got a cached store did in fact get one.

        The cache root is made unusable by putting a plain file where its parent
        directory would go, not by clearing a write bit. Permissions are the obvious
        way and the wrong one: root ignores a missing write bit, and CI runs this
        suite as root inside `python:3.12-slim`, so the mkdir would succeed and the
        refusal under test would never fire - the assertion would hold on a developer
        machine and fail only in the container. ENOTDIR is not a permission check, so
        it blocks every user alike.
        """
        blocked = Path(self._tmp.name) / "not-a-directory"
        blocked.write_text("", encoding="utf-8")
        os.environ[self.store_cache.ENV_CACHE] = str(blocked / "stores")
        with self.assertRaises(self.store_cache.StoreCacheError) as caught:
            self.store_cache.load(self.sources(), lenient=False, mode="cached")
        # A refusal that does not say how to proceed is just an obstacle.
        self.assertIn("memory", str(caught.exception))
        # And a refusal that wrote something anyway would not be one.
        self.assertTrue(blocked.is_file())


class TestReadonlyMode(StoreCacheTestCase):
    def test_it_refuses_when_nothing_is_cached(self):
        with self.assertRaises(self.store_cache.StoreCacheError) as caught:
            self.store_cache.load(self.sources(), lenient=False, mode="readonly")
        message = str(caught.exception)
        self.assertIn("readonly", message)
        self.assertIn("cached", message)

    def test_it_opens_a_warmed_cache_read_only(self):
        self.store_cache.load(self.sources(), lenient=False, mode="cached")
        loaded = self.store_cache.load(self.sources(), lenient=False, mode="readonly")
        self.assertEqual(loaded.origin, "cache-hit-ro")


class TestRefreshMode(StoreCacheTestCase):
    def test_it_rebuilds_over_an_existing_store(self):
        first = self.store_cache.load(self.sources(), lenient=False, mode="cached")
        self.assertEqual(first.origin, "cache-built")
        again = self.store_cache.load(self.sources(), lenient=False, mode="refresh")
        self.assertEqual(again.origin, "cache-built")
        self.assertEqual(again.quads_loaded, first.quads_loaded)


class TestSidecar(StoreCacheTestCase):
    def test_a_hit_reports_the_same_totals_as_the_build(self):
        built = self.store_cache.load(self.sources(), lenient=False, mode="cached")
        hit = self.store_cache.load(self.sources(), lenient=False, mode="cached")
        self.assertEqual(hit.quads_loaded, built.quads_loaded)
        self.assertEqual(hit.graph_names, built.graph_names)
        self.assertEqual(hit.flattened_inputs, built.flattened_inputs)

    def test_a_sidecar_that_does_not_match_is_a_miss_not_a_guess(self):
        """Trusting a sidecar that does not describe the store reports wrong totals."""
        self.store_cache.load(self.sources(), lenient=False, mode="cached")
        [store_dir] = self.store_dirs()
        meta_path = store_dir / self.store_cache.META_FILENAME
        meta = json.loads(meta_path.read_text())
        meta["key"] = "0" * 64
        meta_path.write_text(json.dumps(meta))
        rebuilt = self.store_cache.load(self.sources(), lenient=False, mode="cached")
        self.assertEqual(rebuilt.origin, "cache-built")

    def test_a_corrupt_sidecar_is_a_miss(self):
        self.store_cache.load(self.sources(), lenient=False, mode="cached")
        [store_dir] = self.store_dirs()
        (store_dir / self.store_cache.META_FILENAME).write_text("{ not json")
        rebuilt = self.store_cache.load(self.sources(), lenient=False, mode="cached")
        self.assertEqual(rebuilt.origin, "cache-built")

    def test_an_unknown_sidecar_version_is_a_miss(self):
        self.store_cache.load(self.sources(), lenient=False, mode="cached")
        [store_dir] = self.store_dirs()
        meta_path = store_dir / self.store_cache.META_FILENAME
        meta = json.loads(meta_path.read_text())
        meta["schema_version"] = self.store_cache.META_SCHEMA_VERSION + 1
        meta_path.write_text(json.dumps(meta))
        rebuilt = self.store_cache.load(self.sources(), lenient=False, mode="cached")
        self.assertEqual(rebuilt.origin, "cache-built")


class TestEviction(StoreCacheTestCase):
    def build_several(self, count: int) -> None:
        """Build ``count`` distinct stores by giving each its own copy of a fixture."""
        for index in range(count):
            copy = Path(self._tmp.name) / f"data-{index}.trig"
            copy.write_bytes(support.BASE.read_bytes())
            self.store_cache.load(self.sources(copy), lenient=False, mode="cached")

    def test_the_count_bound_holds(self):
        """The key moves on every dataset refresh, so growth has to be bounded."""
        os.environ[self.store_cache.ENV_KEEP] = "1"
        self.build_several(3)
        self.assertEqual(len(self.store_dirs()), 1)

    def test_the_byte_budget_holds_independently_of_the_count(self):
        """A count is not a budget: store size tracks dataset size, a count does not."""
        os.environ[self.store_cache.ENV_KEEP] = "99"
        self.build_several(2)
        self.assertEqual(len(self.store_dirs()), 2)
        newest = max(self.store_dirs(), key=lambda entry: entry.stat().st_mtime)
        self.store_cache.evict(99, protect=newest, budget=1)
        self.assertEqual(self.store_dirs(), [newest])

    def test_the_protected_store_survives_a_budget_it_cannot_meet(self):
        """Evicting what was just built would mean rebuilding it forever."""
        self.store_cache.load(self.sources(), lenient=False, mode="cached")
        [only] = self.store_dirs()
        self.store_cache.evict(1, protect=only, budget=1)
        self.assertEqual(self.store_dirs(), [only])

    def test_both_bounds_off_leaves_the_cache_alone(self):
        """'Keep nothing' is what memory mode is for; cleanup must not empty the cache."""
        self.store_cache.load(self.sources(), lenient=False, mode="cached")
        self.store_cache.evict(0, budget=0)
        self.assertEqual(len(self.store_dirs()), 1)

    def test_malformed_settings_fall_back_to_the_defaults(self):
        """A housekeeping knob must not be able to fail a query."""
        os.environ[self.store_cache.ENV_KEEP] = "lots"
        os.environ[self.store_cache.ENV_MAX_BYTES] = "plenty"
        self.assertEqual(self.store_cache.keep_count(), self.store_cache.DEFAULT_KEEP)
        self.assertEqual(self.store_cache.max_bytes(), self.store_cache.DEFAULT_MAX_BYTES)


class TestAdapterIntegration(StoreCacheTestCase):
    def test_a_cached_adapter_answers_the_same_as_an_uncached_one(self):
        """The point of a mode is that nothing else about the answer changes."""
        from linked_archi_connect.adapters import open_adapter

        query = "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }"
        memory = open_adapter(data=[support.BASE], store="memory")
        cached = open_adapter(data=[support.BASE], store="cached")
        self.assertEqual(memory.execute(query).rows, cached.execute(query).rows)
        self.assertEqual(memory.quads_loaded, cached.quads_loaded)
        self.assertEqual(memory.graph_names, cached.graph_names)
        self.assertEqual(memory.dataset_id, cached.dataset_id)
        self.assertEqual(memory.named_graphs_present, cached.named_graphs_present)

    def test_the_adapter_reports_where_its_store_came_from(self):
        """A cache that is silently inactive is worse than no cache."""
        from linked_archi_connect.adapters import open_adapter

        described = open_adapter(data=[support.BASE], store="cached").describe()
        self.assertIn("store:", described)
        self.assertIn("cache:", described)

    def test_memory_mode_says_so_without_naming_a_cache(self):
        from linked_archi_connect.adapters import open_adapter

        described = open_adapter(data=[support.BASE], store="memory").describe()
        self.assertIn("parsed into memory", described)
        self.assertNotIn("cache:", described)

    def test_load_ms_reaches_the_raw_result(self):
        """The field whose absence hid a 2.5 s cost under a 5 ms query."""
        from linked_archi_connect.adapters import open_adapter

        adapter = open_adapter(data=[support.BASE], store="memory")
        raw = adapter.execute("SELECT ?s WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 1")
        self.assertIn("load_ms", raw.as_contract())
        self.assertGreaterEqual(raw.load_ms, 0)

    def test_validation_errors_do_not_depend_on_the_mode(self):
        """A bad path must fail the same way whether or not a store exists."""
        from linked_archi_connect.adapters import AdapterError, open_adapter

        for mode in ("memory", "cached", "readonly"):
            with self.subTest(mode=mode):
                with self.assertRaises(AdapterError):
                    open_adapter(
                        data=[support.FIXTURES / "does-not-exist.trig"], store=mode
                    )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestBatchLoadAttribution(StoreCacheTestCase):
    """One parse must read as one parse, whatever the batch size.

    ``_decorate`` stamps adapter state onto every result, so before this was handled a
    five-query batch reported five full loads. That turns the one number proving the
    batch worked into the number denying it.
    """

    def test_only_the_first_result_carries_the_load(self):
        from linked_archi_connect.adapters import open_adapter

        adapter = open_adapter(data=[support.BASE], store="memory")
        results = adapter.execute_many([
            "SELECT ?s WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 1",
            "SELECT ?p WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 1",
            "ASK { GRAPH ?g { ?s ?p ?o } }",
        ])
        self.assertEqual(len(results), 3)
        self.assertEqual([raw.load_ms for raw in results[1:]], [0, 0])
        self.assertGreaterEqual(results[0].load_ms, 0)

    def test_a_single_execute_still_reports_its_load(self):
        """execute() routes through execute_many, so it must not lose the load."""
        from linked_archi_connect.adapters import open_adapter

        adapter = open_adapter(data=[support.BASE], store="memory")
        raw = adapter.execute("ASK { GRAPH ?g { ?s ?p ?o } }")
        self.assertEqual(raw.load_ms, adapter.load_ms)

    def test_the_batch_totals_do_not_double_count(self):
        """Summing load_ms across a batch must equal one load, not N."""
        from linked_archi_connect.adapters import open_adapter

        adapter = open_adapter(data=[support.BASE], store="memory")
        results = adapter.execute_many(["ASK { ?s ?p ?o }"] * 4)
        self.assertEqual(sum(raw.load_ms for raw in results), adapter.load_ms)


class TestBatchManifest(unittest.TestCase):
    """A manifest is written once and run repeatedly, so it fails closed."""

    def setUp(self) -> None:
        from linked_archi_query import cli as query_cli

        self.cli = query_cli
        self._tmp = TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def manifest(self, text: str) -> str:
        path = Path(self._tmp.name) / "batch.json"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_a_valid_manifest_normalises_every_entry(self):
        path = self.manifest(json.dumps({
            "schema_version": 1,
            "queries": [
                {"template": "core/models"},
                {"id": "mine", "file": "q.rq", "set": {"LIMIT": "5"}, "out": "/tmp/x.json"},
            ],
        }))
        entries = self.cli._batch_manifest(path)
        self.assertEqual(len(entries), 2)
        # An id defaults to something a human can match against the summary lines.
        self.assertEqual(entries[0]["id"], "core/models")
        self.assertEqual(entries[1]["id"], "mine")
        self.assertEqual(entries[1]["set"], {"LIMIT": "5"})
        self.assertEqual(entries[1]["out"], "/tmp/x.json")

    def test_an_unknown_schema_version_is_refused(self):
        path = self.manifest('{"schema_version": 2, "queries": [{"template": "a"}]}')
        with self.assertRaises(self.cli.RenderError):
            self.cli._batch_manifest(path)

    def test_an_empty_queries_array_is_refused(self):
        path = self.manifest('{"schema_version": 1, "queries": []}')
        with self.assertRaises(self.cli.RenderError):
            self.cli._batch_manifest(path)

    def test_two_sources_in_one_entry_are_refused(self):
        """template and file together is ambiguous, so it is not silently resolved."""
        path = self.manifest(
            '{"schema_version": 1, "queries": [{"template": "a", "file": "b"}]}'
        )
        with self.assertRaises(self.cli.RenderError) as caught:
            self.cli._batch_manifest(path)
        self.assertIn("exactly one", str(caught.exception))

    def test_no_source_in_an_entry_is_refused(self):
        path = self.manifest('{"schema_version": 1, "queries": [{"id": "x"}]}')
        with self.assertRaises(self.cli.RenderError):
            self.cli._batch_manifest(path)

    def test_an_unknown_field_is_refused_by_name(self):
        """A misspelled key must not read as a setting that had no effect."""
        path = self.manifest(
            '{"schema_version": 1, "queries": [{"template": "a", "outt": "x"}]}'
        )
        with self.assertRaises(self.cli.RenderError) as caught:
            self.cli._batch_manifest(path)
        self.assertIn("outt", str(caught.exception))

    def test_invalid_json_names_the_file(self):
        path = self.manifest("{ not json")
        with self.assertRaises(self.cli.RenderError) as caught:
            self.cli._batch_manifest(path)
        self.assertIn(path, str(caught.exception))

    def test_a_missing_manifest_names_the_file(self):
        with self.assertRaises(self.cli.RenderError) as caught:
            self.cli._batch_manifest(str(Path(self._tmp.name) / "absent.json"))
        self.assertIn("absent.json", str(caught.exception))
