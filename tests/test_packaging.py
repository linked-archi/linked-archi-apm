"""Strict Agent-Skill ownership and isolated-install regression tests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support
import version_sync
from support import ROOT

SKILLS = ROOT / "skills"
SOURCE = SKILLS / "linked-archi-source"
PROFILE = SKILLS / "linked-archi-profile"
CONNECT = SKILLS / "linked-archi-connect"
QUERY = SKILLS / "linked-archi-query"
ANALYSE = SKILLS / "linked-archi-analyse"
VALIDATE = SKILLS / "linked-archi-validate"


def _env(skills_dir: Path | None = None) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "LINKED_ARCHI_APM_HOME", "LINKED_ARCHI_SKILLS_DIR"}
    }
    if skills_dir is not None:
        env["LINKED_ARCHI_SKILLS_DIR"] = str(skills_dir)
    return env


def _run(
    script: Path,
    *args: str,
    cwd: Path,
    skills_dir: Path | None = None,
    stdin: object | None = None,
    extra_env: dict[str, str] | None = None,
):
    env = _env(skills_dir)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=json.dumps(stdin) if stdin is not None else None,
        capture_output=True, text=True, timeout=180, cwd=cwd,
        env=env,
    )


class TestStrictOwnership(unittest.TestCase):
    def test_root_runtime_and_bundler_are_absent(self):
        for path in (ROOT / "lib", ROOT / "profiles", ROOT / "templates", ROOT / "bin" / "bundle.py"):
            self.assertFalse(path.exists(), f"obsolete authoritative path remains: {path}")

    def test_every_skill_is_a_runtime_owner_with_its_own_package(self):
        """All six own a runtime now, and each owns exactly one package.

        Both earlier exceptions are gone and the history is worth keeping: validate was
        instructions-only until it gained in-process SHACL rather than driving an external
        converter, and analyse was instructions-only until A4 gave it planning and bundling.
        Neither gained the thing that actually matters - query execution - and the tests
        below are what hold that line now that "has no Python" no longer can.
        """
        for skill, package in (
            (SOURCE, "linked_archi_source"),
            (PROFILE, "linked_archi_profile"),
            (CONNECT, "linked_archi_connect"),
            (QUERY, "linked_archi_query"),
            (VALIDATE, "linked_archi_validate"),
            (ANALYSE, "linked_archi_analyse"),
        ):
            with self.subTest(skill.name):
                self.assertTrue(list((skill / "scripts" / package).rglob("*.py")))
        offenders = [path.relative_to(ROOT).as_posix() for path in SKILLS.glob("*/assets/**/*.py")]
        self.assertEqual(offenders, [], "assets are data; runtime belongs in scripts/")

    def test_analyse_plans_and_bundles_but_never_executes(self):
        """The line A4 exists to hold: analyse decides and records; query executes.

        If analyse ever opened a store or issued SPARQL, read-only enforcement would have a
        second home and the reproducibility envelope a second author. Greping the runtime is
        crude and exactly right: these names cannot appear by accident.
        """
        runtime = "\n".join(
            path.read_text("utf-8")
            for path in sorted((ANALYSE / "scripts" / "linked_archi_analyse").rglob("*.py"))
        )
        for forbidden in (
            "pyoxigraph",          # no local store
            "urllib",              # no transport of its own
            "http.client",
            "SELECT ",             # no SPARQL, not even a fragment
            "CONSTRUCT ",
            "ASK ",
            "GRAPH ?",
            "validate_readonly",   # read-only policy stays with query
        ):
            self.assertNotIn(
                forbidden, runtime, f"analyse runtime must not reference {forbidden!r}"
            )
        # What it does do: emit commands, and read what query wrote.
        self.assertIn("la-query", runtime)
        self.assertIn("catalog", runtime)

    def test_validate_owns_shacl_and_never_executes_queries(self):
        """Validation is SHACL. Query execution and read-only policy stay query-owned.

        The boundary is worth pinning: if validate ever grew a SPARQL execution path it
        would become a second place where read-only enforcement has to be correct.
        """
        runtime = "\n".join(
            path.read_text("utf-8")
            for path in sorted((VALIDATE / "scripts" / "linked_archi_validate").glob("*.py"))
        )
        for forbidden in ("pyoxigraph", "SELECT ", "sparql", "validate_readonly"):
            self.assertNotIn(
                forbidden, runtime, f"validate runtime must not reference {forbidden!r}"
            )
        self.assertIn("pyshacl", runtime)

    def test_no_python_payload_hash_is_duplicated_across_skills(self):
        owners: dict[str, list[str]] = {}
        for skill in sorted(SKILLS.iterdir()):
            for path in sorted(skill.rglob("*.py")):
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                owners.setdefault(digest, []).append(path.relative_to(ROOT).as_posix())
        duplicates = [paths for paths in owners.values() if len({p.split('/')[1] for p in paths}) > 1]
        self.assertEqual(duplicates, [], f"duplicated Python payloads: {duplicates}")

    def test_assets_have_exact_owners(self):
        profile_files = {path.relative_to(PROFILE / "assets" / "profiles").as_posix() for path in (PROFILE / "assets" / "profiles").rglob("*.yaml")}
        self.assertEqual(profile_files, {
            "linked-archi-default.yaml", "linked-archi-direct.yaml", "linked-archi-merged.yaml",
            "examples/cloudplatform.yaml", "examples/curated-store.yaml",
            "examples/flattened-turtle.yaml", "examples/with-vocabulary.yaml",
        })
        template_files = {path.relative_to(QUERY / "assets" / "templates").as_posix() for path in (QUERY / "assets" / "templates").rglob("*.rq")}
        self.assertEqual(len(template_files), 39)
        for skill in (CONNECT, ANALYSE, VALIDATE):
            self.assertFalse((skill / "assets" / "profiles").exists())
            self.assertFalse((skill / "assets" / "templates").exists())
        self.assertFalse((PROFILE / "assets" / "templates").exists())
        self.assertFalse((QUERY / "assets" / "profiles").exists())

    def test_distinct_executables_are_present_and_old_wrappers_absent(self):
        expected = {
            SOURCE: "la-source",
            PROFILE: "la-profile",
            CONNECT: "la-connect",
            QUERY: "la-query",
            VALIDATE: "la-validate",
            ANALYSE: "la-analyse",
        }
        for skill, executable in expected.items():
            path = skill / "scripts" / executable
            self.assertTrue(path.is_file())
            self.assertTrue(os.access(path, os.X_OK))
        for skill in SKILLS.iterdir():
            self.assertFalse((skill / "scripts" / "la-kg").exists())

    def test_owner_packages_do_not_import_each_other(self):
        names = (
            "linked_archi_source",
            "linked_archi_profile",
            "linked_archi_connect",
            "linked_archi_query",
            "linked_archi_validate",
            "linked_archi_analyse",
        )
        offenders = []
        for skill in (SOURCE, PROFILE, CONNECT, QUERY, VALIDATE, ANALYSE):
            own = skill.name.replace("linked-archi-", "linked_archi_")
            for path in skill.rglob("*.py"):
                text = path.read_text("utf-8")
                for name in names:
                    if name != own and name in text:
                        offenders.append(f"{path.relative_to(ROOT)} imports/references {name}")
        self.assertEqual(offenders, [])


class TestIsolatedOwners(unittest.TestCase):
    def test_profile_list_show_and_derive_work_in_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); skill = root / PROFILE.name; shutil.copytree(PROFILE, skill)
            script = skill / "scripts" / "la-profile"
            self.assertEqual(_run(script, "list", cwd=root).returncode, 0)
            self.assertIn("linked-archi-default", _run(script, "show", cwd=root).stdout)
            mapping = root / "mapping.yaml"; mapping.write_text("namespaces:\n  ex: https://e/\n", encoding="utf-8")
            result = _run(script, "derive", "draft", "--type-mapping", str(mapping), cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("profile: draft", result.stdout)

    def test_connect_datasets_and_loading_work_in_isolation(self):
        support.requires_pyoxigraph(self)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); skill = root / CONNECT.name; shutil.copytree(CONNECT, skill)
            graph = root / "graph.trig"; shutil.copy2(support.BASE, graph)
            script = skill / "scripts" / "la-connect"
            listing = _run(script, "datasets", root.as_posix(), cwd=root)
            self.assertEqual(listing.returncode, 0, listing.stderr)
            loaded = _run(script, "connect", "--data", str(graph), cwd=root)
            self.assertEqual(loaded.returncode, 0, loaded.stderr)
            self.assertIn("named graph(s)", loaded.stdout)

    def test_query_catalog_and_lint_work_in_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); skill = root / QUERY.name; shutil.copytree(QUERY, skill)
            script = skill / "scripts" / "la-query"
            catalog = _run(script, "catalog", "list", cwd=root)
            self.assertEqual(catalog.returncode, 0, catalog.stderr)
            self.assertIn("39 template(s)", catalog.stdout)
            shown = _run(script, "catalog", "show", "core/dependents-qualified", cwd=root)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertIn("parameters", shown.stdout)
            self.assertIn("requires", shown.stdout)
            lint = _run(script, "lint", "--query", "ASK { ?s ?p ?o }", cwd=root)
            self.assertEqual(lint.returncode, 0, lint.stderr)

    def test_datasets_invalid_directory_returns_two_without_traceback(self):
        result = _run(CONNECT / "scripts" / "la-connect", "datasets", "/definitely/not/here", cwd=ROOT)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_installed_sibling_commands_run_by_skill_relative_path(self):
        support.requires_pyoxigraph(self)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for source in (PROFILE, CONNECT, QUERY):
                shutil.copytree(source, root / source.name)
            graph = root / "graph.trig"
            shutil.copy2(support.BASE, graph)

            profile = _run(
                Path("scripts/la-profile"), "verify", "--data", str(graph),
                cwd=root / PROFILE.name,
            )
            self.assertEqual(profile.returncode, 0, profile.stderr)
            connect = _run(
                Path("scripts/la-connect"), "connect", "--data", str(graph),
                cwd=root / CONNECT.name,
            )
            self.assertEqual(connect.returncode, 0, connect.stderr)
            query = _run(
                Path("scripts/la-query"), "query", "run", "core/models",
                "--data", str(graph), cwd=root / QUERY.name,
            )
            self.assertEqual(query.returncode, 0, query.stderr)


class TestCompanionContracts(unittest.TestCase):
    def test_explicit_skills_dir_never_falls_back_to_path_companions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            marker = root / "path-companion-ran"
            fake = '#!/bin/sh\ntouch "$MARKER"\nexit 0\n'
            for name in ("la-profile", "la-connect", "la-query"):
                path = fake_bin / name
                path.write_text(fake, encoding="utf-8")
                path.chmod(0o755)
            extra_env = {
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "MARKER": str(marker),
            }

            profile_root = root / "profile-case"
            shutil.copytree(PROFILE, profile_root / PROFILE.name)
            profile = _run(
                profile_root / PROFILE.name / "scripts" / "la-profile",
                "verify", "--data", str(support.BASE), cwd=profile_root,
                skills_dir=profile_root, extra_env=extra_env,
            )
            self.assertEqual(profile.returncode, 2)
            self.assertIn("Missing required skill: linked-archi-connect", profile.stderr)

            query_root = root / "query-case"
            shutil.copytree(QUERY, query_root / QUERY.name)
            query = _run(
                query_root / QUERY.name / "scripts" / "la-query",
                "query", "render", "core/models", cwd=query_root,
                skills_dir=query_root, extra_env=extra_env,
            )
            self.assertEqual(query.returncode, 2)
            self.assertIn("Missing required skill: linked-archi-profile", query.stderr)

            connect_root = root / "connect-case"
            shutil.copytree(CONNECT, connect_root / CONNECT.name)
            connect = _run(
                connect_root / CONNECT.name / "scripts" / "la-connect",
                "_machine", "execute", cwd=connect_root,
                skills_dir=connect_root, extra_env=extra_env,
                stdin={
                    "schema_version": 1,
                    "target": {"endpoint": "https://graph.example/query"},
                    "query": "ASK { ?s ?p ?o }",
                },
            )
            self.assertEqual(connect.returncode, 2)
            self.assertIn("Missing required skill: linked-archi-query", connect.stderr)
            self.assertFalse(marker.exists(), "a PATH companion was executed")

    def test_missing_companion_errors_name_the_exact_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            isolated_profile = root / PROFILE.name; shutil.copytree(PROFILE, isolated_profile)
            result = _run(
                isolated_profile / "scripts" / "la-profile", "verify", "--data", str(support.BASE),
                cwd=root, skills_dir=root,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Missing required skill: linked-archi-connect", result.stderr)
            shutil.rmtree(isolated_profile)
            isolated_query = root / QUERY.name; shutil.copytree(QUERY, isolated_query)
            result = _run(
                isolated_query / "scripts" / "la-query", "query", "render", "core/models",
                cwd=root, skills_dir=root,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Missing required skill: linked-archi-profile", result.stderr)
            shutil.copytree(PROFILE, root / PROFILE.name)
            graph = root / "graph.trig"; shutil.copy2(support.BASE, graph)
            result = _run(
                isolated_query / "scripts" / "la-query", "query", "run", "core/models",
                "--data", str(graph), cwd=root, skills_dir=root,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Missing required skill: linked-archi-connect", result.stderr)

    def test_profile_machine_resolve_emits_normalized_versioned_snapshot(self):
        result = _run(
            PROFILE / "scripts" / "la-profile", "_machine", "resolve", cwd=ROOT,
            stdin={"schema_version": 1, "profile": "linked-archi-default"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads(result.stdout)
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertTrue(Path(snapshot["source"]).is_absolute())
        self.assertIsInstance(snapshot["roles"]["label"], list)
        self.assertTrue(snapshot["roles"]["label"][0].startswith("http"))
        self.assertIsNone(snapshot["roles"]["owner"])
        for key in ("namespaces", "graphs", "capabilities", "notations", "taxonomies", "limits"):
            self.assertIn(key, snapshot)

    def test_profile_machine_resolve_rejects_non_object_json_without_traceback(self):
        result = _run(
            PROFILE / "scripts" / "la-profile", "_machine", "resolve", cwd=ROOT,
            stdin=[],
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("JSON object", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_query_machine_lint_is_versioned_and_structured(self):
        script = QUERY / "scripts" / "la-query"
        allowed = _run(
            script, "_machine", "lint", cwd=ROOT,
            stdin={"schema_version": 1, "query": "ASK { ?s ?p ?o }"},
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(json.loads(allowed.stdout), {
            "schema_version": 1, "accepted": True,
        })

        refused = _run(
            script, "_machine", "lint", cwd=ROOT,
            stdin={"schema_version": 1, "query": "DELETE WHERE { ?s ?p ?o }"},
        )
        self.assertEqual(refused.returncode, 0, refused.stderr)
        decision = json.loads(refused.stdout)
        self.assertFalse(decision["accepted"])
        self.assertIn("SPARQL Update", decision["reason"])

        malformed = _run(
            script, "_machine", "lint", cwd=ROOT,
            stdin={"schema_version": 2, "query": "ASK { ?s ?p ?o }"},
        )
        self.assertEqual(malformed.returncode, 2)
        self.assertNotIn("Traceback", malformed.stderr)

    def test_connect_machine_execute_emits_backend_neutral_raw_result(self):
        support.requires_pyoxigraph(self)
        result = _run(
            CONNECT / "scripts" / "la-connect", "_machine", "execute", cwd=ROOT,
            stdin={
                "schema_version": 1,
                "target": {"data": [str(support.BASE)], "timeout_ms": 30000},
                "query": "SELECT ?s WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 1",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        raw = json.loads(result.stdout)
        self.assertEqual(raw["schema_version"], 1)
        for key in ("form", "variables", "rows", "boolean", "triples", "elapsed_ms", "dataset_id", "named_graphs_present", "description"):
            self.assertIn(key, raw)
        self.assertEqual(raw["form"], "SELECT")

    def test_connect_transport_delegates_read_only_policy_to_query_owner(self):
        result = _run(
            CONNECT / "scripts" / "la-connect", "_machine", "execute", cwd=ROOT,
            stdin={
                "schema_version": 1,
                "target": {"data": [str(support.BASE)], "timeout_ms": 30000},
                "query": "DELETE WHERE { ?s ?p ?o }",
            },
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Query safety check refused execution", result.stderr)
        self.assertIn("SPARQL Update", result.stderr)

    def test_combined_siblings_support_profile_verify_and_query_run(self):
        support.requires_pyoxigraph(self)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for source in (PROFILE, CONNECT, QUERY):
                shutil.copytree(source, root / source.name)
            graph = root / "graph.trig"; shutil.copy2(support.BASE, graph)
            verify = _run(root / PROFILE.name / "scripts" / "la-profile", "verify", "--data", str(graph), cwd=root, skills_dir=root)
            self.assertEqual(verify.returncode, 0, verify.stderr)
            query = _run(root / QUERY.name / "scripts" / "la-query", "query", "run", "core/models", "--data", str(graph), cwd=root, skills_dir=root)
            self.assertEqual(query.returncode, 0, query.stderr)
            self.assertIn("profile linked-archi-default", query.stdout)

    def test_root_dispatcher_preserves_public_syntax(self):
        support.requires_pyoxigraph(self)
        result = _run(ROOT / "bin" / "la-kg", "query", "run", "core/models", "--data", str(support.BASE), cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("row(s)", result.stdout)


class TestLocalCliLink(unittest.TestCase):
    def test_link_cli_warns_and_prints_zshrc_guidance_when_bin_is_off_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            env = dict(os.environ)
            env["PATH"] = "/usr/bin:/bin"
            result = subprocess.run(
                ["make", "link-cli", f"BIN_DIR={bin_dir}"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((bin_dir / "la-kg").is_symlink())
            self.assertIn(f"warning: {bin_dir} is not on PATH", result.stdout)
            self.assertIn(
                f'export PATH="{bin_dir}:$PATH"',
                result.stdout,
            )


if __name__ == "__main__":
    unittest.main()


class TestCompanionResolutionIsUniform(unittest.TestCase):
    """Every owner resolves siblings the same way, and says the same thing when it cannot.

    Four owners had four slightly different resolvers, none of which was documented in the
    skills themselves. That is why an agent went looking for sibling skills with `find`
    instead of trusting a rule. The order is deliberate:

    1. ``$LINKED_ARCHI_SKILLS_DIR`` when set - authoritative, and it must never fall back,
       because naming an install root and silently getting a different generation of a
       skill is worse than a clear failure;
    2. the sibling directory beside the skill, which is how installed skill sets sit;
    3. the command on PATH, for a packaged or symlinked install.
    """

    #: (owner module path, resolver attribute, error type attribute, own-skill name)
    OWNERS = (
        ("linked_archi_source.cli", "linked-archi-source"),
        ("linked_archi_profile.cli", "linked-archi-profile"),
        ("linked_archi_connect.adapters.base", "linked-archi-connect"),
        ("linked_archi_query.cli", "linked-archi-query"),
        ("linked_archi_validate.cli", "linked-archi-validate"),
        ("linked_archi_analyse.cli", "linked-archi-analyse"),
    )

    def _resolver(self, module_name: str):
        import importlib

        module = importlib.import_module(module_name)
        return module._companion, module.OWN_SKILL

    def test_every_owner_exposes_the_same_resolver_shape(self):
        for module_name, own in self.OWNERS:
            with self.subTest(module_name):
                resolve, declared = self._resolver(module_name)
                self.assertEqual(declared, own)
                self.assertTrue(callable(resolve))

    def test_adjacency_resolves_without_any_environment(self):
        for module_name, _own in self.OWNERS:
            with self.subTest(module_name):
                resolve, _ = self._resolver(module_name)
                saved = os.environ.pop("LINKED_ARCHI_SKILLS_DIR", None)
                try:
                    found = resolve("linked-archi-query", "la-query")
                finally:
                    if saved is not None:
                        os.environ["LINKED_ARCHI_SKILLS_DIR"] = saved
                self.assertEqual(Path(found).name, "la-query")
                self.assertTrue(Path(found).is_file())

    def test_an_explicit_skills_dir_is_authoritative_and_never_falls_back(self):
        # The companion exists next door, so only an explicit empty root can fail here.
        for module_name, _own in self.OWNERS:
            with self.subTest(module_name):
                resolve, _ = self._resolver(module_name)
                with tempfile.TemporaryDirectory() as empty:
                    saved = os.environ.get("LINKED_ARCHI_SKILLS_DIR")
                    os.environ["LINKED_ARCHI_SKILLS_DIR"] = empty
                    try:
                        with self.assertRaises(Exception) as caught:
                            resolve("linked-archi-query", "la-query")
                    finally:
                        if saved is None:
                            os.environ.pop("LINKED_ARCHI_SKILLS_DIR", None)
                        else:
                            os.environ["LINKED_ARCHI_SKILLS_DIR"] = saved
                message = str(caught.exception)
                self.assertIn("Missing required skill: linked-archi-query", message)
                self.assertIn("under explicit LINKED_ARCHI_SKILLS_DIR=", message)

    def test_the_unresolvable_message_names_the_skill_and_every_route(self):
        for module_name, own in self.OWNERS:
            with self.subTest(module_name):
                resolve, _ = self._resolver(module_name)
                saved = os.environ.pop("LINKED_ARCHI_SKILLS_DIR", None)
                try:
                    with self.assertRaises(Exception) as caught:
                        resolve("linked-archi-nonexistent", "la-nonexistent")
                finally:
                    if saved is not None:
                        os.environ["LINKED_ARCHI_SKILLS_DIR"] = saved
                message = str(caught.exception)
                self.assertIn("Missing required skill: linked-archi-nonexistent", message)
                self.assertIn(f"Install it beside {own}", message)
                self.assertIn("on PATH", message)
                self.assertIn("LINKED_ARCHI_SKILLS_DIR", message)


class TestQueryOutputRedirection(unittest.TestCase):
    """`-o` on every la-query command, not only the three that write an artifact.

    `catalog list --why` is the longest output the CLI produces and the one a caller most
    wants in a file, and it was the one command that forced a shell redirect. `catalog
    dump` is JSON, which is worse: a caller had to capture it through the shell to parse
    it, while `run -o` wrote its JSON directly.
    """

    LA_QUERY = QUERY / "scripts" / "la-query"

    #: Commands whose output IS their stdout, so `-o` means "that, in a file". The
    #: artifact writers - render, run, literal - do their own writing and are not here.
    REDIRECTED = (
        ("catalog list", ("catalog", "list")),
        ("catalog list --why", ("catalog", "list", "--profile", "linked-archi-default",
                                "--why")),
        ("catalog show", ("catalog", "show", "core/traceability")),
        ("catalog dump", ("catalog", "dump")),
        ("lint", ("lint", "--query", "SELECT ?s WHERE { ?s ?p ?o }")),
        ("doctor", ("doctor",)),
    )

    def test_every_command_accepts_it_and_writes_the_file(self):
        for label, args in self.REDIRECTED:
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "nested" / "out.txt"
                done = _run(self.LA_QUERY, *args, "-o", str(target), cwd=ROOT)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertTrue(target.is_file(), f"{label} wrote no file")
                self.assertTrue(target.read_text(encoding="utf-8").strip(), label)
                self.assertIn("Wrote", done.stdout)

    def test_the_file_holds_what_stdout_would_have_held(self):
        """Not a summary of it, and not a different serialisation."""
        for label, args in self.REDIRECTED:
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "out.txt"
                piped = _run(self.LA_QUERY, *args, cwd=ROOT)
                _run(self.LA_QUERY, *args, "-o", str(target), cwd=ROOT)
                self.assertEqual(target.read_text(encoding="utf-8"), piped.stdout, label)

    def test_catalog_dump_writes_parseable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "catalog.json"
            _run(self.LA_QUERY, "catalog", "dump", "-o", str(target), cwd=ROOT)
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertIn("core/traceability", payload["templates"])

    def test_run_still_writes_an_envelope_rather_than_its_table(self):
        """The other meaning of `-o`, unchanged. Collapsing the two would silently turn
        every recorded step into a markdown table."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "step.json"
            done = _run(
                self.LA_QUERY, "query", "run", "core/models",
                "--data", str(support.BASE), "-o", str(target), cwd=ROOT,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertIn("query_id", payload)

    def test_a_catalogue_problem_still_reaches_stderr(self):
        """Diagnostics must not be redirected into the file whose contents they qualify.

        Nothing is wrong with the committed catalogue, so this asserts the channel rather
        than an error: stdout carries only the confirmation, and the listing is in the file.
        """
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.txt"
            done = _run(self.LA_QUERY, "catalog", "list", "-o", str(target), cwd=ROOT)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertNotIn("RESOLUTION", done.stdout)
            self.assertIn("RESOLUTION", target.read_text(encoding="utf-8"))


class TestDoctorCommands(unittest.TestCase):
    """Every runtime owner answers "where am I and what can I reach" in one call."""

    OWNERS = (
        ("linked-archi-source", "la-source"),
        ("linked-archi-profile", "la-profile"),
        ("linked-archi-connect", "la-connect"),
        ("linked-archi-query", "la-query"),
        ("linked-archi-validate", "la-validate"),
        ("linked-archi-analyse", "la-analyse"),
    )

    def test_doctor_reports_the_owner_and_resolves_companions(self):
        for skill, executable in self.OWNERS:
            with self.subTest(skill):
                done = _run(SKILLS / skill / "scripts" / executable, "doctor", cwd=ROOT)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertIn(skill, done.stdout)
                self.assertIn("owner root:", done.stdout)
                self.assertIn("command:", done.stdout)
                self.assertNotIn("MISSING", done.stdout)

    def test_doctor_states_the_resolution_order_instead_of_inviting_a_search(self):
        for skill, executable in self.OWNERS:
            with self.subTest(skill):
                done = _run(SKILLS / skill / "scripts" / executable, "doctor", cwd=ROOT)
                self.assertIn("LINKED_ARCHI_SKILLS_DIR", done.stdout)
                self.assertIn("filesystem", done.stdout.lower())

    def test_doctor_fails_when_a_required_companion_is_absent(self):
        # Validate and source need no companion to do their own job, so they stay usable.
        for skill, executable in (
            ("linked-archi-profile", "la-profile"),
            ("linked-archi-connect", "la-connect"),
            ("linked-archi-query", "la-query"),
            # Analyse cannot execute a plan without query, and says so rather than
            # emitting a plan whose every command will fail.
            ("linked-archi-analyse", "la-analyse"),
        ):
            with self.subTest(skill):
                with tempfile.TemporaryDirectory() as empty:
                    done = _run(
                        SKILLS / skill / "scripts" / executable,
                        "doctor",
                        cwd=ROOT,
                        skills_dir=Path(empty),
                    )
                self.assertEqual(done.returncode, 1, done.stdout)
                self.assertIn("MISSING", done.stdout)


class TestDocumentedCommandsAreExecutable(unittest.TestCase):
    """Every command a skill documents must be runnable under what it grants itself.

    Found by walking the plan's own acceptance checklist: P1 cut `allowed-tools` to
    `Read Bash(python3:*)` while the G8 bootstrap snippet still used `command -v`, `ls` and
    `readlink -f`. Two completed items, each defensible, contradicting each other in the same
    file - and the frontmatter is the half a client enforces, so the documented bootstrap was
    the half that would fail.

    Resolution: the bootstrap is one `python3` call. This test is what stops the next
    convenient `ls` from creeping back in.
    """

    #: Shell builtins and syntax invoke no external program, so they need no grant.
    BUILTINS = {
        "export", "cd", "set", "unset", "echo", "for", "do", "done", "if", "then", "fi",
        "while", "printf", "read", "PY", "EOF", "source", ".",
    }

    #: The owner commands. Every SKILL.md defines these as shorthand for
    #: `python3 <resolved script>`, because a full path on every line hides the command.
    OWNERS = {
        "la-source", "la-profile", "la-connect", "la-query", "la-validate", "la-analyse",
        "la-kg",
    }

    #: Never acceptable in a skill's own instructions: each either contradicts the "never
    #: search the filesystem" prohibition, or is not granted by any skill's allowed-tools.
    FORBIDDEN = {"ls", "find", "grep", "rg", "readlink", "command", "which", "locate", "make"}

    def _blocks(self, path: Path):
        """First words of the commands in every fenced bash block.

        Continuation lines are skipped: a `\\`-wrapped command is one command, and treating
        its second line as a new one reported every flag as an unrunnable program.
        """
        fenced = False
        continuation = False
        for line in path.read_text("utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                fenced = stripped.startswith("```bash") or stripped.startswith("```sh")
                continuation = False
                continue
            if not fenced or not stripped or stripped.startswith("#"):
                continue
            was_continuation, continuation = continuation, stripped.endswith("\\")
            if was_continuation:
                continue
            # A heredoc body is python, not shell.
            if stripped.startswith(("import ", "from ", "print(", "root ", "for owner")):
                continue
            first = stripped.split()[0]
            if "=" in first and not first.startswith("-"):
                continue  # variable assignment
            yield first.lstrip("$(").rstrip(";")

    def test_no_skill_documents_a_search_tool(self):
        offenders = []
        for skill in sorted(SKILLS.glob("*/SKILL.md")):
            for command in self._blocks(skill):
                if command in self.FORBIDDEN:
                    offenders.append(f"{skill.parent.name}: {command}")
        self.assertEqual(offenders, [], "documented but forbidden: " + "; ".join(offenders))

    def test_every_documented_command_is_python3_or_an_owner_shorthand(self):
        allowed = self.BUILTINS | self.OWNERS | {"python3"}
        offenders = []
        for skill in sorted(SKILLS.glob("*/SKILL.md")):
            granted = ""
            for line in skill.read_text("utf-8").splitlines():
                if line.startswith("allowed-tools:"):
                    granted = line
                    break
            for command in self._blocks(skill):
                if command in allowed:
                    continue
                # Anything else must be named in this skill's own grant.
                if f"Bash({command}:" in granted:
                    continue
                offenders.append(f"{skill.parent.name}: {command}")
        self.assertEqual(offenders, [], "not executable under allowed-tools: " + "; ".join(offenders))

    def test_the_bootstrap_costs_one_call(self):
        """The plan's budget is two from a cold start. One leaves room for the question."""
        for skill in sorted(SKILLS.glob("*/SKILL.md")):
            body = skill.read_text("utf-8")
            if "python3 - <<" not in body:
                continue  # validate documents resolution in prose, with no snippet
            with self.subTest(skill.parent.name):
                block = body.split("python3 - <<'PY'", 1)[1].split("```", 1)[0]
                # One heredoc, so one call: no second command hiding after it.
                self.assertEqual(block.count("PY"), 1, "more than one bootstrap call")

    def test_the_bootstrap_never_searches_from_a_broad_root(self):
        for skill in sorted(SKILLS.glob("*/SKILL.md")):
            body = skill.read_text("utf-8")
            with self.subTest(skill.parent.name):
                for pattern in ('rglob("', 'glob("**', 'Path("/")', 'walk("/'):
                    self.assertNotIn(pattern, body, "a recursive search is not a resolution")


class TestNoEmptyDirectoriesShip(unittest.TestCase):
    """An empty directory is a promise nothing keeps.

    `analyse/scripts/` sat empty for a while, which reads as "this skill has a runtime that
    failed to install" - and `connect/references/` and `validate/references/` were empty while
    their SKILL.md files carried the detail that belonged in them. Both are now resolved, so
    the state is worth pinning: a directory either has content or is not there.
    """

    def test_no_skill_directory_is_empty(self):
        empty = [
            path.relative_to(ROOT).as_posix()
            for path in sorted(SKILLS.rglob("*"))
            if path.is_dir()
            and "__pycache__" not in path.parts
            and not any(child.name != "__pycache__" for child in path.iterdir())
        ]
        self.assertEqual(empty, [], f"empty skill directories: {empty}")

    def test_every_skill_has_a_references_directory_with_something_in_it(self):
        """Progressive disclosure only works if there is somewhere to disclose to."""
        for skill in sorted(SKILLS.iterdir()):
            if not skill.is_dir():
                continue
            with self.subTest(skill.name):
                references = skill / "references"
                self.assertTrue(references.is_dir(), f"{skill.name} has no references/")
                self.assertTrue(
                    list(references.glob("*.md")), f"{skill.name}/references/ is empty"
                )


class TestAllowedToolsMatchThePolicy(unittest.TestCase):
    """Frontmatter must not permit what the prose forbids.

    Every SKILL.md says "never search the filesystem for skills, scripts, templates or
    profiles". Advertising `Glob`, `Grep` and `Bash(ls:*)` in `allowed-tools` said the
    opposite in the same file, and the frontmatter is the half a client enforces. A
    permission granted is a behaviour normalised.

    `Bash(make:*)` went for a different reason: `make` is repository development, absent from
    an installed copy, so granting it to a normal run advertises a capability that will not be
    there.
    """

    #: The tools a normal run needs. Read a local graph path someone named, and run the
    #: owner command. Source additionally clones and fetches, which is its whole job.
    EXPECTED = {
        "linked-archi-analyse": "Read Bash(python3:*)",
        "linked-archi-connect": "Read Bash(python3:*)",
        "linked-archi-profile": "Read Bash(python3:*)",
        "linked-archi-query": "Read Bash(python3:*)",
        "linked-archi-validate": "Read Bash(python3:*)",
        "linked-archi-source": "Read Bash(python3:*) Bash(git:*)",
    }

    FORBIDDEN = ("Glob", "Grep", "Bash(ls:*)", "Bash(find:*)", "Bash(rg:*)", "Bash(make:*)")

    def _allowed(self, skill: str) -> str:
        for line in (SKILLS / skill / "SKILL.md").read_text("utf-8").splitlines():
            if line.startswith("allowed-tools:"):
                return line.split(":", 1)[1].strip()
        self.fail(f"{skill} declares no allowed-tools")

    def test_each_skill_declares_exactly_what_a_normal_run_needs(self):
        for skill, expected in self.EXPECTED.items():
            with self.subTest(skill):
                self.assertEqual(self._allowed(skill), expected)

    def test_no_skill_advertises_a_search_tool(self):
        for skill in self.EXPECTED:
            declared = self._allowed(skill)
            for tool in self.FORBIDDEN:
                with self.subTest(f"{skill}:{tool}"):
                    self.assertNotIn(tool, declared)

    def test_the_prose_still_forbids_searching(self):
        """The other half of the pair. Removing one without the other is worse than neither."""
        for skill in self.EXPECTED:
            with self.subTest(skill):
                body = (SKILLS / skill / "SKILL.md").read_text("utf-8")
                self.assertIn("Never search the filesystem", body)


class TestDocumentedCommandsExist(unittest.TestCase):
    """Every `la-<owner> <subcommand>` the documentation names is a real subcommand.

    Written after the analyse workflow was documented with `la-source fetch`, which does
    not exist - the subcommands are `url`, `git`, `gitlab-mcp` and `complete`. An agent
    following instructions runs whatever is written, so a wrong command in a SKILL.md is a
    defect in the product rather than a typo in prose, and nothing else in the suite reads
    the prose.
    """

    OWNERS = {
        "la-source": SOURCE / "scripts" / "la-source",
        "la-profile": PROFILE / "scripts" / "la-profile",
        "la-connect": CONNECT / "scripts" / "la-connect",
        "la-query": QUERY / "scripts" / "la-query",
        "la-validate": VALIDATE / "scripts" / "la-validate",
        "la-analyse": ANALYSE / "scripts" / "la-analyse",
        "la-kg": ROOT / "bin" / "la-kg",
    }

    #: Command groups with a second level, e.g. `la-query query run`.
    NESTED = (("la-query", "query"), ("la-query", "catalog"))

    #: Words that follow a command in documentation without being subcommands.
    NOT_A_SUBCOMMAND = {"is", "in", "and", "or", "for", "with", "names", "reports",
                        "executes", "does", "lists", "run", "runs", "writes", "when",
                        "on", "to", "the", "then", "still", "keeps", "adds", "prints"}

    @classmethod
    def setUpClass(cls):
        cls.available: dict[tuple[str, ...], set[str]] = {}
        for executable, script in cls.OWNERS.items():
            cls.available[(executable,)] = cls._choices(script)
        for executable, group in cls.NESTED:
            cls.available[(executable, group)] = cls._choices(cls.OWNERS[executable], group)

    @staticmethod
    def _choices(script: Path, *path: str) -> set[str]:
        """The argparse choices for a command, read from its own --help."""
        done = _run(script, *path, "--help", cwd=ROOT)
        found: set[str] = set()
        for match in re.finditer(r"\{([a-z0-9_,\-]+)\}", done.stdout):
            found.update(match.group(1).split(","))
        return found

    #: The closing quote is optional and matters: examples are written as
    #: `python3 "$SKILL/scripts/la-profile" derive ...`, and a regex demanding whitespace
    #: straight after the command name silently stops checking every one of them.
    _COMMAND = re.compile(
        r"\b(la-source|la-profile|la-connect|la-query|la-validate|la-analyse|la-kg)[\"']?\s+"
        r"([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*))?"
    )

    def _invocations(self):
        """Every documented invocation, taken from code spans only.

        Prose mentions a command name without invoking it ("`linked-archi-query` executes
        every step"), so matching whole lines would need a list of English words to ignore
        and would drift. Fenced blocks and inline code spans are where an invocation
        actually lives, and an agent copies exactly those.
        """
        docs = [
            *sorted(SKILLS.glob("*/SKILL.md")),
            *sorted(SKILLS.glob("*/references/*.md")),
            ROOT / "USAGE.md",
            ROOT / "README.md",
            ROOT / "ADAPTING.md",
        ]
        for doc in docs:
            if not doc.exists():
                continue
            fenced = False
            for line in doc.read_text("utf-8").splitlines():
                if line.lstrip().startswith("```"):
                    fenced = not fenced
                    continue
                if fenced:
                    # A trailing shell comment inside a block is prose again. Anchored on
                    # whitespace so an IRI fragment (`...#ArchiMate3.2`) survives.
                    spans = [re.sub(r"(^|\s)#.*$", "", line)]
                else:
                    spans = re.findall(r"`([^`]+)`", line)
                for span in spans:
                    for match in self._COMMAND.finditer(span):
                        yield doc, match.group(1), match.group(2), match.group(3)

    def test_no_document_names_a_command_that_does_not_exist(self):
        unknown = []
        for doc, executable, first, second in self._invocations():
            where = doc.relative_to(ROOT).as_posix()
            if first in self.NOT_A_SUBCOMMAND:
                continue
            if first not in self.available[(executable,)]:
                unknown.append(f"{where}: {executable} {first}")
                continue
            key = (executable, first)
            if second and second not in self.NOT_A_SUBCOMMAND and key in self.available:
                if second not in self.available[key]:
                    unknown.append(f"{where}: {executable} {first} {second}")
        self.assertEqual(
            unknown, [],
            "documented commands that do not exist: " + "; ".join(sorted(set(unknown))),
        )

    def test_the_check_can_actually_see_the_subcommands(self):
        """Guard against passing because --help parsing or the scan returned nothing."""
        self.assertIn("query", self.available[("la-query",)])
        self.assertIn("run", self.available[("la-query", "query")])
        self.assertIn("url", self.available[("la-source",)])
        self.assertNotIn("fetch", self.available[("la-source",)])
        self.assertIn("validate", self.available[("la-kg",)])
        found = {(exe, first) for _, exe, first, _ in self._invocations()}
        self.assertIn(("la-query", "query"), found)
        self.assertIn(("la-profile", "verify"), found)
        self.assertGreater(len(found), 12, "the scan is finding almost nothing")

    def test_the_check_catches_a_command_that_does_not_exist(self):
        """The bug this exists for: `la-source fetch`, which was nearly shipped."""
        self.assertNotIn("fetch", self.available[("la-source",)])
        span = "la-source fetch https://example.org/model.ttl"
        match = self._COMMAND.search(span)
        self.assertIsNotNone(match)
        self.assertEqual((match.group(1), match.group(2)), ("la-source", "fetch"))
        self.assertNotIn(match.group(2), self.NOT_A_SUBCOMMAND)


class TestHelpIsAuthoritative(unittest.TestCase):
    """`COMMAND --help` alone is enough to use the command correctly.

    The standard this pins: an agent that runs `--help` should not then have to read
    SKILL.md or the Python to know what a flag does. Field sessions guessed `--sparql`,
    hit an argparse error, ran `--help`, and found flags with no help text at all - so
    the help was costing a round trip and then not paying for it.

    Walking the parsers in process rather than diffing rendered output: the assertion is
    about every option having help, not about terminal width or argparse's wrapping.
    """

    OWNERS = {
        "la-source": "linked_archi_source.cli",
        "la-profile": "linked_archi_profile.cli",
        "la-connect": "linked_archi_connect.cli",
        "la-query": "linked_archi_query.cli",
        "la-validate": "linked_archi_validate.cli",
        "la-analyse": "linked_archi_analyse.cli",
    }

    @staticmethod
    def _parsers(parser, path):
        """Every parser in the tree, with the command path that reaches it."""
        import argparse as ap

        yield path, parser
        for action in parser._actions:
            if isinstance(action, ap._SubParsersAction):
                for name, sub in action.choices.items():
                    yield from TestHelpIsAuthoritative._parsers(sub, f"{path} {name}")

    def _built(self):
        import importlib

        for executable, module in self.OWNERS.items():
            yield executable, importlib.import_module(module).build_parser()

    def test_every_public_option_has_help(self):
        import argparse as ap

        gaps = []
        for executable, root in self._built():
            for path, parser in self._parsers(root, executable):
                for action in parser._actions:
                    if isinstance(action, (ap._HelpAction, ap._SubParsersAction)):
                        continue
                    if action.help is ap.SUPPRESS:
                        continue
                    if not (action.help or "").strip():
                        name = "/".join(action.option_strings) or action.dest
                        gaps.append(f"{path}: {name}")
        self.assertEqual(gaps, [], "options with no help: " + "; ".join(gaps))

    def test_every_command_says_what_it_is_for(self):
        """A description, so `cmd sub --help` explains itself and not just its flags."""
        gaps = [
            path
            for executable, root in self._built()
            for path, parser in self._parsers(root, executable)
            if not (parser.description or "").strip()
        ]
        self.assertEqual(gaps, [], "commands with no description: " + "; ".join(gaps))

    def test_every_owner_documents_examples_and_exit_codes(self):
        for executable, root in self._built():
            with self.subTest(executable):
                epilog = root.epilog or ""
                self.assertIn("Examples:", epilog)
                self.assertIn("Exit codes:", epilog)

    def test_a_flag_taking_a_value_has_a_metavar_or_a_choice_list(self):
        """`--data DATA` tells a reader nothing; `--data FILE` tells them what to pass."""
        import argparse as ap

        gaps = []
        for executable, root in self._built():
            for path, parser in self._parsers(root, executable):
                for action in parser._actions:
                    if isinstance(action, (ap._HelpAction, ap._SubParsersAction)):
                        continue
                    if action.help is ap.SUPPRESS or not action.option_strings:
                        continue
                    if action.nargs == 0 or isinstance(action, ap._StoreConstAction):
                        continue  # a flag takes no value
                    if not action.metavar and not action.choices:
                        gaps.append(f"{path}: {'/'.join(action.option_strings)}")
        self.assertEqual(gaps, [], "value options without a metavar: " + "; ".join(gaps))

    def test_a_default_that_changes_behaviour_is_stated(self):
        """A default a caller can be surprised by belongs in the help, not in the source."""
        import argparse as ap

        gaps = []
        for executable, root in self._built():
            for path, parser in self._parsers(root, executable):
                for action in parser._actions:
                    if isinstance(action, (ap._HelpAction, ap._SubParsersAction)):
                        continue
                    if action.help is ap.SUPPRESS or not action.option_strings:
                        continue
                    interesting = (
                        action.default not in (None, False, [], (), "")
                        and not isinstance(action.default, bool)
                    )
                    if interesting and "default" not in (action.help or "").lower():
                        gaps.append(
                            f"{path}: {'/'.join(action.option_strings)}"
                            f" (default {action.default!r})"
                        )
        self.assertEqual(gaps, [], "undocumented defaults: " + "; ".join(gaps))

    def test_a_repeatable_option_says_so(self):
        """Nothing in argparse's rendering reveals that `--data` can be passed twice."""
        import argparse as ap

        gaps = []
        for executable, root in self._built():
            for path, parser in self._parsers(root, executable):
                for action in parser._actions:
                    if action.help is ap.SUPPRESS:
                        continue
                    if isinstance(action, ap._AppendAction):
                        if "repeatable" not in (action.help or "").lower():
                            gaps.append(f"{path}: {'/'.join(action.option_strings)}")
        self.assertEqual(gaps, [], "repeatable options that do not say so: " + "; ".join(gaps))

    def test_the_machine_contract_is_documented_rather_than_hidden(self):
        """G6, as behaviour: `_machine` is machine-facing, not private.

        It used to be `help=argparse.SUPPRESS`, which argparse still prints in the usage
        line as the literal string `==SUPPRESS==` - visible and unexplained, while three
        skills depended on it across process boundaries.
        """
        for executable, root in self._built():
            with self.subTest(executable):
                machine = None
                for path, parser in self._parsers(root, executable):
                    if path.endswith(" _machine"):
                        machine = parser
                self.assertIsNotNone(machine, "every owner publishes a _machine contract")
                rendered = root.format_help() + machine.format_help()
                self.assertNotIn("==SUPPRESS==", rendered)
                self.assertIn("contract", rendered)
                self.assertIn("schema_version", machine.format_help())

    def test_no_rendered_help_leaks_the_suppress_sentinel(self):
        for executable, root in self._built():
            for path, parser in self._parsers(root, executable):
                with self.subTest(path):
                    self.assertNotIn("==SUPPRESS==", parser.format_help())


class TestDocumentedCountsMatchReality(unittest.TestCase):
    """A number written in prose is a claim, and prose does not fail a build.

    `fixtures/PROVENANCE.md` said "All 28 catalogued templates return rows" long after the
    catalogue reached 35. Nothing was wrong with the templates; the sentence had simply
    stopped being true, and no test read it. The counts themselves are pinned elsewhere
    (`test_assets_have_exact_owners`, `test_catalog`), so what is missing is the link
    between the pin and the documentation - which is this.

    Only phrasings that mean *the whole catalogue* are matched. "the three orientation
    templates" is a statement about a subset and is left alone.
    """

    #: Phrasings that can only mean every template in the catalogue.
    WHOLE_CATALOGUE = (
        re.compile(r"[Aa]ll (\d+) catalogued templates"),
        re.compile(r"[Aa]ll (\d+) templates"),
        re.compile(r"across all (\d+) templates"),
        re.compile(r"(\d+) template\(s\)"),
        re.compile(r"(\d+) templates, \d+ available"),
        # README's own phrasing, added because it drifted: it said 36 while the catalogue
        # held 38, in the one sentence most readers see first.
        re.compile(r"(\d+) tested templates"),
    )

    #: "N templates, M available under <profile>" - the availability number too.
    AVAILABILITY = re.compile(r"\d+ templates, (\d+) available")

    def _docs(self):
        """Every Markdown file, with no exemptions.

        There used to be two: `REVALIDATION-PLAN.md` and `AGENT-UX-PLAN.md` were skipped
        because a plan records what was true when it was written. Both have since been
        retired — their open items and the decisions worth keeping moved into `PROPOSAL.md`,
        which is held to current accuracy like everything else. So every doc in the tree is
        now checked, and a new one cannot quietly opt out of that by being called a plan.
        """
        for doc in sorted(ROOT.rglob("*.md")):
            if any(part in doc.parts for part in (".git", "dist", "node_modules")):
                continue
            yield doc

    def test_documented_template_totals_match_the_catalogue(self):
        actual = len({
            path.relative_to(QUERY / "assets" / "templates").as_posix()
            for path in (QUERY / "assets" / "templates").rglob("*.rq")
        })
        wrong = []
        for doc in self._docs():
            text = doc.read_text("utf-8")
            for pattern in self.WHOLE_CATALOGUE:
                for match in pattern.finditer(text):
                    if int(match.group(1)) != actual:
                        wrong.append(
                            f"{doc.relative_to(ROOT).as_posix()}: "
                            f"{match.group(0)!r} but there are {actual}"
                        )
        self.assertEqual(wrong, [], "documented template count is stale:\n  " + "\n  ".join(wrong))

    def test_documented_availability_matches_the_default_profile(self):
        """The "N available" figure, which is a different number and drifts separately."""
        listing = subprocess.run(
            [sys.executable, str(QUERY / "scripts" / "la-query"), "catalog", "list",
             "--profile", "linked-archi-default"],
            capture_output=True, text=True, timeout=120, cwd=ROOT,
        )
        self.assertEqual(listing.returncode, 0, listing.stderr)
        stated = re.search(r"(\d+) available under profile", listing.stdout)
        self.assertIsNotNone(stated, listing.stdout)
        available = int(stated.group(1))

        wrong = []
        for doc in self._docs():
            for match in self.AVAILABILITY.finditer(doc.read_text("utf-8")):
                if int(match.group(1)) != available:
                    wrong.append(
                        f"{doc.relative_to(ROOT).as_posix()}: {match.group(0)!r} "
                        f"but {available} are available"
                    )
        self.assertEqual(wrong, [], "documented availability is stale:\n  " + "\n  ".join(wrong))


class TestNoPrivateHostsShip(unittest.TestCase):
    """No committed file may name a host outside the public set this package documents.

    The failure this prevents is not hypothetical and not really about hosts: it is about
    evidence. Auditing this package against a real customer estate produces IRIs, model
    names, release digests and a GitLab host, all of it useful and none of it publishable.
    Keeping it out by remembering to grep works until the once it does not, and a leak is
    unrecoverable in a way a bug is not - a published commit cannot be unpublished.

    An allowlist rather than a denylist, deliberately. A denylist has to name the customer
    to exclude them, which puts the thing being protected into the repository that must not
    contain it, and it protects exactly one engagement. This fails on any host that is not
    documentation, so the next dataset is covered by a test written before it arrives.

    Reserved and documentation names are allowed by rule rather than by listing: RFC 2606
    `.example`/`.test`/`.invalid`/`.localhost`, the `example.org|net|com` documentation
    domains, and the private and link-local IP ranges the transport tests use as SSRF
    targets. Hosts with no dot are skipped as truncated test stubs (`https://bad`), since
    they cannot name a real machine.
    """

    #: Real public hosts this package legitimately references.
    ALLOWED = {
        "meta.linked.archi",          # the published ontologies
        "schema.org", "purl.org", "www.w3.org",
        "github.com", "git-lfs.github.com", "microsoft.github.io", "gitlab.com",
        "keepachangelog.com", "semver.org",
        "agentskills.io", "kiro.dev",
        "acme.leanix.net",            # a vendor endpoint shape, in an example profile
        "e.org",                      # a stub target in the transport tests
        "arxiv.org",                  # papers the design cites
        # A `dct:source` inside the extracted Backstage shape, citing the upstream docs
        # for the relation it constrains. Extracted content, not authored here - the
        # provenance of a published constraint is part of the constraint.
        "backstage.io",
    }

    #: Reserved for documentation and testing, so allowed by suffix.
    ALLOWED_SUFFIXES = (
        ".example", ".example.org", ".example.net", ".example.com",
        ".invalid", ".test", ".localhost",
    )
    ALLOWED_EXACT_SUFFIX_ROOTS = {"example.org", "example.net", "example.com"}

    #: Private, loopback, link-local and CGNAT literals: the SSRF test targets.
    RESERVED_IP = re.compile(
        r"^(?:127\.|10\.|192\.168\.|169\.254\.|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|"
        r"172\.(?:1[6-9]|2\d|3[01])\.)"
    )

    HOST = re.compile(r"https?://([A-Za-z0-9._-]+)")

    TEXT_SUFFIXES = {
        ".py", ".md", ".rq", ".json", ".yaml", ".yml", ".ttl", ".trig", ".txt", ".cfg",
        ".toml", ".sh", ".ini",
    }

    def _files(self):
        skip = {".git", ".linked-archi-cache", "__pycache__", "dist", "node_modules",
                ".venv", ".pytest_cache"}
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or any(part in skip for part in path.parts):
                continue
            if path.suffix in self.TEXT_SUFFIXES or path.name in {"la-kg", "Makefile"}:
                yield path

    def _allowed(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        if "." not in host:
            return True
        if host in self.ALLOWED or self.RESERVED_IP.match(host):
            return True
        if host in self.ALLOWED_EXACT_SUFFIX_ROOTS:
            return True
        return host.endswith(self.ALLOWED_SUFFIXES)

    def test_no_committed_file_names_a_non_public_host(self):
        offenders: dict[str, set[str]] = {}
        for path in self._files():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:  # pragma: no cover - binary asset
                continue
            for host in self.HOST.findall(text):
                if not self._allowed(host):
                    offenders.setdefault(
                        host.lower(), set()
                    ).add(path.relative_to(ROOT).as_posix())
        self.assertEqual(
            offenders, {},
            "non-public hosts in committed files (add to ALLOWED only if the host is "
            "genuinely public and belongs in this package): "
            + "; ".join(
                f"{host} in {', '.join(sorted(files))}"
                for host, files in sorted(offenders.items())
            ),
        )

    def test_the_guard_would_catch_a_private_host(self):
        """A guard that cannot fail is decoration, so this checks the rule itself."""
        for host in ("source.internal.corp", "archi.acmebank", "gitlab.acme-corp.io",
                     "203.0.113.7"):
            with self.subTest(host):
                self.assertFalse(self._allowed(host))
        for host in ("meta.linked.archi", "models.example.org", "graph.example",
                     "127.0.0.1", "192.168.1.1", "bad"):
            with self.subTest(host):
                self.assertTrue(self._allowed(host))


class TestOneVersionStatedEverywhereItIsRepeated(unittest.TestCase):
    """`apm.yml` said 0.3.0 while ten other files said 0.1.0, and nothing read them.

    Two releases of drift accumulated in the copies a consumer sees first: the install pin
    in `README.md` and `USAGE.md` named a tag two versions old, and `metadata.version` in
    all six `SKILL.md` files still said 0.1.0. That frontmatter is the *only* version an
    installed skill carries - `apm.yml` is not deployed into a harness - so the stalest
    copy was the one an operator would rely on to identify what they had.

    `tests/version_sync.py` names every site once; `make bump TO=X.Y.Z` writes them all.
    This is the half that fails the build when they disagree.
    """

    def test_every_derived_copy_agrees_with_the_manifest(self):
        problems = version_sync.disagreements()
        self.assertEqual(problems, [], "run: make bump TO=" + version_sync.manifest_version())

    def test_the_check_would_catch_drift(self):
        """A check that cannot fail is decoration, so this drifts the expectation instead."""
        problems = version_sync.disagreements(version="9.9.9")
        self.assertNotEqual(problems, [])
        self.assertTrue(
            all("9.9.9" in problem for problem in problems),
            "each report should name the version it expected",
        )

    def test_every_skill_is_a_version_site(self):
        """A seventh skill must not be able to ship an unchecked version by being new."""
        listed = {
            site for site, _ in version_sync.SITES if site.endswith("SKILL.md")
        }
        actual = {
            path.relative_to(ROOT).as_posix() for path in SKILLS.glob("*/SKILL.md")
        }
        self.assertEqual(listed, actual)

    def test_the_manifest_version_is_semver(self):
        self.assertRegex(version_sync.manifest_version(), r"^\d+\.\d+\.\d+$")


class TestEveryWrittenTestIsActuallyRunnable(unittest.TestCase):
    """A test that cannot be collected reports success while checking nothing.

    Found the hard way. `support.requires_pyoxigraph` is a helper called with `self`, not
    a decorator; written as `@requires_pyoxigraph` it runs at class-definition time and its
    return value - `None` - replaces the method. `unittest` then cannot see the method, the
    suite passes with one fewer test than it has, and the only visible symptom is a total
    that does not move when tests are added. The count half of the `PROVENANCE.md` table
    check shipped that way, in the same commit whose message said the table was enforced.

    Nothing else in the suite would notice a second instance, which is the whole reason
    this exists: the failure is silent, and silent failure is the thing this package spends
    most of its effort refusing to do.

    Two ways a written test goes missing, so two checks. An attribute that is no longer
    callable, and a name defined twice in one class - where the second definition replaces
    the first and only one of the two ever runs.
    """

    #: Modules in `tests/` that are not test modules.
    HELPERS = frozenset({"support", "validate_skills", "version_sync"})

    def _modules(self):
        for path in sorted((ROOT / "tests").glob("*.py")):
            if path.stem not in self.HELPERS:
                yield path

    def test_every_test_attribute_is_callable(self):
        import importlib

        offenders = []
        for path in self._modules():
            module = importlib.import_module(f"tests.{path.stem}")
            for name, obj in vars(module).items():
                if not (isinstance(obj, type) and issubclass(obj, unittest.TestCase)):
                    continue
                loadable = set(unittest.TestLoader().getTestCaseNames(obj))
                for attribute in dir(obj):
                    if not attribute.startswith("test"):
                        continue
                    if not callable(getattr(obj, attribute, None)):
                        offenders.append(
                            f"{path.name}::{name}.{attribute} is not callable - a helper "
                            "used as a decorator overwrites the method with its return value"
                        )
                    elif attribute not in loadable:
                        offenders.append(
                            f"{path.name}::{name}.{attribute} exists but unittest will not "
                            "collect it"
                        )
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_test_name_is_defined_twice_in_one_class(self):
        """The second definition wins and the first never runs, with nothing said."""
        import ast

        offenders = []
        for path in self._modules():
            tree = ast.parse(path.read_text("utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                seen: set[str] = set()
                for item in node.body:
                    if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if not item.name.startswith("test"):
                        continue
                    if item.name in seen:
                        offenders.append(
                            f"{path.name}::{node.name}.{item.name} is defined twice "
                            f"(line {item.lineno}); only the last one runs"
                        )
                    seen.add(item.name)
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_guard_would_catch_the_defect_it_was_written_for(self):
        """A guard that cannot fail is decoration - so reproduce the original mistake."""
        import support

        class Sample(unittest.TestCase):
            @support.requires_pyoxigraph          # the misuse, verbatim
            def test_silently_removed(self):      # pragma: no cover - never collected
                raise AssertionError("unreachable")

        self.assertIsNone(
            getattr(Sample, "test_silently_removed"),
            "if this is callable, the helper became a real decorator and this guard is "
            "checking a defect that can no longer happen",
        )
        self.assertNotIn(
            "test_silently_removed",
            unittest.TestLoader().getTestCaseNames(Sample),
            "unittest should not collect it, which is what makes the failure silent",
        )
