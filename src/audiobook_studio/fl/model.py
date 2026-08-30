"""Federatable model abstraction for privacy-preserving federated learning.

The project's only trainable, free-to-run model is the count-based n-gram
autoregressive model (``LocalARModel``) used for speculative decoding. It is
therefore the natural "model" to federate: multiple users can collaboratively
train a better n-gram language model / draft model / text-normalization model
from their *private* corpora (e.g. their own books) **without ever sharing the
raw text**.

This module defines a small backend-agnostic interface (:class:`FederatableModel`)
plus a concrete adapter for ``LocalARModel``. Any model that can expose its
parameters as a ``{context -> count-vector}`` table is federatable.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from ..llm.speculative import LocalARModel

logger = logging.getLogger(__name__)

ContextKey = Tuple[int, ...]


@dataclass
class ModelParameters:
    """Trainable parameters of a federatable count-based model.

    ``counts[key]`` is a per-vocabulary count vector for the n-gram context
    ``key``. Aggregation (FedAvg) simply averages these count vectors across
    clients, which is the correct way to combine empirical n-gram statistics.
    """

    vocab_size: int
    order: int
    counts: Dict[ContextKey, List[float]] = field(default_factory=dict)

    def keys(self) -> List[ContextKey]:
        return sorted(self.counts.keys())

    def to_flat(self, key_order: Sequence[ContextKey]) -> np.ndarray[Any, Any]:
        """Flatten to a fixed-shape vector aligned to ``key_order``.

        Contexts absent from this model contribute a zero vector, so two models
        flattened with the *same* ``key_order`` are identically shaped (required
        for secure aggregation and differential privacy).
        """
        parts: List[np.ndarray[Any, Any]] = []
        for k in key_order:
            v = self.counts.get(k)
            parts.append(
                np.asarray(v, dtype=np.float64) if v is not None else np.zeros(self.vocab_size, dtype=np.float64)
            )
        if not parts:
            return np.zeros(0, dtype=np.float64)
        return np.concatenate(parts)

    @classmethod
    def from_flat(
        cls,
        arr: np.ndarray[Any, Any],
        key_order: Sequence[ContextKey],
        vocab_size: int,
        order: int,
    ) -> "ModelParameters":
        out = cls(vocab_size=vocab_size, order=order)
        arr = np.asarray(arr, dtype=np.float64)
        for i, k in enumerate(key_order):
            out.counts[k] = arr[i * vocab_size : (i + 1) * vocab_size].tolist()
        return out

    def empty_like(self) -> "ModelParameters":
        return ModelParameters(vocab_size=self.vocab_size, order=self.order)


class FederatableModel(ABC):
    """Backend-agnostic surface a federated server/client can operate on."""

    @abstractmethod
    def get_parameters(self) -> ModelParameters: ...

    @abstractmethod
    def set_parameters(self, p: ModelParameters) -> None: ...

    @abstractmethod
    def train(self, token_ids: Sequence[int]) -> None:
        """Train on *private* local data. Must only touch local state."""

    @abstractmethod
    def evaluate(self, token_ids: Sequence[int]) -> float:
        """Return a higher-is-better quality metric (mean log-likelihood)."""

    @abstractmethod
    def empty_copy(self) -> "FederatableModel": ...


class LocalARModelAdapter(FederatableModel):
    """Adapts :class:`LocalARModel` (n-gram LM) to the federated interface."""

    def __init__(self, order: int, vocab_size: int, seed: int = 0) -> None:
        self.model = LocalARModel(order=order, vocab_size=vocab_size, seed=seed)

    def get_parameters(self) -> ModelParameters:
        return ModelParameters(
            vocab_size=self.model.vocab_size,
            order=self.model.order,
            counts={k: v.tolist() for k, v in self.model.counts.items()},
        )

    def set_parameters(self, p: ModelParameters) -> None:
        self.model.counts = {k: np.asarray(v, dtype=np.float64) for k, v in p.counts.items()}

    def train(self, token_ids: Sequence[int]) -> None:
        self.model.train(token_ids)

    def evaluate(self, token_ids: Sequence[int]) -> float:
        """Mean log-likelihood of the sequence under the model (higher = better)."""
        if len(token_ids) < 2:
            return 0.0
        total = 0.0
        n = 0
        for i in range(1, len(token_ids)):
            logp = self.model.logits(list(token_ids[:i]))
            total += float(logp[int(token_ids[i])])
            n += 1
        return total / max(n, 1)

    def empty_copy(self) -> "LocalARModelAdapter":
        return LocalARModelAdapter(self.model.order, self.model.vocab_size)
