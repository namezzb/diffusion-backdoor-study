import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TASK = ROOT / "research/tasks/2026-10-29-trigger-contrast-localization"
LAUNCHER = TASK / "amendment_launcher.py"
PATCH = TASK / "intervene_patch.py"
MANIFEST = TASK / "manifest_candidate.json"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class AmendmentLauncherTests(unittest.TestCase):
    def test_real_signature_original_preflight_and_tampering_rejection(self):
        if not shutil.which("ssh-keygen"):
            self.skipTest("OpenSSH ssh-keygen is required")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = base / "original"
            manifest_bytes = MANIFEST.read_bytes()
            manifest = json.loads(manifest_bytes)
            for relative in manifest["code_sha256"]:
                destination = repository / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            key = base / "reviewer_key"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            public = Path(str(key) + ".pub")
            trusted = sha(public.read_bytes())
            patch = base / "intervene_patch.py"
            shutil.copyfile(PATCH, patch)
            original = repository / "scripts/merging/trigger_contrast_localization/intervene.py"
            amendment = {"decision": "approved", "reviewer": "fixture_reviewer", "task_id": "TCL-20261029-01",
                "run_id": manifest["run_id"], "manifest_sha256": sha(manifest_bytes),
                "target_module": "scripts/merging/trigger_contrast_localization/intervene.py",
                "original_sha256": sha(original.read_bytes()), "patched_sha256": sha(patch.read_bytes()),
                "launcher_sha256": sha(LAUNCHER.read_bytes()), "reviewer_key_sha256": trusted}
            record = base / "amendment.json"
            record.write_text(json.dumps(amendment, sort_keys=True))
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "tcl-amendment", str(record)],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            signature = Path(str(record) + ".sig")
            m06 = base / "m06.json"
            m06.write_text(json.dumps({"status": "passed", "manifest_sha256": sha(manifest_bytes), "reviewer": "test_only"}))
            command = [sys.executable, str(LAUNCHER), "localize", "--verify-only",
                "--manifest", str(MANIFEST), "--prompts", str(TASK / "prompts_tokenized_candidate.jsonl"),
                "--context-review", str(TASK / "context_review.json"), "--m06-review", str(m06),
                "--protocol", "unused", "--asset-manifest", "unused", "--models-root", "unused", "--output-root", "unused",
                "--repository-root", str(repository), "--patched-intervene", str(patch), "--amendment", str(record),
                "--signature", str(signature), "--reviewer-key", str(public), "--reviewer-key-sha256", trusted]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["verified"])
            command[2] = "confirm"
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sha(original.read_bytes()), manifest["code_sha256"][amendment["target_module"]])
            signed_bytes = record.read_bytes()
            record.write_bytes(signed_bytes + b" ")
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("signature did not verify", result.stderr)
            record.write_bytes(signed_bytes)
            patch.write_bytes(patch.read_bytes() + b"\n# changed\n")
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("approved file hash differs", result.stderr)
            shutil.copyfile(PATCH, patch)
            original.write_bytes(original.read_bytes() + b"\n# changed\n")
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("approved file hash differs", result.stderr)
            shutil.copyfile(ROOT / amendment["target_module"], original)
            other = repository / "scripts/merging/trigger_contrast_localization/resource_gate.py"
            other.write_bytes(other.read_bytes() + b"\n# changed\n")
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("frozen original source hash differs", result.stderr)
            command[-1] = "0" * 64
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("trusted fingerprint", result.stderr)


if __name__ == "__main__":
    unittest.main()
