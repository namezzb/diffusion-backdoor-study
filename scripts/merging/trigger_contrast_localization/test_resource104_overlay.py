import errno
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
DIR=ROOT/'research/tasks/2026-10-29-trigger-contrast-localization'
sys.path.insert(0,str(DIR))
import resource104_gdm_patch as overlay
import resource104_launcher as launcher
import test_resource_gate as fixtures


class Resource104Tests(unittest.TestCase):
    def test_gdm_identity_and_permission_denied_fallback(self):
        metadata=SimpleNamespace(st_uid=0,st_mode=stat.S_IFREG|0o755,st_dev=1,st_ino=2)
        denied=PermissionError(errno.EACCES,'denied')
        def fake_bytes(path):
            return b'/usr/bin/gnome-shell\0--flag\0'
        with patch.object(overlay,'_uid',return_value=125), patch.object(overlay,'_start',return_value=100), \
             patch.object(Path,'read_bytes',fake_bytes), patch.object(Path,'stat',return_value=metadata), \
             patch.object(os,'readlink',side_effect=denied):
            result=overlay._gdm('6941','/usr/bin/gnome-shell','G','4 MiB')
            self.assertFalse(result['exe_readable'])
            self.assertEqual(result['verification'],'proc_exe_inaccessible_cmdline_and_system_path')
            for name,kind,memory in [('python','G','4 MiB'),('/usr/bin/gnome-shell','C','4 MiB'),
                                      ('/usr/bin/gnome-shell','G','9 MiB'),('/usr/bin/gnome-shell','G','N/A')]:
                with self.assertRaises(ValueError): overlay._gdm('6941',name,kind,memory)
        metadata.st_mode=stat.S_IFREG|0o777
        with patch.object(overlay,'_uid',return_value=125), patch.object(overlay,'_start',return_value=100), \
             patch.object(Path,'read_bytes',fake_bytes), patch.object(Path,'stat',return_value=metadata), \
             patch.object(os,'readlink',side_effect=denied):
            with self.assertRaisesRegex(ValueError,'untrusted'): overlay._gdm('6941','/usr/bin/gnome-shell','G','4 MiB')

    def test_uid_requires_system_gdm_all_four_uids_and_proc_owner(self):
        def status(path): return 'Uid:\t125\t125\t125\t125\n'
        with patch.object(Path,'read_text',status), patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=125)), \
             patch.object(overlay.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=125)):
            self.assertEqual(overlay._uid('6941'),125)
        for text, owner, uid in [('Uid:\t125\t1000\t125\t125\n',125,125),('Uid:\t125\t125\t125\t125\n',1000,125),('Uid:\t1000\t1000\t1000\t1000\n',1000,1000)]:
            with patch.object(Path,'read_text',return_value=text), patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=owner)), \
                 patch.object(overlay.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=uid)):
                with self.assertRaises(ValueError): overlay._uid('6941')

    def test_xml_fails_closed_and_allows_only_verified_gdm(self):
        gate=SimpleNamespace(_xorg=lambda *args:None)
        check=overlay.build_check(gate)
        gdm='<process_info><pid>6941</pid><type>G</type><process_name>/usr/bin/gnome-shell</process_name><used_memory>4 MiB</used_memory></process_info>'
        with patch.object(overlay,'_gdm',return_value={'pid':'6941','exe_readable':False}):
            self.assertEqual(check(fixtures.xml(gdm),fixtures.UUID)['system_gdm_processes'],1)
        with patch.object(overlay,'_gdm',side_effect=PermissionError('unknown')):
            with self.assertRaisesRegex(ValueError,'unverified'): check(fixtures.xml(gdm),fixtures.UUID)
        for bad in (fixtures.xml(gdm,mode='Prohibited'), fixtures.xml(gdm,uuid='wrong'), fixtures.xml(gdm+gdm), fixtures.xml(include_processes=False)):
            with self.assertRaises(ValueError): check(bad,fixtures.UUID)

    def test_wrong_executable_and_nonpermission_failures_do_not_fallback(self):
        metadata=SimpleNamespace(st_uid=0,st_mode=stat.S_IFREG|0o755,st_dev=1,st_ino=2)
        with patch.object(overlay,'_uid',return_value=125), patch.object(overlay,'_start',return_value=100), \
             patch.object(Path,'read_bytes',return_value=b'/usr/bin/gnome-shell\0'), patch.object(Path,'stat',return_value=metadata):
            with patch.object(os,'readlink',return_value='/tmp/fake'):
                with self.assertRaises(ValueError): overlay._gdm('6941','gnome-shell','G','4 MiB')
            with patch.object(os,'readlink',side_effect=FileNotFoundError()):
                with self.assertRaises(FileNotFoundError): overlay._gdm('6941','gnome-shell','G','4 MiB')

    def test_signed_overlay_keeps_original_gate_and_rejects_changed_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory); key=temp/'key'
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
            public=Path(str(key)+'.pub'); fingerprint=hashlib.sha256(public.read_bytes()).hexdigest()
            manifest=DIR/'manifest_candidate.json'; original=ROOT/launcher.MODULE
            patch_file=temp/'patch.py'; patch_file.write_bytes((DIR/'resource104_gdm_patch.py').read_bytes())
            sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
            report={'decision':'approved','task_id':'TCL-20261029-01','run_id':'tcl-20261029-01-v1',
                'manifest_sha256':launcher.MANIFEST_SHA,'server':'school104','reviewer':'reviewer','reviewer_key_sha256':fingerprint,
                'original_resource_gate_sha256':sha(original),'overlay_sha256':sha(patch_file),
                'launcher_sha256':sha(DIR/'resource104_launcher.py'),'shard_runner_sha256':sha(DIR/'shard104_runner.py'),
                'shard_policy_sha256':sha(DIR/'shard104_policy.py'),'allowed_account':'gdm',
                'allowed_executable':'/usr/bin/gnome-shell','max_memory_mib':8}
            review=temp/'review'; review.write_text(json.dumps(report,sort_keys=True))
            subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n','tcl-resource-amendment',str(review)],check=True,capture_output=True)
            signature=Path(str(review)+'.sig')
            with patch.object(launcher,'REVIEW_KEY_SHA',fingerprint):
                source,_,_=launcher.verify(manifest,ROOT,patch_file,review,signature,public)
                self.assertEqual(source,original.read_bytes())
                patch_file.write_bytes(patch_file.read_bytes()+b'\n# changed')
                with self.assertRaisesRegex(ValueError,'does not bind'):
                    launcher.verify(manifest,ROOT,patch_file,review,signature,public)

if __name__=='__main__': unittest.main()
