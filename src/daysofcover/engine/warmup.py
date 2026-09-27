"""Warm-up truncation: the Marginal Standard Error Rule, batch size 5 (MSER-5).

A replication's first days carry a transient bias -- the state the
simulation starts in (empty pipelines, zero backlog) is not the steady
state the metrics are meant to describe -- and averaging over those days
along with the rest biases every statistic the replication runner
collects. MSER-5 (White, 1997, "An Effective Truncation Heuristic for
Bias Reduction in Simulation Output") is the standard, cheap way to pick
a truncation point without eyeballing a plot: batch the series into
consecutive batches of 5 observations, and choose the number of leading
batches to discard that minimises the sample variance of the batch means
that remain, scaled by how many remain. Discarding too little leaves the
transient's bias in; discarding too much throws away real data and
inflates the resulting statistic's own variance -- MSER trades the two
off automatically, for whatever series it is given.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def mser5_truncation_point(series: Sequence[float], *, batch_size: int = 5) -> int:
    """The MSER-5 warm-up truncation point, in units of the original series.

    Batches ``series`` into ``k = len(series) // batch_size`` consecutive,
    non-overlapping batches (any remainder shorter than ``batch_size`` at
    the end is dropped, never folded into the last full batch) and forms
    each batch's mean, ``Y_1far to Y_k``. For every candidate number of
    discarded batches ``d`` from ``0`` to ``k - 2``, computes

        MSER(d) = Var(Y_{d+1}, ..., Y_k) / (k - d)

    (the population-variance form of White's rule -- see the module
    docstring) and returns ``d* * batch_size``, where ``d*`` minimises
    MSER(d): the number of leading observations in the *original* series
    to discard as warm-up.

    Returns ``0`` (nothing discarded) when ``series`` is too short to
    form at least two full batches, since MSER needs at least two
    remaining batch means to have a variance to compare.
    """
    values = np.asarray(series, dtype=float)
    n_batches = len(values) // batch_size
    if n_batches < 2:
        return 0

    batch_means = np.array(
        [values[i * batch_size : (i + 1) * batch_size].mean() for i in range(n_batches)]
    )

    best_d = 0
    best_mser = float("inf")
    for d in range(n_batches - 1):  # d from 0 to k - 2 inclusive
        remaining = batch_means[d:]
        mser = float(np.var(remaining)) / (n_batches - d)
        if mser < best_mser:
            best_mser = mser
            best_d = d

    return best_d * batch_size
