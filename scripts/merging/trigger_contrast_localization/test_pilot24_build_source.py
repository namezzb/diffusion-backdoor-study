"""Construct source evidence with synthetic fixtures only; no GPU is used."""
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

import pilot24_build_source as builder
from pilot24_inputs import PARENT, RUN
from test_pilot24_provenance import Fixture, REPOSITORY


class BuildSourceTests(Fixture):
    def setUp(self):
        super().setUp()
        self.input = self.root / 'actual_source'
        (self.input / 'selection').mkdir(parents=True)
        for item in self.copies:
            role = item['role']
            source = Path(item['path'])
            if role == 'selection' or role.startswith('mask:'):
                shutil.copyfile(source, self.input / 'selection' / source.name)
            elif role == 'localization_terminal':
                shutil.copyfile(source, self.input / 'localization_terminal.json')
            elif role == 'localization_ledger':
                shutil.copyfile(source, self.input / 'localization.sqlite')
        self.candidates = self.root / 'candidates.json'
        self.candidates.write_text(json.dumps({'run_id': RUN, 'status': 'provisional_not_imported',
            'candidate_count': 1, 'records': [{'source': 'unavailable'}]}))
        self.request = {'repository_root': str(self.repository), 'source_run_root': str(self.input),
            'source_server': 'school104', 'package_root': str(self.root / 'package'),
            'output_root': str(self.output), 'old_output_roots': [{'server': 'school103', 'path': self.old_root}],
            'legacy_launch_records': [str(self.root / 'launch.json')],
            'legacy_upper_bound_basis': 'fixture only', 'candidates_file': str(self.candidates),
            'candidate_sources': {'unavailable': {'exclude_reason': 'fixture source inaccessible'}},
            'no_reuse_reason': 'fixture cannot authenticate the image'}

    def tearDown(self):
        package = self.root / 'package'
        if package.exists():
            for item in package.rglob('*'):
                if item.is_dir():
                    item.chmod(0o755)
        super().tearDown()

    def build_fixture(self):
        with patch.object(builder, 'CANDIDATES_SHA256', builder.sha_file(self.candidates)), patch.object(builder, 'CANDIDATE_COUNT', 1):
            return builder.build(self.request)

    def test_r0_builds_real_copies_and_records_backup_origin(self):
        report_ref = self.build_fixture()
        report = json.loads(Path(report_ref['path']).read_text())
        self.assertEqual(report['authenticated_imports'], 0)
        self.assertEqual(report['omitted_by_source'], {'unavailable': 1})
        proof = json.loads(Path(report['source_isolation']['path']).read_text())
        self.assertEqual(proof['source_writer_state'], 'unknown')
        self.assertEqual(proof['construction_evidence'], report['construction_evidence'])
        self.assertEqual(builder.ref(report['construction_evidence']['path']), report['construction_evidence'])
        copy = next(x for x in proof['copies'] if x['role'] == 'localization_ledger')
        backup = report['sqlite_backups'][0]
        self.assertEqual(copy['origin']['path'], backup['consistent_backup']['path'])
        self.assertEqual(copy['sha256'], backup['consistent_backup']['sha256'])
        self.assertEqual(backup['original_before']['main']['path'], str(self.input / 'localization.sqlite'))
        self.assertIn('not a claim of equality', backup['note'])

    def test_no_reuse_requires_explanation(self):
        self.request['no_reuse_reason'] = ''
        with self.assertRaisesRegex(ValueError, 'R=0'):
            self.build_fixture()

    def test_rejects_any_unpinned_candidate_list(self):
        with self.assertRaisesRegex(ValueError, 'fixed 363-unit'):
            builder.build(self.request)

    def test_source_and_output_cannot_overlap(self):
        self.request['output_root'] = str(self.input / RUN)
        with self.assertRaisesRegex(ValueError, 'must be disjoint'):
            self.build_fixture()

    def transported_fixture(self):
        row = self.add_import()
        local = self.root / 'transferred'
        local.mkdir()
        image = local / 'image.png'
        shutil.copyfile(row['image']['path'], image)
        ledger = local / 'images.sqlite'
        shutil.copyfile(row['ledger']['path'], ledger)
        remote = self.root / 'remote_images'
        candidate = {'source': 'remote', 'key': row['origin_key'], 'image_path': str(remote / image.name),
                     'image_sha': row['image']['sha256'], 'input_sha': row['input_sha256'],
                     'mask_sha': row['mask_sha256'], 'scores': row['scores'], 'bytes': image.stat().st_size}
        ledger_sha = builder.sha_file(ledger)
        self.candidates.write_text(json.dumps({'run_id': RUN, 'status': 'provisional_not_imported',
            'candidate_count': 1, 'records': [candidate], 'observations': {'remote': {'ledger_sha256': ledger_sha}}}))
        self.request['candidate_sources'] = {'remote': {'server': 'school104', 'ledger': str(ledger),
            'image_root': str(local), 'recorded_image_root': str(remote)}}
        return ledger_sha, candidate

    def test_relocated_source_needs_receipt(self):
        self.transported_fixture()
        with self.assertRaisesRegex(ValueError, 'requires a transfer receipt'):
            self.build_fixture()

    def test_relocated_source_receipt_binds_every_image(self):
        ledger_sha, candidate = self.transported_fixture()
        receipt = self.root / 'receipt.json'
        source_evidence = self.root / 'source-evidence.json'
        source_evidence.write_text(json.dumps({'server': 'school127',
            'original_ledger': str(self.root / 'images.sqlite'), 'original_sha256_before_after': ledger_sha,
            'wal_sha256_before_after': '0' * 64, 'sqlite_backup_sha256': ledger_sha, 'sqlite_quick_check': 'ok',
            'candidate_count': 1, 'images': [{'origin': candidate['image_path'], 'copied': 'images/image.png',
                                              'sha256': candidate['image_sha'], 'bytes': candidate['bytes']}]}))
        payload = {'source_ledger_sha256': ledger_sha, 'source_consistent_backup_sha256': ledger_sha,
                   'destination_consistent_backup_sha256': ledger_sha, 'source_server': 'school127',
                   'destination_server': 'school104', 'images': {'image.png': candidate['image_sha']},
                   'source_evidence_path': str(source_evidence),
                   'source_evidence_sha256': builder.sha_file(source_evidence)}
        receipt.write_text(json.dumps(payload))
        self.request['candidate_sources']['remote']['transport_receipt'] = str(receipt)
        report = json.loads(Path(self.build_fixture()['path']).read_text())
        self.assertEqual(report['authenticated_imports'], 1)
        proof = json.loads(Path(report['source_isolation']['path']).read_text())
        self.assertTrue(any(x['role'] == 'transport_receipt:0' for x in proof['copies']))
        self.assertTrue(any(x['role'] == 'transport_source_evidence:0' for x in proof['copies']))

    def test_source_transfer_evidence_hash_is_required(self):
        ledger_sha, candidate = self.transported_fixture()
        source_evidence = self.root / 'source-evidence.json'
        source_evidence.write_text('{}')
        receipt = self.root / 'receipt.json'
        receipt.write_text(json.dumps({'source_ledger_sha256': ledger_sha,
            'source_consistent_backup_sha256': ledger_sha, 'destination_consistent_backup_sha256': ledger_sha,
            'source_server': 'school127', 'destination_server': 'school104',
            'images': {'image.png': candidate['image_sha']}, 'source_evidence_path': str(source_evidence),
            'source_evidence_sha256': '0' * 64}))
        self.request['candidate_sources']['remote']['transport_receipt'] = str(receipt)
        with self.assertRaisesRegex(ValueError, 'referenced content hash differs'):
            self.build_fixture()

    def test_source_transfer_mapping_must_match_fixed_candidates(self):
        ledger_sha, candidate = self.transported_fixture()
        source_evidence = self.root / 'source-evidence.json'
        source_evidence.write_text(json.dumps({'server': 'school127',
            'original_ledger': str(self.root / 'images.sqlite'), 'original_sha256_before_after': ledger_sha,
            'wal_sha256_before_after': '0' * 64, 'sqlite_backup_sha256': ledger_sha, 'sqlite_quick_check': 'ok',
            'candidate_count': 1, 'images': [{'origin': candidate['image_path'], 'copied': 'images/image.png',
                                              'sha256': '0' * 64, 'bytes': candidate['bytes']}]}))
        receipt = self.root / 'receipt.json'
        receipt.write_text(json.dumps({'source_ledger_sha256': ledger_sha,
            'source_consistent_backup_sha256': ledger_sha, 'destination_consistent_backup_sha256': ledger_sha,
            'source_server': 'school127', 'destination_server': 'school104',
            'images': {'image.png': candidate['image_sha']}, 'source_evidence_path': str(source_evidence),
            'source_evidence_sha256': builder.sha_file(source_evidence)}))
        self.request['candidate_sources']['remote']['transport_receipt'] = str(receipt)
        with self.assertRaisesRegex(ValueError, 'differs from frozen image mapping'):
            self.build_fixture()

    def test_one_exact_ledger_and_image_is_imported(self):
        row = self.add_import()
        old_image = self.root / 'historical' / 'original.png'
        old_image.parent.mkdir()
        shutil.copyfile(row['image']['path'], old_image)
        gen_ledger = self.root / 'historical' / 'images.sqlite'
        shutil.copyfile(row['ledger']['path'], gen_ledger)
        key = row['origin_key']
        candidate = {'source': 'historical', 'key': key, 'image_path': str(old_image),
                     'image_sha': row['image']['sha256'], 'input_sha': row['input_sha256'],
                     'mask_sha': row['mask_sha256'], 'scores': row['scores']}
        self.candidates.write_text(json.dumps({'run_id': RUN, 'status': 'provisional_not_imported',
                                               'candidate_count': 1, 'records': [candidate],
                                               'observations': {'historical': {'ledger_sha256': builder.sha_file(gen_ledger)}}}))
        self.request['candidate_sources'] = {'historical': {'server': 'school104', 'ledger': str(gen_ledger),
            'image_root': str(old_image.parent), 'recorded_image_root': str(old_image.parent)}}
        report = json.loads(Path(self.build_fixture()['path']).read_text())
        self.assertEqual(report['authenticated_imports'], 1)
        proof = json.loads(Path(report['source_isolation']['path']).read_text())
        self.assertEqual(proof['imports'][0]['origin_key'][0], PARENT)
        self.assertEqual(proof['freeze']['source_imports'], 1)

    def test_mismatched_candidate_does_not_import(self):
        row = self.add_import()
        old_image = self.root / 'original.png'
        shutil.copyfile(row['image']['path'], old_image)
        gen_ledger = self.root / 'images.sqlite'
        shutil.copyfile(row['ledger']['path'], gen_ledger)
        candidate = {'source': 'historical', 'key': row['origin_key'], 'image_path': str(old_image),
                     'image_sha': row['image']['sha256'], 'input_sha': '0' * 64,
                     'mask_sha': row['mask_sha256'], 'scores': row['scores']}
        self.candidates.write_text(json.dumps({'run_id': RUN, 'status': 'provisional_not_imported',
                                               'candidate_count': 1, 'records': [candidate],
                                               'observations': {'historical': {'ledger_sha256': builder.sha_file(gen_ledger)}}}))
        self.request['candidate_sources'] = {'historical': {'server': 'school104', 'ledger': str(gen_ledger),
            'image_root': str(self.root), 'recorded_image_root': str(self.root)}}
        with self.assertRaisesRegex(ValueError, 'differs from exact'):
            self.build_fixture()

    def test_consistent_sqlite_backup_includes_wal(self):
        original = self.root / 'wal.sqlite'
        output = self.root / 'copy.sqlite'
        evidence = []
        with sqlite3.connect(original) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('CREATE TABLE sample(value INTEGER)')
            db.execute('INSERT INTO sample VALUES(7)')
            db.commit()
            self.assertTrue(Path(str(original) + '-wal').exists())
            builder.sqlite_backup(original, output, evidence)
            with sqlite3.connect(output.as_uri() + '?mode=ro', uri=True) as copy:
                self.assertEqual(copy.execute('SELECT value FROM sample').fetchall(), [(7,)])
        self.assertIn('-wal', evidence[0]['original_before'])
        self.assertFalse(Path(str(output) + '-wal').exists())


if __name__ == '__main__':
    unittest.main()
