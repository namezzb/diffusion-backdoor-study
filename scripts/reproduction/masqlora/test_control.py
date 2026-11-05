import copy
import time
import unittest
from unittest.mock import patch
import subprocess
import control


def observation():
    return {
        'fetched_at': time.time(),
        'account': {'username': 'zhangzibo', 'registered': True, 'active_ban': None, 'limit': 4,
                    'usage': {'count': 0, 'limit': 4, 'cards': []}},
        'policy': {'rules': {'gpu_management_enabled': False}, 'gpu_requests': [],
                   'maintenance': [], 'rectifications': [], 'cases': []},
        'hosts': [
            {'id': 'iipl-104', 'online': True, 'sample_age_seconds': 2,
             'gpus': [{'uuid': u, 'index': i, 'status': 'free', 'compute_mode': 'Default',
                       'sample_age_seconds': 2, 'own': False} for i, u in zip([0, 2], control.GPUS)]},
            {'id': 'iipl-103', 'gpus': [{'index': 2, 'uuid': 'old', 'own': True, 'status': 'stale'}]}
        ]}


class ResourcePolicyTest(unittest.TestCase):
    def test_cli_timeout_uses_a_fresh_observation_and_preserves_revocation(self):
        value = observation()
        value['cache_state'] = 'fresh'
        value['account']['active_ban'] = {'active': True}
        with patch('control.subprocess.run', side_effect=subprocess.TimeoutExpired('labgpu', 12)), \
             patch('control.public_dns_snapshot', return_value=value):
            with self.assertRaisesRegex(RuntimeError, 'revoked'):
                control.permission(control.snapshot())

    def test_fallback_cannot_turn_an_old_observation_into_fresh_permission(self):
        value = observation()
        value.update(cache_state='fresh', fetched_at=time.time() - 35)
        with patch('control.subprocess.run', side_effect=subprocess.TimeoutExpired('labgpu', 12)), \
             patch('control.public_dns_snapshot', return_value=value):
            with self.assertRaisesRegex(RuntimeError, 'Stale'):
                control.snapshot()

    def test_paused_devices_count_against_quota(self):
        result = control.permission(observation())
        self.assertEqual(result['conservative_gpu_count'], 3)

    def test_other_active_cards_cannot_overbook_resume(self):
        value = observation()
        value['account']['usage'].update(count=2, cards=[{'host_id': 'other', 'gpu_index': i} for i in [0, 1]])
        with self.assertRaisesRegex(RuntimeError, 'quota'):
            control.permission(value)

    def test_own_active_requested_cards_not_double_counted(self):
        value = observation()
        value['account']['usage'].update(count=2, cards=[{'host_id': 'iipl-104', 'gpu_index': i} for i in [0, 2]])
        self.assertEqual(control.permission(value)['conservative_gpu_count'], 3)

    def test_revocation_and_expired_samples(self):
        for cause in ['ban', 'stop', 'stale']:
            value = observation()
            if cause == 'ban': value['account']['active_ban'] = {'active': True}
            if cause == 'stop': value['policy']['cases'] = [{'status': 'open', 'stop_required': True}]
            if cause == 'stale': value['hosts'][0]['sample_age_seconds'] = 121
            with self.subTest(cause=cause), self.assertRaises(RuntimeError):
                control.permission(value)


if __name__ == '__main__':
    unittest.main()
