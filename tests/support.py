"""Shared test helpers: paths, fixture loading, and the real IRIs tests assert on."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for scripts in (
    ROOT / "skills" / "linked-archi-source" / "scripts",
    ROOT / "skills" / "linked-archi-profile" / "scripts",
    ROOT / "skills" / "linked-archi-connect" / "scripts",
    ROOT / "skills" / "linked-archi-query" / "scripts",
    ROOT / "skills" / "linked-archi-validate" / "scripts",
    ROOT / "skills" / "linked-archi-analyse" / "scripts",
):
    sys.path.insert(0, str(scripts))

FIXTURES = ROOT / "fixtures"
BASE = FIXTURES / "base.trig"
AUGMENTED = FIXTURES / "augmented.trig"
FLAT = FIXTURES / "flat.ttl"
#: The final 1.3 graph layout, from a real multi-input conversion. A different shape
#: from BASE, not a newer version of it: model resources in ``graph/model``,
#: membership as ``arch:inModel``, and a semantic graph partitioned per input.
#: Both files carry the same ``schema:softwareVersion``, which is why fixtures are
#: told apart by shape - see ``tests/test_fixtures.py`` and ``fixtures/PROVENANCE.md``.
CONVERTER_13 = FIXTURES / "converter-1.3.trig"
#: Published vocabulary - the BPMN taxonomy and the classes it groups, plus the core
#: property axioms. Not converter output: the converters emit no ontology, which is why a
#: template that needs the class hierarchy has to be given it.
#:
#: Turtle, deliberately, because that is what `meta.linked.archi` serves and therefore
#: what an operator actually pairs. It was a named-graph `.trig` first, which made the
#: fixture easier than reality: the same triples returned five rows from a named graph and
#: none from the default graph a Turtle file loads into, with no error either way.
VOCABULARY = FIXTURES / "vocabulary.ttl"
#: Published SHACL: which relationship may connect which element types. No conversion
#: emits it, and `rdfs:domain`/`rdfs:range` cannot express it for the unqualified (direct
#: triple) forms - those carry neither. See ``fixtures/PROVENANCE.md``.
SHAPES = FIXTURES / "shapes.ttl"

#: Real IRIs from real converter output, present in the committed fixtures. Tests
#: assert against these rather than inventing IRIs, so a test that passes is
#: evidence about the actual graph shape.
BPMN_TASK = "https://example.org/la/bpmn/order-fulfillment/element/Task_Payment"
BPMN_LAST_TASK = "https://example.org/la/bpmn/order-fulfillment/element/Task_Ship"
BPMN_PROCESS = "https://example.org/la/bpmn/order-fulfillment/element/OrderFulfillment"
#: The BPMN *model*, not the process inside it. Membership queries anchor on the model,
#: which is what core/models and core/resolve-model return.
BPMN_MODEL = "https://example.org/la/bpmn/order-fulfillment"
ARCHIMATE_ELEMENT = "https://example.org/la/model/archisurance/element/id-861"
C4_CONTAINER = "https://example.org/la/c4/commerce-platform/element/2"
#: A view that really places three elements in the augmented fixture, so a floor of 3
#: is a fact about converter output rather than a number chosen to make a test pass.
C4_VIEW = "https://example.org/la/c4/commerce-platform/view/Containers"
#: A second view of the same model, so a diff between two views is a real difference
#: rather than a comparison with an empty set. It places 2 elements, one shared with
#: C4_VIEW.
C4_CONTEXT_VIEW = "https://example.org/la/c4/commerce-platform/view/Context"
BACKSTAGE_COMPONENT = (
    "https://example.org/la/backstage/commerce-catalog/element/component/default/"
    "order-service"
)

CORE = "https://meta.linked.archi/core#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
TAX_ROOT = "https://meta.linked.archi/core-tax#ArchComponent"
#: An unqualified predicate the augmented fixture really asserts, with a chain to walk.
#: ``arch:unqualifiedForm`` declares it for ``am:Flow``, which is why a direct triple
#: exists for it at all - see fixtures/PROVENANCE.md on where direct predicates come from.
ARCHIMATE_FLOWS_TO = "https://meta.linked.archi/archimate3/onto#flowsTo"
#: An element with an outgoing ``am:flowsTo`` edge in the augmented fixture.
ARCHIMATE_FLOW_SOURCE = "https://example.org/la/model/archisurance/element/id-528"


def requires_pyshacl(test: unittest.TestCase) -> None:
    """Skip when the validate owner's dependencies are absent.

    Same reasoning as pyoxigraph below: validation is one owner's concern, and a
    contributor without it should still be able to run and trust the rest of the suite.
    """
    try:
        import pyshacl  # noqa: F401
        import rdflib  # noqa: F401
    except ModuleNotFoundError:  # pragma: no cover - environment dependent
        test.skipTest("pyshacl is not installed")


def requires_pyoxigraph(test: unittest.TestCase) -> None:
    """Skip a test when the local adapter's dependency is absent.

    Skipping is right rather than failing: the endpoint adapter needs nothing beyond
    the standard library, so a contributor without pyoxigraph can still run and trust
    most of the suite.
    """
    try:
        import pyoxigraph  # noqa: F401
    except ModuleNotFoundError:  # pragma: no cover - environment dependent
        test.skipTest("pyoxigraph is not installed")


_STORES: dict[Path, object] = {}


def load_fixture(*paths: Path):
    """Open one or more fixtures through the local adapter, once per combination.

    Parsing the same 900 quads for every test class is wasted time, and the adapter is
    read-only so sharing one is safe.

    Several paths is how a dataset is paired with published vocabulary at query time:
    the converters emit no ontology, so `vocabulary.ttl` is attached beside the data
    rather than baked into it. The adapter already accepted a list; only this helper
    insisted on one file.
    """
    key = paths if len(paths) > 1 else paths[0]
    if key not in _STORES:
        from linked_archi_connect.adapters import open_adapter
        _STORES[key] = open_adapter(data=list(paths))
    return _STORES[key]


def load_resolved_profile(reference: str):
    """Resolve through the profile owner, then consume only the query contract."""
    from linked_archi_profile import load_profile
    from linked_archi_query import ResolvedProfile

    return ResolvedProfile(load_profile(reference).resolved_snapshot())
