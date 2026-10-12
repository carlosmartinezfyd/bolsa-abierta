import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from bolsa_abierta.private_archive import export_bundle


class RecoveryDrillTests(unittest.TestCase):
    def test_real_restore_checks_current_hashes_and_preserves_nonredundant_history(self):
        from bolsa_abierta.recovery import recovery_drill
        key = base64.b64encode(bytes(range(32))).decode()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            private = root / 'private'; private.mkdir()
            body = b'%PDF-synthetic'; digest = hashlib.sha256(body).hexdigest()
            (private / (digest + '.pdf')).write_bytes(body)
            export_bundle(private, root / 'archives', key=key)
            result = recovery_drill(root / 'archives', [digest], key=key)
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(result['restored_documents'], 1)
            self.assertFalse(result['origin_check_performed'])
            with self.assertRaises(ValueError):
                recovery_drill(root / 'archives', ['a' * 64], key=key)
            self.assertEqual(len(list((root / 'archives').glob('*.baenc'))), 1)

    def test_retention_preserves_active_hashes_two_latest_and_unknown_age(self):
        from bolsa_abierta.recovery import retention_candidates
        from datetime import datetime, timezone
        records = [({'path': str(i), 'hashes': [str(i)], 'checked_at': stamp})
                   for i, stamp in enumerate(['2025-01-01T00:00:00Z', '2025-02-01T00:00:00Z',
                       '2025-03-01T00:00:00Z', '2025-04-01T00:00:00Z', None])]
        remove = retention_candidates(records, {'0'}, datetime(2026, 10, 13, tzinfo=timezone.utc))
        self.assertEqual([r['path'] for r in remove], ['1'])
