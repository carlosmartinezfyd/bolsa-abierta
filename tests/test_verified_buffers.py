"""Provenance survives replacement of a downloaded path before PDF opening."""
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from bolsa_abierta import position_amendments, position_documents, position_observations, position_sync
from tests.test_position_documents import fixture as award_fixture
from tests.test_position_observations import fixture as observation_fixture


class VerifiedBufferTests(unittest.TestCase):
    def test_awards_and_observations_open_the_bytes_that_were_hashed(self):
        for module, reader, fixture in (
            (position_documents, position_documents.read_document, award_fixture),
            (position_observations, position_observations.read_observation_document, observation_fixture),
        ):
            with self.subTest(reader=reader.__name__), TemporaryDirectory() as folder:
                path = Path(folder) / 'original.pdf'
                verified = b'%PDF-1.4 VERIFIED ORIGINAL'
                path.write_bytes(verified)
                pages, metadata = fixture()
                metadata['sha256'] = hashlib.sha256(verified).hexdigest()
                opened_bytes = []
                def open_after_replacement(target):
                    path.write_bytes(b'%PDF-1.4 REPLACED ORIGINAL')
                    opened_bytes.append(target.read() if hasattr(target, 'read') else Path(target).read_bytes())
                    pdf = MagicMock()
                    pdf.__enter__.return_value = SimpleNamespace(pages=pages)
                    return pdf
                with patch.object(module.pdfplumber, 'open', side_effect=open_after_replacement):
                    reader(path, metadata)
                self.assertEqual(opened_bytes, [verified])

    def test_discovered_award_metadata_describes_the_opened_bytes(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'original.pdf'
            verified = b'%PDF-1.4 VERIFIED ORIGINAL'
            path.write_bytes(verified)
            pages, _ = award_fixture()
            opened_bytes = []
            def open_after_replacement(target):
                path.write_bytes(b'%PDF-1.4 REPLACED ORIGINAL')
                opened_bytes.append(target.read() if hasattr(target, 'read') else Path(target).read_bytes())
                pdf = MagicMock()
                pdf.__enter__.return_value = SimpleNamespace(pages=pages)
                return pdf
            with patch.object(position_documents.pdfplumber, 'open', side_effect=open_after_replacement):
                result = position_documents.scan_document(path,
                    'https://www.carm.es/web/descarga?IDCONTENIDO=209126', '2026-10-04T12:00:00Z')
            self.assertEqual(opened_bytes, [verified])
            self.assertEqual(result['metadata']['sha256'], hashlib.sha256(opened_bytes[0]).hexdigest())

    def test_amendment_opens_its_authenticated_buffer(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'original.pdf'
            verified = b'%PDF-1.4 VERIFIED ORIGINAL'
            path.write_bytes(verified)
            opened_bytes = []
            def open_after_replacement(target):
                path.write_bytes(b'%PDF-1.4 REPLACED ORIGINAL')
                opened_bytes.append(target.read() if hasattr(target, 'read') else Path(target).read_bytes())
                pdf = MagicMock()
                pdf.__enter__.return_value = SimpleNamespace(pages=[MagicMock()])
                return pdf
            with patch.object(position_amendments.pdfplumber, 'open', side_effect=open_after_replacement), \
                    patch.object(position_amendments, 'parse_amendment', return_value=[]):
                position_amendments.read_amendment(path, {'sha256': hashlib.sha256(verified).hexdigest(),
                    'pages': 1, 'content_id': '208379'})
            self.assertEqual(opened_bytes, [verified])

    def test_collection_revalidates_and_parses_one_baseline_buffer(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'original.pdf'
            verified = b'%PDF-1.4 VERIFIED ORIGINAL'
            path.write_bytes(verified)
            source = {'sha256': hashlib.sha256(verified).hexdigest(), 'row_count': 1,
                'specialties': [{'code': '0590001', 'count': 1}]}
            opened_bytes = []
            def parse_after_replacement(target):
                path.write_bytes(b'%PDF-1.4 REPLACED ORIGINAL')
                opened_bytes.append(target.read() if hasattr(target, 'read') else Path(target).read_bytes())
                return [{'specialty': '0590001'}]
            with patch.object(position_sync, 'parse_pdf', side_effect=parse_after_replacement), \
                    patch('bolsa_abierta.position_identity.annotate_memberships', side_effect=lambda rows, course: rows):
                position_sync.read_collection(source, {source['sha256']: path})
                self.assertEqual(opened_bytes, [verified])
                with self.assertRaises(ValueError):
                    position_sync.read_collection(source, {source['sha256']: path})
