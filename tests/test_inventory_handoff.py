import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bolsa_abierta import position_sync


class InventoryHandoffTests(unittest.TestCase):
    def collect(self, directory, count=1, changed=False, enabled=True, preserve_inventory=False):
        root = Path(directory)
        bodies = {str(900000+n): b'%PDF-verified-'+str(n).encode() for n in range(count)}
        items = [{'content_id': str(900000 + n), 'kind': 'award',
                  'sha256': hashlib.sha256(bodies[str(900000+n)]).hexdigest(),
                  'source_url': f'https://www.carm.es/web/descarga?IDCONTENIDO={900000+n}',
                  'downloaded_at': '2026-10-01T00:00:00Z'} for n in range(count)]
        for name, value in [('source', {}), ('documents', {'documents': []}),
                            ('inventory', {'documents': items})]:
            if name == 'inventory' and preserve_inventory:
                continue
            (root / f'{name}.json').write_text(json.dumps(value))
        args = argparse.Namespace(source=str(root / 'source.json'),
            documents=str(root / 'documents.json'), maestros=str(root / 'absent.json'),
            inventory_state=str(root / 'inventory.json'), inventory_dir=str(root / 'originals'),
            fetch_missing_inventory=enabled)
        client = Mock()
        client.fetch.side_effect = lambda url, **kwargs: SimpleNamespace(
            body=b'%PDF-changed' if changed else bodies[url.split('=')[-1]])
        def scan(path, url, checked_at):
            item = next(item for item in items if item['source_url'] == url)
            return {'metadata': {**item, 'checked_at': checked_at}}
        with patch.object(position_sync, 'OfficialClient', return_value=client), \
             patch('bolsa_abierta.position_documents.scan_document', side_effect=scan) as parser:
            result = position_sync.source_collection(args, {})
        return result, client, parser

    def test_previous_inventory_original_is_refetched_and_hash_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            (source, _, pending), client, parser = self.collect(directory)
            self.assertEqual(pending, 0)
            self.assertEqual(len(source['documents']), 1)
            client.fetch.assert_called_once()
            parser.assert_called_once()
            self.assertNotEqual(source['documents'][0]['checked_at'], '2026-10-01T00:00:00Z')

    def test_changed_original_stays_pending_without_parsing_or_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            (source, _, pending), client, parser = self.collect(directory, changed=True)
            self.assertEqual(pending, 1)
            self.assertEqual(source['documents'], [])
            parser.assert_not_called()
            self.assertFalse(list(Path(directory).rglob('*.pdf')))

    def test_recovery_is_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            (_, _, pending), client, parser = self.collect(directory, enabled=False)
            self.assertEqual(pending, 1)
            client.fetch.assert_not_called()
            parser.assert_not_called()

    def test_missing_originals_have_a_five_request_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            (source, _, pending), client, parser = self.collect(directory, count=7)
            self.assertEqual(client.fetch.call_count, 5)
            self.assertEqual(len(source['documents']), 5)
            self.assertEqual(pending, 2)

    def test_failed_newer_originals_do_not_starve_older_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            _, first, _ = self.collect(directory, count=7, changed=True)
            (_, _, pending), second, _ = self.collect(directory, count=7, changed=True,
                                                       preserve_inventory=True)
            attempted = {call.args[0] for client in (first, second)
                         for call in client.fetch.call_args_list}
            self.assertEqual(len(attempted), 7)
            self.assertEqual(second.fetch.call_count, 5)
            self.assertEqual(pending, 7)
            inventory = json.loads((Path(directory) / 'inventory.json').read_text())
            self.assertTrue(all(item.get('position_attempted_at') for item in inventory['documents']))
