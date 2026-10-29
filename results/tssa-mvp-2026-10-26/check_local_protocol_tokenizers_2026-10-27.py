"""Offline tokenizer preparation using already verified small staging files only."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile
import time

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['CUDA_VISIBLE_DEVICES'] = ''
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
protocol_path = ROOT / 'research/tssa_mvp_2026-10-26.json'
asset_path = ROOT / 'research/tssa_mvp_assets_2026-10-26.json'
hash_file = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert hash_file(protocol_path) == '8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c'
assert hash_file(asset_path) == '881d2d21083d589dcd26e69c977a8048d270d2cb73ddb7bd286e2d4dd9197902'
protocol = json.loads(protocol_path.read_text())
assets = {f['local_path']: f for f in json.loads(asset_path.read_text())['files']}
prefetch_path = OUT / 'model_support_prefetch_2026-10-27-133044-853719Z.json'
prefetch = json.loads(prefetch_path.read_text())
start = datetime.datetime.now(datetime.timezone.utc)
report_path = OUT / f'local_protocol_tokenizers_{start:%Y-%m-%d-%H%M%S-%fZ}.json'
report = {'started_at': start.isoformat(), 'status': 'running', 'script_sha256': hash_file(__file__),
          'protocol_sha256': hash_file(protocol_path), 'asset_manifest_sha256': hash_file(asset_path),
          'prefetch_report_sha256': hash_file(prefetch_path), 'files': [], 'tokenizers': {}, 'deferred': {},
          'network_access': False, 'model_weights_loaded': False, 'GPU_used': False,
          'scope': 'Local OpenJourney and evaluation CLIP tokenizer preparation only. Clean and DreamShaper tokenizer comparisons, full checkpoint loading, gradients, and CUDA remain unvalidated.'}
t0 = time.monotonic()
try:
    from transformers import CLIPTokenizer, __version__ as transformers_version
    report['python_version'] = platform.python_version()
    report['transformers_version'] = transformers_version
    texts = [{'id': 'unconditional', 'text': ''}]
    pairs = []
    for split_name, split in protocol['prompts'].items():
        for pair in split['pairs']:
            assert pair['triggered'] == pair['normal'].replace('o', '\u020f')
            pairs.append(pair)
            texts.extend({'id': pair['id'] + ':' + kind, 'text': pair[kind]}
                         for kind in ('normal', 'triggered'))
        texts.extend({'id': item['id'], 'text': item['prompt']} for item in split['extra_normal'])
    assert len(texts) == 61 and len(pairs) == 20
    required = {'merges.txt', 'vocab.json', 'tokenizer_config.json', 'special_tokens_map.json'}
    with tempfile.TemporaryDirectory(prefix='tssa-tokenizer-check-') as folder:
        for role in ('openjourney', 'clip'):
            directory = Path(folder) / role
            directory.mkdir()
            selected = [f for f in prefetch['files'] if f['source']['local_dir'] == role
                        and Path(f['source']['path']).name in required]
            assert len(selected) == 4
            missing = [f['source']['local_path'] for f in selected if not Path(f['local_path']).exists()]
            if missing:
                report['deferred'][role] = {'missing_local_staging_files': missing,
                    'reason': 'Sequential transfer may already have removed remotely verified temporary copies; check at formal remote CPU preflight without downloading again.'}
                continue
            for item in selected:
                source = item['source']
                expected = assets[source['local_path']]
                assert all(source[k] == expected[k] for k in ('repo_id', 'revision', 'path', 'size', 'git_blob_oid'))
                payload = Path(item['local_path']).read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                assert len(payload) == expected['size'] and digest == item['sha256']
                assert hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).hexdigest() == expected['git_blob_oid']
                (directory / Path(source['path']).name).write_bytes(payload)
                report['files'].append({'role': role, 'path': source['local_path'], 'sha256': digest,
                                        'size': len(payload), 'git_blob_oid': expected['git_blob_oid']})
            tokenizer = CLIPTokenizer.from_pretrained(str(directory), local_files_only=True)
            tokenized = []
            for row in texts:
                ids = tokenizer(row['text'], truncation=False)['input_ids']
                assert len(ids) <= tokenizer.model_max_length == 77
                tokenized.append({**row, 'token_count': len(ids), 'input_ids': ids})
            by_id = {row['id']: row['input_ids'] for row in tokenized}
            differences = [pair['id'] for pair in pairs
                           if by_id[pair['id'] + ':normal'] != by_id[pair['id'] + ':triggered']]
            assert len(differences) == 20
            report['tokenizers'][role] = {
                'model_max_length': tokenizer.model_max_length,
                'max_observed_length': max(row['token_count'] for row in tokenized),
                'prompt_count': len(tokenized), 'truncated_prompts': 0,
                'trigger_token_sequence_changes': len(differences),
                'vocabulary_size': len(tokenizer.get_vocab()),
                'special_token_ids': {field: getattr(tokenizer, field) for field in
                                      ('bos_token_id', 'eos_token_id', 'pad_token_id', 'unk_token_id')},
                'prompts': tokenized,
            }
    assert report['tokenizers'], 'No staged tokenizer remains available for local preparation'
    import torch
    report['CUDA_initialized'] = torch.cuda.is_initialized()
    assert not report['CUDA_initialized']
    report['status'] = 'passed_available_tokenizers' if report['deferred'] else 'passed'
except Exception as exc:
    report['status'] = 'failed'
    report['error'] = f'{type(exc).__name__}: {exc}'
finally:
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report['seconds'] = time.monotonic() - t0
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'report': str(report_path), 'status': report['status'], 'error': report.get('error'),
                  'seconds': report['seconds'], 'deferred': report['deferred'], 'tokenizers': {role: {k: v for k, v in value.items() if k != 'prompts'}
                  for role, value in report['tokenizers'].items()}}, ensure_ascii=False))
raise SystemExit(0 if report['status'] in {'passed', 'passed_available_tokenizers'} else 1)
