"""Additional signed short-lived 104 zero-attempt lock observation for 127."""
import base64
import datetime
import json
from pathlib import Path
import shard104_policy as base

MACHINE_SHA='af2fbecce76fa0ac96161ea712cc39576d9a198c4bc0f43585de6821ed5b5555'


def verify_fence(path,public_key,key_sha,principal,plan_sha,identity_sha,pid,start,now=None):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>65536: raise ValueError('104 fence witness unavailable')
    envelope=json.loads(path.read_bytes())
    message=base64.b64decode(envelope['message_b64'],validate=True)
    signature=base64.b64decode(envelope['signature_b64'],validate=True)
    base.verify_signature(message,signature,public_key,key_sha,principal,'tcl-shard104-fence')
    data=json.loads(message)
    expected={'status':'104_shard_fenced_zero_attempts','machine_sha256':MACHINE_SHA,'old_identity_sha256':identity_sha,
              'plan_sha256':plan_sha,'pid':pid,'pid_start_ticks':start}
    ledger=data.get('ledger')
    if (any(data.get(k)!=v for k,v in expected.items()) or not isinstance(ledger,dict)
            or ledger.get('attempts')!=0 or ledger.get('ledger') not in ('absent','present')
            or (ledger.get('ledger')=='present' and ledger.get('counts')!={'attempts':0,'attempt_history':0,'attempt_dispositions':0,'gates':0})):
        raise ValueError('104 fence witness identity or zero-attempt proof differs')
    line=data.get('lock_line','').split()
    if (len(line)!=8 or not line[0].endswith(':') or not line[0][:-1].isdigit()
        or line[1:5]!=['FLOCK','ADVISORY','WRITE',str(pid)] or line[6:]!=['0','EOF']):
        raise ValueError('104 fence lock status unknown')
    try:
        device_major,device_minor,inode=line[5].split(':'); int(device_major,16); int(device_minor,16)
        if int(inode)<=0: raise ValueError('bad inode')
        issued=datetime.datetime.fromisoformat(data['issued_at_utc']); expires=datetime.datetime.fromisoformat(data['expires_at_utc'])
    except (ValueError,KeyError) as exc: raise ValueError('104 fence witness malformed') from exc
    now=now or datetime.datetime.now(datetime.timezone.utc)
    if (issued.tzinfo is None or expires.tzinfo is None or issued.utcoffset()!=datetime.timedelta(0)
        or expires.utcoffset()!=datetime.timedelta(0) or issued>now or now>=expires
        or not 0<(expires-issued).total_seconds()<=30):
        raise ValueError('104 fence witness expired or invalid')
    return {'fence_sha256':base.sha(message),'expires_at_utc':expires.isoformat()}
