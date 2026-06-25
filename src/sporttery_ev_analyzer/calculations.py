from __future__ import annotations


def validate_decimal_odds(odds: dict[str, float]) -> None:
    if not odds:
        raise ValueError("odds must not be empty")
    invalid = {name: value for name, value in odds.items() if value <= 1}
    if invalid:
        raise ValueError(f"decimal odds must be greater than 1: {invalid}")


def remove_margin_proportional(odds: dict[str, float]) -> dict[str, float]:
    validate_decimal_odds(odds)
    inverse_sum = sum(1 / value for value in odds.values())
    if inverse_sum <= 0:
        raise ValueError("odds imply invalid margin")
    return {name: (1 / value) / inverse_sum for name, value in odds.items()}


def single_ev(fair_probability: float, offered_odds: float) -> float:
    if not 0 <= fair_probability <= 1:
        raise ValueError("fair_probability must be between 0 and 1")
    if offered_odds <= 1:
        raise ValueError("offered_odds must be greater than 1")
    return fair_probability * offered_odds - 1


def combo_ev(first_ev: float, second_ev: float) -> float:
    return (1 + first_ev) * (1 + second_ev) - 1


def fractional_kelly_stake_ratio(
    combo_expected_value: float,
    combo_odds: float,
    kelly_fraction: float,
) -> float:
    if combo_odds <= 1:
        raise ValueError("combo_odds must be greater than 1")
    if not 0 <= kelly_fraction <= 1:
        raise ValueError("kelly_fraction must be between 0 and 1")
    if combo_expected_value <= 0:
        return 0.0
    return kelly_fraction * combo_expected_value / (combo_odds - 1)
