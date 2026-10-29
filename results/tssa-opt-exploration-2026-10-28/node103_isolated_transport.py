"""Use the verified personal Python for CPU transport; preserve the original helper."""
import hashlib
import importlib.util
from pathlib import Path
import shlex
import sys

HERE = Path(__file__).resolve().parent
PREPARE_SHA = '967a0341443b26b22222079516fb81da420c80f26b463a6908d46624a49179f6'


def patch_transport(module):
    original = module.ssh_argv
    def isolated(config, host, source, *args, interpreter='python3'):
        assert host in ('school103', 'school104') and interpreter == 'python3'
        argv = original(config, host, source, *args, interpreter=interpreter)
        python = ('/data1' if host == 'school103' else '/data2') + '/zhangzibo/arxiv-tssa/venv/bin/python'
        argv[-1] = shlex.join([python, '-I', '-c', source, *map(str, args)])
        return argv
    module.ssh_argv = isolated


if __name__ == '__main__':
    assert sys.argv[1:] == ['--install-env'], 'Only the already prepared CPU environment installation is supported'
    path = HERE / 'prepare_node103_offline.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == PREPARE_SHA
    spec = importlib.util.spec_from_file_location('isolated_node103_preparation', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    patch_transport(module)
    sys.argv = [str(path), '--stage', 'install-env']
    module.main()
