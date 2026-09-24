"""Federated learning for privacy-preserving multi-user model aggregation.

Free-resource, numpy-only implementation covering the three pillars of private
federated learning:

* **FedAvg** aggregation (:mod:`audiobook_studio.fl.aggregator`).
* **Secure Aggregation** (pairwise-mask MPC; server only sees the masked sum)
  (:mod:`audiobook_studio.fl.secagg`).
* **Differential Privacy** (client-side clip + Gaussian noise + epsilon/delta
  accounting + a membership-inference auditor) (:mod:`audiobook_studio.fl.privacy`).

The orchestration engine (:mod:`audiobook_studio.fl.engine`) wires a
:class:`FederatedServer` and :class:`FederatedClient` together. Raw user data
never leaves the client; only (optionally masked / noised) model parameters do.
"""

from __future__ import annotations

from .aggregator import Aggregator, FedAvgAggregator, fedavg_count_models, fedavg_vectors
from .engine import (
    ClientResult,
    FederatedClient,
    FederatedServer,
    FLConfig,
    create_federated_n_gram_server,
    is_federated_enabled,
)
from .model import ContextKey, FederatableModel, LocalARModelAdapter, ModelParameters
from .privacy import (
    DpConfig,
    MembershipInferenceEstimator,
    add_gaussian_noise,
    clip_to_norm,
    gaussian_dp_epsilon,
)
from .secagg import SecAggSession, dequantize, quantize

__all__ = [
    "Aggregator",
    "FedAvgAggregator",
    "fedavg_count_models",
    "fedavg_vectors",
    "FLConfig",
    "ClientResult",
    "FederatedClient",
    "FederatedServer",
    "create_federated_n_gram_server",
    "is_federated_enabled",
    "ContextKey",
    "FederatableModel",
    "LocalARModelAdapter",
    "ModelParameters",
    "DpConfig",
    "MembershipInferenceEstimator",
    "add_gaussian_noise",
    "clip_to_norm",
    "gaussian_dp_epsilon",
    "SecAggSession",
    "dequantize",
    "quantize",
]
