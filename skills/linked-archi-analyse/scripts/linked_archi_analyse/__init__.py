"""Plan an investigation and bundle its evidence. Never execute anything.

The line this package exists to hold: **analyse decides and records; query executes.**
There is no dataset access here, no SPARQL, no transport, and no import of another owner's
package. Metadata about templates is read by running the query owner's documented
`catalog dump` in a subprocess, which is a contract rather than a coupling.

Two commands, and the split between them is the point:

``plan``
    Turns a question into an ordered, numbered sequence of `la-query` commands with their
    purposes, parameters, stop conditions and - when query is installed - each template's
    availability under the chosen profile. Emitting the commands rather than running them
    keeps execution, read-only enforcement and result provenance in one place.

``bundle``
    Takes the envelopes `la-query --json -o FILE` already wrote and assembles one artifact.
    It re-executes nothing, refuses envelopes from two different datasets or profiles, and
    requires the interpretation to cite the steps it rests on.
"""

from .patterns import Pattern, load_patterns, route
from .plan import Plan, Step, build_plan
from .bundle import Bundle, build_bundle, render_markdown

__all__ = [
    "Bundle",
    "Pattern",
    "Plan",
    "Step",
    "build_bundle",
    "build_plan",
    "load_patterns",
    "render_markdown",
    "route",
]
