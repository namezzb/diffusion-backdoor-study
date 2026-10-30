"""Hold or observe the old 104 shard lock without modifying its ledger."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path('/data2/zhangzibo/arxiv-tssa/results/tcl-20261029-01-v1-shard104-20261030')
MACHINE_SHA='af2fbecce76fa0ac96161ea712cc39576d9a198c4bc0f43585de6821ed5b5555'
MANIFEST_SHA='c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa'
FENCE_SCRIPT='/data2/zhangzibo/arxiv-tssa/preparations/tcl127_104_fence.py'


def proc_start(proc, pid):
    text=(proc/str(pid)/'stat').read_text(); pos=text.rfind(')'); parts=text[pos+1:].split()
    if pos<0 or len(parts)<20 or parts[0] in ('Z','X') or int(text.split(' ',1)[0])!=pid:
        raise ValueError('fence process is absent or exited')
    return int(parts[19])


def validate_old_shard(root, machine_file, expected_identity_sha):
    root=Path(root)
    if hashlib.sha256(Path(machine_file).read_bytes()).hexdigest()!=MACHINE_SHA:
        raise ValueError('wrong 104 machine')
    identity_file=root/'shard_identity.json'
    if identity_file.is_symlink() or not identity_file.is_file(): raise ValueError('old shard identity unavailable')
    content=identity_file.read_bytes(); identity=json.loads(content)
    if (hashlib.sha256(content).hexdigest()!=expected_identity_sha or identity.get('run_id')!='tcl-20261029-01-v1'
        or identity.get('manifest_sha256')!=MANIFEST_SHA or identity.get('server')!='school104'
        or identity.get('output_root')!=str(ROOT)):
        raise ValueError('old shard identity differs')
    image_dir=root/'images'
    if image_dir.is_symlink() or (image_dir.exists() and any(image_dir.iterdir())):
        raise ValueError('old shard contains image files or unknown image directory')
    path=root/'images.sqlite'
    if path.is_symlink(): raise ValueError('old shard ledger is symlink')
    if not path.exists():
        if any(Path(str(path)+suffix).exists() or Path(str(path)+suffix).is_symlink() for suffix in ('-wal','-shm')):
            raise ValueError('orphaned old shard SQLite auxiliary file')
        return {'ledger':'absent','attempts':0}
    if not path.is_file(): raise ValueError('old shard ledger is not a regular file')
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        counts={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('attempts','attempt_history','attempt_dispositions','gates')}
        if any(counts.values()): raise ValueError('104 shard contains scientific attempts or decisions')
        meta=json.loads(db.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0])
        if meta.get('run_id')!='tcl-20261029-01-v1' or meta.get('manifest_sha')!=MANIFEST_SHA:
            raise ValueError('old shard ledger identity differs')
    return {'ledger':'present','attempts':0,'counts':counts}


def lock_status(proc, lock_path, pid):
    st=Path(lock_path).stat(); wanted=(os.major(st.st_dev),os.minor(st.st_dev),st.st_ino)
    found=[]
    for line in (Path(proc)/'locks').read_text().splitlines():
        fields=line.split()
        if len(fields)!=8 or fields[1:4]!=['FLOCK','ADVISORY','WRITE'] or fields[4]!=str(pid) or fields[6:]!=['0','EOF']: continue
        try:
            major,minor,inode=fields[5].split(':'); target=(int(major,16),int(minor,16),int(inode))
        except ValueError: continue
        if target==wanted: found.append(line)
    if len(found)!=1: raise ValueError('104 shard lock not held by the expected fence PID')
    return found[0]


def observe(root,proc,machine,identity_sha,pid,start,plan_sha,now=None):
    root=Path(root); proc=Path(proc)
    if proc_start(proc,pid)!=start or (proc/str(pid)).stat().st_uid!=os.getuid():
        raise ValueError('104 fence process identity or owner differs')
    command=(proc/str(pid)/'cmdline').read_bytes().split(b'\0')
    if os.fsencode(FENCE_SCRIPT) not in command or b'hold' not in command:
        raise ValueError('104 fence process command is not the reviewed holder')
    before=lock_status(proc,root/'.run.lock',pid)
    result=validate_old_shard(root,machine,identity_sha)
    after=lock_status(proc,root/'.run.lock',pid)
    if before.split()[1:]!=after.split()[1:] or proc_start(proc,pid)!=start:
        raise ValueError('104 fence changed during observation')
    now=now or datetime.datetime.now(datetime.timezone.utc); issued=now-datetime.timedelta(seconds=2)
    return {'status':'104_shard_fenced_zero_attempts','machine_sha256':MACHINE_SHA,'old_identity_sha256':identity_sha,
            'plan_sha256':plan_sha,'pid':pid,'pid_start_ticks':start,'lock_line':after,'ledger':result,
            'issued_at_utc':issued.isoformat(),'expires_at_utc':(issued+datetime.timedelta(seconds=30)).isoformat()}


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('action',choices=('hold','observe'))
    p.add_argument('--identity-sha256',required=True); p.add_argument('--plan-sha256'); p.add_argument('--pid',type=int); p.add_argument('--start',type=int)
    a=p.parse_args()
    if a.action=='hold':
        lock=ROOT/'.run.lock'
        if lock.is_symlink() or not lock.is_file(): raise ValueError('existing 104 lock file required')
        fd=os.open(lock,os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        evidence=validate_old_shard(ROOT,'/etc/machine-id',a.identity_sha256)
        print(json.dumps({'pid':os.getpid(),'start_ticks':proc_start(Path('/proc'),os.getpid()),'evidence':evidence}),flush=True)
        while True: time.sleep(60)
    if not a.plan_sha256 or not a.pid or not a.start: raise ValueError('observe requires plan SHA, PID and start ticks')
    print(json.dumps(observe(ROOT,'/proc','/etc/machine-id',a.identity_sha256,a.pid,a.start,a.plan_sha256),sort_keys=True,separators=(',',':')))

if __name__=='__main__': main()
