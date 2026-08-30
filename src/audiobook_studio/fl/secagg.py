"""Secure Aggregation (privacy-preserving model aggregation).

Implements the *pairwise-mask* secure aggregation protocol (Bonawitz et al.,
2017, "Practical Secure Aggregation for Privacy-Preserving Machine Learning").
The defining privacy property: **the server only ever receives each client's
masked vector; it can recover the *sum* of the client parameters but never any
individual client's parameters.**

How it works (simulated, stdlib + numpy only):
  * Every unordered pair of clients (i, j) shares a random integer mask vector
    ``m[i,j]`` (in real life established pairwise, e.g. via Diffie-Hellman, and
    never revealed to the server).
  * Client i uploads ``y_i = params_i + sum_{j>i} m[i,j] - sum_{j<i} m[j,i]``
    (all arithmetic mod a large prime P).
  * The server sums all ``y_i`` mod P. Every mask ``m[i,j]`` appears exactly
    twice with opposite signs, so the masks cancel and the server recovers
    ``sum_i params_i``. It never sees any ``params_i`` or any ``m[i,j]``.

Dropout handling: if a client drops, its present peers reveal the masks they
shared with it; the server subtracts them so the sum of the *remaining* clients
is still recovered (at the cost of the dropped client's secrecy for that round,
which is the standard trade-off).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class SecAggSession:
    """Coordinates pairwise masks between clients. Pure simulation (no crypto)."""

    def __init__(
        self,
        num_clients: int,
        vector_dim: int,
        prime: int,
        rng: np.random.Generator,
    ) -> None:
        self.num_clients = num_clients
        self.vector_dim = vector_dim
        self.prime = prime
        # (i, j) with i < j -> shared random mask vector (unknown to the server).
        self.masks: Dict[Tuple[int, int], np.ndarray[Any, Any]] = {}
        for a in range(num_clients):
            for b in range(a + 1, num_clients):
                self.masks[(a, b)] = rng.integers(0, prime, size=vector_dim, dtype=np.int64)

    def client_mask(self, client_index: int, params_int: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        """Client-side: mask ``params_int`` so the server cannot read it."""
        out = np.asarray(params_int, dtype=np.int64) % self.prime
        for j in range(self.num_clients):
            if j == client_index:
                continue
            if client_index < j:
                out = (out + self.masks[(client_index, j)]) % self.prime
            else:
                out = (out - self.masks[(j, client_index)]) % self.prime
        return out

    def server_aggregate(self, masked_list: Sequence[np.ndarray[Any, Any]]) -> np.ndarray[Any, Any]:
        """Server-side: recover sum(params) without ever seeing any params_i."""
        s = np.zeros(self.vector_dim, dtype=np.int64)
        for m in masked_list:
            s = (s + np.asarray(m, dtype=np.int64)) % self.prime
        return s

    def server_aggregate_with_dropout(
        self,
        masked_list: Sequence[np.ndarray[Any, Any]],
        dropped_index: int,
        revealed_masks: Dict[int, np.ndarray[Any, Any]],
    ) -> np.ndarray[Any, Any]:
        """Recover sum of the *remaining* clients when one dropped out.

        ``revealed_masks[j]`` is the mask client ``dropped_index`` shared with
        present client ``j`` (revealed by peer j to keep cancellation working).

        A present client ``j`` contributed ``+mask(j, dropped)`` to its masked
        upload when ``j < dropped`` (client j adds the mask with the later peer),
        and ``-mask(dropped, j)`` when ``j > dropped`` (client j subtracts the
        mask with the earlier peer). Removing those leaves the sum of the
        remaining clients' parameters.
        """
        s = self.server_aggregate(masked_list)
        for j, m in revealed_masks.items():
            m = np.asarray(m, dtype=np.int64)
            if dropped_index < j:  # present client j > dropped: it subtracted mask(dropped, j)
                s = (s + m) % self.prime
            else:  # present client j < dropped: it added mask(j, dropped)
                s = (s - m) % self.prime
        return s


def quantize(flat: np.ndarray[Any, Any], scale: float) -> np.ndarray[Any, Any]:
    """Fixed-point quantization so floats can travel through the integer field."""
    return np.asarray(np.round(np.asarray(flat, dtype=np.float64) * scale), dtype=np.int64)


def dequantize(flat_int: np.ndarray[Any, Any], scale: float) -> np.ndarray[Any, Any]:
    return np.asarray(np.asarray(flat_int, dtype=np.float64) / scale, dtype=np.float64)
