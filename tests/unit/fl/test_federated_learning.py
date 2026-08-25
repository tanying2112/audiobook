"""Tests for the federated learning framework (privacy-preserving aggregation).

Covers the three pillars requested: multi-user local training (raw data never
leaves the client), FedAvg aggregation, Secure Aggregation (server only sees the
masked sum) and Differential Privacy (client-side clip + noise + epsilon/delta
accounting + a membership-inference privacy auditor).

Acceptance target: model aggregation under multi-user data-privacy protection.
"""

import numpy as np
import pytest

from src.audiobook_studio.fl import (
    DpConfig,
    FLConfig,
    FedAvgAggregator,
    FederatedClient,
    FederatedServer,
    LocalARModelAdapter,
    MembershipInferenceEstimator,
    ModelParameters,
    SecAggSession,
    create_federated_n_gram_server,
    dequantize,
    gaussian_dp_epsilon,
    is_federated_enabled,
    quantize,
)


def _corpus(off, n=300):
    return [(i * 7 + off) % 40 for i in range(n)]


def _make_clients(n, config, seed=1):
    data = [_corpus(off) for off in range(0, n * 11, 11)]
    return [
        FederatedClient(f"u:{i}", d, LocalARModelAdapter(order=3, vocab_size=40), config, np.random.default_rng(seed + i))
        for i, d in enumerate(data)
    ]


# ---------------------------------------------------------------------------
# Pillar 1: multi-user local training; raw data never leaves the client
# ---------------------------------------------------------------------------


def test_raw_data_never_transmitted():
    cfg = FLConfig(seed=1)
    clients = _make_clients(3, cfg)
    server, _ = create_federated_n_gram_server(3, 40, cfg)
    server.bootstrap_keys(clients)
    results = [c.build_update(server.key_order if cfg.mode == "secagg" else None) for c in clients]
    # Server never stores any client's private data.
    assert not hasattr(server, "private_data")
    for c, r in zip(clients, results):
        # The client keeps its OWN raw data locally.
        assert r is not None
        # The exact comma-joined training sequence must NOT appear in the upload.
        seq_repr = ",".join(str(int(t)) for t in c.private_data)
        blob = str(r.params) + str(r.masked)
        assert seq_repr not in blob
        # The upload is aggregated statistics / a masked vector, not the raw list.
        assert r.params is not c.private_data
        assert c.private_data is not None


def test_federated_beats_single_client():
    cfg = FLConfig(seed=2)
    clients = _make_clients(3, cfg)
    server, _ = create_federated_n_gram_server(3, 40, cfg)
    server.bootstrap_keys(clients)
    for _ in range(3):
        server.run_round(clients)
    held = _corpus(5, 200)
    local0 = LocalARModelAdapter(3, 40)
    local0.train(clients[0].private_data)
    fed_ll = server.model.evaluate(held)
    single_ll = local0.evaluate(held)
    assert fed_ll > single_ll  # pooled statistics generalize better


# ---------------------------------------------------------------------------
# Pillar 2: FedAvg aggregation correctness
# ---------------------------------------------------------------------------


def test_fedavg_averages_counts():
    p1 = ModelParameters(vocab_size=2, order=2, counts={("a",): [1.0, 3.0], ("b",): [0.0, 2.0]})
    p2 = ModelParameters(vocab_size=2, order=2, counts={("a",): [3.0, 1.0], ("c",): [4.0, 0.0]})
    agg = FedAvgAggregator().aggregate([p1, p2], [1.0, 1.0])
    # key 'a' averaged: [2,2]; keys b/c only in one client are averaged over both
    # clients (the other contributes 0 for that context) -> halved.
    assert agg.counts[("a",)] == [2.0, 2.0]
    assert agg.counts[("b",)] == [0.0, 1.0]
    assert agg.counts[("c",)] == [2.0, 0.0]


# ---------------------------------------------------------------------------
# Pillar 3: Secure Aggregation — server only recovers the SUM, never individuals
# ---------------------------------------------------------------------------


def test_secagg_server_only_sees_sum_not_individuals():
    rng = np.random.default_rng(0)
    p0 = rng.integers(0, 100, size=8).astype(np.int64)
    p1 = rng.integers(0, 100, size=8).astype(np.int64)
    p2 = rng.integers(0, 100, size=8).astype(np.int64)
    prime = (1 << 31) - 1
    sess = SecAggSession(3, 8, prime, rng)
    m0, m1, m2 = sess.client_mask(0, p0), sess.client_mask(1, p1), sess.client_mask(2, p2)

    # Each masked upload hides the true params (information-theoretically).
    assert not np.array_equal(m0, p0)
    assert not np.array_equal(m1, p1)
    assert not np.array_equal(m2, p2)

    recovered = sess.server_aggregate([m0, m1, m2])
    expected = (p0 + p1 + p2) % prime
    assert np.array_equal(recovered, expected)


def test_secagg_dropout_recovers_remaining_sum():
    rng = np.random.default_rng(3)
    prime = (1 << 31) - 1
    params = [rng.integers(0, 50, size=6).astype(np.int64) for _ in range(4)]
    sess = SecAggSession(4, 6, prime, rng)
    masked = [sess.client_mask(i, params[i]) for i in range(4)]
    # client 2 drops; its present peers reveal the masks they shared with it.
    dropped = 2
    revealed = {}
    for j in range(4):
        if j == dropped:
            continue
        if dropped < j:
            revealed[j] = sess.masks[(dropped, j)]
        else:
            revealed[j] = sess.masks[(j, dropped)]
    remaining = [masked[j] for j in range(4) if j != dropped]
    recovered = sess.server_aggregate_with_dropout(remaining, dropped, revealed)
    expected = sum(params[j] for j in range(4) if j != dropped) % prime
    assert np.array_equal(recovered, expected)


# ---------------------------------------------------------------------------
# Pillar 4: Differential Privacy — clip + noise + epsilon accounting
# ---------------------------------------------------------------------------


def test_dp_clip_and_noise():
    from src.audiobook_studio.fl.privacy import add_gaussian_noise, clip_to_norm

    v = np.array([10.0, 0.0, 0.0])
    clipped = clip_to_norm(v, 1.0)
    assert np.linalg.norm(clipped) <= 1.0 + 1e-9
    rng = np.random.default_rng(0)
    noised = add_gaussian_noise(np.zeros(100), 1.0, rng)
    assert abs(np.mean(noised)) < 0.5  # ~N(0,1)


def test_gaussian_dp_epsilon_monotonic():
    # Larger noise_multiplier / smaller delta -> smaller epsilon.
    e_low = gaussian_dp_epsilon(1.0, 2.0, 1e-5, steps=1)
    e_high = gaussian_dp_epsilon(5.0, 2.0, 1e-5, steps=1)
    assert e_high < e_low
    assert gaussian_dp_epsilon(0.0, 2.0, 1e-5) == float("inf")
    # per-client guarantee from a DP config
    cfg = DpConfig(clip_norm=1.0, noise_multiplier=1.5, delta=1e-5)
    eps = cfg.epsilon_spent(rounds=1)
    assert 0.0 < eps < 10.0


def test_dp_reduces_membership_inference():
    rng = np.random.default_rng(7)
    vocab, order = 40, 3

    def score(model, seq):
        return model.evaluate(seq)

    member_seqs = [_corpus(0, 80) for _ in range(5)]
    # A *genuinely different* distribution: step-13 chain (not the +7 rule the
    # member data follows) so the model fit to members does NOT fit nonmembers.
    nonmember_seqs = [[(i * 13 + 5) % 40 for i in range(80)] for _ in range(5)]

    # Without DP: the global model is trained directly on the member data.
    before = LocalARModelAdapter(order, vocab)
    after = LocalARModelAdapter(order, vocab)
    after.train(member_seqs[0])
    all_seqs = member_seqs + nonmember_seqs
    lp_b = [score(before, s) for s in all_seqs]
    lp_a = [score(after, s) for s in all_seqs]
    acc_no_dp = MembershipInferenceEstimator.attack_accuracy(
        lp_b, lp_a, list(range(5)), list(range(5, 10))
    )
    assert acc_no_dp >= 0.7  # membership clearly visible without protection

    # With DP: the client clips + heavily noises its upload before aggregation.
    from src.audiobook_studio.fl.privacy import clip_to_norm, add_gaussian_noise

    local = LocalARModelAdapter(order, vocab)
    local.train(member_seqs[0])
    flat = np.array(
        [x for v in local.get_parameters().counts.values() for x in v], dtype=np.float64
    )
    flat = clip_to_norm(flat, 5.0)
    flat = add_gaussian_noise(flat, 5.0 * 3.0, rng)  # strong noise
    noisy = ModelParameters.from_flat(
        flat, list(local.get_parameters().counts.keys()), vocab, order
    )
    after_dp = LocalARModelAdapter(order, vocab)
    after_dp.set_parameters(noisy)
    lp_a_dp = [score(after_dp, s) for s in all_seqs]
    acc_dp = MembershipInferenceEstimator.attack_accuracy(
        lp_b, lp_a_dp, list(range(5)), list(range(5, 10))
    )
    assert acc_dp < acc_no_dp  # DP meaningfully lowers the attacker's accuracy


# ---------------------------------------------------------------------------
# End-to-end: secure aggregation round produces a valid global model
# ---------------------------------------------------------------------------


def test_secagg_round_end_to_end():
    cfg = FLConfig(mode="secagg", seed=11)
    clients = _make_clients(3, cfg)
    server, _ = create_federated_n_gram_server(3, 40, cfg)
    server.bootstrap_keys(clients)
    p = server.run_round(clients)
    assert len(p.keys()) > 0
    # global model usable
    held = _corpus(9, 100)
    assert server.model.evaluate(held) > -5.0


def test_dp_fedavg_round_end_to_end():
    cfg = FLConfig(mode="fedavg", dp=DpConfig(clip_norm=10.0, noise_multiplier=1.0, delta=1e-5), seed=13)
    clients = _make_clients(3, cfg)
    server, _ = create_federated_n_gram_server(3, 40, cfg)
    server.bootstrap_keys(clients)
    p = server.run_round(clients)
    # global still has the right shape and is usable
    assert len(p.keys()) > 0
    assert cfg.dp.epsilon_spent(1) < float("inf")


# ---------------------------------------------------------------------------
# env gating
# ---------------------------------------------------------------------------


def test_env_gating(monkeypatch):
    monkeypatch.delenv("FEDERATED_LEARNING_ENABLED", raising=False)
    assert is_federated_enabled() is False
    monkeypatch.setenv("FEDERATED_LEARNING_ENABLED", "true")
    assert is_federated_enabled() is True
