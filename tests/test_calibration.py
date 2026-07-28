import pytest

from arbiter.calibration import agreement_report, cohen_kappa, load_human_labels, save_human_label


def test_cohen_kappa_known_values():
    assert cohen_kappa(["pass", "fail"] * 5, ["pass", "fail"] * 5) == 1.0
    a = ["pass"] * 20 + ["fail"] * 5 + ["pass"] * 10 + ["fail"] * 15
    b = ["pass"] * 20 + ["pass"] * 5 + ["fail"] * 10 + ["fail"] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)
    assert cohen_kappa([], []) is None


def test_kappa_is_zero_when_judge_always_says_pass():
    human = ["pass"] * 8 + ["fail"] * 2
    assert cohen_kappa(human, ["pass"] * 10) == pytest.approx(0.0)


def test_agreement_report_per_criterion():
    human = {"i1": {"a": "pass", "b": "fail"}, "i2": {"a": "fail", "b": "fail"}, "i3": {"a": "pass"}}
    judge = {"i1": {"a": "pass", "b": "pass"}, "i2": {"a": "fail", "b": "fail"}, "i3": {"a": "fail"}}
    rep = agreement_report(human, judge, ["a", "b", "c"])
    assert rep["a"]["n"] == 3 and rep["a"]["agreement"] == pytest.approx(2 / 3)
    assert rep["b"]["confusion"]["human=fail/judge=pass"] == 1
    assert rep["c"] == {"n": 0}


def test_labels_persist_and_validate(tmp_path):
    p = tmp_path / "h.json"
    save_human_label("i1", "a", "pass", p)
    save_human_label("i1", "a", "fail", p)
    assert load_human_labels(p) == {"i1": {"a": "fail"}}
    with pytest.raises(ValueError):
        save_human_label("i1", "a", "maybe", p)
