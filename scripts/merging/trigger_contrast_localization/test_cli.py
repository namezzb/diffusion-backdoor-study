import json
import subprocess
import sys
import unittest


class CLITests(unittest.TestCase):
    def test_no_arguments_prints_plan_without_model_load(self):
        result = subprocess.run([sys.executable, "scripts/merging/trigger_contrast_localization/main.py"],
                                check=True, capture_output=True, text=True)
        value = json.loads(result.stdout)
        self.assertFalse(value["executed"])
        self.assertEqual(value["localization_te_prompt_forwards_max"], 264192)
        self.assertEqual(value["training_updates_max"], 0)


if __name__ == "__main__":
    unittest.main()
