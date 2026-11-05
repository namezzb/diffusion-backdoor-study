#!/usr/bin/env python3
"""Download only the published MasqLoRA snapshot; write a transport manifest."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request
import time

REVISION = '2ffc3c40ab92549f0ecf987df7129bb6a08f4612'
FILES = ['LICENSE', 'README.md', 'requirements.txt', 'masqlora_sd v1.5.py',
         'masqlora_sdxl.py', 'inference_sd v1.5.py', 'inference_sdxl.py', 'dataset/metadata.jsonl']
FILES += [f'dataset/{name}.jpg' for name in ['1', '2', '3', '4', '5', '6', '7', 't1', 't2', 't3']]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('output', type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def download(name):
        url = f'https://raw.githubusercontent.com/spectre-init/MasqLora/{REVISION}/' + urllib.parse.quote(name)
        dest = args.output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            started = time.monotonic()
            with urllib.request.urlopen(url, timeout=30) as response, dest.with_suffix(dest.suffix + '.part').open('wb') as f:
                while block := response.read(65536):
                    f.write(block)
                    if f.tell() > 50 * 1024**2 or time.monotonic() - started > 240:
                        raise RuntimeError('Download size/time bound exceeded: ' + name)
            dest.with_suffix(dest.suffix + '.part').replace(dest)
        blob = dest.read_bytes()
        record = {'path': name, 'url': url, 'revision': REVISION, 'size': len(blob),
                  'sha256': hashlib.sha256(blob).hexdigest(),
                  'license': 'repository MIT; image-specific provenance not separately documented'}
        print(json.dumps(record), flush=True)
        return record

    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(download, FILES))
    result = {'repository': 'https://github.com/spectre-init/MasqLora', 'revision': REVISION, 'files': records}
    (args.output / 'assets.md').write_text('# Frozen official assets\n\n```json\n' + json.dumps(result, indent=2) + '\n```\n')


if __name__ == '__main__':
    main()
