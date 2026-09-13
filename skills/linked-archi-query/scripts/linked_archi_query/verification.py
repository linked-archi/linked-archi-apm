"""Has this profile ever been checked against this dataset?

Four skills with an implied order and no checkpoint means the order is advisory, and
advisory steps get dropped under time pressure. One field session went connect then query,
skipped `profile verify`, and got lucky that the default profile fitted. When it does not
fit, the failure is silent: every scoped query returns nothing, or returns rows that mean
something other than what the reader assumes.

So this records that a (dataset, profile) pair was verified, and lets a later query notice
when it was not. Deliberately **not** a gate:

* the CLIs stay stateless per invocation - there is no session to track;
* a gate keyed on process state is trivially bypassed and would break the machine
  contracts and CI;
* and being unable to verify is a legitimate position, not an error.

It is a caveat attached to the result, so it travels into whatever the answer becomes.

The marker is a content key, not a lock. Nothing here is a security boundary: a missing
marker only ever produces advice.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

#: Shared between the profile owner (which writes) and the query owner (which reads), by
#: path convention rather than by importing code. Both document it.
ENV_STATE_DIR = "LINKED_ARCHI_STATE_DIR"
DEFAULT_STATE_DIR = Path("~/.cache/linked-archi/verified")


def state_dir() -> Path:
    configured = os.environ.get(ENV_STATE_DIR)
    base = Path(configured).expanduser() if configured else DEFAULT_STATE_DIR.expanduser()
    return base


def marker_name(dataset_id: str, profile_id: str, fingerprint: object) -> str:
    """A stable filename for one (dataset, profile, fingerprint) triple.

    Hashed because a dataset identity is a list of filenames and a profile reference can be
    a path; neither is safe to use as a filename directly.

    ``fingerprint`` is the profile snapshot's own digest, which the profile owner computes
    and publishes in the snapshot. It used to be the profile's declared ``version``, and
    that was too weak: the version is a hand-maintained integer, so editing what a profile
    claims without bumping it left an old marker vouching for the new claims. The
    fingerprint moves whenever the meaning does, with nobody having to remember.
    """
    key = f"{dataset_id}\n{profile_id}\n{fingerprint}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest() + ".verified"


def marker_path(dataset_id: str, profile_id: str, fingerprint: object) -> Path:
    return state_dir() / marker_name(dataset_id, profile_id, fingerprint)


def is_verified(dataset_id: str, profile_id: str, fingerprint: object) -> bool:
    if not dataset_id or dataset_id == "<unset>":
        return True  # nothing to say about a dataset we cannot identify
    try:
        return marker_path(dataset_id, profile_id, fingerprint).is_file()
    except OSError:  # pragma: no cover - unreadable state directory
        return True  # never turn a diagnostics problem into a caveat about the data


def record(dataset_id: str, profile_id: str, fingerprint: object) -> Path | None:
    """Note that this pair verified cleanly. Best effort; failure is not an error."""
    if not dataset_id or dataset_id == "<unset>":
        return None
    path = marker_path(dataset_id, profile_id, fingerprint)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{dataset_id}\n{profile_id}\n{fingerprint}\n", encoding="utf-8")
    except OSError:  # pragma: no cover - read-only or missing cache location
        return None
    return path


def caveat(profile_id: str) -> str:
    return (
        f"profile {profile_id!r} has not been verified against this dataset. A profile that "
        "does not fit fails silently - scoped queries return nothing, or rows that mean "
        f"something else. Check it with: la-profile verify --profile {profile_id} --data ..."
    )
