"""V8 Block 4: Cohen's kappa between two independent human labelers, and the label_cli verdict
derivation from the two guide dimensions (grounded, complete) — tested with synthetic data since
the real second labeler has not run yet."""
from app.evaluation.calibrate_critic import human_human_kappa
from app.evaluation.label_cli import verdict


def test_human_human_kappa_is_one_on_perfect_agreement():
    a = {"q1": {"label": "correct", "grounded": "sim", "complete": "sim"},
         "q2": {"label": "incorrect", "grounded": "nao", "complete": "sim"},
         "q3": {"label": "correct", "grounded": "sim", "complete": "sim"},
         "q4": {"label": "partially_correct", "grounded": "parcial", "complete": "sim"}}
    b = dict(a)
    result = human_human_kappa({"ana": a, "bruno": b})
    assert result["shared_items"] == 4
    assert result["verdict"]["cohen_kappa"] == 1.0
    assert result["grounded"]["cohen_kappa"] == 1.0


def test_human_human_kappa_is_near_zero_on_chance_level_disagreement():
    # Four items, two labels each 50/50, labeler B's verdict is the opposite of A's — worse than
    # chance, so kappa should be negative (below 0), never close to the perfect-agreement 1.0.
    a = {f"q{i}": {"label": "correct" if i % 2 == 0 else "incorrect"} for i in range(8)}
    b = {f"q{i}": {"label": "incorrect" if i % 2 == 0 else "correct"} for i in range(8)}
    result = human_human_kappa({"ana": a, "bruno": b})
    assert result["verdict"]["cohen_kappa"] < 0.5


def test_human_human_kappa_only_compares_shared_items():
    a = {"q1": {"label": "correct"}, "q2": {"label": "correct"}}
    b = {"q2": {"label": "correct"}, "q3": {"label": "incorrect"}}
    result = human_human_kappa({"ana": a, "bruno": b})
    assert result["shared_items"] == 1


def test_human_human_kappa_needs_at_least_two_labelers():
    assert human_human_kappa({"ana": {"q1": {"label": "correct"}}}) is None
    assert human_human_kappa({}) is None


def test_verdict_combines_grounded_and_complete():
    assert verdict("sim", "sim", False) == "correct"
    assert verdict("parcial", "sim", False) == "partially_correct"
    assert verdict("sim", "parcial", False) == "partially_correct"
    assert verdict("nao", "sim", False) == "incorrect"
    assert verdict("sim", "nao", False) == "incorrect"


def test_verdict_unsafe_overrides_everything():
    assert verdict("sim", "sim", True) == "unsafe"
