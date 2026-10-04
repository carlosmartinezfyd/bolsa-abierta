import base64
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


KEY = base64.b64encode(bytes(range(32))).decode()


class PrivateArchiveTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('bolsa_abierta.private_archive'), 'Missing authenticated private recovery')
        return importlib.import_module('bolsa_abierta.private_archive')

    def test_round_trip_reproduces_exact_hashes_sizes_and_counts_without_plaintext_archive(self):
        module = self.module()
        with TemporaryDirectory() as folder:
            root = Path(folder); private = root / 'private'; private.mkdir()
            body = b'%PDF-1.4 PERSONA NOMINAL DE EJEMPLO'
            digest = hashlib.sha256(body).hexdigest()
            (private / (digest + '.pdf')).write_bytes(body)
            result = module.export_bundle(private, root / 'archive', key=KEY,
                metadata={'document_count': 1, 'record_count': 137})
            bundle = Path(result['path'])
            self.assertNotIn(body, bundle.read_bytes())
            restored = module.restore_bundle(bundle, root / 'restore', key=KEY)
            self.assertEqual(restored['hashes'], [digest])
            self.assertEqual(restored['document_count'], 1)
            self.assertEqual(restored['total_bytes'], len(body))
            self.assertEqual(restored['metadata']['record_count'], 137)
            self.assertFalse(restored['origin_check_performed'])
            self.assertEqual((root / 'restore' / (digest + '.pdf')).read_bytes(), body)
            repeated = module.export_bundle(private, root / 'archive', key=KEY,
                metadata={'document_count': 1, 'record_count': 137})
            self.assertEqual(result['path'], repeated['path'])
            self.assertEqual(len(list((root / 'archive').iterdir())), 1)

    def test_missing_invalid_or_ingestion_token_key_cannot_export(self):
        module = self.module()
        with TemporaryDirectory() as folder:
            root = Path(folder); (root / 'private').mkdir()
            for key in (None, '', 'x' * 40, base64.b64encode(b'a' * 16).decode()):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    module.export_bundle(root / 'private', root / 'archive', key=key)
            self.assertFalse((root / 'archive').exists())
            with patch.dict('os.environ', {'POSITION_INGEST_TOKEN': 'a' * 50}, clear=True):
                with self.assertRaises(ValueError): module.archive_key()

    def test_corruption_key_mismatch_and_conflicting_existing_file_reject_before_restore(self):
        module = self.module()
        with TemporaryDirectory() as folder:
            root = Path(folder); private = root / 'private'; private.mkdir()
            body = b'%PDF-1.4 fixture'; digest = hashlib.sha256(body).hexdigest()
            (private / (digest + '.pdf')).write_bytes(body)
            result = module.export_bundle(private, root / 'archive', key=KEY)
            bundle = Path(result['path'])
            with self.assertRaises(ValueError):
                module.restore_bundle(bundle, root / 'wrongkey', key=base64.b64encode(b'z' * 32).decode())
            self.assertFalse((root / 'wrongkey').exists())
            original = bundle.read_bytes(); bundle.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            with self.assertRaises(ValueError): module.restore_bundle(bundle, root / 'corrupt', key=KEY)
            self.assertFalse((root / 'corrupt').exists())
            bundle.write_bytes(original); target = root / 'conflict'; target.mkdir()
            (target / (digest + '.pdf')).write_bytes(b'changed')
            with self.assertRaises(ValueError): module.restore_bundle(bundle, target, key=KEY)
            self.assertEqual((target / (digest + '.pdf')).read_bytes(), b'changed')

    def test_export_rejects_traversal_symlinks_hash_mismatch_missing_files_and_limits(self):
        module = self.module()
        with TemporaryDirectory() as folder:
            root = Path(folder); private = root / 'private'; private.mkdir()
            bad = private / ('a' * 64 + '.pdf'); bad.write_bytes(b'%PDF-wrong')
            with self.assertRaises(ValueError): module.export_bundle(private, root / 'archive', key=KEY)
            bad.unlink(); (private / 'unexpected.pdf').write_bytes(b'%PDF-wrong')
            with self.assertRaises(ValueError): module.export_bundle(private, root / 'archive', key=KEY)
            (private / 'unexpected.pdf').unlink()
            body = b'%PDF-fixture'; digest = hashlib.sha256(body).hexdigest()
            good = private / (digest + '.pdf'); good.write_bytes(body)
            with patch.object(module, 'MAX_FILE_BYTES', 2), self.assertRaises(ValueError):
                module.export_bundle(private, root / 'archive', key=KEY)
            with self.assertRaises(ValueError):
                module.export_bundle(private, root / 'archive', key=KEY, expected_hashes=['b' * 64])
            good.unlink(); good.symlink_to(root / 'elsewhere')
            with self.assertRaises(ValueError): module.export_bundle(private, root / 'archive', key=KEY)

    def test_authenticated_malformed_bundle_never_creates_traversal_or_partial_files(self):
        module = self.module()
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for record in ({'name': '../escape.pdf', 'sha256': 'a' * 64, 'size': 1, 'data': 'eA=='},
                           {'sha256': 'a' * 64, 'size': 1, 'data': 'eA=='},
                           {'sha256': 'a' * 64, 'size': 1}):
                payload = json.dumps({'format': 1, 'files': [record], 'metadata': {}}).encode()
                nonce = b'n' * 12
                encrypted = module.MAGIC + nonce + AESGCM(base64.b64decode(KEY)).encrypt(nonce, payload, module.MAGIC)
                bundle = root / (hashlib.sha256(payload).hexdigest() + '.baenc'); bundle.write_bytes(encrypted)
                with self.assertRaises(ValueError): module.restore_bundle(bundle, root / 'restore', key=KEY)
                self.assertFalse((root / 'restore').exists())
                self.assertFalse((root / 'escape.pdf').exists())

    def test_interrupted_archive_write_never_publishes_partial_final_and_retry_succeeds(self):
        module = self.module()
        original_open = Path.open
        class InterruptedWriter:
            def __init__(self, handle): self.handle = handle
            def __enter__(self): return self
            def __exit__(self, *args): self.handle.close()
            def __getattr__(self, name): return getattr(self.handle, name)
            def write(self, data):
                self.handle.write(data[:40]); self.handle.flush()
                raise OSError('simulated interrupted archive write')
        with TemporaryDirectory() as folder:
            root = Path(folder); private = root / 'private'; private.mkdir()
            body = b'%PDF-1.4 interrupted fixture'; digest = hashlib.sha256(body).hexdigest()
            (private / (digest + '.pdf')).write_bytes(body)
            output = root / 'archive'
            def interrupted(path, mode='r', *args, **kwargs):
                handle = original_open(path, mode, *args, **kwargs)
                return InterruptedWriter(handle) if path.parent == output and mode in ('wb', 'xb') else handle
            with patch.object(Path, 'open', interrupted), self.assertRaises(OSError):
                module.export_bundle(private, output, key=KEY)
            self.assertEqual(list(output.glob('*.baenc')), [], 'Partial archive must never receive a final name')
            self.assertEqual(list(output.iterdir()), [], 'Failed write must remove private temporary files')
            result = module.export_bundle(private, output, key=KEY)
            restored = module.restore_bundle(result['path'], root / 'restore', key=KEY)
            self.assertEqual(restored['hashes'], [digest])

    def test_install_race_preserves_other_writer_authenticated_immutable_bundle(self):
        module = self.module()
        import os
        with TemporaryDirectory() as folder:
            root = Path(folder); private = root / 'private'; private.mkdir()
            body = b'%PDF-1.4 concurrent fixture'; digest = hashlib.sha256(body).hexdigest()
            (private / (digest + '.pdf')).write_bytes(body)
            reference = module.export_bundle(private, root / 'reference', key=KEY)
            reference_bytes = Path(reference['path']).read_bytes()
            def race_install(source, destination):
                Path(destination).write_bytes(reference_bytes)
                raise FileExistsError('simulated other successful exporter')
            with patch.object(os, 'link', race_install):
                result = module.export_bundle(private, root / 'archive', key=KEY)
            self.assertEqual(Path(result['path']).read_bytes(), reference_bytes)
            self.assertEqual(len(list((root / 'archive').iterdir())), 1)
