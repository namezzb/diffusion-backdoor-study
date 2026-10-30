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
import resource127_gdm_xorg_patch as overlay
import resource127_launcher as launcher
import test_resource_gate as fixtures


class Resource127Tests(unittest.TestCase):
    def test_new_resource_permits_do_not_overwrite_prior_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); old=root/'resource_permit.json'; old.write_bytes(b'prior permit')
            first=launcher.permit_directory(root); second=launcher.permit_directory(root)
            self.assertNotEqual(first,second)
            (first/'resource_permit.json').write_bytes(b'new permit')
            self.assertEqual(old.read_bytes(),b'prior permit')
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as other:
            root=Path(directory); (root/'resource_permit_attempts').symlink_to(other,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'permit directory'):
                launcher.permit_directory(root)

    def test_gdm_identity_and_permission_denied_fallback(self):
        metadata=SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFREG|0o755,st_dev=1,st_ino=27265194)
        denied=PermissionError(errno.EACCES,'denied')
        def fake_bytes(path):
            return b'/usr/lib/xorg/Xorg\0--flag\0'
        with patch.object(overlay,'_uid',return_value=128), patch.object(overlay,'_start',return_value=100), \
             patch.object(Path,'read_bytes',fake_bytes), patch.object(Path,'stat',return_value=metadata), \
             patch.object(os,'readlink',side_effect=denied):
            result=overlay._gdm('49207','/usr/lib/xorg/Xorg','G','4 MiB')
            self.assertFalse(result['exe_readable'])
            self.assertEqual(result['verification'],'proc_exe_inaccessible_cmdline_and_system_path')
            for name,kind,memory in [('python','G','4 MiB'),('/usr/lib/xorg/Xorg','C','4 MiB'),
                                      ('/usr/lib/xorg/Xorg','G','9 MiB'),('/usr/lib/xorg/Xorg','G','N/A')]:
                with self.assertRaises(ValueError): overlay._gdm('49207',name,kind,memory)
        metadata.st_mode=stat.S_IFREG|0o777
        with patch.object(overlay,'_uid',return_value=128), patch.object(overlay,'_start',return_value=100), \
             patch.object(Path,'read_bytes',fake_bytes), patch.object(Path,'stat',return_value=metadata), \
             patch.object(os,'readlink',side_effect=denied):
            with self.assertRaisesRegex(ValueError,'untrusted'): overlay._gdm('49207','/usr/lib/xorg/Xorg','G','4 MiB')

    def test_uid_requires_system_gdm_all_four_uids_and_proc_owner(self):
        def status(path): return 'Name:\tXorg\nTgid:\t49207\nUid:\t128\t128\t128\t128\nGid:\t132\t132\t132\t132\n'
        with patch.object(Path,'read_text',status), patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=128)), \
             patch.object(overlay.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=128,pw_gid=132)):
            self.assertEqual(overlay._uid('49207'),128)
        valid=status(None)
        for text, owner, uid in [(valid.replace('128\t128\t128\t128','128\t1000\t128\t128'),128,128),
                                 (valid,1000,128),(valid.replace('132\t132\t132\t132','132\t1000\t132\t132'),128,128),
                                 (valid.replace('Name:\tXorg','Name:\tpython'),128,128),
                                 (valid.replace('Tgid:\t49207','Tgid:\t123'),128,128)]:
            with patch.object(Path,'read_text',return_value=text), patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=owner)), \
                 patch.object(overlay.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=uid,pw_gid=132)):
                with self.assertRaises(ValueError): overlay._uid('49207')

    def test_xml_fails_closed_and_allows_only_verified_gdm(self):
        gate=SimpleNamespace(_xorg=lambda *args:None)
        check=overlay.build_check(gate)
        gdm='<process_info><pid>49207</pid><type>G</type><process_name>/usr/lib/xorg/Xorg</process_name><used_memory>4 MiB</used_memory></process_info>'
        with patch.object(overlay,'_gdm',return_value={'pid':'49207','exe_readable':False}):
            self.assertEqual(check(fixtures.xml(gdm),fixtures.UUID)['system_gdm_processes'],1)
        with patch.object(overlay,'_gdm',side_effect=PermissionError('unknown')):
            with self.assertRaisesRegex(ValueError,'unverified'): check(fixtures.xml(gdm),fixtures.UUID)
        for bad in (fixtures.xml(gdm,mode='Prohibited'), fixtures.xml(gdm,uuid='wrong'), fixtures.xml(gdm+gdm), fixtures.xml(include_processes=False)):
            with self.assertRaises(ValueError): check(bad,fixtures.UUID)

    def test_wrong_executable_and_nonpermission_failures_do_not_fallback(self):
        metadata=SimpleNamespace(st_uid=0,st_gid=0,st_mode=stat.S_IFREG|0o755,st_dev=1,st_ino=27265194)
        with patch.object(overlay,'_uid',return_value=128), patch.object(overlay,'_start',return_value=100), \
             patch.object(Path,'read_bytes',return_value=b'/usr/lib/xorg/Xorg\0'), patch.object(Path,'stat',return_value=metadata):
            with patch.object(os,'readlink',return_value='/tmp/fake'):
                with self.assertRaises(ValueError): overlay._gdm('49207','Xorg','G','4 MiB')
            with patch.object(os,'readlink',side_effect=FileNotFoundError()):
                with self.assertRaises(FileNotFoundError): overlay._gdm('49207','Xorg','G','4 MiB')

    def test_signed_overlay_keeps_original_gate_and_rejects_changed_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory); key=temp/'key'
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
            public=Path(str(key)+'.pub'); fingerprint=hashlib.sha256(public.read_bytes()).hexdigest()
            manifest=DIR/'manifest_candidate.json'; original=ROOT/launcher.MODULE
            patch_file=temp/'patch.py'; patch_file.write_bytes((DIR/'resource127_gdm_xorg_patch.py').read_bytes())
            sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
            report={'decision':'approved','task_id':'TCL-20261029-01','run_id':'tcl-20261029-01-v1',
                'manifest_sha256':launcher.MANIFEST_SHA,'server':'school127','reviewer':'reviewer','reviewer_key_sha256':fingerprint,
                'original_resource_gate_sha256':sha(original),'overlay_sha256':sha(patch_file),
                'launcher_sha256':sha(DIR/'resource127_launcher.py'),'shard_runner_sha256':sha(DIR/'shard127_runner.py'),
                'shard_policy_sha256':sha(DIR/'shard104_policy.py'),'fence_policy_sha256':sha(DIR/'shard127_policy.py'),'allowed_account':'gdm',
                'allowed_executable':'/usr/lib/xorg/Xorg','max_memory_mib':8,
                'gdm_uid':128,'gdm_gid':132,'xorg_file_uid':0,'xorg_file_gid':0,'xorg_file_mode':'0755','xorg_file_inode':27265194,
                'destination_machine_sha256':'99b0f2a4634566cc13b4686bcfad863346e6975d37221fb1fc27ebb0d814848d',
                'gpu_uuid':'GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91'}
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
