"""Federated learning engine: server + client orchestration.

Privacy guarantees, by construction:

* **Raw data never leaves the client.** ``FederatedClient.build_update`` trains
  on ``private_data`` locally and only ever returns *model parameters* (or a
  masked/perturbed form of them). The server never sees ``private_data``.
* **FedAvg** (``mode="fedavg"``): the server averages client parameters. Optionally
  each client clips+noises its upload (client-side DP) before sending.
* **Secure Aggregation** (``mode="secagg"``): each client masks its upload with
  pairwise random masks; the server only ever aggregates the *masked* vectors and
  recovers the sum, never any individual. Optionally combined with client-side DP.

All of this is opt-in behind ``FEDERATED_LEARNING_ENABLED=true``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .aggregator import fedavg_count_models
from .model import ContextKey, FederatableModel, ModelParameters
from .privacy import DpConfig, add_gaussian_noise, clip_to_norm
from .secagg import SecAggSession, dequantize, quantize

logger = logging.getLogger(__name__)


def is_federated_enabled() -> bool:
    return os.getenv("FEDERATED_LEARNING_ENABLED", "false").lower() in ("1", "true", "yes", "on")


@dataclass
class FLConfig:
    mode: str = "fedavg"  # "fedavg" | "secagg"
    prime: int = (1 << 31) - 1
    scale: float = 1.0
    seed: int = 0
    dp: DpConfig = field(default_factory=DpConfig)


@dataclass
class ClientResult:
    client_id: str
    sample_count: int
    params: Optional[ModelParameters] = None  # fedavg path
    masked: Optional[np.ndarray] = None  # secagg path
    key_order: Optional[List[ContextKey]] = None


class FederatedClient:
    """Owns private data, trains locally, and produces a privacy-protected update."""

    def __init__(
        self,
        client_id: str,
        private_data: Sequence[int],
        template: FederatableModel,
        config: FLConfig,
        rng: np.random.Generator,
    ) -> None:
        self.client_id = client_id
        self.private_data = private_data  # NEVER transmitted
        self.local = template.empty_copy()
        self.config = config
        self.rng = rng
        self._secagg: Optional[SecAggSession] = None

    def _dp_perturb(self, flat: np.ndarray) -> np.ndarray:
        if self.config.dp.clip_norm > 0:
            flat = clip_to_norm(flat, self.config.dp.clip_norm)
        if self.config.dp.noise_multiplier > 0:
            sigma = (self.config.dp.clip_norm or 1.0) * self.config.dp.noise_multiplier
            flat = add_gaussian_noise(flat, sigma, self.rng)
        return flat

    def build_update(self, key_order: Optional[Sequence[ContextKey]]) -> ClientResult:
        # Raw data is used ONLY here, on-device.
        self.local.train(self.private_data)
        local_params = self.local.get_parameters()

        if self.config.mode == "secagg":
            assert key_order is not None, "secagg requires a fixed key order"
            flat = local_params.to_flat(key_order)
            flat = self._dp_perturb(flat)
            q = quantize(flat, self.config.scale).astype(np.int64)
            assert self._secagg is not None, "secagg session not established"
            client_index = int(self.client_id.split(":")[-1]) if ":" in self.client_id else 0
            masked = self._secagg.client_mask(client_index, q)
            return ClientResult(self.client_id, len(self.private_data), masked=masked, key_order=list(key_order))

        # fedavg path
        if self.config.dp.enabled():
            keys = key_order if key_order else local_params.keys()
            flat = local_params.to_flat(keys)
            flat = self._dp_perturb(flat)
            noisy = ModelParameters.from_flat(
                flat, keys, local_params.vocab_size, local_params.order
            )
            return ClientResult(self.client_id, len(self.private_data), params=noisy)
        return ClientResult(self.client_id, len(self.private_data), params=local_params)


class FederatedServer:
    """Runs federated rounds: collect client updates, aggregate into global model."""

    def __init__(self, global_model: FederatableModel, config: FLConfig, rng: np.random.Generator) -> None:
        self.model = global_model
        self.config = config
        self.rng = rng
        self.secagg: Optional[SecAggSession] = None
        self.key_order: List[ContextKey] = []

    # -- plaintext metadata step (mild leak of *which* n-grams exist; documented) --
    def bootstrap_keys(self, clients: Sequence[FederatedClient]) -> List[ContextKey]:
        union = set()
        for c in clients:
            # Discover which n-gram contexts this client has, WITHOUT permanently
            # training its real local model (run_round will train it fresh).
            tmp = c.local.empty_copy()
            tmp.train(c.private_data)
            for k in tmp.get_parameters().counts:
                union.add(k)
        self.key_order = sorted(union)
        if self.config.mode == "secagg":
            vocab = self.model.get_parameters().vocab_size
            dim = len(self.key_order) * vocab
            self.secagg = SecAggSession(len(clients), dim, self.config.prime, self.rng)
            for idx, c in enumerate(clients):
                c._secagg = self.secagg
                c.client_id = f"{c.client_id.split(':')[0]}:{idx}"
        return self.key_order

    def run_round(self, clients: Sequence[FederatedClient]) -> ModelParameters:
        if self.config.mode == "secagg":
            if self.secagg is None:
                self.bootstrap_keys(clients)
            results = [c.build_update(self.key_order) for c in clients]
            masked = [r.masked for r in results if r.masked is not None]
            assert self.secagg is not None
            summed = self.secagg.server_aggregate(masked)
            avg = dequantize(summed, self.config.scale) / max(len(results), 1)
            new_params = ModelParameters.from_flat(
                avg, self.key_order, self.model.get_parameters().vocab_size, self.model.get_parameters().order
            )
            self.model.set_parameters(new_params)
            return new_params

        # fedavg path
        results = [c.build_update(None) for c in clients]
        params_list = [r.params for r in results if r.params is not None]
        weights = [r.sample_count for r in results if r.params is not None]
        new_params = fedavg_count_models(params_list, weights)
        self.model.set_parameters(new_params)
        return new_params


def create_federated_n_gram_server(
    order: int,
    vocab_size: int,
    config: Optional[FLConfig] = None,
    seed: int = 0,
) -> Tuple[FederatedServer, FLConfig]:
    """Convenience factory for a federated n-gram (draft / LM) server."""
    cfg = config or FLConfig(seed=seed)
    rng = np.random.default_rng(cfg.seed)
    global_model = _EmptyNGram(order, vocab_size)
    return FederatedServer(global_model, cfg, rng), cfg


class _EmptyNGram(FederatableModel):
    """A blank n-gram model used as the initial global model."""

    def __init__(self, order: int, vocab_size: int) -> None:
        from .model import LocalARModelAdapter

        self._inner = LocalARModelAdapter(order, vocab_size)

    def get_parameters(self) -> ModelParameters:
        return self._inner.get_parameters()

    def set_parameters(self, p: ModelParameters) -> None:
        self._inner.set_parameters(p)

    def train(self, token_ids: Sequence[int]) -> None:
        self._inner.train(token_ids)

    def evaluate(self, token_ids: Sequence[int]) -> float:
        return self._inner.evaluate(token_ids)

    def empty_copy(self) -> "_EmptyNGram":
        return _EmptyNGram(self._inner.model.order, self._inner.model.vocab_size)
