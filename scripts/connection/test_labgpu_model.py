"""Safety-relevant normalization tests using entirely synthetic member data."""
import copy
import json
import unittest

from labgpu_model import normalize


NOW = 1800000000.0
UUID = "GPU-11111111-2222-3333-4444-555555555555"


def fixture():
    return {"username": "tester", "role": "viewer", "limit": 4,
            "usage": {"count": 0, "limit": 4}, "rules": {"gpu_limit": 4},
            "maintenance": [], "gpu_requests": [], "hosts": [{
                "id": "test-104", "label": "104", "online": True,
                "sampled_at": NOW - 4, "processes_sampled_at": NOW - 4,
                "age_seconds": 4, "expected_gpu_count": 1,
                "processes_complete": True, "process_state_complete": True,
                "processes": [], "gpus": [{"index": 0, "uuid": UUID,
                    "name": "Synthetic GPU", "compute_mode": "Default",
                    "memory_used": 0, "memory_total": 24000,
                    "utilization_gpu": 0, "temperature": 35}]}]}


class NormalizeTests(unittest.TestCase):
    def norm(self, payload=None, **kwargs):
        options = dict(fetched_at=NOW, now=NOW, source="https://example.test/api/me", cache_state="fresh")
        options.update(kwargs)
        return normalize(payload if payload is not None else fixture(), **options)

    def status(self, payload=None, **kwargs):
        return self.norm(payload, **kwargs)["hosts"][0]["gpus"][0]["status"]

    def test_complete_idle_is_free_but_never_authorization(self):
        result = self.norm()
        self.assertEqual(result["summary"]["free_gpus"], 1)
        self.assertIs(result["policy"]["query_is_authorization"], False)

    def test_offline_and_expired_sample_are_stale(self):
        for change in ({"online": False}, {"sampled_at": NOW - 121},
                       {"processes_sampled_at": NOW - 121}, {"gpu_data_stale": True},
                       {"age_seconds": 121}):
            with self.subTest(change=change):
                p = fixture(); p["hosts"][0].update(change)
                self.assertEqual(self.status(p), "stale")

    def test_process_sample_age_is_exposed_for_launch_freshness(self):
        p = fixture(); p["hosts"][0]["processes_sampled_at"] = NOW - 115
        self.assertEqual(self.status(p), "free")
        self.assertEqual(self.norm(p)["hosts"][0]["process_sample_age_seconds"], 115)
        self.assertEqual(self.status(p, now=NOW + 6), "stale")

    def test_cache_failure_never_shows_old_free(self):
        for state in ("stale", "offline", "error", "unrecognized"):
            self.assertEqual(self.status(cache_state=state), "stale")
        self.assertEqual(self.status(cache_state="cached", now=NOW + 121), "stale")
        self.assertEqual(self.status(cache_state="cached", now=NOW + 1), "free")

    def test_host_completeness_missing_is_unknown(self):
        for key in ("online", "sampled_at", "processes_sampled_at", "processes",
                    "processes_complete", "process_state_complete"):
            with self.subTest(key=key):
                p = fixture(); del p["hosts"][0][key]
                self.assertEqual(self.status(p), "unknown")

    def test_false_and_invalid_completeness_are_unknown(self):
        for value in (False, "true", 1, None):
            p = fixture(); p["hosts"][0]["processes_complete"] = value
            self.assertEqual(self.status(p), "unknown")

    def test_disabled_dominates_occupancy_and_staleness(self):
        p = fixture(); h = p["hosts"][0]
        h["gpus"][0]["compute_mode"] = "Prohibited"
        h["online"] = False
        h["processes"] = [{"gpu_uuid": UUID, "user": "other", "own": False}]
        self.assertEqual(self.status(p), "disabled")
        self.assertEqual(self.norm(p)["hosts"][0]["gpus"][0]["users"], ["other"])

    def test_mine_others_shared_and_unknown_owner(self):
        for users, expected in ((["tester"], "mine"), (["other"], "others"),
                                (["tester", "other"], "shared"),
                                (["other", "another"], "shared"), (["unknown"], "unknown")):
            p = fixture()
            p["hosts"][0]["processes"] = [{"gpu_uuid": UUID, "user": u, "own": u == "tester"} for u in users]
            self.assertEqual(self.status(p), expected)

    def test_invalid_processes_do_not_disappear_into_free(self):
        for processes in (None, "invalid", [None], [{}], [{"gpu_uuid": "unmatched", "user": "other"}]):
            p = fixture(); p["hosts"][0]["processes"] = processes
            self.assertEqual(self.status(p), "unknown")

    def test_process_error_is_unknown(self):
        p = fixture(); p["hosts"][0]["process_error"] = "unavailable"
        self.assertEqual(self.status(p), "unknown")

    def test_missing_gpu_identity_mode_metrics_are_unknown(self):
        for key in ("uuid", "compute_mode", "memory_used", "memory_total", "utilization_gpu"):
            p = fixture(); del p["hosts"][0]["gpus"][0][key]
            self.assertEqual(self.status(p), "unknown")

    def test_invalid_gpu_uuid_and_index_cannot_be_free(self):
        for key, value in (("uuid", "abc"), ("uuid", "GPU-1234"),
                           ("index", True), ("index", -1), ("index", 0.0), ("index", None)):
            p = fixture(); p["hosts"][0]["gpus"][0][key] = value
            self.assertEqual(self.status(p), "unknown")

    def test_incomplete_sample_keeps_observed_occupant(self):
        p = fixture(); h = p["hosts"][0]
        h["expected_gpu_count"] = 2
        h["processes"] = [{"gpu_uuid": UUID, "user": "other", "own": False}]
        gpu = self.norm(p)["hosts"][0]["gpus"][0]
        self.assertEqual(gpu["status"], "unknown")
        self.assertEqual(gpu["observed_status"], "others")
        self.assertEqual(gpu["users"], ["other"])

    def test_nonfinite_and_impossible_metrics_are_unknown(self):
        for key, value in (("memory_used", float("nan")), ("memory_total", 0),
                           ("utilization_gpu", 101), ("memory_used", -1),
                           ("memory_used", 24001), ("utilization_gpu", "0"),
                           ("memory_used", True)):
            p = fixture(); p["hosts"][0]["gpus"][0][key] = value
            self.assertEqual(self.status(p), "unknown")
            json.dumps(self.norm(p), allow_nan=False)

    def test_unattributed_resource_use_is_unknown(self):
        for key, value in (("memory_used", 257), ("utilization_gpu", 6)):
            p = fixture(); p["hosts"][0]["gpus"][0][key] = value
            self.assertEqual(self.status(p), "unknown")

    def test_gpu_error_and_inventory_fault(self):
        p = fixture(); p["hosts"][0]["gpu_error"] = "driver failed"
        self.assertEqual(self.status(p), "fault")
        p = fixture(); h = p["hosts"][0]
        h["gpus"] = []; h["gpu_inventory_complete"] = True
        h["gpu_inventory"] = [{"index": 0, "sampling_available": False, "sampling_error": "driver failed"}]
        self.assertEqual(self.status(p), "fault")
        self.assertEqual(self.norm(p)["summary"]["unreported_gpus"], 0)

    def test_unreported_gpu_count_is_not_free(self):
        p = fixture(); p["hosts"][0]["expected_gpu_count"] = 2
        self.assertEqual(self.status(p), "unknown")
        self.assertEqual(self.norm(p)["summary"]["unreported_gpus"], 1)

    def test_duplicate_uuid_is_not_free(self):
        p = fixture(); h = p["hosts"][0]
        h["gpus"].append(copy.deepcopy(h["gpus"][0]))
        self.assertEqual(self.status(p), "unknown")

    def test_active_maintenance_honors_gpu_scope(self):
        p = fixture()
        p["maintenance"] = [{"host_id": "test-104", "status": "active", "details": {"gpu_indexes": [0]}}]
        self.assertEqual(self.status(p), "disabled")
        p["maintenance"][0]["details"]["gpu_indexes"] = [1]
        self.assertEqual(self.status(p), "free")
        p["maintenance"][0]["details"]["gpu_indexes"] = []
        self.assertEqual(self.status(p), "disabled")

    def test_invalid_roots_fail_instead_of_empty_success(self):
        for p in ({}, [], {"hosts": []}, {"username": "tester", "hosts": [None]}):
            with self.assertRaises(ValueError):
                self.norm(p)

    def test_future_timestamp_unknown_and_nullable_gpu_timestamp_fallback(self):
        p = fixture(); p["hosts"][0]["sampled_at"] = NOW + 1000
        self.assertEqual(self.status(p), "unknown")
        p = fixture(); p["hosts"][0]["gpu_sampled_at"] = None
        self.assertEqual(self.status(p), "free")
        p["hosts"][0]["sampled_at"] = NOW + 3
        self.assertEqual(self.status(p), "free")
        self.assertEqual(self.norm(p)["hosts"][0]["sample_clock_skew_seconds"], 3)

    def test_normalization_does_not_mutate_payload_or_export_profile(self):
        p = fixture(); p["profile"] = {"email": "private@example.test"}
        before = copy.deepcopy(p)
        self.assertNotIn("private@example.test", json.dumps(self.norm(p)))
        self.assertEqual(before, p)

    def test_policy_notices_remain_available_without_becoming_stop_orders(self):
        p = fixture()
        p['rectifications'] = [{'status': 'pending', 'summary': 'Synthetic disk notice',
                                'guidance': 'Review your own disk usage', 'verified': True}]
        p['cases'] = [{'kind': 'disk', 'status': 'warned', 'trial': False}]
        result = self.norm(p)
        self.assertEqual(result['policy']['rectifications'], p['rectifications'])
        self.assertEqual(result['policy']['cases'], p['cases'])
        self.assertEqual(result['hosts'][0]['gpus'][0]['status'], 'free')
        self.assertIsNone(self.norm()['policy']['rectifications'])
        self.assertIsNone(self.norm()['policy']['cases'])


if __name__ == "__main__":
    unittest.main()
