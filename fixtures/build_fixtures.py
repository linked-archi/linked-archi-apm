#!/usr/bin/env python3
"""Build the committed fixtures by extracting from real converter output.

Run through ``make fixtures``. Reads the ``.trig`` files the Linked.Archi
converters produce, keeps a small connected subset, and writes the fixtures the
test suite runs against.

Extraction rather than authoring is the point. Hand-written RDF drifts from what
the converters actually emit - which is how the package this one replaces ended up
testing 15 templates against a vocabulary that did not exist. Everything in
``base.trig`` is a real quad from a real conversion; only the selection is ours.

Two fixtures cannot be extracted, because the converters do not produce them:

``augmented.trig``  adds direct relationship triples, cross-source identity
                    assertions, taxonomy classifications and a SHACL report.
                    Direct triples are derived from the qualified relationships
                    already present, so their shape follows the data. The rest is
                    authored, and is what the gated templates need in order to be
                    testable at all.
``flat.ttl``        the same content with graph identity discarded, which is what
                    the converters' Turtle output collapses to. Exercises the
                    ``single`` layout.

``converter-1.3.trig`` is real converter output too, but it is NOT built by the
default run, and it is not trimmed at all. It is a separate step
(``--rebuild-13``) because producing it needs the converter jars and a JDK, not
just a checked-in ``out/`` directory. See ``recipe_13()`` for the exact
invocation and :func:`refresh_converter_13` for the shape it is required to have.

Why it exists is worth stating, because it is the failure this whole file is
meant to prevent, found in the fixtures themselves. The ``out/*.trig`` files the
default run extracts from are stamped ``1.3.0-SNAPSHOT`` and yet carry none of
the graph layout that version emits: no direct membership edge, no ``graph/model``,
no partitioned semantic graphs. They were produced by an earlier build wearing
the same label. ``1.3.0-SNAPSHOT`` is a moving label, so a version stamp cannot
tell two shapes apart - which is why the fixtures are distinguished by shape, and
why ``tests/test_fixtures.py`` asserts the shape of each one rather than trusting
what it says about itself.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent
REPO = FIXTURES.parent
sys.path.insert(0, str(REPO / "lib"))

CONVERTERS = REPO.parent.parent / "converters"
SOURCES = {
    "bpmn": CONVERTERS / "example-architecture-project/out/bpmn.trig",
    "c4": CONVERTERS / "example-architecture-project/out/structurizr.trig",
    "backstage": CONVERTERS / "example-architecture-project/out/backstage.trig",
    "leanix": CONVERTERS / "example-architecture-project/out/leanix.trig",
    "archimate": CONVERTERS / "linked-archi-converters/playground/out/archisurance.trig",
}

#: How many elements to keep per model. Small enough to read, large enough that a
#: two-hop traversal has somewhere to go.
ELEMENT_BUDGET = 12

#: How many view nodes to keep per views graph. Geometry and a style blank node per
#: node add up fast, and a fixture nobody can read is a fixture that drifts.
VIEW_NODE_BUDGET = 6

#: Containers holding a kept element - a BPMN Process, a C4 system.
PARENT_BUDGET = 3

#: Deliberately unconnected elements, so the model-quality templates have something
#: to find. A fixture with no gaps is tidier than any real model.
ORPHAN_BUDGET = 2

CORE = "https://meta.linked.archi/core#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
TAX = "https://meta.linked.archi/core-tax#"


def _quads_for(store, graph):
    return [q for q in store if q.graph_name == graph]


def extract(paths: dict[str, Path]) -> "tuple[object, list[str]]":
    """Load the sources and keep a connected subset of each model."""
    from pyoxigraph import BlankNode, NamedNode, RdfFormat, Store

    source_store = Store()
    notes: list[str] = []
    for label, path in paths.items():
        if not path.is_file():
            notes.append(f"MISSING {label}: {path}")
            continue
        with path.open("rb") as handle:
            source_store.bulk_load(handle, RdfFormat.TRIG)
        notes.append(f"{label:10} {path.relative_to(CONVERTERS.parent)}")

    kept = Store()
    rel_class = NamedNode(f"{CORE}QualifiedRelationship")
    src, tgt = NamedNode(f"{CORE}source"), NamedNode(f"{CORE}target")

    graphs = sorted({str(q.graph_name.value) for q in source_store}, key=str)
    semantic = [g for g in graphs if g.endswith("graph/semantic")]

    for graph_iri in semantic:
        graph = NamedNode(graph_iri)
        model_prefix = graph_iri[: -len("/graph/semantic")]

        element_class = NamedNode(f"{CORE}Element")
        rdf_type = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")

        def notation_types(node):
            return {
                str(q.object.value)
                for q in source_store.quads_for_pattern(node, rdf_type, None, graph)
                if not str(q.object.value).startswith(CORE)
            }

        # Relationships first: they decide which elements are worth keeping, since
        # an element with no relationship makes every traversal template vacuous.
        #
        # Relationships joining DIFFERENT element types are preferred, because a
        # fixture whose every edge connects two things of the same kind cannot
        # exercise a cross-layer or cross-notation question - and those are the
        # questions the graph exists to answer.
        relationships = [
            q.subject for q in source_store.quads_for_pattern(None, None, rel_class, graph)
        ]

        def diversity(rel):
            ends = [q.object for q in source_store.quads_for_pattern(rel, src, None, graph)]
            ends += [q.object for q in source_store.quads_for_pattern(rel, tgt, None, graph)]
            if len(ends) < 2:
                return 0
            return 1 if notation_types(ends[0]) != notation_types(ends[1]) else 0

        relationships.sort(key=diversity, reverse=True)

        keep_elements: set = set()
        keep_relationships: list = []
        for rel in relationships:
            ends = [
                q.object for q in source_store.quads_for_pattern(rel, src, None, graph)
            ] + [q.object for q in source_store.quads_for_pattern(rel, tgt, None, graph)]
            if len(keep_elements | set(ends)) > ELEMENT_BUDGET and keep_relationships:
                continue
            keep_elements |= set(ends)
            keep_relationships.append(rel)

        # Containers that hold a kept element - a BPMN Process owning its flows, a C4
        # system owning its containers. They are reached by a predicate rather than a
        # relationship resource, so the pass above never sees them, and without them
        # notation/bpmn/process-flow has no process to ask about. Folders and blank
        # list items are excluded: they are structure, not architecture.
        parents: set = set()
        for element in list(keep_elements):
            for quad in source_store.quads_for_pattern(None, None, element, graph):
                candidate = quad.subject
                if isinstance(candidate, BlankNode) or candidate in keep_elements:
                    continue
                is_element = any(
                    source_store.quads_for_pattern(candidate, rdf_type, element_class, graph)
                )
                if is_element:
                    parents.add(candidate)
        keep_elements |= set(list(parents)[:PARENT_BUDGET])

        # A couple of genuinely unconnected elements, so core/orphans has something
        # to find. Selecting only well-connected elements would make the fixture
        # tidier than any real model and leave the model-quality templates untested.
        orphans = [
            q.subject
            for q in source_store.quads_for_pattern(None, rdf_type, element_class, graph)
            if q.subject not in keep_elements
            and not any(source_store.quads_for_pattern(None, src, q.subject, graph))
            and not any(source_store.quads_for_pattern(None, tgt, q.subject, graph))
        ]
        keep_elements |= set(orphans[:ORPHAN_BUDGET])

        subjects = set(keep_elements) | set(keep_relationships)
        # Any model-level triple still in the semantic graph. In the 1.3 layout the model
        # resource itself moved to `graph/model`, kept verbatim below, so this usually adds
        # nothing - but it costs nothing and keeps the extraction correct for output that
        # still declares the model here.
        subjects.add(NamedNode(model_prefix))

        for subject in subjects:
            for quad in source_store.quads_for_pattern(subject, None, None, graph):
                kept.add(quad)

        # Provenance verbatim: it is a dozen quads per model and trimming it would
        # defeat the point of having it.
        provenance = f"{model_prefix}/graph/provenance"
        if provenance in graphs:
            for quad in _quads_for(source_store, NamedNode(provenance)):
                kept.add(quad)

        # The model graph verbatim, for the same reason. `arch:Model`, its metamodel
        # conformance and the folder tree live here in the 1.3 layout, having moved out of
        # the semantic graph - so an extraction that skips it produces a fixture where
        # `core/models` and every model-level question have nothing to read. That is exactly
        # what the first 1.3 extraction did, silently, because this block did not exist.
        model_graph = f"{model_prefix}/graph/model"
        if model_graph in graphs:
            for quad in _quads_for(source_store, NamedNode(model_graph)):
                kept.add(quad)

        # Views trimmed, and trimmed hard. One ArchiMate model contributes over a
        # thousand nodes with geometry and a style blank node each, which would make
        # the fixture unreviewable - and a fixture nobody reads is a fixture that
        # drifts. Keep the nodes that point at elements we kept, then top up so the
        # stale ArchiMate output (which predates archvis:archElement) still
        # contributes something.
        views_iri = f"{model_prefix}/graph/views"
        if views_iri not in graphs:
            continue
        views = NamedNode(views_iri)
        node_element = NamedNode("https://meta.linked.archi/core-vis#archElement")
        view_ref = NamedNode("https://meta.linked.archi/core-vis#view")

        linked = {
            q.subject
            for q in source_store.quads_for_pattern(None, node_element, None, views)
            if q.object in keep_elements
        }
        if len(linked) < VIEW_NODE_BUDGET:
            spare = [
                q.subject
                for q in source_store.quads_for_pattern(None, view_ref, None, views)
                if q.subject not in linked
            ]
            linked |= set(spare[: VIEW_NODE_BUDGET - len(linked)])

        referenced_views = set()
        for node in linked:
            for quad in source_store.quads_for_pattern(node, None, None, views):
                kept.add(quad)
                if quad.predicate == view_ref:
                    referenced_views.add(quad.object)
                # Style is a blank node hanging off the node; without it the node
                # keeps a dangling reference.
                if isinstance(quad.object, BlankNode):
                    for nested in source_store.quads_for_pattern(
                        quad.object, None, None, views
                    ):
                        kept.add(nested)

        # The arch:View resources those nodes belong to, from the SEMANTIC graph.
        # Easy to forget, because the nodes are in the views graph and look like the
        # whole story - but a view's label, viewpoint and model membership live with
        # the model, so without this core/views returns nothing while the views graph
        # is visibly populated.
        for view in referenced_views:
            for quad in source_store.quads_for_pattern(view, None, None, graph):
                kept.add(quad)

    return kept, notes


# --------------------------------------------------------------------------
# converter-1.3.trig - the final 1.3 graph layout, from a multi-input conversion
# --------------------------------------------------------------------------

#: The 1.3 fixture. Committed verbatim: no trimming, no selection, no additions.
CONVERTER_13 = FIXTURES / "converter-1.3.trig"

#: The three markers that distinguish the final 1.3 layout from everything the
#: default ``out/`` extraction produces. All three are required, and
#: :func:`refresh_converter_13` refuses a file missing any of them.
#:
#: The nested semantic graph is the one that needs a MULTI-input conversion.
#: ``IriMinting`` partitions the semantic graph "by input where a model has more
#: than one", so a single-file conversion emits a plain ``graph/semantic`` and
#: proves nothing about the partitioned shape.
MARKERS_13 = ("arch:inModel", "a graph/model graph", "a partitioned semantic graph")

#: Which entities go to which synthetic repository. Splitting the example
#: catalog is what makes the conversion multi-input; the split itself is the only
#: authored decision, and it changes no triple's content.
SPLIT_13 = {"catalogs/orders/order-service.yaml": "order",
            "catalogs/payments/payment-service.yaml": None}

#: Pinned so a rebuild diffs cleanly against the committed fixture. Real commits
#: and checksums, had they been real, would rotate on every pull; these do not.
SOURCE_MAP_13 = """\
backstageCatalogSources: "1"
pulledAt: 2026-09-02T10:00:00Z
catalogs:
  - file: catalogs/orders/order-service.yaml
    repo: https://git.example.org/group/order-service
    ref: main
    commit: 4f2c1ab8e0d1c2b3a4958677889900aabbccddee
    path: catalog-info.yaml
    blobUrl: https://git.example.org/group/order-service/-/blob/4f2c1ab8e0/catalog-info.yaml
    contentSha256: 4c294617b60715c1d218e61164a3abd4808a4284cbc30e6728a01ad9aada4481
  - file: catalogs/payments/payment-service.yaml
    repo: https://git.example.org/group/payment-service
    ref: main
    commit: 99aabbccddee00112233445566778899aabbccdd
    path: catalog-info.yaml
    blobUrl: https://git.example.org/group/payment-service/-/blob/99aabbccdd/catalog-info.yaml
    contentSha256: 91b1d4de1c1f4f7c9a2b3c4d5e6f70819293a4b5c6d7e8f90a1b2c3d4e5f6071
"""

#: Where the Backstage catalog the split is derived from lives.
CATALOG_13 = CONVERTERS / "example-architecture-project/models/backstage/catalog-info.yaml"

#: The converter jar. A fat jar, so ``java -jar`` is enough - no installDist, which
#: matters because installDist copies every dependency and needs disk this fixture
#: was first built without.
JAR_13 = (CONVERTERS / "linked-archi-converters/converter-backstage/build/libs"
          / "backstage2linkedarchi.jar")


def write_13_inputs(dest: Path) -> list[str]:
    """Write the multi-repo input layout the 1.3 fixture is converted from.

    Derived from the converter project's own ``catalog-info.yaml``: the entity
    descriptors are copied unchanged and only distributed across two directories,
    so the conversion has two sources and the semantic graph gets partitioned.
    """
    if not CATALOG_13.is_file():
        raise FileNotFoundError(f"no Backstage catalog at {CATALOG_13}")

    documents = [d for d in CATALOG_13.read_text("utf-8").split("\n---\n") if d.strip()]
    markers = [m for m in SPLIT_13.values() if m]
    written = []
    for relative, marker in SPLIT_13.items():
        if marker:
            chosen = [d for d in documents if marker in d.lower()]
        else:
            # The remainder, so every descriptor lands in exactly one repository
            # and the conversion cannot double-count.
            chosen = [d for d in documents
                      if not any(m in d.lower() for m in markers)]
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n---\n".join(chosen) + "\n", "utf-8")
        written.append(f"{relative}  ({len(chosen)} descriptor(s))")

    (dest / "source-map.yaml").write_text(SOURCE_MAP_13, "utf-8")
    written.append("source-map.yaml")
    return written


def recipe_13(inputs: Path = Path("<inputs>")) -> str:
    """The exact invocation that produced the committed fixture."""
    return f"""\
  # 1. write the multi-repo input layout
  python3 fixtures/build_fixtures.py --emit-13-inputs {inputs}

  # 2. convert it. A JDK matching the one the jar was built with is required -
  #    the jar is class file 69 (Java 25), and a Java 21 runtime refuses it with
  #    UnsupportedClassVersionError. Point JAVA at that JDK.
  cd {inputs} && $JAVA -jar {JAR_13} convert catalogs/ \\
      --base-iri https://example.org/la/ \\
      --source-map source-map.yaml \\
      --model-id usl-api-registry \\
      --image-ref 'registry.gitlab.com/linked-archi/converters@sha256:89ab' \\
      -o /tmp/converter-1.3.trig

  # 3. install it, which verifies the shape before overwriting anything
  python3 fixtures/build_fixtures.py --rebuild-13 /tmp/converter-1.3.trig

--source-map and --image-ref are not optional decoration. Without the source map
the conversion has one source and emits an unpartitioned graph/semantic; without
the image reference the agent record carries no dct:identifier. Several
provenance terms are conditional on them - see fixtures/PROVENANCE.md."""


def shape_13(path: Path) -> "tuple[dict[str, bool], dict[str, object]]":
    """Which 1.3 markers a TriG file carries, and a few counts worth reporting."""
    from pyoxigraph import NamedNode, RdfFormat, Store

    store = Store()
    with path.open("rb") as handle:
        store.bulk_load(handle, RdfFormat.TRIG)

    graphs = sorted({str(q.graph_name.value) for q in store})
    part_of_model = sum(
        1 for _ in store.quads_for_pattern(
            None, NamedNode(f"{CORE}inModel"), None, None)
    )
    model_graphs = [g for g in graphs if g.endswith("/graph/model")]
    partitioned = [
        g for g in graphs
        if "/graph/semantic/" in g and not g.endswith("/graph/semantic")
    ]
    present = {
        MARKERS_13[0]: part_of_model > 0,
        MARKERS_13[1]: bool(model_graphs),
        MARKERS_13[2]: bool(partitioned),
    }
    return present, {
        "quads": len(store),
        "graphs": len(graphs),
        "inModel": part_of_model,
        "partitions": len(partitioned),
        "graph_iris": graphs,
    }


def refresh_converter_13(source: Path) -> int:
    """Install a real 1.3 conversion as the fixture, refusing the wrong shape.

    The gate is the point. A fixture is only worth having if it demonstrates the
    thing it is named after, and the reason this fixture exists at all is that the
    version stamp on the older output claimed a shape the output did not have. So
    the shape is checked here rather than trusted, and a file that does not carry
    all three markers is rejected instead of quietly replacing a good fixture.
    """
    if not source.is_file():
        print(f"no such conversion output: {source}", file=sys.stderr)
        print("\nProduce one:\n" + recipe_13(), file=sys.stderr)
        return 2

    present, counts = shape_13(source)
    missing = [name for name, ok in present.items() if not ok]
    if missing:
        print(f"REFUSED {source}", file=sys.stderr)
        print("  not the final 1.3 layout - missing:", file=sys.stderr)
        for name in missing:
            print(f"    - {name}", file=sys.stderr)
        print(f"  graphs found: {counts['graphs']}", file=sys.stderr)
        for graph in counts["graph_iris"]:
            print(f"    {graph}", file=sys.stderr)
        print("\n  A conversion of a single input cannot produce a partitioned",
              file=sys.stderr)
        print("  semantic graph, however new the converter is.\n", file=sys.stderr)
        print(recipe_13(), file=sys.stderr)
        return 2

    shutil.copyfile(source, CONVERTER_13)
    print(f"{CONVERTER_13.name}  {counts['quads']} quads, "
          f"{counts['graphs']} named graphs, verbatim")
    print(f"  arch:inModel          {counts['inModel']}")
    print(f"  semantic partitions   {counts['partitions']}")
    for graph in counts["graph_iris"]:
        print(f"    {graph}")
    return 0


#: rdf:reifies, the RDF 1.2 bridge from a qualified resource to a triple term.
REIFIES = "http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies"



#: Extracted class-to-predicate pairs. See ``--refresh-forms``.
FORMS_FILE = FIXTURES / "unqualified-forms.json"


def load_unqualified_forms() -> dict[str, str]:
    """The ontologies' ``arch:unqualifiedForm`` pairs, as extracted.

    Read from a committed file rather than from the ontologies directly, so the
    fixture build is reproducible without a checkout of ``linked-archi-meta``.
    ``--refresh-forms`` is how the file gets updated.
    """
    import json

    if not FORMS_FILE.is_file():
        return {}
    return json.loads(FORMS_FILE.read_text("utf-8")).get("unqualified_forms", {})


def refresh_unqualified_forms(meta_root: Path) -> int:
    """Re-extract the pairs from a ``linked-archi-meta`` checkout."""
    import datetime
    import json

    from pyoxigraph import RdfFormat, Store

    files = sorted(
        set(meta_root.glob("modelingLanguages/**/*.ttl"))
        | set(meta_root.glob("core/**/*.ttl"))
    )
    if not files:
        print(f"no ontology files under {meta_root}", file=sys.stderr)
        return 0

    store, loaded = Store(), 0
    for path in files:
        try:
            store.load(path=str(path), format=RdfFormat.TURTLE)
            loaded += 1
        except Exception:  # a malformed or non-ontology .ttl is not fatal here
            continue

    pairs: dict[str, str] = {}
    for row in store.query(
        f"SELECT ?c ?u WHERE {{ ?c <{CORE}unqualifiedForm> ?u }}"
    ):
        cls, pred = str(row["c"])[1:-1], str(row["u"])[1:-1]
        # Keep only class -> predicate. The ontologies also declare the pair on the
        # qualified *property* (am:qualifiedServes), which is the same mapping from
        # the other side and would collide on the same key space.
        local = cls.rsplit("#", 1)[-1]
        if not local[:1].isupper():
            continue
        pairs[cls] = pred

    FORMS_FILE.write_text(
        json.dumps(
            {
                "_comment": (
                    "Extracted, not authored. arch:unqualifiedForm pairs from the "
                    "linked-archi-meta ontologies: qualified relationship class -> "
                    "unqualified predicate. Refresh with "
                    "`python3 fixtures/build_fixtures.py --refresh-forms`."
                ),
                "_source": "linked-archi-meta/modelingLanguages/**/*.ttl and core/**/*.ttl",
                "_extracted": datetime.date.today().isoformat(),
                "_pair_count": len(pairs),
                "unqualified_forms": dict(sorted(pairs.items())),
            },
            indent=2,
        )
        + "\n",
        "utf-8",
    )
    print(f"{FORMS_FILE.name}: {len(pairs)} pair(s) from {loaded} ontology file(s)")
    return len(pairs)


# --------------------------------------------------------------------------
# Published constraints - what says whether a query's PATH makes sense
# --------------------------------------------------------------------------
#
# A conversion emits instances. Nothing in it says which relationship may connect
# which element type, so a query can traverse a path the metamodel forbids, return
# nothing, and read as evidence of absence. Two published artifacts answer that, and
# they answer it for different relationship forms:
#
#   rdfs:domain / rdfs:range   in `core/core-onto.ttl`. Covers the core predicates -
#                              arch:source, arch:target, arch:inModel and the rest -
#                              which is what an Ontology-Based Query Check walks
#                              (Allemang & Sequeda, arXiv:2405.11706).
#
#   SHACL node shapes          in `modelingLanguages/**/-shapes.ttl`. The UNQUALIFIED
#                              (direct triple) forms have no domain or range at all,
#                              so RDFS says nothing about them whatsoever. Validity is
#                              declared only as SHACL: a node shape per source class,
#                              one sh:property per predicate, and sh:or over the target
#                              classes allowed. That is the same (source, predicate,
#                              target) table the RDFS rules need, in a different
#                              vocabulary - and extending the check to read it is what
#                              the paper does not do.
#
# Both are PUBLISHED, never converted, so they are paired at query time by the
# operator - like `vocabulary.trig` and for the same reason. These fixtures exist so
# the check is testable, not so it ships with a metamodel baked in.

VOCABULARY_FILE = FIXTURES / "vocabulary.trig"
VOCABULARY_GRAPH = "https://meta.linked.archi/graph/vocabulary"
SHAPES_FILE = FIXTURES / "shapes.trig"
SHAPES_GRAPH = "https://meta.linked.archi/graph/shapes"

RDFS = "http://www.w3.org/2000/01/rdf-schema#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SH = "http://www.w3.org/ns/shacl#"

#: The axioms a query check reads, and nothing else. Labels are included because a
#: violation naming `arch:source` is less use than one naming "source".
AXIOM_PREDICATES = (
    f"{RDFS}domain", f"{RDFS}range", f"{RDFS}subPropertyOf",
    f"{RDFS}subClassOf", f"{RDF_NS}type", f"{RDFS}label", f"{SKOS}prefLabel",
)

#: Which shapes to carry, named rather than matched.
#:
#: Selecting by "every class the fixture data uses" was tried and is wrong twice over.
#: It pulled in 45 shapes, most of them attribute constraints - API visibility,
#: lifecycle state, entity labels - which say nothing about whether a relationship is
#: allowed, and it produced a 586 kB file of blank-node soup that no reader could check
#: by eye. Both defeat the purpose.
#:
#: So the selection covers every SHACL CONSTRUCT a shape reader has to handle, one
#: instance each, and nothing else:
SHAPE_SELECTION = {
    # Unqualified, published directly: sh:property per direct predicate, sh:or over
    # the allowed target classes. Only ArchiMate publishes this form.
    "https://meta.linked.archi/archimate3/shapes#BusinessRoleRelShape":
        "unqualified predicates, published (ArchiMate only)",
    # Qualified: sh:or over sh:and pairs, each pinning arch:source to one class and
    # arch:target to an sh:or list. The nesting is what makes ArchiMate's matrix
    # distinctive, and Aggregation is the smallest of the eleven that augmented.trig
    # exercises - 361 valid pairs against Association's 3600.
    "https://meta.linked.archi/archimate3/shapes#AggregationShape":
        "qualified relationship, sh:or over sh:and source/target pairs",
    # Qualified with a flat sh:class on the source: the shape most notations publish.
    # Backstage declares no unqualified constraint, so bs:ownedBy has to be DERIVED
    # from this shape through arch:unqualifiedForm. That derivation is the reason this
    # one is here.
    "https://meta.linked.archi/backstage/shapes#OwnershipShape":
        "qualified relationship, unqualified form must be derived",
    # The shared shape every relationship is subject to, whatever the notation.
    "https://meta.linked.archi/core-shapes#QualifiedRelationshipShape":
        "core constraint on every qualified relationship",
}

#: Where the shapes come from. ArchiMate is the only notation that publishes the
#: unqualified form as well as the qualified one; for the others the unqualified
#: constraint has to be DERIVED, by following `arch:unqualifiedForm` from the
#: relationship class to its direct predicate and reusing the qualified shape's
#: source and target classes. Carrying both kinds here is what makes that
#: derivation testable against a notation that publishes the answer directly.
SHAPE_SOURCES = (
    "modelingLanguages/archimate/3.2/archimate3.2-relationship-shapes.ttl",
    "modelingLanguages/backstage/backstage-shapes.ttl",
    "modelingLanguages/leanIX/leanIX-shapes.ttl",
    "modelingLanguages/c4/c4-shapes.ttl",
    "core/core-shapes.ttl",
)


def _describe(store, subject, into: set, seen: set | None = None) -> None:
    """Add ``subject``'s triples to ``into``, following blank nodes to the end.

    A node shape is mostly blank nodes: every ``sh:property`` is one, every
    ``sh:or`` is an RDF list of them. Copying the named subject's triples alone
    would produce a shape whose constraints all dangle.
    """
    from pyoxigraph import BlankNode

    seen = seen if seen is not None else set()
    key = subject.value if hasattr(subject, "value") else str(subject)
    if key in seen:
        return
    seen.add(key)
    for quad in store.quads_for_pattern(subject, None, None):
        into.add((quad.subject, quad.predicate, quad.object))
        if isinstance(quad.object, BlankNode):
            _describe(store, quad.object, into, seen)


def _load_all(paths) -> object:
    from pyoxigraph import RdfFormat, Store

    store = Store()
    for path in paths:
        store.load(path=str(path), format=RdfFormat.TURTLE)
    return store


def refresh_vocabulary_axioms(meta_root: Path) -> int:
    """Add `core-onto.ttl`'s property axioms to the vocabulary fixture.

    Additive on purpose. The BPMN taxonomy already in the fixture is what
    `core/elements-by-category` reads, and rebuilding it from the published
    selection rule produces 298 triples rather than the committed 253 - the
    subClassOf walk reaches further than the original selection did. Replacing it
    would move a template's row floor as a side effect of adding axioms, so this
    only ever adds, and only in the core namespace it owns.
    """
    from pyoxigraph import NamedNode, Quad, RdfFormat, Store

    source = meta_root / "core/core-onto.ttl"
    if not source.is_file():
        print(f"no core ontology at {source}", file=sys.stderr)
        return 0
    onto = _load_all([source])

    fixture = Store()
    if VOCABULARY_FILE.is_file():
        fixture.load(path=str(VOCABULARY_FILE), format=RdfFormat.TRIG)
    before = len(fixture)

    # Idempotent: drop what a previous run of this function put here. Nothing else
    # in the fixture has a core-namespace subject - the committed content is all
    # bpmn/tax and bpmn/onto - so ownership is unambiguous.
    for quad in list(fixture):
        if quad.subject.value.startswith(CORE):
            fixture.remove(quad)

    graph = NamedNode(VOCABULARY_GRAPH)
    terms: set[str] = set()
    for predicate in (f"{RDFS}domain", f"{RDFS}range"):
        for row in onto.query(f"SELECT ?p ?o WHERE {{ ?p <{predicate}> ?o }}"):
            if not str(row["p"]).startswith(f"<{CORE}"):
                continue
            terms.add(str(row["p"]))
            if isinstance(row["o"], NamedNode) and row["o"].value.startswith(CORE):
                terms.add(f"<{row['o'].value}>")

    added = 0
    for term in sorted(terms):
        for predicate in AXIOM_PREDICATES:
            for row in onto.query(f"SELECT ?o WHERE {{ {term} <{predicate}> ?o }}"):
                quad = Quad(NamedNode(term[1:-1]), NamedNode(predicate), row["o"], graph)
                if quad not in fixture:
                    fixture.add(quad)
                    added += 1

    write(fixture, VOCABULARY_FILE, "TRIG")
    print(f"{VOCABULARY_FILE.name}: {before} -> {len(fixture)} quads "
          f"({added} axiom quad(s) for {len(terms)} core term(s))")
    return added


def refresh_shapes(meta_root: Path) -> int:
    """Extract the SHACL relationship constraints the fixtures exercise.

    Whole node shapes, never a slice of one. Narrowing an ``sh:or`` list is not
    taking a subset of the truth the way trimming instance data is - it makes
    something the metamodel permits look forbidden. So a shape is either carried
    complete or left out, and a checker that finds no shape for a class must report
    that it has no constraint rather than that the query is fine.

    Which shapes, and why each one, is :data:`SHAPE_SELECTION`. A missing shape is an
    error rather than a smaller fixture: a selection that silently shrinks because an
    ontology moved would leave a construct untested and nothing would say so.
    """
    from pyoxigraph import NamedNode, Quad, Store

    missing = [p for p in SHAPE_SOURCES if not (meta_root / p).is_file()]
    if missing:
        for path in missing:
            print(f"no shapes at {meta_root / path}", file=sys.stderr)
        return 0
    shapes = _load_all([meta_root / p for p in SHAPE_SOURCES])

    triples: set = set()
    kept: list[str] = []
    for shape, why in SHAPE_SELECTION.items():
        node = NamedNode(shape)
        found = list(shapes.quads_for_pattern(node, None, None))
        if not found:
            print(f"REFUSED: {shape} is not in the published shapes", file=sys.stderr)
            return 0
        targets = [
            str(quad.object.value) for quad in found
            if quad.predicate.value == f"{SH}targetClass"
        ]
        _describe(shapes, node, triples)
        kept.append(f"{shape.rsplit('#', 1)[-1]:<28} {why}\n"
                    f"{'':30}targets {', '.join(t.rsplit('#', 1)[-1] for t in targets)}")

    graph = NamedNode(SHAPES_GRAPH)
    fixture = Store()
    for subject, predicate, obj in triples:
        fixture.add(Quad(subject, predicate, obj, graph))

    written = _write_nested_trig(fixture, SHAPES_FILE, graph)
    size = SHAPES_FILE.stat().st_size
    print(f"{SHAPES_FILE.name}: {written} quads, {len(kept)} shape(s), {size // 1024} kB")
    for line in kept:
        print(f"  {line}")
    return written


#: Prefixes only these fixtures need. The shape namespaces are where the node shapes
#: themselves live; without them every shape name is written out in full.
SHAPE_PREFIXES = {
    "amsh": "https://meta.linked.archi/archimate3/shapes#",
    "bssh": "https://meta.linked.archi/backstage/shapes#",
    "lxsh": "https://meta.linked.archi/leanix/shapes#",
    "c4sh": "https://meta.linked.archi/c4/shapes#",
    "coresh": "https://meta.linked.archi/core-shapes#",
}


def _write_nested_trig(store, path: Path, graph) -> int:
    """Write one named graph as TriG, with blank nodes nested and lists as collections.

    Worth the extra step because of what a shape IS. A node shape is almost entirely
    blank nodes - every ``sh:property`` is one, every ``sh:or`` is an RDF list of them -
    and pyoxigraph's serialiser writes each one as explicit ``rdf:first``/``rdf:rest``
    statements with generated labels. The same four shapes came to 261 kB that way, 58%
    of it list plumbing and 2,603 of 2,630 subjects a blank node: correct RDF that no
    reviewer could check against the published source. Nested, it is 33 kB and reads
    like the document it was extracted from.

    Verified rather than trusted: the result is parsed back and compared quad for quad,
    because the graph wrapper here is text assembly around a serialiser's output.
    """
    try:
        from rdflib import Dataset, Graph, URIRef  # noqa: F401
    except ModuleNotFoundError:
        print("nested output needs rdflib (a maintainer-only dependency, and already "
              "present with pyshacl):  pip install rdflib", file=sys.stderr)
        raise

    from pyoxigraph import RdfFormat, Store

    labels = _canonical_blank_labels(store)
    flat = Graph()
    for quad in store:
        # Every term goes through the same conversion. A pyoxigraph BlankNode also has
        # `.value`, so testing for that attribute silently turned each one into a
        # relative IRI - `<a006b55…>` instead of `_:a006b55…` - which is unparseable
        # and, worse, stops the serialiser nesting anything.
        flat.add((
            _rdflib_term(quad.subject, labels),
            _rdflib_term(quad.predicate, labels),
            _rdflib_term(quad.object, labels),
        ))
    for prefix, namespace in {**DUMP_PREFIXES, **SHAPE_PREFIXES}.items():
        flat.bind(prefix, namespace)

    turtle = flat.serialize(format="turtle")
    header = [line for line in turtle.splitlines() if line.startswith("@prefix")]
    body = [line for line in turtle.splitlines() if not line.startswith("@prefix")]
    document = (
        "\n".join(header)
        + f"\n\n<{graph.value}> {{\n"
        + "\n".join(f"    {line}" if line.strip() else "" for line in body).strip("\n")
        + "\n}\n"
    )
    path.write_text(document, encoding="utf-8")

    check = Store()
    check.load(path=str(path), format=RdfFormat.TRIG)
    if len(check) != len(store):
        raise SystemExit(
            f"REFUSED: {path.name} round-tripped to {len(check)} quads, not {len(store)}"
        )
    return len(check)


def _canonical_blank_labels(store) -> dict[str, str]:
    """Stable names for blank nodes, so a refresh diffs cleanly.

    Without this the file is correct and unreviewable: a store assigns fresh blank-node
    ids on every load, the serialiser orders sibling ``sh:property`` values by node
    identity, and so two runs over identical shapes produced 34 changed lines of
    reordered constraints. A rebuild has to diff clean or nobody can see a real change
    inside the noise.

    The name comes from the content - a hash over each node's own triples, with nested
    blank nodes contributing their hash - so equal structure always gets an equal name,
    and structure is all a blank node has. Memoised, because an ``sh:or`` list of 361
    entries is a 700-link chain and recomputing the tail per link is quadratic.
    """
    import hashlib
    from pyoxigraph import BlankNode

    outgoing: dict[str, list] = {}
    for quad in store:
        if isinstance(quad.subject, BlankNode):
            outgoing.setdefault(quad.subject.value, []).append(
                (quad.predicate.value, quad.object)
            )

    cache: dict[str, str] = {}

    def digest(label: str, guard: tuple[str, ...] = ()) -> str:
        if label in cache:
            return cache[label]
        if label in guard:  # shapes are trees today; a cycle must not hang the build
            return "cycle"
        parts = []
        for predicate, obj in outgoing.get(label, ()):
            if isinstance(obj, BlankNode):
                parts.append(f"{predicate} [{digest(obj.value, guard + (label,))}]")
            else:
                parts.append(f"{predicate} {obj}")
        value = hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()[:16]
        cache[label] = value
        return value

    # Deeply nested lists outrun the default recursion limit long before they outrun
    # memory, and this is a maintainer-only build step.
    previous = sys.getrecursionlimit()
    sys.setrecursionlimit(max(previous, 10_000))
    try:
        ordered = sorted(outgoing, key=lambda label: (digest(label), label))
    finally:
        sys.setrecursionlimit(previous)
    width = len(str(len(ordered)))
    return {
        label: f"b{index:0{width}d}" for index, label in enumerate(ordered, start=1)
    }


def _rdflib_term(term, labels: dict[str, str] | None = None):
    """One pyoxigraph term as its rdflib equivalent."""
    from rdflib import BNode, Literal as RdfLiteral, URIRef

    kind = type(term).__name__
    if kind == "BlankNode":
        return BNode((labels or {}).get(term.value, term.value))
    if kind == "Literal":
        if term.language:
            return RdfLiteral(term.value, lang=term.language)
        datatype = getattr(term, "datatype", None)
        return RdfLiteral(
            term.value,
            datatype=URIRef(datatype.value) if datatype is not None else None,
        )
    return URIRef(term.value)


def augment(store) -> list[str]:
    """Add what the converters never emit, so the gated templates are testable."""
    from pyoxigraph import BlankNode, Literal, NamedNode, Quad, Store, Triple

    added: list[str] = []
    rel_class = NamedNode(f"{CORE}QualifiedRelationship")
    src, tgt = NamedNode(f"{CORE}source"), NamedNode(f"{CORE}target")
    rdf_type = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")

    # The ontologies' class-to-predicate mapping, extracted rather than guessed. Loaded
    # here because BOTH the direct triples and the RDF 1.2 bridge below need it.
    forms = load_unqualified_forms()

    # -- direct relationship triples ---------------------------------------
    # Derived from the qualified resources already present, which is exactly what
    # --emit-direct-rel-triples does: the notation class becomes the predicate.
    #
    # The predicate comes from arch:unqualifiedForm, NOT from lower-casing the class
    # name. That heuristic is what this used to do, and it invents terms: the mapping is
    # irregular, so am:Serving became `am:serving` where the ontology says `am:serves`.
    # A fixture carrying predicates no ontology declares is the exact failure this
    # package exists to prevent - and it made the fixture unusable as evidence, because
    # a probe that checks a direct edge against its DECLARED form would rightly reject
    # most of these. A class with no declared form gets no direct triple, for the same
    # reason it gets no bridge.
    direct = skipped = 0
    used_forms: dict[str, str] = {}
    for quad in list(store.quads_for_pattern(None, rdf_type, rel_class, None)):
        rel, graph = quad.subject, quad.graph_name
        sources = [q.object for q in store.quads_for_pattern(rel, src, None, graph)]
        targets = [q.object for q in store.quads_for_pattern(rel, tgt, None, graph)]
        kinds = [
            str(q.object.value)
            for q in store.quads_for_pattern(rel, rdf_type, None, graph)
            if not str(q.object.value).startswith(CORE)
        ]
        if not (sources and targets and kinds):
            continue
        predicate = forms.get(kinds[0])
        if predicate is None:
            skipped += 1
            continue
        store.add(Quad(sources[0], NamedNode(predicate), targets[0], graph))
        used_forms[kinds[0]] = predicate
        direct += 1
    added.append(
        f"{direct} direct relationship triple(s), predicate from arch:unqualifiedForm; "
        f"{skipped} relationship(s) left direct-free (no declared form)"
    )

    # -- RDF 1.2 reification bridge -----------------------------------------
    # `rdf:reifies <<( source predicate target )>>`, the core ontology's
    # three-declaration pattern, and what makes the direct triple above CHECKABLE:
    # the triple term names the predicate and both endpoints, so `verify` can tell a
    # real direct edge from an unrelated one between the same pair. There used to be
    # an `arch:relPredicate` declaration added here for that job; core never
    # published that term and no converter emits it, so the bridge does the work.
    #
    # Every converter emits this, but only inside the branch that writes the direct
    # triple, so a default-flag conversion has neither and its PRESENCE here is
    # authored - like the direct triples it accompanies. The class-to-predicate
    # mapping is extracted rather than invented: the pairs come from
    # arch:unqualifiedForm in the ontologies themselves, via unqualified-forms.json.
    # Guessing them would have been wrong, because the mapping is irregular
    # (Serving -> serves, Flow -> flowsTo, Composition -> composedOf).
    #
    # A class with no declared unqualified form gets NO bridge. am:UsedBy and
    # bpmn:SequenceFlow are both in that position, which is why core/reifies-audit
    # has genuine `missing-term` rows to report rather than a planted defect.
    bridged = unbridged = 0
    if forms:
        for quad in list(store.quads_for_pattern(None, rdf_type, rel_class, None)):
            rel, graph = quad.subject, quad.graph_name
            sources = [q.object for q in store.quads_for_pattern(rel, src, None, graph)]
            targets = [q.object for q in store.quads_for_pattern(rel, tgt, None, graph)]
            kinds = [
                str(q.object.value)
                for q in store.quads_for_pattern(rel, rdf_type, None, graph)
                if not str(q.object.value).startswith(CORE)
            ]
            if not (sources and targets and kinds):
                continue
            predicate = forms.get(kinds[0])
            if predicate is None:
                unbridged += 1
                continue
            store.add(Quad(
                rel, NamedNode(REIFIES),
                Triple(sources[0], NamedNode(predicate), targets[0]),
                graph,
            ))
            bridged += 1
        added.append(
            f"{bridged} rdf:reifies triple term(s) from arch:unqualifiedForm; "
            f"{unbridged} relationship(s) left unbridged (no declared form)"
        )
    else:
        added.append("no rdf:reifies bridge (unqualified-forms.json missing)")

    # -- taxonomy classification -------------------------------------------
    scheme = NamedNode("https://meta.linked.archi/core-tax")
    broader = NamedNode(f"{SKOS}broader")
    in_scheme = NamedNode(f"{SKOS}inScheme")
    pref = NamedNode(f"{SKOS}prefLabel")
    classified_by = NamedNode(f"{CORE}conceptClassification")
    root = NamedNode(f"{TAX}ArchComponent")
    software = NamedNode(f"{TAX}Software")

    classified = 0
    for graph_iri in sorted({str(q.graph_name.value) for q in store}):
        if not graph_iri.endswith("graph/semantic"):
            continue
        graph = NamedNode(graph_iri)
        store.add(Quad(root, in_scheme, scheme, graph))
        store.add(Quad(root, pref, Literal("Arch component", language="en"), graph))
        store.add(Quad(software, broader, root, graph))
        store.add(Quad(software, pref, Literal("Software", language="en"), graph))
        elements = [
            q.subject
            for q in store.quads_for_pattern(
                None, rdf_type, NamedNode(f"{CORE}Element"), graph
            )
        ][:3]
        for element in elements:
            store.add(Quad(element, classified_by, software, graph))
            classified += 1
    added.append(f"{classified} element(s) classified under {TAX}Software (skos:broader ArchComponent)")

    # -- cross-source identity ---------------------------------------------
    # Authored, in its own graph, and skos:exactMatch rather than owl:sameAs -
    # correspondence between records, not a claim that they are one thing.
    reconciliation = NamedNode("https://example.org/la/graphs/reconciliation")
    exact = NamedNode(f"{SKOS}exactMatch")
    pairs = [
        (
            "https://example.org/la/backstage/commerce-catalog/element/component/default/order-service",
            "https://example.org/la/c4/commerce-platform/element/2",
        ),
    ]
    identity = 0
    for left, right in pairs:
        left_node, right_node = NamedNode(left), NamedNode(right)
        if not any(store.quads_for_pattern(left_node, None, None, None)):
            continue
        if not any(store.quads_for_pattern(right_node, None, None, None)):
            continue
        store.add(Quad(left_node, exact, right_node, reconciliation))
        store.add(Quad(right_node, exact, left_node, reconciliation))
        identity += 2
    added.append(f"{identity} skos:exactMatch assertion(s) in a reconciliation graph")

    # -- ownership promoted to the core predicate --------------------------
    # Derived from Backstage's bs:Ownership relationships, which is the enrichment a
    # curated pipeline actually performs: ownership arrives as a relationship and
    # arch:conceptOwner is what makes "who owns this" answerable without knowing
    # which notation the answer came from. Converters never emit it.
    owner_pred = NamedNode(f"{CORE}conceptOwner")
    ownership_class = NamedNode("https://meta.linked.archi/backstage/onto#Ownership")
    owners = 0
    for quad in list(store.quads_for_pattern(None, rdf_type, ownership_class, None)):
        rel, graph = quad.subject, quad.graph_name
        entities = [q.object for q in store.quads_for_pattern(rel, src, None, graph)]
        holders = [q.object for q in store.quads_for_pattern(rel, tgt, None, graph)]
        if entities and holders:
            store.add(Quad(entities[0], owner_pred, holders[0], graph))
            owners += 1
    added.append(f"{owners} arch:conceptOwner assertion(s), promoted from bs:Ownership")

    # -- SHACL report -------------------------------------------------------
    # A report with a violation AND a modest evaluated count, so a reader has to
    # confront coverage rather than just a verdict.
    sh = "http://www.w3.org/ns/shacl#"
    report_graph = NamedNode("https://example.org/la/graphs/validation")
    report = NamedNode("https://example.org/la/graphs/validation#report")
    store.add(Quad(report, rdf_type, NamedNode(f"{sh}ValidationReport"), report_graph))
    store.add(Quad(report, NamedNode(f"{sh}conforms"),
                   Literal("false", datatype=NamedNode(
                       "http://www.w3.org/2001/XMLSchema#boolean")), report_graph))
    for index, (severity, shape) in enumerate(
        [("Violation", "ElementMustHaveLabel"), ("Warning", "RelationshipEndpoints")], 1
    ):
        result = NamedNode(f"https://example.org/la/graphs/validation#result-{index}")
        store.add(Quad(report, NamedNode(f"{sh}result"), result, report_graph))
        store.add(Quad(result, rdf_type, NamedNode(f"{sh}ValidationResult"), report_graph))
        store.add(Quad(result, NamedNode(f"{sh}resultSeverity"),
                       NamedNode(f"{sh}{severity}"), report_graph))
        store.add(Quad(result, NamedNode(f"{sh}sourceShape"),
                       NamedNode(f"https://example.org/la/shapes#{shape}"), report_graph))
        store.add(Quad(result, NamedNode(f"{sh}focusNode"),
                       NamedNode("https://example.org/la/bpmn/order-fulfillment/element/Start_1"),
                       report_graph))
    added.append("1 sh:ValidationReport with 2 results, in its own graph")
    return added


#: Written into the fixtures so a reviewer reads ``am:ApplicationComponent`` rather
#: than a 50-character IRI. Taken from the default profile's namespace map, which is
#: itself taken from what the converters emit.
DUMP_PREFIXES = {
    "arch": "https://meta.linked.archi/core#",
    "archvis": "https://meta.linked.archi/core-vis#",
    "arch-tax": "https://meta.linked.archi/core-tax#",
    "am": "https://meta.linked.archi/archimate3/onto#",
    "amvp": "https://meta.linked.archi/archimate3/viewpoints#",
    "bpmn": "https://meta.linked.archi/bpmn/onto#",
    "infra": "https://meta.linked.archi/bpmn/infra#",
    "c4": "https://meta.linked.archi/c4/onto#",
    "bs": "https://meta.linked.archi/backstage/onto#",
    "lmm": "https://meta.linked.archi/leanix/onto#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dct": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#",
    "adms": "http://www.w3.org/ns/adms#",
    "schema": "https://schema.org/",
    "sh": "http://www.w3.org/ns/shacl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    # Deliberately no prefix for the instance base. A prefix whose namespace ends
    # in "/" forces every slash in the local part to be escaped, so
    # `la:model\/archisurance\/element\/id-861` replaces a plainly readable IRI.
    # Vocabulary terms benefit from prefixes; instance IRIs do not.
}


def write(store, path: Path, fmt: str) -> int:
    from pyoxigraph import RdfFormat
    with path.open("wb") as handle:
        store.dump(handle, getattr(RdfFormat, fmt), prefixes=DUMP_PREFIXES)
    return len(store)


def write_flat(store, path: Path) -> int:
    """Dump every graph into one Turtle document, discarding graph identity.

    Reproduces what the converters' ``TURTLE`` output does, and what happens when a
    TriG file is renamed ``.ttl``. Worth having as a fixture precisely because it is
    the shape in which a graph-scoped query silently returns nothing.
    """
    from pyoxigraph import DefaultGraph, Quad, RdfFormat, Store

    flat = Store()
    for quad in store:
        flat.add(Quad(quad.subject, quad.predicate, quad.object, DefaultGraph()))
    with path.open("wb") as handle:
        flat.dump(handle, RdfFormat.TURTLE, from_graph=DefaultGraph(),
                  prefixes=DUMP_PREFIXES)
    return len(flat)


#: Where ``--refresh-forms`` looks for the ontologies: a sibling checkout by default, or
#: wherever ``LINKED_ARCHI_META`` points.
#:
#: Maintainer-only either way. The extracted pairs are committed to
#: ``unqualified-forms.json``, so a consumer never needs a meta checkout, and the default is
#: a sibling rather than a fixed depth so it does not assume this package sits inside a
#: particular monorepo layout.
META_ROOT = Path(os.environ.get("LINKED_ARCHI_META") or REPO.parent / "linked-archi-meta")


def main() -> int:
    try:
        from pyoxigraph import RdfFormat, Store
    except ModuleNotFoundError:
        print("needs pyoxigraph:  pip install pyoxigraph", file=sys.stderr)
        return 2

    if "--refresh-forms" in sys.argv:
        if not META_ROOT.is_dir():
            print(f"no linked-archi-meta checkout at {META_ROOT}", file=sys.stderr)
            return 2
        return 0 if refresh_unqualified_forms(META_ROOT) else 2
    if "--refresh-axioms" in sys.argv:
        if not META_ROOT.is_dir():
            print(f"no linked-archi-meta checkout at {META_ROOT}", file=sys.stderr)
            return 2
        refresh_vocabulary_axioms(META_ROOT)
        return 0
    if "--refresh-shapes" in sys.argv:
        if not META_ROOT.is_dir():
            print(f"no linked-archi-meta checkout at {META_ROOT}", file=sys.stderr)
            return 2
        return 0 if refresh_shapes(META_ROOT) else 2

    if "--emit-13-inputs" in sys.argv:
        index = sys.argv.index("--emit-13-inputs")
        if index + 1 >= len(sys.argv):
            print("--emit-13-inputs needs a destination directory", file=sys.stderr)
            return 2
        destination = Path(sys.argv[index + 1]).expanduser().resolve()
        try:
            written = write_13_inputs(destination)
        except FileNotFoundError as error:
            print(error, file=sys.stderr)
            return 2
        print(f"wrote the multi-repo input layout to {destination}")
        for line in written:
            print(f"  {line}")
        print("\nNext:\n" + recipe_13(destination))
        return 0

    if "--rebuild-13" in sys.argv:
        index = sys.argv.index("--rebuild-13")
        if index + 1 >= len(sys.argv):
            print("--rebuild-13 needs the conversion output to install",
                  file=sys.stderr)
            print("\n" + recipe_13(), file=sys.stderr)
            return 2
        return refresh_converter_13(Path(sys.argv[index + 1]).expanduser().resolve())

    missing = [str(p) for p in SOURCES.values() if not p.is_file()]
    if len(missing) == len(SOURCES):
        print("No converter output found. Run the converters first:", file=sys.stderr)
        for path in SOURCES.values():
            print(f"  {path}", file=sys.stderr)
        return 2

    base, notes = extract(SOURCES)
    print("extracted from:")
    for note in notes:
        print(f"  {note}")

    base_path = FIXTURES / "base.trig"
    count = write(base, base_path, "TRIG")
    graphs = len({str(q.graph_name.value) for q in base})
    print(f"\nbase.trig          {count:>6} quads, {graphs} named graphs")

    # Augmented: copy the base, then add what converters never emit.
    augmented = Store()
    with base_path.open("rb") as handle:
        augmented.bulk_load(handle, RdfFormat.TRIG)
    added = augment(augmented)
    aug_count = write(augmented, FIXTURES / "augmented.trig", "TRIG")
    aug_graphs = len({str(q.graph_name.value) for q in augmented})
    print(f"augmented.trig     {aug_count:>6} quads, {aug_graphs} named graphs")
    for line in added:
        print(f"  + {line}")

    # Flattened: the same content with graph identity discarded.
    flat_count = write_flat(base, FIXTURES / "flat.ttl")
    print(f"flat.ttl           {flat_count:>6} triples, flattened to the default graph")

    # The 1.3 fixture is deliberately NOT rebuilt here, and saying so beats leaving
    # a reader to assume this run refreshed everything. It needs the converter jars
    # and a JDK, so it is an explicit step - and the fixture it would overwrite is
    # the only record of the layout the checked-in out/ files do not have.
    print()
    if CONVERTER_13.is_file():
        present, counts = shape_13(CONVERTER_13)
        state = "intact" if all(present.values()) else "DOES NOT MATCH ITS NAME"
        print(f"converter-1.3.trig {counts['quads']:>6} quads, "
              f"{counts['graphs']} named graphs, {counts['partitions']} semantic "
              f"partition(s) - {state}, not rebuilt by this run")
        for name, ok in present.items():
            if not ok:
                print(f"  ! missing {name}")
    else:
        print("converter-1.3.trig missing - rebuild it with --rebuild-13")
    print("  the base extraction above cannot produce it: every conversion it reads has a")
    print("  single input, and the semantic graph is only partitioned where a model has")
    print("  more than one. This fixture is the only partitioned coverage there is.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
