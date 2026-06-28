from __future__ import annotations

from math import sqrt
from typing import Any


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


def remove_margin_shin(odds: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    validate_decimal_odds(odds)
    inverse_odds = {name: 1 / value for name, value in odds.items()}
    inverse_sum = sum(inverse_odds.values())
    if inverse_sum <= 1:
        raise ValueError("shin method requires overround odds")

    def probabilities(z: float) -> dict[str, float]:
        return {
            name: (sqrt(z * z + 4 * (1 - z) * q * q / inverse_sum) - z) / (2 * (1 - z))
            for name, q in inverse_odds.items()
        }

    z = _bisect(lambda value: sum(probabilities(value).values()) - 1, 0.0, 0.4)
    return probabilities(z), {"z": z}


def remove_margin_power(odds: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    validate_decimal_odds(odds)
    inverse_odds = {name: 1 / value for name, value in odds.items()}
    k = _bisect(lambda value: sum(q**value for q in inverse_odds.values()) - 1, 0.01, 10.0)
    return {name: q**k for name, q in inverse_odds.items()}, {"k": k}


def remove_margin_all_methods(odds: dict[str, float]) -> dict[str, dict[str, Any]]:
    methods = {
        "proportional": lambda: (remove_margin_proportional(odds), {}),
        "shin": lambda: remove_margin_shin(odds),
        "power": lambda: remove_margin_power(odds),
    }
    results: dict[str, dict[str, Any]] = {}
    for name, method in methods.items():
        try:
            probabilities, params = method()
        except ValueError as exc:
            results[name] = {"status": "failed", "error": str(exc), "probabilities": {}, "params": {}}
        else:
            results[name] = {"status": "ok", "probabilities": probabilities, "params": params}
    return results


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


def _bisect(function, low: float, high: float, *, iterations: int = 80) -> float:
    low_value = function(low)
    high_value = function(high)
    if abs(low_value) < 1e-12:
        return low
    if abs(high_value) < 1e-12:
        return high
    if low_value * high_value > 0:
        raise ValueError("could not bracket margin removal root")
    for _ in range(iterations):
        mid = (low + high) / 2
        mid_value = function(mid)
        if abs(mid_value) < 1e-12:
            return mid
        if low_value * mid_value > 0:
            low = mid
            low_value = mid_value
        else:
            high = mid
    return (low + high) / 2
