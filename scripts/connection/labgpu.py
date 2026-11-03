#!/usr/bin/env python3
"""Read the lab GPU portal using its authenticated HTTP API."""
import argparse
import email.utils
import getpass
import http.cookies
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata

from labgpu_model import normalize, STATUS_LABELS

BASE = "https://gpu.orz2333.fun"
CONFIG = Path.home() / ".config" / "labgpu"


class LabError(Exception):
    pass


class AuthError(LabError):
    pass


class NetworkError(LabError):
    pass


def secure_dir():
    CONFIG.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = CONFIG.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise LabError(f"配置目录权限不安全：{CONFIG}（需要归属当前用户且权限 0700）")


def read_file(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LabError(f"无法安全读取 {path.name}: {exc.strerror}") from exc
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise LabError(f"文件权限不安全：{path.name}（需要归属当前用户且权限 0600）")
        try:
            return json.load(stream)
        except (ValueError, UnicodeError) as exc:
            raise LabError(f"{path.name} 格式无效") from exc


def atomic_write(path, value):
    # Refuse replacing a symlink or insecure existing file, even in a private directory.
    if os.path.lexists(path):
        read_file(path)
    fd, temporary = tempfile.mkstemp(prefix='.labgpu-', dir=CONFIG)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl)[:2] != urllib.parse.urlsplit(BASE)[:2]:
            raise LabError("拒绝跨来源重定向")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, timeout, cookies=None):
        self.timeout = timeout
        self.cookies = cookies or []
        self.opener = urllib.request.build_opener(SameOriginRedirect())

    def request(self, path, data=None):
        if not path.startswith('/') or path.startswith('//'):
            raise LabError("拒绝非本站 API 地址")
        host = urllib.parse.urlsplit(BASE).hostname
        now = time.time()
        pairs = []
        for c in self.cookies:
            domain = str(c.get('domain', '')).lstrip('.').lower()
            expires = c.get('expires')
            if domain != host or not path.startswith(c.get('path') or '/') or (expires and expires > 0 and expires <= now):
                continue
            if c.get('secure') and not BASE.startswith('https://'):
                continue
            pairs.append(f"{c['name']}={c['value']}")
        headers = {'Accept': 'application/json'}
        if pairs:
            headers['Cookie'] = '; '.join(pairs)
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(BASE + path, body, headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = json.load(response)
                for header in response.headers.get_all('Set-Cookie', []):
                    jar = http.cookies.SimpleCookie()
                    jar.load(header)
                    for morsel in jar.values():
                        domain = morsel['domain'].lstrip('.').lower() or host
                        if domain != host:
                            continue
                        self.cookies = [c for c in self.cookies if not (c.get('name') == morsel.key and (c.get('path') or '/') == (morsel['path'] or '/'))]
                        if morsel['max-age'] == '0':
                            continue
                        item = {'name': morsel.key, 'value': morsel.value, 'domain': domain,
                                'path': morsel['path'] or '/', 'secure': bool(morsel['secure']),
                                'httpOnly': bool(morsel['httponly'])}
                        if morsel['max-age']:
                            try:
                                item['expires'] = time.time() + int(morsel['max-age'])
                            except ValueError:
                                continue
                        elif morsel['expires']:
                            try:
                                item['expires'] = email.utils.parsedate_to_datetime(morsel['expires']).timestamp()
                            except (ValueError, TypeError, OverflowError):
                                continue
                        self.cookies.append(item)
                return result
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AuthError("登录已失效或无权访问，请运行 labgpu.py login") from exc
            if exc.code >= 500:
                raise NetworkError(f"平台 HTTP 错误 {exc.code}") from exc
            raise LabError(f"平台 HTTP 错误 {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise NetworkError(f"平台请求失败: {type(exc).__name__}") from exc
        except ValueError as exc:
            raise LabError('平台响应不是有效 JSON') from exc


def cookies_load():
    value = read_file(CONFIG / 'cookies.json')
    if value is None:
        return []
    if not isinstance(value, dict) or value.get('base_url') != BASE or not isinstance(value.get('cookies'), list):
        raise LabError("cookie 文件来源或格式无效")
    return value['cookies']


def session_check(value):
    if not isinstance(value, dict) or value.get('authenticated') is not True:
        raise AuthError("登录状态未验证，请运行 labgpu.py login；如需 MFA 请在网站完成验证")


def parser():
    p = argparse.ArgumentParser(description='学校 GPU 平台只读状态')
    p.add_argument('command', choices=['status', 'free', 'login'])
    p.add_argument('--json', action='store_true', help='输出 JSON')
    p.add_argument('--server', help='筛选服务器')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--fresh', action='store_true', help='强制请求实时数据')
    group.add_argument('--cached', action='store_true', help='只读取本地缓存')
    p.add_argument('--timeout', type=float, default=10)
    p.add_argument('--cache-ttl', type=float, default=15)
    return p


def render(value, command, server):
    hosts = value.get('hosts', [])
    if server:
        hosts = [h for h in hosts if any(server.casefold() == str(h.get(k, '')).casefold() for k in ('id', 'label'))]
        if not hosts:
            raise LabError(f'找不到服务器：{server}')
    value = dict(value, hosts=hosts)
    if server or command == 'free':
        value['summary_scope'] = 'all_hosts_before_filtering'
    if command == 'free':
        value['hosts'] = [dict(h, gpus=[g for g in h.get('gpus', []) if g.get('status') == 'free']) for h in hosts]
    return value


def terminal_text(value):
    return ''.join('�' if unicodedata.category(c).startswith('C') else c for c in str(value))


def table(rows):
    rows = [tuple(terminal_text(value) for value in row) for row in rows]
    def width(value):
        return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in str(value))
    widths = [max(width(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print('  '.join(str(x) + ' ' * (widths[i] - width(x)) for i, x in enumerate(row)).rstrip())


def main(argv=None):
    args = parser().parse_args(argv)
    started = time.time()
    if not math.isfinite(args.timeout) or not math.isfinite(args.cache_ttl) or args.timeout <= 0 or args.cache_ttl < 0:
        parser().error('--timeout 必须大于 0，--cache-ttl 不得小于 0')
    try:
        secure_dir()
        if args.command == 'login':
            print('用户名: ', end='', file=sys.stderr, flush=True)
            username = input().strip()
            password = getpass.getpass('密码: ')
            client = Client(args.timeout)
            result = client.request('/api/login', {'username': username, 'password': password})
            del password
            if isinstance(result, dict) and result.get('mfa') == 'verify':
                ticket = result.get('ticket')
                if not isinstance(ticket, str) or not ticket:
                    raise AuthError('MFA 响应缺少验证票据，请重新登录')
                code = getpass.getpass('MFA 6 位动态码: ').replace(' ', '')
                if len(code) != 6 or not code.isascii() or not code.isdigit():
                    raise AuthError('MFA 动态码须为 6 位数字')
                client.request('/api/login/mfa', {'ticket': ticket, 'code': code})
                del code, ticket
            elif isinstance(result, dict) and result.get('mfa'):
                raise AuthError('账号需要登记 MFA，请先在网站完成绑定')
            session_check(client.request('/api/session'))
            if not client.cookies:
                raise AuthError('登录响应没有会话 cookie，请检查平台登录状态')
            # Invalidate first: a crash between these writes cannot expose an old
            # account's snapshot under a newly saved session.
            atomic_write(CONFIG / 'status.json', {'base_url': BASE, 'invalidated': True})
            atomic_write(CONFIG / 'cookies.json', {'base_url': BASE, 'cookies': client.cookies})
            print(json.dumps({'ok': True}, ensure_ascii=False) if args.json else '登录成功，已保存会话 cookie。')
            return 0
        cache_path = CONFIG / 'status.json'
        error = None
        cached = read_file(cache_path)
        now = time.time()
        valid = (isinstance(cached, dict) and cached.get('base_url') == BASE
                 and type(cached.get('fetched_at')) in (int, float)
                 and math.isfinite(cached['fetched_at']) and cached['fetched_at'] <= now
                 and 'payload' in cached)
        age = now - cached['fetched_at'] if valid else float('inf')
        use_cache = valid and (args.cached or (args.fresh and cached['fetched_at'] >= started) or (not args.fresh and 0 <= age <= args.cache_ttl))
        if not use_cache and not args.cached:
            try:
                client = Client(args.timeout, cookies_load())
                old_cookies = list(client.cookies)
                payload = fetch_payload(client)
                cached = {'base_url': BASE, 'fetched_at': time.time(), 'payload': payload}
                try:
                    normalize(payload, fetched_at=cached['fetched_at'], now=cached['fetched_at'], source=BASE, cache_state='fresh')
                except (ValueError, TypeError, KeyError) as exc:
                    raise LabError('平台状态响应不完整或格式无效') from exc
                atomic_write(cache_path, cached)
                if client.cookies != old_cookies:
                    atomic_write(CONFIG / 'cookies.json', {'base_url': BASE, 'cookies': client.cookies})
                valid = True
                state = 'fresh'
            except AuthError:
                raise
            except NetworkError as exc:
                if not valid or args.fresh or args.command == 'free':
                    raise
                error = str(exc)
                state = 'stale'
        elif use_cache:
            state = 'cached' if 0 <= age <= args.cache_ttl else 'stale'
        else:
            raise LabError('没有本地状态缓存')
        try:
            value = normalize(cached['payload'], fetched_at=cached['fetched_at'], now=time.time(), source=BASE, cache_state=state)
        except (ValueError, TypeError, KeyError) as exc:
            raise LabError('缓存状态不完整或格式无效') from exc
        value = render(value, args.command, args.server)
        if error:
            value['error'] = error
        if args.json:
            print(json.dumps(value, ensure_ascii=False))
        else:
            print(f"数据: {state}，缓存年龄 {value.get('cache_age_seconds')} 秒；空闲候选不代表使用许可")
            summary = value.get('summary', {})
            print(f"全局: {summary.get('hosts', '?')} 台服务器，{summary.get('total_gpus', '?')} 张已报告 GPU，{summary.get('free_gpus', '?')} 张空闲候选，{summary.get('unreported_gpus', '?')} 张未报告")
            account = value.get('account') or {}
            usage = account.get('usage') if isinstance(account.get('usage'), dict) else {}
            rules = (value.get('policy') or {}).get('rules')
            enabled = rules.get('gpu_management_enabled') if isinstance(rules, dict) else None
            management = '开启' if enabled is True else '关闭' if enabled is False else '未知'
            print(terminal_text(f"本人占卡: {usage.get('count', '?')}；平台返回额度: {usage.get('limit', account.get('limit', '?'))}；GPU 管理: {management}（额度是否生效以平台规则为准）"))
            if error:
                print(terminal_text(f"刷新失败: {error}"), file=sys.stderr)
            rows = [('服务器', 'GPU', '型号', '显存(MiB)', '利用率', '温度', '占用者', '采样年龄(秒)', '状态')]
            notes = []
            for host in value['hosts']:
                label = host.get('label') or host.get('id', '?')
                issues = host.get('issues', [])
                if issues or (args.command != 'free' and not host.get('gpus')):
                    details = '；'.join(str(x) for x in issues) or '无 GPU 记录'
                    notes.append(f"{label}: {details}")
                for gpu in host.get('gpus', []):
                    memory = f"{gpu.get('memory_used', '?')}/{gpu.get('memory_total', '?')}"
                    users = ','.join(str(x) for x in gpu.get('users', [])) or '-'
                    age = gpu.get('sample_age_seconds')
                    age = f'{age:.0f}' if isinstance(age, (int, float)) and math.isfinite(age) else '?'
                    rows.append((label, gpu.get('index', '?'), gpu.get('name') or '?', memory, f"{gpu.get('utilization_gpu', '?')}%", f"{gpu.get('temperature', '?')}℃", users, age, STATUS_LABELS.get(gpu.get('status'), '未知')))
                    if gpu.get('status') in ('unknown', 'stale', 'fault', 'disabled') and gpu.get('reasons'):
                        notes.append(f"{label} GPU {gpu.get('index', '?')}: {'；'.join(str(x) for x in gpu['reasons'])}")
            table(rows)
            for note in notes:
                print(terminal_text(f'提示: {note}'))
            if args.command == 'free' and len(rows) == 1:
                print('未发现满足条件的空闲候选')
        return 1 if state == 'stale' else 0
    except LabError as exc:
        if args.json:
            print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        else:
            print(terminal_text(str(exc)), file=sys.stderr)
        return 1


def fetch_payload(client):
    payload = client.request('/api/me')
    if not isinstance(payload, dict) or not isinstance(payload.get('hosts'), list):
        raise LabError('平台状态响应格式无效')
    return payload


if __name__ == '__main__':
    sys.exit(main())
