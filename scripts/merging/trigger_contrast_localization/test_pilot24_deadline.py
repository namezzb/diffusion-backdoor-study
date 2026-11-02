import unittest

from pilot24_deadline import assess_throughput, deadline_state


class DeadlineTests(unittest.TestCase):
    def test_fixed_t0_boundaries_and_clock_regression(self):
        t0 = "2026-11-02T00:00:00Z"
        self.assertTrue(deadline_state(t0, "2026-11-02T21:59:59Z")["generation_permitted"])
        self.assertFalse(deadline_state(t0, "2026-11-02T22:00:00Z")["generation_permitted"])
        self.assertTrue(deadline_state(t0, "2026-11-02T22:14:59Z")["compute_permitted"])
        self.assertFalse(deadline_state(t0, "2026-11-02T22:15:00Z")["compute_permitted"])
        self.assertTrue(deadline_state(t0, "2026-11-03T00:00:00Z")["report_overdue"])
        with self.assertRaises(ValueError):
            deadline_state(t0, "2026-11-02T01:00:00Z", previous_observed_utc="2026-11-02T01:01:00Z")

    def test_measured_plan_is_not_approved_without_coverage_validation(self):
        result = assess_throughput("2026-11-02T00:00:00Z", "2026-11-02T02:00:00Z",
                                   finished=64, by_worker={"a": 32, "b": 32},
                                   remaining_attempts=6080, seconds_per_attempt=8)
        self.assertTrue(result["sample_count_eligible"])
        self.assertTrue(result["capacity_sufficient_if_coverage_verified"])
        self.assertFalse(result["class_coverage_verified"])
        self.assertEqual(result["decision"], "requires_class_and_rate_validation")
        with self.assertRaises(ValueError):
            assess_throughput("2026-11-02T00:00:00Z", "2026-11-02T02:00:00Z", finished=64,
                              by_worker={"a": 63}, remaining_attempts=10, seconds_per_attempt=1)


if __name__ == "__main__":
    unittest.main()
