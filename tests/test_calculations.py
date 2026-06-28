import unittest

from sporttery_ev_analyzer.calculations import (
    combo_ev,
    fractional_kelly_stake_ratio,
    remove_margin_all_methods,
    remove_margin_power,
    remove_margin_proportional,
    remove_margin_shin,
    single_ev,
)


class CalculationTests(unittest.TestCase):
    def test_remove_margin_probabilities_sum_to_one(self):
        probabilities = remove_margin_proportional({"home": 1.9, "draw": 3.45, "away": 4.2})

        self.assertEqual(round(sum(probabilities.values()), 12), 1)
        self.assertEqual(round(probabilities["home"], 6), 0.499225)

    def test_advanced_margin_methods_are_deterministic(self):
        shin_probabilities, shin_params = remove_margin_shin({"home": 1.9, "draw": 3.45, "away": 4.2})
        power_probabilities, power_params = remove_margin_power({"home": 1.9, "draw": 3.45, "away": 4.2})

        self.assertEqual(round(sum(shin_probabilities.values()), 12), 1)
        self.assertEqual(round(sum(power_probabilities.values()), 12), 1)
        self.assertEqual(round(shin_probabilities["home"], 6), 0.505907)
        self.assertEqual(round(power_probabilities["home"], 6), 0.508442)
        self.assertGreaterEqual(shin_params["z"], 0)
        self.assertGreater(power_params["k"], 1)

    def test_symmetric_two_way_market_stays_symmetric(self):
        for method in (remove_margin_proportional, lambda odds: remove_margin_shin(odds)[0], lambda odds: remove_margin_power(odds)[0]):
            probabilities = method({"a": 1.9, "b": 1.9})

            self.assertEqual(round(probabilities["a"], 6), 0.5)
            self.assertEqual(round(probabilities["b"], 6), 0.5)

    def test_margin_method_dispatch_reports_individual_failures(self):
        methods = remove_margin_all_methods({"home": 3.0, "draw": 3.0, "away": 3.0})

        self.assertEqual(methods["proportional"]["status"], "ok")
        self.assertEqual(methods["shin"]["status"], "failed")

    def test_single_ev_can_be_positive_or_negative(self):
        self.assertEqual(round(single_ev(0.5, 2.1), 4), 0.05)
        self.assertEqual(round(single_ev(0.45, 2.0), 4), -0.1)

    def test_combo_ev_and_fractional_kelly(self):
        expected_value = combo_ev(0.05, 0.04)

        self.assertEqual(round(expected_value, 4), 0.092)
        self.assertEqual(round(fractional_kelly_stake_ratio(expected_value, 4.0, 0.1), 6), 0.003067)


if __name__ == "__main__":
    unittest.main()
