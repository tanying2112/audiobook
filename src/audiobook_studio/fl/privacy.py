"""Differential Privacy for federated learning.

Two complementary privacy tools:

1. **Client-side DP** (applied to a client's uploaded update before it leaves
   the device): clip the update's L2 norm, then add Gaussian noise. This is the
   mechanism used together with Secure Aggregation in production systems (e.g.
   Google's cross-device FL) so that even the *aggregated* result protects each
   user's contribution.

2. **Membership-inference estimation**: a simple black-box attacker that tries to
   tell whether a given example was in a client's private training set by
   measuring how much the global model moved *towards* that example after the
   client's round. We use it to demonstrate that adding DP noise actually lowers
   the attack's accuracy toward random guessing (0.5).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, List, Sequence

import numpy as np

logger = logging.getLogger(__name__)


def clip_to_norm(vec: np.ndarray[Any, Any], clip_norm: float) -> np.ndarray[Any, Any]:
    """Clip ``vec`` so its L2 norm is at most ``clip_norm`` (no-op if already)."""
    arr = np.asarray(vec, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    if clip_norm <= 0 or norm <= clip_norm:
        return arr
    return arr * (clip_norm / norm)


def add_gaussian_noise(vec: np.ndarray[Any, Any], sigma: float, rng: np.random.Generator) -> np.ndarray[Any, Any]:
    return np.asarray(vec, dtype=np.float64) + rng.normal(0.0, sigma, size=np.asarray(vec).shape)


def gaussian_dp_epsilon(
    sigma: float,
    sensitivity: float,
    delta: float,
    steps: int = 1,
) -> float:
    """(epsilon, delta)-bound for the Gaussian mechanism (Abadi et al., simplified).

    For a single application with noise std ``sigma`` and L2 sensitivity
    ``sensitivity``::

        epsilon = sqrt(2 * ln(1.25 / delta)) * (sensitivity / sigma)

    ``steps`` compositions via the basic (sqrt) composition bound.
    Returns ``inf`` for degenerate inputs (no privacy).
    """
    if sigma <= 0 or sensitivity <= 0 or delta <= 0:
        return float("inf")
    eps_step = math.sqrt(2.0 * math.log(1.25 / delta)) * (sensitivity / sigma)
    return eps_step * math.sqrt(steps)


@dataclass
class DpConfig:
    clip_norm: float = 0.0
    noise_multiplier: float = 0.0
    delta: float = 1e-5

    def enabled(self) -> bool:
        return self.clip_norm > 0 and self.noise_multiplier > 0

    def epsilon_spent(self, rounds: int = 1) -> float:
        """Honest per-client epsilon for one (or ``rounds``) DP update(s).

        Sensitivity of a clipped per-client vector is ``2 * clip_norm`` (an
        adversary can change at most one client's whole vector). We report the
        worst-case *local* guarantee a client faces.
        """
        if not self.enabled():
            return float("inf")
        sigma = self.clip_norm * self.noise_multiplier
        return gaussian_dp_epsilon(sigma, 2.0 * self.clip_norm, self.delta, rounds)


class MembershipInferenceEstimator:
    """Black-box membership-inference attacker (a privacy *auditor*, not an attack)."""

    @staticmethod
    def attack_accuracy(
        logp_before: Sequence[float],
        logp_after: Sequence[float],
        member_idx: Sequence[int],
        nonmember_idx: Sequence[int],
    ) -> float:
        """Accuracy of an attacker labelling examples as 'member' if the global
        model's log-likelihood on them *improved* after the client's round.

        With strong DP noise the improvement is indistinguishable from noise, so
        accuracy drops toward 0.5 (random guessing).
        """
        scores = [logp_after[i] - logp_before[i] for i in range(len(logp_before))]
        tp = sum(1 for i in member_idx if scores[i] > 0)
        tn = sum(1 for i in nonmember_idx if scores[i] <= 0)
        total = len(member_idx) + len(nonmember_idx)
        if total == 0:
            return 0.5
        return (tp + tn) / total
