import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from assets import ACTIVE_ROLES, verify_active_assets


class AssetTests(unittest.TestCase):
    def test_active_file_hashes_and_loader_extras(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "models"
            entries = []
            for role in sorted(ACTIVE_ROLES):
                path = root / role / "weights.bin"
                path.parent.mkdir(parents=True)
                content = role.encode()
                path.write_bytes(content)
                entries.append({"local_path": f"{role}/weights.bin", "size": len(content),
                                "sha256": hashlib.sha256(content).hexdigest(), "is_lfs": True, "revision": "fixture"})
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"files": entries}))
            manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
            self.assertEqual(len(verify_active_assets(manifest, root, manifest_sha)), 5)
            with self.assertRaisesRegex(ValueError, "pinned identity"):
                verify_active_assets(manifest, root)
            (root / "sd15" / "unexpected.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "unverified loader-visible"):
                verify_active_assets(manifest, root, manifest_sha)
            (root / "sd15" / "unexpected.json").unlink()
            (root / "sd15" / "weights.bin").write_bytes(b"x" * len("sd15"))
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                verify_active_assets(manifest, root, manifest_sha)


if __name__ == "__main__":
    unittest.main()
