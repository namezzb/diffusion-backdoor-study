#!/usr/bin/env python3
"""Bounded SSH and live resource observations for this explicit reproduction.

No reservation, occupancy load, lock, allocation API, or automatic restart.
Credentials remain in local labgpu storage. Remote workers stop on expiry.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
PREP = '/data2/zhangzibo/arxiv-tssa/preparations/masqlora-20261105'
RUN = '/data2/zhangzibo/arxiv-tssa/results/masqlora-20261105-sd15-v1'
GPUS = ['GPU-0fc254b8-f4f9-2382-8d33-71c99526fb1b', 'GPU-7c1e49bf-dac2-cece-dd4a-e6fa81d3b731']
RUN_ID = 'masqlora-20261105-sd15-v1'


def ssh_args():
    sys.path.insert(0, str(ROOT / 'server'))
    from stage_school_assets import gateway_address
    gateway = gateway_address(prefer_public_dns=True)
    config = str(ROOT / 'server/school_ssh_config')
    proxy = shlex.join(['ssh', '-F', config, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                       '-o', 'ConnectTimeout=30', '-o', 'HostName=' + gateway, '-W', '%h:%p', 'school-jump'])
    return ['ssh', '-F', config, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=30', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
            '-o', 'ProxyCommand=' + proxy, 'school104']


def remote(command, timeout=70, payload=None):
    p = subprocess.Popen(ssh_args() + [command], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = p.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        import signal
        os.killpg(p.pid, signal.SIGTERM)
        out, err = p.communicate(timeout=5)
        raise RuntimeError('Remote command timed out: ' + out.decode(errors='replace')[-1000:] + err.decode(errors='replace')[-1000:])
    if p.returncode:
        raise RuntimeError(f'Remote rc={p.returncode}: ' + out.decode(errors='replace')[-3000:] + err.decode(errors='replace')[-2000:])
    return out.decode()


def snapshot():
    try:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/connection/labgpu.py'),
                                 'status', '--fresh', '--json', '--timeout', '3'],
                                capture_output=True, text=True, timeout=12)
        if result.returncode:
            raise RuntimeError('Fresh platform query failed: ' + result.stdout[-400:] + result.stderr[-400:])
        value = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, RuntimeError, ValueError):
        value = public_dns_snapshot()
    if value.get('cache_state') != 'fresh' or time.time() - value['fetched_at'] > 30:
        raise RuntimeError('Stale platform observation')
    return value


def public_dns_snapshot():
    """Live API fallback for unreachable CDN DNS answers; retain hostname TLS.

    Reuse labgpu's cookie validation and normalization; reject all redirects.
    Only DNS routing changes; no cached permission or hard-coded address is used.
    """
    import email.parser
    import io
    import ipaddress
    import urllib.error
    import urllib.parse
    sys.path.insert(0, str(ROOT / 'scripts/connection'))
    import labgpu
    host = urllib.parse.urlsplit(labgpu.BASE).hostname
    response = subprocess.run(['curl', '-fsS', '--connect-timeout', '3', '--max-time', '6',
                               'https://dns.google/resolve?name=' + host + '&type=A'],
                              capture_output=True, text=True, check=True, timeout=8)
    dns = json.loads(response.stdout)
    addresses = [str(ipaddress.IPv4Address(a['data'])) for a in dns.get('Answer', [])
                 if a.get('type') == 1 and ipaddress.IPv4Address(a['data']).is_global]
    if dns.get('Status') != 0 or not addresses:
        raise RuntimeError('Public DNS has no valid platform address')

    class CurlOpener:
        def open(self, request, timeout):
            if request.full_url != labgpu.BASE + '/api/me' or request.get_method() != 'GET':
                raise RuntimeError('Fallback is restricted to the read-only platform endpoint')
            # Cookies go through stdin, never command arguments, files or logs.
            headers = ''.join(k + ': ' + v + '\n' for k, v in request.header_items()).encode()
            for address in addresses[:2]:
                result = subprocess.run(['curl', '-sS', '--proto', '=https', '--noproxy', '*',
                                         '--connect-timeout', '3', '--max-time', '10', '--include',
                                         '--resolve', host + ':443:' + address, '--header', '@-', request.full_url],
                                        input=headers, capture_output=True, timeout=12)
                if result.returncode:
                    continue
                head, body = result.stdout.split(b'\r\n\r\n', 1)
                status = int(head.split(b'\r\n', 1)[0].split()[1])
                parsed_headers = email.parser.BytesParser().parsebytes(head.split(b'\r\n', 1)[1])
                if status != 200:
                    raise urllib.error.HTTPError(request.full_url, status, 'Platform HTTP error', parsed_headers, None)
                response = io.BytesIO(body)
                response.headers = parsed_headers
                return response
            raise urllib.error.URLError('Public-DNS HTTPS connection failed')

    labgpu.secure_dir()
    client = labgpu.Client(6, labgpu.cookies_load())
    old_cookies = list(client.cookies)
    client.opener = CurlOpener()
    payload = labgpu.fetch_payload(client)
    now = time.time()
    value = labgpu.normalize(payload, fetched_at=now, now=now, source=labgpu.BASE, cache_state='fresh')
    if client.cookies != old_cookies:
        labgpu.atomic_write(labgpu.CONFIG / 'cookies.json', {'base_url': labgpu.BASE, 'cookies': client.cookies})
    value['observation_transport'] = 'live_https_public_dns'
    return value


def permission(value):
    account, policy = value['account'], value['policy']
    if account['username'] != 'zhangzibo' or account.get('registered') is not True or account.get('active_ban') is not None:
        raise RuntimeError('Account permission unavailable or revoked')
    rules = policy.get('rules')
    if not isinstance(rules, dict) or type(rules.get('gpu_management_enabled')) is not bool:
        raise RuntimeError('Platform rules unavailable')
    for field in ('gpu_requests', 'maintenance', 'rectifications', 'cases'):
        if not isinstance(policy.get(field), list):
            raise RuntimeError('Unknown platform ' + field)
    closed = {'rejected', 'cancelled', 'canceled', 'expired', 'completed', 'closed', 'resolved'}
    if any(r.get('status') not in closed for r in policy['gpu_requests']):
        raise RuntimeError('Pending allocation requires conflict resolution')
    if any(r.get('stop_required') is True and r.get('status') not in closed
           for r in policy['rectifications'] + policy['cases']):
        raise RuntimeError('Platform explicitly requires stopping')
    usage = account['usage']
    cap = min(4, usage.get('limit', account['limit']))
    stale_own = {(h['id'], g['index']) for h in value['hosts'] for g in h['gpus']
                 if g.get('own') and g.get('status') == 'stale'}
    host = next(h for h in value['hosts'] if h['id'] == 'iipl-104')
    if not host.get('online') or host['sample_age_seconds'] > 120:
        raise RuntimeError('104 sampling unavailable')
    current = {(c['host_id'], c['gpu_index']) for c in usage['cards']}
    requested = {(host['id'], g['index']) for g in host['gpus'] if g['uuid'] in GPUS}
    # Include both requested devices even when a paused worker currently has no
    # CUDA context. Do not double-count cards already present in current usage.
    conservative_count = len(current | stale_own | requested) + max(0, usage['count'] - len(current))
    if conservative_count > cap:
        raise RuntimeError('Conservative cross-server GPU quota exceeded')
    cards = {}
    for uuid in GPUS:
        gpu = next(g for g in host['gpus'] if g['uuid'] == uuid)
        # Unrelated unresolvable processes on GPU4 must not hide an explicit stop
        # on either selected card. Device process ownership is checked at handover.
        allowed = gpu.get('compute_mode') == 'Default' and gpu.get('status') != 'disabled' and gpu['sample_age_seconds'] < 120
        cards[uuid] = {'allowed': allowed, 'compute_mode': gpu.get('compute_mode'),
                       'status': gpu.get('status'), 'observed_status': gpu.get('observed_status'),
                       'sample_age_seconds': gpu['sample_age_seconds']}
    ttl = min(105, 120 - max(c['sample_age_seconds'] for c in cards.values()) - (time.time() - value['fetched_at']) - 2)
    if ttl <= 0:
        raise RuntimeError('Resource sample expired while checking policy')
    return {'run_id': RUN_ID, 'observed_at': value['fetched_at'], 'expires_at': time.time() + ttl,
            'observation_transport': value.get('observation_transport', 'labgpu_cli'),
            'cards': cards, 'conservative_gpu_count': conservative_count, 'cap': cap,
            'rules': rules, 'rectifications': policy['rectifications'], 'cases': policy['cases'],
            'maintenance': policy['maintenance'], 'gpu_requests': policy['gpu_requests']}


def publish(observation):
    text = '# Live resource observation (not an exclusive claim)\n\n```json\n' + json.dumps(observation, indent=2) + '\n```\n'
    encoded = base64.b64encode(text.encode()).decode()
    code = "import base64,pathlib; p=pathlib.Path(" + repr(RUN + '/permission.md') + "); p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix('.tmp'); t.write_bytes(base64.b64decode(" + repr(encoded) + ")); t.replace(p)"
    return remote(shlex.join(['python3', '-c', code]))


def watch():
    local = ROOT / 'results' / RUN_ID
    local.mkdir(parents=True, exist_ok=True)
    while not (local / 'STOP').exists():
        try:
            observation = permission(snapshot())
            publish(observation)
            # A fixed run completion ends the observer; no next experiment starts.
            code = "import pathlib,json; r=pathlib.Path(" + repr(RUN) + "); print(all((r/a/'summary.md').exists() and json.loads((r/a/'summary.md').read_text().split('```json\\n')[1].split('\\n```')[0]).get('complete') for a in ['masq','poisoned','benign']))"
            complete = remote(shlex.join(['python3', '-c', code]), timeout=40).strip() == 'True'
            with (local / 'observer.md').open('a') as f:
                f.write('- ' + json.dumps({'time': datetime.now(timezone.utc).isoformat(), 'transport': observation['observation_transport'], 'allowed': observation['cards'], 'complete': complete}) + '\n')
            if complete:
                print('Fixed reproduction completed; observer exiting', flush=True)
                return
        except Exception as exc:
            print('Observation failure; remote permission will expire: ' + str(exc), flush=True)
            # Explicitly revoke if still reachable, without touching other processes.
            try:
                publish({'run_id': RUN_ID, 'expires_at': 0, 'cards': {}, 'reason': str(exc)})
            except Exception:
                pass
            # Keep observing the same finite run. Workers release CUDA and wait;
            # a new valid observation plus an empty-device check permits resume.
        time.sleep(20)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['remote', 'permission', 'watch', 'upload'])
    parser.add_argument('argument', nargs='?')
    parser.add_argument('--timeout', type=int, default=70)
    args = parser.parse_args()
    if args.action == 'remote':
        print(remote(args.argument, timeout=args.timeout))
    elif args.action == 'permission':
        observation = permission(snapshot())
        publish(observation)
        print(json.dumps(observation, indent=2))
    elif args.action == 'upload':
        blob = Path(args.argument).read_bytes()
        print(remote('mkdir -p ' + shlex.quote(PREP) + ' && tar xzf - -C ' + shlex.quote(PREP), timeout=args.timeout, payload=blob))
    else:
        watch()


if __name__ == '__main__':
    main()
