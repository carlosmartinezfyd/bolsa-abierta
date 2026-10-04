"""Authenticated, immutable recovery of hash-addressed private PDF originals.

Only encrypted bundles may leave an ephemeral runner. Restoring a bundle does
not establish that an official source remains current or accessible.
"""
import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .store import atomic_write

MAGIC = b'BA-PRIVATE-ARCHIVE-v1\x00'
MAX_FILES = 100
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_BUNDLE_BYTES = 180 * 1024 * 1024
HASH = re.compile(r'[a-f0-9]{64}')


def archive_key(value=None):
    """Require the dedicated base64-encoded 32-byte secret, never a fallback."""
    value = os.environ.get('PRIVATE_ARCHIVE_KEY', '') if value is None else value
    if not isinstance(value, str):
        raise ValueError('Private archive key is not configured')
    try:
        key = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('Invalid private archive key') from exc
    if len(key) != 32 or base64.b64encode(key).decode() != value:
        raise ValueError('Private archive key must encode exactly 32 bytes')
    return key


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()


def _private_directory(path):
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError('Invalid private directory')
    return path


def _decode_bundle(bundle, key):
    bundle = Path(bundle)
    if bundle.is_symlink() or not HASH.fullmatch(bundle.stem) or bundle.suffix != '.baenc':
        raise ValueError('Invalid encrypted bundle filename')
    if not bundle.is_file() or not len(MAGIC) + 28 <= bundle.stat().st_size <= MAX_BUNDLE_BYTES:
        raise ValueError('Invalid encrypted bundle size')
    encrypted = bundle.read_bytes()
    if not encrypted.startswith(MAGIC):
        raise ValueError('Unsupported private archive format')
    nonce = encrypted[len(MAGIC):len(MAGIC) + 12]
    try:
        payload = AESGCM(key).decrypt(nonce, encrypted[len(MAGIC) + 12:], MAGIC)
        if hashlib.sha256(payload).hexdigest() != bundle.stem:
            raise ValueError('Private archive identity mismatch')
        value = json.loads(payload)
    except (InvalidTag, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Private archive authentication failed') from exc
    return value, payload


def _validated_files(value):
    if (not isinstance(value, dict) or set(value) != {'format', 'files', 'metadata'}
            or type(value['format']) is not int or value['format'] != 1
            or not isinstance(value['metadata'], dict)
            or not isinstance(value['files'], list) or not 1 <= len(value['files']) <= MAX_FILES):
        raise ValueError('Incomplete private archive manifest')
    files, seen, total = [], set(), 0
    for entry in value['files']:
        if not isinstance(entry, dict) or set(entry) != {'sha256', 'size', 'data'}:
            raise ValueError('Incomplete private archive file')
        digest, size = entry['sha256'], entry['size']
        if (not isinstance(digest, str) or not HASH.fullmatch(digest) or digest in seen
                or type(size) is not int or not 1 <= size <= MAX_FILE_BYTES
                or not isinstance(entry['data'], str) or len(entry['data']) > (MAX_FILE_BYTES + 2) // 3 * 4):
            raise ValueError('Invalid private archive file metadata')
        try:
            body = base64.b64decode(entry['data'], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Invalid archived original encoding') from exc
        if len(body) != size or hashlib.sha256(body).hexdigest() != digest or not body.startswith(b'%PDF-'):
            raise ValueError('Archived original hash or size differs')
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError('Private archive exceeds total byte budget')
        files.append((digest, body)); seen.add(digest)
    if ('document_count' in value['metadata'] and
            (type(value['metadata']['document_count']) is not int or value['metadata']['document_count'] != len(files))):
        raise ValueError('Private archive document count differs')
    return files, total


def export_bundle(private_dir, output_dir, *, key=None, metadata=None, expected_hashes=None):
    """Encrypt verified originals with a random nonce; identical exports reuse a bundle."""
    secret = archive_key(key)
    private = _private_directory(private_dir)
    if not private.is_dir():
        raise ValueError('Missing private originals directory')
    paths = sorted(private.iterdir())
    if not 1 <= len(paths) <= MAX_FILES:
        raise ValueError('Private originals exceed document budget or are missing')
    entries, total = [], 0
    for path in paths:
        if (path.is_symlink() or not path.is_file() or path.suffix != '.pdf'
                or not HASH.fullmatch(path.stem) or not 1 <= path.stat().st_size <= MAX_FILE_BYTES):
            raise ValueError('Invalid hash-addressed original')
        body = path.read_bytes(); total += len(body)
        if total > MAX_TOTAL_BYTES or len(body) > MAX_FILE_BYTES:
            raise ValueError('Private originals exceed byte budget')
        if hashlib.sha256(body).hexdigest() != path.stem or not body.startswith(b'%PDF-'):
            raise ValueError('Private original hash differs')
        entries.append({'sha256': path.stem, 'size': len(body), 'data': base64.b64encode(body).decode()})
    hashes = [entry['sha256'] for entry in entries]
    if expected_hashes is not None and sorted(expected_hashes) != hashes:
        raise ValueError('Private originals are missing or unexpected')
    value = {'format': 1, 'files': entries, 'metadata': metadata or {}}
    _validated_files(value)
    payload = _json(value); digest = hashlib.sha256(payload).hexdigest()
    output = _private_directory(output_dir)
    path = output / (digest + '.baenc')
    if path.exists() or path.is_symlink():
        _, existing = _decode_bundle(path, secret)
        if existing != payload:
            raise ValueError('Immutable archive conflict')
    else:
        nonce = os.urandom(12)
        encrypted = MAGIC + nonce + AESGCM(secret).encrypt(nonce, payload, MAGIC)
        if len(encrypted) > MAX_BUNDLE_BYTES:
            raise ValueError('Encrypted bundle exceeds byte budget')
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        # The final suffix is only visible after a complete, durable write.
        # A hard link installs atomically without replacing another exporter.
        fd, temporary_name = tempfile.mkstemp(prefix='.archive-', suffix='.part', dir=output)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with temporary.open('wb') as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                _, existing = _decode_bundle(path, secret)
                if existing != payload:
                    raise ValueError('Immutable archive conflict')
            directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
    return {'path': str(path), 'bundle_id': digest, 'document_count': len(hashes),
            'hashes': hashes, 'total_bytes': total, 'origin_check_performed': False}


def restore_bundle(bundle, private_dir, *, key=None, expected_hashes=None):
    """Authenticate and validate every file before writing any recovered original."""
    value, _ = _decode_bundle(bundle, archive_key(key))
    files, total = _validated_files(value)
    hashes = sorted(digest for digest, _ in files)
    if expected_hashes is not None and sorted(expected_hashes) != hashes:
        raise ValueError('Recovered originals are missing or unexpected')
    target = _private_directory(private_dir)
    for digest, body in files:
        path = target / (digest + '.pdf')
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_bytes() != body)):
            raise ValueError('Conflicting recovery destination')
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for digest, body in files:
        path = target / (digest + '.pdf')
        if not path.exists():
            atomic_write(path, body); path.chmod(0o600)
    return {'hashes': hashes, 'document_count': len(files), 'total_bytes': total,
            'metadata': value['metadata'], 'origin_check_performed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    export = sub.add_parser('export'); export.add_argument('--private-dir', required=True); export.add_argument('--archive-dir', required=True)
    restore = sub.add_parser('restore'); restore.add_argument('--bundle', required=True); restore.add_argument('--private-dir', required=True)
    args = parser.parse_args(argv)
    try:
        result = (export_bundle(args.private_dir, args.archive_dir) if args.action == 'export'
                  else restore_bundle(args.bundle, args.private_dir))
        # Encrypted metadata can contain private material from callers; never log it.
        print(json.dumps({k: v for k, v in result.items() if k != 'metadata'}, sort_keys=True))
        return 0
    except Exception:
        print('Private original recovery failed; no official source check is recorded.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
