import pytest


def test_undercharged_same_weather_adjusts_up(config):
    from src.calculator.feedback import compute_feedback_adjustment
    adj = compute_feedback_adjustment(config=config, today_grid_import_kwh=4.0,
        today_surplus_export_kwh=0.0, today_weather="cloudy",
        tomorrow_weather="cloudy", previous_cumulative=0)
    assert adj > 0
    assert adj <= config.feedback.max_per_night_pct


def test_overcharged_same_weather_adjusts_down(config):
    from src.calculator.feedback import compute_feedback_adjustment
    adj = compute_feedback_adjustment(config=config, today_grid_import_kwh=0.0,
        today_surplus_export_kwh=5.0, today_weather="cloudy",
        tomorrow_weather="sunny", previous_cumulative=0)
    assert adj < 0
    assert abs(adj) <= config.feedback.max_per_night_pct


def test_cumulative_cap(config):
    from src.calculator.feedback import compute_feedback_adjustment
    adj = compute_feedback_adjustment(config=config, today_grid_import_kwh=10.0,
        today_surplus_export_kwh=0.0, today_weather="rainy",
        tomorrow_weather="rainy", previous_cumulative=20)
    assert adj <= 5  # can only add 5 more to reach cap of 25


def test_decay_reduces_cumulative(config):
    from src.calculator.feedback import apply_decay
    decayed = apply_decay(15, config.feedback.decay_per_day_pct)
    assert decayed == 10


def test_no_adjustment_when_weather_improves_after_undercharge(config):
    from src.calculator.feedback import compute_feedback_adjustment
    adj = compute_feedback_adjustment(config=config, today_grid_import_kwh=5.0,
        today_surplus_export_kwh=0.0, today_weather="rainy",
        tomorrow_weather="sunny", previous_cumulative=0)
    assert adj == 0
