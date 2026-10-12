"""Opt-in ordinary Chromium transport for CARM's browser-compatible endpoint.

The empty, locally fulfilled page establishes an origin only. It is never source
evidence. Remote scripts, subresources, redirects and service workers cannot run.
Only a bounded GET through browser networking returns bytes to OfficialClient.
"""
import atexit
import base64
import ipaddress
import socket
import threading
import time
import uuid

from requests.structures import CaseInsensitiveDict

from .sources import SourceError, _allowed_url


FETCH = """async ({url, headers, limit, milliseconds}) => {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), milliseconds);
  let reader;
  try {
    const response = await fetch(url, {method:'GET', headers, redirect:'manual',
      credentials:'same-origin', cache:'no-store', signal:abort.signal});
    if (response.type === 'opaqueredirect') return {error_code:'access_challenge'};
    const kept = {};
    for (const name of ['content-type','content-length','etag','last-modified','retry-after']) {
      const value = response.headers.get(name);
      if (value !== null) kept[name] = value;
    }
    if (Number(kept['content-length']) > limit) return {error_code:'size_limit'};
    const chunks = []; let size = 0;
    if (response.body) {
      reader = response.body.getReader();
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        size += value.length;
        if (size > limit) return {error_code:'size_limit'};
        chunks.push(value);
      }
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.length;}
    let binary = '';
    for (let i=0; i<bytes.length; i+=32768) binary += String.fromCharCode(...bytes.subarray(i,i+32768));
    return {status:response.status, headers:kept, body:btoa(binary)};
  } catch (_) {
    return {error_code:abort.signal.aborted ? 'time_limit' : 'network_error'};
  } finally {
    if (reader) await reader.cancel().catch(() => {});
    abort.abort(); clearTimeout(timer);
  }
}"""


class Response:
    def __init__(self, status, headers, body):
        self.status_code, self.headers, self.body = status, CaseInsensitiveDict(headers), body

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]

    def close(self):
        self.body = b''


def decode_response(result, limit):
    code = result.get('error_code')
    if code in ('access_challenge', 'size_limit', 'time_limit', 'network_error'):
        raise SourceError('Official browser request could not be verified', code)
    if result.get('status') not in range(200, 600):
        raise SourceError('Invalid browser response status', 'invalid_response')
    encoded = result.get('body', '')
    if not isinstance(encoded, str) or len(encoded) > 4 * ((limit + 2) // 3):
        raise SourceError('Official browser response exceeds byte limit', 'size_limit')
    try:
        body = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise SourceError('Invalid browser response encoding', 'invalid_response') from error
    if len(body) > limit:
        raise SourceError('Official browser response exceeds byte limit', 'size_limit')
    return Response(result['status'], result.get('headers', {}), body)


def remaining(deadline):
    milliseconds = int((deadline - time.monotonic()) * 1000)
    if milliseconds < 1:
        raise SourceError('Official browser request exceeded time budget', 'time_limit')
    return milliseconds


class Browser:
    def __init__(self, deadline):
        from playwright.sync_api import sync_playwright
        answers = socket.getaddrinfo('www.carm.es', 443, type=socket.SOCK_STREAM)
        addresses = [ipaddress.ip_address(answer[4][0]) for answer in answers]
        if not addresses or any(not address.is_global for address in addresses):
            raise SourceError('Official browser DNS is not public', 'private_address')
        address = next((a for a in addresses if a.version == 4), addresses[0])
        pin = str(address) if address.version == 4 else f'[{address}]'
        self.driver = sync_playwright().start()
        self.browser = None
        try:
            self.browser = self.driver.chromium.launch(headless=False, channel='chromium',
                timeout=remaining(deadline), args=['--no-proxy-server',
                    f'--host-resolver-rules=MAP www.carm.es {pin}, MAP * ~NOTFOUND'])
            self.context = self.browser.new_context(service_workers='block', accept_downloads=False)
            self.page = self.context.new_page()
            self.bootstrap = 'https://www.carm.es/__bolsa_abierta_origin_' + uuid.uuid4().hex
            self.bootstrapping = True
            self.context.route('**/*', self.route)
            self.page.goto(self.bootstrap, wait_until='domcontentloaded', timeout=remaining(deadline))
            self.bootstrapping = False
        except Exception:
            self.close()
            raise

    def route(self, route):
        request = route.request
        if self.bootstrapping and request.url == self.bootstrap and request.is_navigation_request():
            route.fulfill(status=200, content_type='text/html', body='<!doctype html><title>Source transport</title>')
            return
        try:
            url = _allowed_url(request.url)
            allowed = (url.scheme == 'https' and url.hostname == 'www.carm.es'
                       and request.method == 'GET' and request.resource_type == 'fetch'
                       and not request.is_navigation_request())
        except SourceError:
            allowed = False
        route.continue_() if allowed else route.abort('blockedbyclient')

    def close(self):
        if self.browser:
            self.browser.close()
        self.driver.stop()


_local = threading.local()


def browser_get(url, *, headers, limit, deadline):
    value = _allowed_url(url)
    if value.scheme != 'https' or value.hostname != 'www.carm.es':
        raise SourceError('URL is outside browser transport scope', 'forbidden_url')
    try:
        browser = getattr(_local, 'browser', None)
        if browser is None:
            browser = _local.browser = Browser(deadline)
            atexit.register(browser.close)
        # Chromium supplies its own genuine browser headers. No UA spoofing,
        # imported cookies, CAPTCHA solving or third-party proxy is involved.
        result = browser.page.evaluate(FETCH, {'url': url,
            'headers': {k: v for k, v in headers.items() if k.lower() in ('accept', 'if-none-match')},
            'limit': limit, 'milliseconds': remaining(deadline)})
        remaining(deadline)
        return decode_response(result, limit)
    except SourceError:
        raise
    except Exception as error:
        # Dependency/setup failures are operational failures; do not conceal them
        # as a source outage, nor log arbitrary browser/page output.
        from playwright.sync_api import TimeoutError as BrowserTimeout, Error as BrowserError
        if isinstance(error, BrowserTimeout):
            raise SourceError('Official browser request timed out', 'time_limit') from error
        if isinstance(error, BrowserError) and getattr(_local, 'browser', None):
            raise SourceError('Official browser request failed', 'network_error') from error
        raise RuntimeError('Official browser transport could not start') from error
