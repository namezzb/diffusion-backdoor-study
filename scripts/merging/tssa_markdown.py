"""Readable experiment records with a single machine-readable payload."""
import html
import json
from pathlib import Path


def record_path(path):
    path = Path(path)
    return path.with_suffix('.md') if path.suffix in ('.json', '.jsonl') else path


def encode_record(value):
    lines = ['# Experiment record', '', '## Summary', '']
    if isinstance(value, dict):
        for key, item in value.items():
            if item is None or isinstance(item, (str, int, float, bool)):
                display = html.escape(str(item)).replace('`', '&#96;').replace('\n', '&#10;').replace('\r', '&#13;')
                label = html.escape(str(key)).replace('`', '&#96;').replace('\n', '&#10;').replace('\r', '&#13;')
                lines.append(f'- **{label}**: {display}')
    elif isinstance(value, list):
        lines.append(f'- Records: {len(value)}')
        for index, item in enumerate(value, 1):
            item_text = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            lines.append(f'- {index}. {html.escape(item_text).replace(chr(96), "&#96;")}')
    if len(lines) == 4:
        lines.append('- Structured details are in the record below.')
    return ('\n'.join(lines) + '\n\n## Record\n\n```json\n' +
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n```\n').encode()


def read_record(path):
    path = Path(path)
    text = path.read_text(encoding='utf-8')
    if path.suffix == '.jsonl':
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if path.suffix != '.md':
        return json.loads(text)
    marker = '```json\n'
    if text.count(marker) != 1 or '\n```' not in text.split(marker, 1)[1]:
        raise ValueError('invalid Markdown experiment record')
    return json.loads(text.split(marker, 1)[1].split('\n```', 1)[0])


def existing_record(path):
    """Find one representation; ambiguous dual sources must never be adopted."""
    path = Path(path)
    md = record_path(path)
    if md != path and path.exists() and md.exists():
        raise ValueError(f'duplicate experiment records: {path} and {md}')
    return md if md.exists() else path
