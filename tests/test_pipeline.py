from glucotwin.models.bundle import ModelBundle


def _rmse(report, model, h):
    return next(t.rmse_mg_dl for t in report.trajectory if t.model == model and t.horizon_min == h)


def test_report_contains_baselines_and_is_marked_synthetic(trained):
    report, *_ = trained
    assert report.dataset.is_synthetic
    models = {t.model for t in report.trajectory}
    assert {"persistence", "damped_trend", "ridge", "hist_gradient_boosting"} <= models
    assert {e.model for e in report.event} == {"trend_rule", "logistic_regression", "hist_gradient_boosting"}


def test_learned_model_beats_persistence_at_60_min(trained):
    report, *_ = trained
    assert _rmse(report, "ridge", 60) < _rmse(report, "persistence", 60)


def test_bundle_roundtrip(trained):
    _, bundle, _, path = trained
    loaded = ModelBundle.load(path)
    assert loaded.model_version == bundle.model_version
    assert loaded.cohort_params == {"n_patients": 10, "days": 4, "seed": 1234}
    assert 0 < loaded.alert_threshold < 1
