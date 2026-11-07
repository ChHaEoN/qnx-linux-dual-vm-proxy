"""pathset.py -- the effective path set: what `config` may make of the frozen allowlist (sdv/connector; SDV Phase 4
WP2).

Standard library only.

The frozen allowlist (twin_allowlist.PATHS) is baked into the connector's image. The cloud's `config` shadow may say
which of those paths are sent, and nothing more: it can narrow the set, never widen it.

    narrow(frozen, wanted)     the frozen tuple's members that `wanted` names, in the frozen tuple's order, and how
                               many entries of `wanted` were ignored. Membership is EXACT and CASE-SENSITIVE string
                               equality with a member of the tuple. No wildcard, no branch, no prefix, and above all
                               no normalisation: nothing is trimmed, case-folded or Unicode-normalised, because a
                               normaliser is how a near-miss string is turned into a hit. An entry that is not a
                               string is ignored like any other non-member.
    effective(frozen, wanted)  the same without the count; `wanted` None means no narrowing, the whole tuple.

An empty list is the empty set, and so is a list of nothing but non-members: an entry that is ignored changes nothing,
so the list is read as if it were not there. A value that is no list is no narrowing at all (TypeError); the caller
keeps the set it had.

The count of ignored entries is all that leaves this module about them. The strings themselves go nowhere: not into
`config` reported, which would make the shadow a reflector, and not into the log.

Does not demonstrate: that the connector subscribes to this set and sends nothing else (the egress test), or anything
against a frozen module that already holds a path it should not (the generator and its --check are that gate).
"""
from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple


def narrow(frozen: Sequence[str], wanted: Any) -> Tuple[Tuple[str, ...], int]:
    """(the members of `frozen` that the list `wanted` names, in `frozen`'s order; how many entries were ignored)."""
    if not isinstance(wanted, (list, tuple)):
        raise TypeError("a desired path set is a list of exact leaf paths")
    members = frozenset(frozen)
    named = set()
    ignored = 0
    for entry in wanted:
        if isinstance(entry, str) and entry in members:
            named.add(entry)
        else:
            ignored += 1
    return tuple(p for p in frozen if p in named), ignored


def effective(frozen: Sequence[str], wanted: Optional[Any] = None) -> Tuple[str, ...]:
    """The effective set: the whole frozen tuple when nothing is wanted, else its members that `wanted` names."""
    if wanted is None:
        return tuple(frozen)
    return narrow(frozen, wanted)[0]
