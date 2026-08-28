"""Mock-backed unit tests for feedback/regression_suite.py.

DI seam used: ``RegressionSuite.check_candidate(candidate_id, eval_fn, auto_add_new)``
takes an injected ``eval_fn`` callable — ``eval_fn(case) -> (regressed: bool,
new_failure: Optional[KnownFailure])``. All "system under test" behaviour is
supplied by small in-process fakes, so no real LLM / HTTP / torch is touched.
The module singleton is reset via ``reset_regression_suite`` before each test.
"""

import pytest

from audiobook_studio.feedback.regression_suite import (
    KnownFailure,
    RegressionSuite,
    RegressionVerdict,
    get_regression_suite,
    reset_regression_suite,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_regression_suite()
    yield
    reset_regression_suite()


def _make_failure(
    stage="edit_for_tts",
    description="reads wrong speaker",
    payload=None,
    producer_id=None,
    added_at="2024-01-01T00:00:00",
):
    return KnownFailure(
        failure_id="",
        stage=stage,
        description=description,
        payload=payload if payload is not None else {"text": "hello"},
        producer_id=producer_id,
        added_at=added_at,
    )


def _suite_with_active(n=2):
    s = RegressionSuite()
    for i in range(n):
        s.add_failure(
            stage="edit_for_tts",
            description=f"bad case {i}",
            payload={"i": i},
            added_at="2024-01-01T00:00:00",
        )
    return s


# ── KnownFailure / RegressionVerdict dataclasses ─────────────────────────────


def test_known_failure_to_dict_roundtrip():
    f = _make_failure(producer_id="p1")
    d = f.to_dict()
    assert d["stage"] == "edit_for_tts"
    assert d["description"] == "reads wrong speaker"
    assert d["producer_id"] == "p1"
    assert d["payload"] == {"text": "hello"}


def test_regression_verdict_rejected_and_to_dict():
    v = RegressionVerdict(
        candidate_id="cand",
        active_cases=3,
        regressed_on=["a", "b"],
        new_failures_added=["c"],
        passed=False,
    )
    assert v.rejected is True
    d = v.to_dict()
    assert d["rejected"] is True
    assert d["passed"] is False
    assert d["active_cases"] == 3
    assert d["regressed_on"] == ["a", "b"]
    assert d["new_failures_added"] == ["c"]


# ── construction / properties ────────────────────────────────────────────────


def test_init_empty_state():
    s = RegressionSuite()
    assert s.total_cases == 0
    assert s.active_cases == 0
    assert s.active_failures() == ()
    assert s.is_known_failure("nope") is False


def test_total_and_active_cases_counts():
    s = _suite_with_active(3)
    assert s.total_cases == 3
    assert s.active_cases == 3
    s.retire(s.active_failures()[0].failure_id)
    assert s.active_cases == 2
    assert s.total_cases == 3


def test_active_failures_excludes_retired():
    s = _suite_with_active(2)
    fid = s.active_failures()[0].failure_id
    s.retire(fid)
    assert all(f.failure_id != fid for f in s.active_failures())
    assert s.is_known_failure(fid) is True


def test_digest_is_deterministic_and_content_based():
    a = RegressionSuite._digest("stage", "desc", {"x": 1})
    b = RegressionSuite._digest("stage", "desc", {"x": 1})
    c = RegressionSuite._digest("stage", "desc", {"x": 2})
    assert a == b
    assert a != c
    assert len(a) == 16


# ── add_failure (append-only) ────────────────────────────────────────────────


def test_add_failure_new_returns_known_failure():
    s = RegressionSuite()
    f = s.add_failure("extract", "reads wrong", {"a": 1}, added_at="t")
    assert isinstance(f, KnownFailure)
    assert s.total_cases == 1
    assert s.active_cases == 1
    assert s.is_known_failure(f.failure_id)


def test_add_failure_with_producer_indexes_producer():
    s = RegressionSuite()
    f = s.add_failure("extract", "reads wrong", {"a": 1}, producer_id="pX")
    assert f.producer_id == "pX"
    by = s.failures_by_producer("pX")
    assert by == (f,)


def test_add_failure_duplicate_reactivates_retired():
    s = RegressionSuite()
    f = s.add_failure("extract", "reads wrong", {"a": 1}, producer_id="pD")
    s.retire(f.failure_id)
    assert s.active_cases == 0
    again = s.add_failure("extract", "reads wrong", {"a": 1}, producer_id="pD")
    # idempotent: same failure id returned, and re-activated to active
    assert again.failure_id == f.failure_id
    assert s.active_cases == 1
    # producer re-indexed on re-activation
    assert s.failures_by_producer("pD") == (again,)


def test_add_failure_duplicate_without_producer_no_index():
    s = RegressionSuite()
    f = s.add_failure("extract", "reads wrong", {"a": 1})
    again = s.add_failure("extract", "reads wrong", {"a": 1})
    assert again.failure_id == f.failure_id
    assert s.failures_by_producer("pD") == ()


# ── retire ──────────────────────────────────────────────────────────────────


def test_retire_missing_returns_false():
    s = RegressionSuite()
    assert s.retire("does-not-exist") is False


def test_retire_existing_returns_true():
    s = RegressionSuite()
    f = s.add_failure("extract", "reads wrong", {"a": 1})
    assert s.retire(f.failure_id) is True
    assert s.active_cases == 0


# ── check_candidate: pass / regress / new failure / error / edge ─────────────


def test_check_candidate_empty_suite_passes():
    s = RegressionSuite()
    calls = []

    def ef(case):
        calls.append(case)
        return False, None

    v = s.check_candidate("c1", ef)
    assert v.passed is True
    assert v.rejected is False
    assert v.regressed_on == []
    assert v.new_failures_added == []
    assert v.active_cases == 0
    assert calls == []


def test_check_candidate_all_pass():
    s = _suite_with_active(3)
    seen = []
    v = s.check_candidate("c1", lambda case: (seen.append(case) or (False, None)))
    assert v.passed is True
    assert v.regressed_on == []
    assert v.new_failures_added == []
    assert len(seen) == 3


def test_check_candidate_regress_only_rejects():
    s = _suite_with_active(2)

    def ef(case):
        return (case.description == "bad case 0"), None

    v = s.check_candidate("c1", ef)
    assert v.rejected is True
    assert v.active_cases == 2
    assert v.new_failures_added == []
    assert len(v.regressed_on) == 1
    assert v.regressed_on[0] == s.active_failures()[0].failure_id


def test_check_candidate_new_failure_auto_added_and_rejects():
    s = _suite_with_active(1)
    new_fail = _make_failure(stage="extract", description="new discovery", payload={"k": 9})

    def ef(case):
        return False, new_fail

    v = s.check_candidate("cand_new", ef)
    # new failure -> candidate rejected (its producer is blocked)
    assert v.rejected is True
    assert len(v.new_failures_added) == 1
    # new failure is now indexed under the candidate as its producer
    added_id = v.new_failures_added[0]
    assert any(f.failure_id == added_id for f in s.failures_by_producer("cand_new"))


def test_check_candidate_regress_and_new_failure_then_dedup():
    s = _suite_with_active(1)
    # The new_failure we return has the SAME content as the active case that
    # already regressed -> its digest equals that case's id, so it must be
    # de-duplicated in regressed_on (append once, not twice).
    active = s.active_failures()[0]

    def ef(case):
        same = _make_failure(stage=case.stage, description=case.description, payload=dict(case.payload))
        return True, same

    v = s.check_candidate("c1", ef)
    assert v.rejected is True
    # regressed_on should contain the id exactly once despite regress + new-add
    assert v.regressed_on.count(active.failure_id) == 1
    assert len(v.regressed_on) == 1


def test_check_candidate_eval_raises_conservative_reject():
    s = _suite_with_active(1)
    before = s.total_cases

    def ef(case):
        raise RuntimeError("boom")

    v = s.check_candidate("c1", ef)
    # conservative: treat as regression + record a new failure
    assert v.rejected is True
    assert len(v.new_failures_added) == 1
    # a new failure was appended to the suite
    assert s.total_cases == before + 1
    added = s.failures_by_producer("c1")
    assert len(added) == 1
    assert "raised" in added[0].description


def test_check_candidate_auto_add_false_does_not_record():
    s = _suite_with_active(1)
    new_fail = _make_failure(description="should not be added", payload={"z": 1})
    before = s.total_cases

    def ef(case):
        return False, new_fail

    v = s.check_candidate("c1", ef, auto_add_new=False)
    assert v.new_failures_added == []
    assert s.total_cases == before
    # even though new failure returned, regressed_on stays empty -> still passed
    assert v.passed is True


def test_check_candidate_duplicate_new_failures_dedup_in_new_added():
    # Two distinct active cases; eval_fn returns identical new_failure content
    # for both -> second add_failure is idempotent, so new_failures_added must
    # contain the id only once.
    s = _suite_with_active(2)
    shared = _make_failure(description="shared new bug", payload={"same": True})

    def ef(case):
        return False, shared

    v = s.check_candidate("c1", ef)
    assert len(v.new_failures_added) == 1
    assert v.rejected is True


def test_check_candidate_returns_regression_verdict_shape():
    s = _suite_with_active(1)
    v = s.check_candidate("c1", lambda case: (False, None))
    assert isinstance(v, RegressionVerdict)
    assert v.candidate_id == "c1"
    assert v.active_cases == 1


# ── snapshot ─────────────────────────────────────────────────────────────────


def test_snapshot_structure_and_content():
    s = _suite_with_active(2)
    f = s.active_failures()[0]
    s.retire(f.failure_id)
    snap = s.snapshot()
    assert snap["total"] == 2
    assert snap["active"] == 1
    assert f.failure_id in snap["retired"]
    assert len(snap["failures"]) == 2
    assert all(isinstance(fd, dict) and "failure_id" in fd for fd in snap["failures"])


# ── module singleton ─────────────────────────────────────────────────────────


def test_singleton_lifecycle():
    a = get_regression_suite()
    b = get_regression_suite()
    assert a is b
    reset_regression_suite()
    c = get_regression_suite()
    assert c is not a
