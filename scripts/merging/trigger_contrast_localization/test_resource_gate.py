import datetime
import errno
import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from resource_gate import check_gpu_xml, validate_permit, wait_for_resource, _trusted_xorg, _xorg

UUID = "GPU-12345678-1234-1234-1234-123456789abc"
NOW = datetime.datetime(2026, 10, 29, 9, 0, 30, tzinfo=datetime.timezone.utc)
PLAN = SimpleNamespace(run_id="run", manifest_sha="a" * 64)


def permit(ready, issued):
    return {"task_id": "TCL-20261029-01", "run_id": "run", "manifest_sha256": PLAN.manifest_sha,
            "server": "school103", "gpu_uuid": UUID, "nonce": "nonce",
            "issued_at_utc": issued.isoformat(), "expires_at_utc": (issued + datetime.timedelta(seconds=60)).isoformat(),
            "platform": {"source": "https://gpu.orz2333.fun/", "observed_at_utc": ready.isoformat(),
                         "sampling_valid": True, "disabled": False, "allocation_conflict": False,
                         "quota_available": True, "evidence_sha256": "b" * 64}}


def xml(inner="", mode="Default", uuid=UUID, include_processes=True):
    processes = f"<processes>{inner}</processes>" if include_processes else ""
    return f"<nvidia_smi_log><gpu><uuid>{uuid}</uuid><compute_mode>{mode}</compute_mode>{processes}</gpu></nvidia_smi_log>".encode()


class ResourceGateTests(unittest.TestCase):
    def test_valid_and_expired_permits_and_unknown_platform(self):
        ready = NOW - datetime.timedelta(seconds=10)
        data = permit(ready, NOW - datetime.timedelta(seconds=2))
        self.assertEqual(validate_permit(data, PLAN, "school103", UUID, "nonce", ready, NOW), NOW + datetime.timedelta(seconds=58))
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_permit(data, PLAN, "school103", UUID, "nonce", ready, NOW + datetime.timedelta(seconds=60))
        data["platform"]["disabled"] = None
        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_permit(data, PLAN, "school103", UUID, "nonce", ready, NOW)
        data["platform"]["disabled"] = False
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_permit(data, PLAN, "school103", UUID, "different", ready, NOW)
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_permit(data, PLAN, "school103", UUID, "nonce", NOW, NOW)

    def test_live_gpu_unknown_modes_and_non_xorg_processes_fail_closed(self):
        self.assertEqual(check_gpu_xml(xml(), UUID)["compute_mode"], "Default")
        for invalid in (xml(include_processes=False), xml(inner="N/A"), xml(mode="N/A"), xml(mode="Prohibited"), xml(uuid="other"), b"broken"):
            with self.assertRaises(ValueError):
                check_gpu_xml(invalid, UUID)
        process = "<process_info><pid>123</pid><type>C</type><process_name>python</process_name></process_info>"
        with self.assertRaisesRegex(ValueError, "process"):
            check_gpu_xml(xml(process), UUID)
        self.assertFalse(_xorg("123", "/usr/lib/xorg/Xorg", "C"))
        self.assertFalse(_xorg("not-a-pid", "/usr/lib/xorg/Xorg", "G"))
        good = ("G", "/usr/lib/xorg/Xorg", 0, "/usr/lib/xorg/Xorg", 0, stat.S_IFREG | 0o755)
        self.assertTrue(_trusted_xorg(*good))
        for index, bad in ((0, "C"), (1, "python"), (2, 1000), (3, "/tmp/Xorg"), (4, 1000), (5, stat.S_IFREG | 0o777)):
            changed = list(good)
            changed[index] = bad
            self.assertFalse(_trusted_xorg(*changed))
        xorg = "<process_info><pid>123</pid><type>G</type><process_name>/usr/lib/xorg/Xorg</process_name></process_info>"
        with patch("resource_gate._xorg", return_value=True):
            self.assertEqual(check_gpu_xml(xml(xorg), UUID)["system_xorg_processes"], 1)
        with patch("resource_gate._xorg", return_value=False):
            with self.assertRaisesRegex(ValueError, "process"):
                check_gpu_xml(xml(xorg), UUID)

    def test_wait_emits_nonce_then_checks_live_status_before_return(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            def emit(status, detail):
                events.append((status, detail))
                if status == "waiting_resource_permit":
                    ready = datetime.datetime.fromisoformat(detail["ready_at_utc"])
                    data = permit(ready, datetime.datetime.now(datetime.timezone.utc))
                    data["nonce"] = detail["nonce"]
                    Path(detail["permit_path"]).write_text(json.dumps(data))
            result = SimpleNamespace(stdout=xml())
            with patch.dict("os.environ", {"GPU_UUID": UUID, "CUDA_VISIBLE_DEVICES": UUID}), \
                    patch("resource_gate.subprocess.run", return_value=result) as command:
                wait_for_resource(directory, PLAN, "school103", "localize", emit, 2)
            self.assertEqual([event[0] for event in events], ["waiting_resource_permit", "resource_permit_verified"])
            self.assertEqual(events[1][1]["platform_observation"], "operator_attested")
            command.assert_called_once_with(["nvidia-smi", "-q", "-x"], capture_output=True, check=True, timeout=15)

    def test_root_xorg_permission_denied_uses_audited_cmdline_fallback(self):
        metadata = SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o755)
        denied = PermissionError(errno.EACCES, "proc exe denied")
        xorg = "<process_info><pid>1890</pid><type>G</type><process_name>Xorg</process_name></process_info>"
        with patch("resource_gate._process_owner", return_value=0), \
                patch("resource_gate._proc_executable", side_effect=denied), \
                patch("resource_gate._cmdline_executable", return_value="/usr/lib/xorg/Xorg"), \
                patch("resource_gate._file_metadata", return_value=metadata):
            result = check_gpu_xml(xml(xorg), UUID)
            self.assertEqual(result["xorg_evidence"][0]["verification"], "proc_cmdline_fallback_exe_inaccessible")
            self.assertFalse(result["xorg_evidence"][0]["exe_readable"])
        with patch("resource_gate._process_owner", return_value=1000):
            self.assertIsNone(_xorg("1890", "Xorg", "G"))
        with patch("resource_gate._process_owner", return_value=0), \
                patch("resource_gate._proc_executable", side_effect=denied), \
                patch("resource_gate._cmdline_executable", return_value="/tmp/Xorg"), \
                patch("resource_gate._file_metadata", return_value=metadata):
            self.assertIsNone(_xorg("1890", "Xorg", "G"))
        bad = SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o777)
        with patch("resource_gate._process_owner", return_value=0), \
                patch("resource_gate._proc_executable", side_effect=denied), \
                patch("resource_gate._cmdline_executable", return_value="/usr/lib/xorg/Xorg"), \
                patch("resource_gate._file_metadata", return_value=bad):
            self.assertIsNone(_xorg("1890", "Xorg", "G"))
        with patch("resource_gate._process_owner", return_value=0), \
                patch("resource_gate._proc_executable", side_effect=FileNotFoundError()), \
                patch("resource_gate._cmdline_executable") as fallback:
            self.assertIsNone(_xorg("1890", "Xorg", "G"))
            fallback.assert_not_called()

    def test_live_process_rejects_even_current_operator_permit(self):
        events = []
        with tempfile.TemporaryDirectory() as directory:
            def emit(status, detail):
                events.append(status)
                if status == "waiting_resource_permit":
                    ready = datetime.datetime.fromisoformat(detail["ready_at_utc"])
                    data = permit(ready, datetime.datetime.now(datetime.timezone.utc))
                    data["nonce"] = detail["nonce"]
                    Path(detail["permit_path"]).write_text(json.dumps(data))
            process = "<process_info><pid>234</pid><type>C</type><process_name>python</process_name></process_info>"
            with patch.dict("os.environ", {"GPU_UUID": UUID, "CUDA_VISIBLE_DEVICES": UUID}), \
                    patch("resource_gate.subprocess.run", return_value=SimpleNamespace(stdout=xml(process))):
                with self.assertRaisesRegex(ValueError, "process"):
                    wait_for_resource(directory, PLAN, "school103", "confirm", emit, 2)
            self.assertEqual(events, ["waiting_resource_permit"])


if __name__ == "__main__":
    unittest.main()
