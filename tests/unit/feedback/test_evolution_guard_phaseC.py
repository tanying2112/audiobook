"""Phase C structural tests for feedback/evolution_guard.py (kill-switch evolution logic)."""

from src.audiobook_studio.feedback.evolution_guard import (
    EvolutionGuard,
    get_evolution_guard,
    reset_evolution_guard,
)


def _promote(guard, nid, mean, effect=0.5, stage="edit_for_tts", ts="2024-01-01T00:00:00"):
    return guard.record(nid, stage, mean, effect, ts)


def test_first_promotion_sets_root_and_active():
    g = EvolutionGuard()
    assert g.active_id is None
    res = _promote(g, "n1", 0.90)
    assert res is None
    assert g.root_id == "n1"
    assert g.active_id == "n1"
    assert g.node_count == 1
    assert g.regression_streak == 0
    assert g.active_node.node_id == "n1"


def test_promotion_chain_and_lineage():
    g = EvolutionGuard()
    _promote(g, "n1", 0.90)
    _promote(g, "n2", 0.92)
    _promote(g, "n3", 0.95)
    assert g.active_id == "n3"
    chain = g.lineage()
    assert [n.node_id for n in chain] == ["n1", "n2", "n3"]


def test_regression_increments_streak_then_rolls_back():
    g = EvolutionGuard(regression_streak=2)
    _promote(g, "n1", 0.90)  # root / active mean 0.90
    # regression #1: lower mean, effect below min_effect
    r1 = g.record("cand_a", "edit_for_tts", 0.80, 0.10, "t2")
    assert r1 is None
    assert g.regression_streak == 1
    assert g.active_id == "n1"  # no promotion
    # regression #2 -> rollback to parent (n1 is root, no parent)
    r2 = g.record("cand_b", "edit_for_tts", 0.70, 0.10, "t3")
    assert r2 is not None
    assert r2.rolled_back_from == "n1"
    assert r2.rolled_back_to == ""
    assert g.is_pruned("n1") is True
    assert g.last_rollback is r2


def test_regression_rolls_back_to_parent_and_prunes_descendants():
    g = EvolutionGuard(regression_streak=2)
    _promote(g, "n1", 0.90)
    _promote(g, "n2", 0.95)
    _promote(g, "n3", 0.97)  # active = n3, parent n2
    # two regressions trigger rollback of n3
    g.record("cand_a", "edit_for_tts", 0.50, 0.10, "t4")
    rb = g.record("cand_b", "edit_for_tts", 0.40, 0.10, "t5")
    assert rb is not None
    assert rb.rolled_back_from == "n3"
    assert rb.rolled_back_to == "n2"
    assert g.is_pruned("n3") is True
    assert g.active_id == "n2"
    # promote again after rollback
    _promote(g, "n4", 0.99)
    assert g.active_id == "n4"
    assert not g.is_pruned("n4")


def test_min_effect_promotes_even_if_mean_drops():
    g = EvolutionGuard()
    _promote(g, "n1", 0.90)
    # mean dropped but effect_size >= min_effect -> treated as promotion
    res = g.record("n2", "edit_for_tts", 0.85, 0.50, "t2")
    assert res is None
    assert g.active_id == "n2"
    assert g.regression_streak == 0


def test_treat_as_regression_false_promotes():
    g = EvolutionGuard()
    _promote(g, "n1", 0.90)
    res = g.record("n2", "edit_for_tts", 0.80, 0.10, "t2", treat_as_regression_on_drop=False)
    assert res is None
    assert g.active_id == "n2"
    assert g.regression_streak == 0


def test_regression_streak_limit_one():
    g = EvolutionGuard(regression_streak=1)
    _promote(g, "n1", 0.90)
    rb = g.record("cand", "edit_for_tts", 0.80, 0.10, "t2")
    assert rb is not None
    assert g.is_pruned("n1") is True


def test_rollback_with_no_active_baseline():
    g = EvolutionGuard()
    rb = g._rollback_and_prune("manual")
    assert rb.rolled_back_from == ""
    assert rb.rolled_back_to == ""
    assert rb.reason == "no active baseline"


def test_lineage_excludes_pruned_branch():
    g = EvolutionGuard(regression_streak=2)
    _promote(g, "n1", 0.90)
    _promote(g, "n2", 0.95)
    _promote(g, "n3", 0.97)
    g.record("cand_a", "edit_for_tts", 0.50, 0.10, "t4")
    g.record("cand_b", "edit_for_tts", 0.40, 0.10, "t5")  # rollback n3
    chain = g.lineage()
    assert [n.node_id for n in chain] == ["n1", "n2"]


def test_to_snapshot_roundtrip():
    g = EvolutionGuard(regression_streak=2)
    _promote(g, "n1", 0.90)
    _promote(g, "n2", 0.95)
    g.record("cand_a", "edit_for_tts", 0.50, 0.10, "t4")
    g.record("cand_b", "edit_for_tts", 0.40, 0.10, "t5")  # rollback n2 -> active n1
    snap = g.to_snapshot()
    assert snap["active_id"] == "n1"
    assert snap["root_id"] == "n1"
    assert "n2" in snap["pruned_ids"]
    assert snap["last_rollback"] is not None
    assert snap["last_rollback"]["rolled_back_from"] == "n2"


def test_singleton_lifecycle():
    reset_evolution_guard()
    g1 = get_evolution_guard()
    g2 = get_evolution_guard()
    assert g1 is g2
    reset_evolution_guard()
    g3 = get_evolution_guard()
    assert g3 is not g1


def test_collect_descendants_recurses():
    g = EvolutionGuard()
    _promote(g, "n1", 0.90)
    _promote(g, "n2", 0.92)  # child of n1
    _promote(g, "n3", 0.94)  # child of n2
    desc = g._collect_descendants("n1")
    assert set(desc) == {"n2", "n3"}
