import unittest

from sporttery_ev_analyzer.calculations import combo_ev, fractional_kelly_stake_ratio, remove_margin_proportional, single_ev


class CalculationTests(unittest.TestCase):
    def test_remove_margin_probabilities_sum_to_one(self):
        probabilities = remove_margin_proportional({"home": 1.9, "draw": 3.45, "away": 4.2})

        self.assertEqual(round(sum(probabilities.values()), 12), 1)
        self.assertEqual(round(probabilities["home"], 6), 0.499225)

    def test_single_ev_can_be_positive_or_negative(self):
        self.assertEqual(round(single_ev(0.5, 2.1), 4), 0.05)
        self.assertEqual(round(single_ev(0.45, 2.0), 4), -0.1)

    def test_combo_ev_and_fractional_kelly(self):
        expected_value = combo_ev(0.05, 0.04)

        self.assertEqual(round(expected_value, 4), 0.092)
        self.assertEqual(round(fractional_kelly_stake_ratio(expected_value, 4.0, 0.1), 6), 0.003067)


if __name__ == "__main__":
    unittest.main()
