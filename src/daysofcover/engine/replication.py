"""Reproducible simulation replications using common random numbers.

Entity-specific NumPy random generators are derived from a master seed,
replication index and stable entity identifier. The same entity therefore
receives the same random stream across comparable scenarios, regardless
of iteration order or the presence of unrelated entities.

Common random numbers reduce noise in scenario comparisons by holding
matched sources of randomness consistent. The replication runner accepts
a caller-supplied scenario function and does not depend on a particular
simulation engine.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import TypeVar

import numpy as np

ResultT = TypeVar("ResultT")


def _entity_seed_sequence(*, seed: int, replication: int, entity_id: str) -> np.random.SeedSequence:
    """The seed sequence for one entity, at one replication, under one master seed.

    ``entity_id`` is hashed with BLAKE2b (not Python's built-in ``hash``,
    which is randomised per-process for strings unless ``PYTHONHASHSEED``
    is fixed) into two 32-bit integers, so the result is reproducible
    across processes and depends only on the three logical inputs -- not
    on how many other entities are in the call, or what order they were
    given in. Two different entity ids collide with the same
    astronomically small probability as any other 64-bit hash.
    """
    digest = hashlib.blake2b(entity_id.encode("utf-8"), digest_size=8).digest()
    hash_lo = int.from_bytes(digest[:4], "big")
    hash_hi = int.from_bytes(digest[4:], "big")
    return np.random.SeedSequence([seed, replication, hash_lo, hash_hi])


def entity_rngs(
    *, entity_ids: list[str], replication: int, seed: int
) -> dict[str, np.random.Generator]:
    """One independent :class:`numpy.random.Generator` per id in ``entity_ids``.

    Calling this again with the same ``seed`` and ``replication`` -- even
    from an unrelated scenario, with a different or reordered
    ``entity_ids`` list -- gives every id that appears in both calls the
    identical generator state, which is the entity-indexed CRN property
    itself. A caller that wants a single scenario-wide generator for
    anything not tied to a named entity can just include a fixed id such
    as ``"__scenario__"`` in ``entity_ids``.
    """
    return {
        entity_id: np.random.default_rng(
            _entity_seed_sequence(seed=seed, replication=replication, entity_id=entity_id)
        )
        for entity_id in entity_ids
    }


def run_replications(  # noqa: UP047 -- see ResultT above: classic TypeVar
    # syntax, not PEP 695, kept so this file stays importable (and its
    # logic actually runnable, not just type-checkable) on Python 3.11
    # during development, even though the project itself requires >=3.12.
    *,
    entity_ids: list[str],
    n_replications: int,
    seed: int,
    scenario: Callable[[int, dict[str, np.random.Generator]], ResultT],
) -> list[ResultT]:
    """Run ``scenario`` once per replication, with fresh entity-indexed CRN each time.

    ``scenario`` is called as ``scenario(replication, rngs)`` where
    ``replication`` runs from ``0`` to ``n_replications - 1`` and
    ``rngs`` is exactly :func:`entity_rngs`'s result for that replication.
    Its return value (whatever shape the caller chooses -- a dataclass,
    a plain number, a dict of metrics) is collected unchanged, one entry
    per replication, in replication order.
    """
    results: list[ResultT] = []
    for replication in range(n_replications):
        rngs = entity_rngs(entity_ids=entity_ids, replication=replication, seed=seed)
        results.append(scenario(replication, rngs))
    return results
