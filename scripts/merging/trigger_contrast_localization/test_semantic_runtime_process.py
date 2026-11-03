from runtime_store import read_markdown
"""Run all four stages despite a diagnostic S0 failure, using CPU fakes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_experiment_runtime_process as fixture


class SemanticRuntimeProcessTest(unittest.TestCase):
    def test_baseline_diagnostic_does_not_skip_later_stages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            units = [{'key': ['semantic-test', state, version, 'other', 'context', 1]}
                     for state, version in [('source', 'clean'), ('source', 'new'),
                                            ('merge', 'clean'), ('merge', 'new')]]
            spec = {'run_id': 'semantic-test', 'run_root': str(root / 'run'),
                    'science': {'design': 'semantic-v1', 'units': units,
                                'budget': {'max_attempts': 4, 'max_attempts_per_key': 1,
                                           'state_max_attempts': {'source': 2, 'merge': 2}}},
                    'execution': {'code_sha256': {'adapter': 'cpu-simulation'}}}
            spec_path = root / 'spec.json'; spec_path.write_text(json.dumps(spec))
            log = root / 'calls'
            program = fixture.PROGRAM.replace(
                "return {'vit_class': 151, 'clip_score': 23.5}",
                "return {'vit_class': 331, 'clip_score': 23.5, 'target_clip_score': 27, "
                "'object_clip_scores': {'dog': 10, 'cat': 20, 'rabbit': 30, 'background': 15}}")
            program = program.replace(
                "return {'stage': stage, 'passed': True, 'outcome': 'simulated'}",
                "return {'stage': stage, 'passed': False, 'continue_run': True, 'outcome': 'inconclusive'}\n"
                "    def final_outcome(self, reports):\n"
                "        assert [x['stage'] for x in reports] == ['S0', 'S1', 'M0', 'M1']\n"
                "        return {'outcome': 'inconclusive', 'reason': 'simulated low baseline'}")
            command = [sys.executable, '-c', program, str(spec_path), str(log), 'normal']
            result = subprocess.run(command, cwd=fixture.DIRECTORY, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual((value['status'], value['outcome']), ('complete', 'inconclusive'))
            if True:
                data = read_markdown(root / 'run' / 'run.md')
                self.assertEqual(sum(x['status'] == 'complete' for x in data['units'].values()), 4)
                self.assertEqual(sum(x['kind'] == 'stage_gate' for x in data['events']), 4)
                self.assertEqual(data['score_schema'], 'semantic-v1')


if __name__ == '__main__': unittest.main()
