"""Federated aggregation: FedAvg (and a generic vector FedAvg helper)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Protocol, Sequence

import numpy as np

from .model import ModelParameters

logger = logging.getLogger(__name__)


class Aggregator(Protocol):
    """Aggregates a list of per-client parameters into a global model."""

    def aggregate(self, params_list: Sequence[ModelParameters], weights: Sequence[float]) -> ModelParameters:
        ...


def fedavg_count_models(
    params_list: Sequence[ModelParameters],
    weights: Sequence[float],
) -> ModelParameters:
    """Federated Averaging for count-based n-gram models.

    For every context key (union over clients) the per-vocabulary count vectors
    are combined as a weighted average by client sample size. This is exactly
    how empirical n-gram statistics should be pooled across users.
    """
    if not params_list:
        raise ValueError("params_list is empty")
    vocab = params_list[0].vocab_size
    order = params_list[0].order
    total_w = float(sum(weights)) or 1.0

    union = set()
    for p in params_list:
        union |= set(p.counts.keys())

    out = ModelParameters(vocab_size=vocab, order=order)
    for k in sorted(union):
        acc = np.zeros(vocab, dtype=np.float64)
        for p, w in zip(params_list, weights):
            v = p.counts.get(k)
            if v is not None:
                acc += np.asarray(v, dtype=np.float64) * w
        out.counts[k] = (acc / total_w).tolist()
    return out


def fedavg_vectors(
    vectors: Sequence[np.ndarray],
    weights: Sequence[float],
) -> np.ndarray:
    """Generic weighted average of equal-shaped parameter vectors (FedAvg)."""
    if not vectors:
        raise ValueError("vectors is empty")
    total_w = float(sum(weights)) or 1.0
    acc = np.zeros_like(np.asarray(vectors[0], dtype=np.float64))
    for v, w in zip(vectors, weights):
        acc += np.asarray(v, dtype=np.float64) * w
    return acc / total_w


@dataclass
class FedAvgAggregator:
    """FedAvg aggregator over count-based :class:`ModelParameters`."""

    def aggregate(
        self,
        params_list: Sequence[ModelParameters],
        weights: Sequence[float],
    ) -> ModelParameters:
        return fedavg_count_models(params_list, weights)
