"""Strict gdm graphical-process allowance for separately reviewed 104 overlay.

Direct /proc/PID/exe and inode are preferred. Permission-denied fallback is
restricted to gdm, verified command and root-owned immutable system path, and
is reported explicitly; unknown identity is rejected.
"""
from __future__ import annotations
import os
import errno
from pathlib import Path
import pwd
import re
import stat
import xml.etree.ElementTree as ET

PATH = '/usr/bin/gnome-shell'
MAX_MIB = 8


def _start(pid):
    data = (Path('/proc') / pid / 'stat').read_text()
    pos = data.rfind(')')
    if pos < 0 or not data[:pos].startswith(pid + ' ('):
        raise ValueError('invalid process stat')
    parts = data[pos + 1:].split()
    if len(parts) < 20:
        raise ValueError('incomplete process stat')
    return int(parts[19])


def _uid(pid):
    root = Path('/proc') / pid
    status = root.joinpath('status').read_text().splitlines()
    lines = [line.split(':',1)[1].split() for line in status if line.startswith('Uid:')]
    if len(lines) != 1 or len(lines[0]) != 4 or any(not x.isdigit() for x in lines[0]):
        raise ValueError('process UID not verifiable')
    user = pwd.getpwnam('gdm')
    uids = [int(x) for x in lines[0]]
    if user.pw_uid <= 0 or user.pw_uid >= 1000 or any(x != user.pw_uid for x in uids) or root.stat().st_uid != user.pw_uid:
        raise ValueError('process is not the gdm system account')
    return user.pw_uid


def _gdm(pid, name, process_type, memory):
    if (not isinstance(pid,str) or not pid.isdigit() or int(pid) <= 0 or process_type != 'G'
            or name not in ('gnome-shell', PATH) or not isinstance(memory,str)):
        raise ValueError('not an allowed gdm graphics process')
    match = re.fullmatch(r'\s*(\d+)\s+MiB\s*',memory)
    if not match or int(match[1]) > MAX_MIB:
        raise ValueError('gdm graphics memory unknown or exceeds limit')
    root = Path('/proc') / pid
    before, uid = _start(pid), _uid(pid)
    command = os.fsdecode(root.joinpath('cmdline').read_bytes().split(b'\0', 1)[0])
    if command != PATH:
        raise ValueError('gdm process command differs')
    exe = root / 'exe'
    expected = Path(PATH).stat()
    if (expected.st_uid != 0 or not stat.S_ISREG(expected.st_mode)
            or not expected.st_mode & stat.S_IXUSR or expected.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        raise ValueError('gdm system path ownership or permissions are untrusted')
    readable = True
    try:
        if os.readlink(exe) != PATH:
            raise ValueError('gdm actual executable differs')
        actual = exe.stat()
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError('gdm executable inode differs')
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EPERM):
            raise
        readable = False
    if _start(pid) != before or _uid(pid) != uid:
        raise ValueError('gdm process identity changed during inspection')
    return {'pid':pid,'uid':uid,'account':'gdm','system_path':PATH,'exe_readable':readable,
            'verification':'proc_exe_inode_and_uid' if readable else 'proc_exe_inaccessible_cmdline_and_system_path',
            'memory_mib':int(match[1]),'start_ticks':before}


def build_check(original):
    """Use the original Xorg verifier and leave all other checks fail-closed."""
    def check(xml_bytes, uuid):
        try:
            root=ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise ValueError('nvidia-smi returned invalid GPU status') from exc
        matches=[gpu for gpu in root.findall('gpu') if gpu.findtext('uuid') == uuid]
        if root.tag != 'nvidia_smi_log' or len(matches) != 1:
            raise ValueError('GPU UUID missing, ambiguous or status unknown')
        gpu=matches[0]
        if gpu.findtext('compute_mode') != 'Default':
            raise ValueError('GPU compute mode is disabled, exclusive or unknown')
        processes=gpu.find('processes')
        if processes is None or (processes.text and processes.text.strip()):
            raise ValueError('GPU process status is unknown')
        xorg=[]; gdm=[]; seen=set()
        for process in processes:
            if process.tag != 'process_info': raise ValueError('GPU process status is unknown')
            pid,name,kind=process.findtext('pid'),process.findtext('process_name'),process.findtext('type')
            if not isinstance(pid,str) or pid in seen: raise ValueError('ambiguous GPU process PID')
            seen.add(pid)
            evidence=original._xorg(pid,name,kind) if isinstance(name,str) else None
            if evidence:
                xorg.append(evidence); continue
            try:
                evidence=_gdm(pid,name,kind,process.findtext('used_memory'))
            except (OSError,RuntimeError,KeyError,ValueError) as exc:
                raise ValueError('GPU has an unverified or non-system process') from exc
            gdm.append(evidence)
        if len(gdm)>1: raise ValueError('multiple gdm graphics processes are not authorized')
        return {'gpu_uuid':uuid,'compute_mode':'Default','system_xorg_processes':len(xorg),
                'xorg_evidence':xorg,'system_gdm_processes':len(gdm),'gdm_evidence':gdm}
    return check
