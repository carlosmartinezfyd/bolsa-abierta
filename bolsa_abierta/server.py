"""Small same-origin WSGI API. Public callers cannot choose a source or upload files."""
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
import json
import mimetypes
from pathlib import Path
import re
from socketserver import ThreadingMixIn
from urllib.parse import unquote, urlsplit
from wsgiref.simple_server import WSGIServer, make_server

from .pipeline import run_refresh
from .store import public_state


class Application:
    def __init__(self, store, source_dir, refresh=run_refresh):
        self.store, self.source = store, Path(source_dir)
        self.refresh = refresh
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='official-refresh')
        self.web_files = {f'/web/{p.name}': p for p in (self.source / 'web').iterdir()
                          if p.is_file() and p.suffix in ('.js', '.css')}
        for weight in ('Regular', 'Medium', 'SemiBold'):
            name = f'IBMPlexSans-{weight}.woff2'
            self.web_files[f'/web/fonts/{name}'] = self.source / 'web' / 'fonts' / name

    def close(self):
        self.executor.shutdown(wait=True)

    def work(self, job_id):
        self.store.finish_job(job_id, {'status': 'running'})
        try:
            result = self.refresh(self.store)
        except Exception:
            result = {'status': 'failed', 'message': 'Falló la comprobación; se conservan los datos publicados.'}
            try:
                state = self.store.state()
                state['freshness'].update(status='failed', error=result['message'])
                self.store.publish(state)
            except (OSError, ValueError):
                pass  # Corrupt/missing storage must not be overwritten with an empty state.
        self.store.finish_job(job_id, result)

    def __call__(self, env, start_response):
        headers = [('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                   ('Referrer-Policy', 'strict-origin-when-cross-origin')]

        def respond(status, body, content_type='application/json; charset=utf-8', extra=()):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            start_response(f'{status} {HTTPStatus(status).phrase}',
                           headers + [('Content-Type', content_type), ('Content-Length', str(len(body)))] + list(extra))
            return [body]

        path = unquote(env.get('PATH_INFO', '/'))
        method = env.get('REQUEST_METHOD', 'GET')
        if '\\' in path or '..' in path.split('/'):
            return respond(404, {'error': 'Not found'})
        try:
            if path == '/api/state' and method == 'GET':
                return respond(200, public_state(self.store.state()))
            if path == '/api/refresh' and method == 'POST':
                origin = env.get('HTTP_ORIGIN')
                if origin and (urlsplit(origin).netloc != env.get('HTTP_HOST') or urlsplit(origin).scheme not in ('https', 'http')):
                    return respond(403, {'error': 'Same-origin requests required'})
                if env.get('HTTP_X_BA_REFRESH') != '1':
                    return respond(403, {'error': 'Missing refresh header'})
                if env.get('CONTENT_TYPE', '').split(';')[0].strip() != 'application/json':
                    return respond(415, {'error': 'JSON required'})
                try:
                    size = int(env.get('CONTENT_LENGTH') or 0)
                except ValueError:
                    return respond(400, {'error': 'Invalid body length'})
                if size < 2 or size > 64:
                    return respond(400, {'error': 'Only an empty JSON object is accepted'})
                try:
                    body = json.loads(env['wsgi.input'].read(size))
                except (ValueError, UnicodeError):
                    return respond(400, {'error': 'Invalid JSON'})
                if body != {}:
                    return respond(400, {'error': 'No parameters accepted'})
                job, claimed = self.store.claim_job()
                if claimed:
                    try:
                        self.executor.submit(self.work, job['id'])
                    except RuntimeError:
                        self.store.finish_job(job['id'], {'status': 'failed', 'message': 'Service shutting down'})
                        return respond(503, {'error': 'Service shutting down'})
                return respond(202, job, extra=[('Retry-After', '3')])
            if re.fullmatch(r'/api/refresh/[0-9a-f]{32}', path) and method == 'GET':
                job = self.store.job(path.rsplit('/', 1)[1])
                return respond(200, job) if job else respond(404, {'error': 'Unknown job'})
            match = re.fullmatch(r'/api/documents/([0-9a-f]{64})\.pdf', path)
            if match and method == 'GET':
                digest = match.group(1)
                if not any(d['id'] == digest and d.get('evidence_status') == 'archived' for d in self.store.state()['documents']):
                    return respond(404, {'error': 'Unknown document'})
                data = self.store.verified_artifact(digest).read_bytes()
                return respond(200, data, 'application/pdf', [('Content-Disposition', f'inline; filename="{digest}.pdf"')])
            if method == 'GET':
                file = self.source / 'index.html' if path in ('/', '/index.html') else self.web_files.get(path)
                if file and file.is_file():
                    if file.suffix == '.woff2':
                        return respond(200, file.read_bytes(), 'font/woff2')
                    kind = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
                    return respond(200, file.read_bytes(), kind + '; charset=utf-8')
            return respond(404, {'error': 'Not found'})
        except (OSError, ValueError):
            return respond(503, {'error': 'Stored evidence unavailable; retry later'})


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def serve(store, source_dir, host='127.0.0.1', port=8000):
    app = Application(store, source_dir)
    with make_server(host, port, app, server_class=ThreadedServer) as httpd:
        print(f'Bolsa Abierta: http://{host}:{port}', flush=True)
        try:
            httpd.serve_forever()
        finally:
            app.close()
