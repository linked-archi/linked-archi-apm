"""Use the published ArchiMate 4 sources when they are present beside the APM checkout."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import support
from linked_archi_profile.derive import derive_profile, read_metamodel
from linked_archi_profile.profile import _verify_metamodel_pairing
from linked_archi_query import load_catalog, render


META = support.ROOT.parents[2] / "linked-archi-meta/modelingLanguages/archimate/4.0"
MANIFEST = META / "archimate4-metamodel.ttl"
VIEWPOINTS = META / "archimate4-viewpoints.ttl"
TAXONOMY = META / "archimate4-tax.ttl"


class TestPublishedArchiMate4Schemes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.requires_pyoxigraph(cls)
        if not all(path.is_file() for path in (MANIFEST, VIEWPOINTS, TAXONOMY)):
            raise unittest.SkipTest("the linked-archi-meta checkout is not beside APM")

    def test_manifest_derivation_preserves_exact_scheme_iris(self):
        info = read_metamodel(MANIFEST)
        self.assertEqual(info.assets["conceptClassification"],
                         ["https://meta.linked.archi/archimate4/tax#"])
        self.assertEqual(info.assets["viewpointLibrary"],
                         ["https://meta.linked.archi/archimate4/viewpoints#ViewpointCatalog"])
        derived = derive_profile("archimate4-test", metamodel=MANIFEST, notation="am4")
        self.assertEqual(derived.taxonomies[0]["scheme"], info.assets["conceptClassification"][0])
        self.assertEqual(derived.notations["am4"]["viewpoint_catalogs"],
                         info.assets["viewpointLibrary"])
        self.assertEqual(derived.notations["am4"]["viewpoint_resources"],
                         info.assets["architectureViewpoints"])
        namespace = derived.notations["am4"]["namespace"]
        self.assertEqual(derived.namespaces[namespace],
                         "https://meta.linked.archi/archimate4/onto#")

    def test_query_reads_published_catalog_and_taxonomy(self):
        from linked_archi_connect.adapters import open_adapter

        profile = support.load_resolved_profile("with-vocabulary")
        catalog = load_catalog()
        adapter = open_adapter(data=[VIEWPOINTS, TAXONOMY])
        resolved = render("core/resolve-vocabulary-concept", profile,
                          {"TERM": "Application Domain"}, catalog=catalog)
        category_rows = adapter.execute(
            resolved.query, template="core/resolve-vocabulary-concept",
            profile_id=profile.name, profile_version=profile.profile_version,
            limit=200,
        ).rows
        # The exact name is the taxonomy's category. Other schemes may offer looser
        # candidates, ranked after it - the published catalogue has a viewpoint called
        # "Application domain, multiple aspects" - which is what review is for.
        self.assertEqual({row["scheme"] for row in category_rows if row["rank"] == "1 exact"},
                         {"https://meta.linked.archi/archimate4/tax#"})
        self.assertEqual(category_rows[0]["concept"],
                         "https://meta.linked.archi/archimate4/tax#ApplicationDomain")
        listed = render("core/viewpoint-catalog", profile, {}, catalog=catalog)
        viewpoint_rows = adapter.execute(
            listed.query, template="core/viewpoint-catalog", profile_id=profile.name,
            profile_version=profile.profile_version, limit=3000,
        ).rows
        self.assertIn("https://meta.linked.archi/archimate4/viewpoints#CapabilityMapViewpoint",
                      {row["viewpoint"] for row in viewpoint_rows})

    def test_verification_detects_a_missing_viewpoint_catalog(self):
        from linked_archi_connect.adapters import open_adapter
        from linked_archi_profile import load_profile

        with TemporaryDirectory() as directory:
            model = Path(directory) / "model.ttl"
            model.write_text(
                "<https://example.org/model> "
                "<https://meta.linked.archi/core#modelConformsToMetamodel> "
                "<https://meta.linked.archi/archimate4/metamodel#ArchiMate4> .\n",
                encoding="utf-8",
            )
            derived = derive_profile("archimate4-test", metamodel=MANIFEST, notation="am4",
                                     extends="examples/with-vocabulary.yaml")
            profile_path = derived.write(Path(directory) / "profile.yaml")
            profile = load_profile(profile_path)
            without = _verify_metamodel_pairing(
                profile, open_adapter(data=[model, MANIFEST, TAXONOMY])
            )
            self.assertTrue(any("viewpoint catalog" in finding.message
                                for finding in without if finding.subject == "metamodel.assets"))
            with_catalog = _verify_metamodel_pairing(
                profile, open_adapter(data=[model, MANIFEST, TAXONOMY, VIEWPOINTS])
            )
            self.assertFalse(any("viewpoint catalog" in finding.message
                                 for finding in with_catalog if finding.subject == "metamodel.assets"))
