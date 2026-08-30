"""Residual Vector Quantization (RVQ).

RVQ is the quantization engine at the heart of every modern neural audio codec
(EnCodec, SoundStream, DAC, SpeechTokenizer).  A latent vector ``z`` is encoded
by a *stack* of codebooks: the first codebook quantizes ``z``, the second
quantizes the residual, and so on.  Decoding simply sums the looked-up
centroids.  Increasing the number of codebooks trades bitrate for quality with
no change to the model architecture -- exactly the "bandwidth" knob real codecs
expose.

Implemented in pure numpy (k-means training + nearest-centroid lookup).  No
torch / GPU required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class RvqConfig:
    n_codebooks: int = 4
    codebook_size: int = 256
    dim: int = 128
    iters: int = 10
    seed: int = 0


class ResidualVectorQuantizer:
    """A stack of ``n_codebooks`` vector quantizers trained with k-means."""

    def __init__(self, config: RvqConfig | None = None) -> None:
        self.cfg = config or RvqConfig()
        self.rng = np.random.default_rng(self.cfg.seed)
        self.codebooks: list[np.ndarray[Any, Any]] = []

    # ------------------------------------------------------------------ #
    # training
    # ------------------------------------------------------------------ #
    def _kmeans_init(self, x: np.ndarray[Any, Any], k: int) -> np.ndarray[Any, Any]:
        """k-means++-lite: spread initial centroids across the data.

        Uses rejection-free random sampling (no ``choice(p=...)`` dependency on an
        exact probability sum) so it never fails on degenerate inputs.
        """
        n = len(x)
        idx0 = int(self.rng.integers(n))
        centroids = [x[idx0]]
        dist2 = np.sum((x - x[idx0]) ** 2, axis=1)
        while len(centroids) < k:
            total = float(dist2.sum())
            if total <= 1e-12:
                # all points already coincide with a chosen centroid
                pick = int(self.rng.integers(n))
            else:
                probs = dist2 / total
                pick = int(self.rng.choice(n, p=probs))
            centroids.append(x[pick])
            d = np.sum((x - x[pick]) ** 2, axis=1)
            dist2 = np.minimum(dist2, d)
        return np.array(centroids, dtype=np.float64)

    @staticmethod
    def _nearest(x: np.ndarray[Any, Any], centroids: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        """Return the index in ``centroids`` nearest to each row of ``x``."""
        m = len(x)
        best = np.full(m, np.inf)
        assign = np.zeros(m, dtype=np.int32)
        chunk = 1024
        for c in range(len(centroids)):
            cv = centroids[c]
            for s in range(0, m, chunk):
                d = np.sum((x[s : s + chunk] - cv) ** 2, axis=1)
                mask = d < best[s : s + chunk]
                best[s : s + chunk][mask] = d[mask]
                assign[s : s + chunk][mask] = c
        return assign

    def fit(self, x: np.ndarray[Any, Any]) -> None:
        """Train the codebook stack on latent vectors ``x`` (shape ``(M, dim)``)."""
        x = np.asarray(x, dtype=np.float64)
        residual = x.copy()
        self.codebooks = []
        for _ in range(self.cfg.n_codebooks):
            cb = self._kmeans_init(residual, self.cfg.codebook_size)
            for _ in range(self.cfg.iters):
                idx = self._nearest(residual, cb)
                new_cb = np.zeros_like(cb)
                for c in range(self.cfg.codebook_size):
                    members = idx == c
                    if np.any(members):
                        new_cb[c] = residual[members].mean(axis=0)
                    else:
                        # keep the centroid if it lost all its members
                        new_cb[c] = cb[c]
                cb = new_cb
            self.codebooks.append(cb)
            residual -= cb[idx]

    # ------------------------------------------------------------------ #
    # encode / decode
    # ------------------------------------------------------------------ #
    def encode(self, x: np.ndarray[Any, Any]) -> list[np.ndarray[Any, Any]]:
        """Encode ``x`` (``(M, dim)``) into a list of ``n_codebooks`` token arrays."""
        x = np.asarray(x, dtype=np.float64)
        residual = x.copy()
        tokens: list[np.ndarray[Any, Any]] = []
        for cb in self.codebooks:
            idx = self._nearest(residual, cb)
            tokens.append(idx.astype(np.int32))
            residual -= cb[idx]
        return tokens

    def decode(self, tokens: list[np.ndarray[Any, Any]]) -> np.ndarray[Any, Any]:
        """Reconstruct the latent from a list of token arrays."""
        out = np.zeros((len(tokens[0]), self.cfg.dim), dtype=np.float64)
        for cb, idx in zip(self.codebooks, tokens):
            out += cb[idx]
        return out

    # ------------------------------------------------------------------ #
    # introspection
    # ------------------------------------------------------------------ #
    def bitrate_bps(self, frame_rate: float) -> float:
        """Bits/second consumed by the token stream at the given frame rate."""
        bits_per_frame = self.cfg.n_codebooks * int(np.ceil(np.log2(self.cfg.codebook_size)))
        return bits_per_frame * frame_rate

    def count_parameters(self) -> int:
        return sum(cb.size for cb in self.codebooks)
