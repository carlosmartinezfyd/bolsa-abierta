"""Bounded official-source discovery. A successful HTTP status is not evidence validity."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import time
import unicodedata
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import requests


ALLOWED_HOSTS = frozenset({'rrhheducacion.carm.es', 'www.carm.es'})
FEED_URL = 'https://rrhheducacion.carm.es/feed/'
INDEX_URL = 'https://rrhheducacion.carm.es/servicio-de-personal-docente/'
KNOWN_ANNOUNCEMENTS = ({
    'url': 'https://rrhheducacion.carm.es/30-09-2026-relacion-de-vacantes-sin-cubrir-secundaria-y-otros-cuerpos/',
    'title': '30/09/2026-Relación de vacantes sin cubrir Secundaria y otros cuerpos',
    'date': '2026-09-30', 'kind': 'vacancies', 'pdf_urls': [],
},)
MAX_ANNOUNCEMENTS = 20
DISCOVERY_SECONDS = 120
TRANSIENT_SOURCE_ERRORS = frozenset(('access_challenge', 'dns_error', 'network_error',
                                    'temporary_http', 'timeout', 'time_limit'))


class SourceError(Exception):
    def __init__(self, message, code='source_error'):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    body: bytes
    content_type: str
    status: int
    headers: dict


def _allowed_url(url):
    try:
        value = urlsplit(url)
        allowed = (value.scheme in ('http', 'https') and value.hostname in ALLOWED_HOSTS
                   and not value.username and not value.password
                   and value.port in (None, 80 if value.scheme == 'http' else 443)
                   and not any(ord(c) < 32 for c in url) and '\\' not in url)
    except (ValueError, TypeError):
        allowed = False
    if not allowed:
        raise SourceError('URL is outside configured official origins', 'forbidden_url')
    return value


def canonical_url(url):
    """Stable identity only; fetch/archive the original URL without rewriting queries."""
    value = _allowed_url(url)
    query = urlencode(sorted(parse_qsl(value.query, keep_blank_values=True)))
    host = value.hostname
    return urlunsplit((value.scheme.lower(), host, value.path or '/', query, ''))


def _identity(url):
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()


def _fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text).lower()
                   if not unicodedata.combining(c))


def _challenge(body):
    text = body[:256_000].decode('utf-8', errors='replace').lower()
    return any(marker in text for marker in (
        'cf-chl-', 'challenges.cloudflare.com', 'verifying your browser',
        'verify you are human', 'checking your browser', 'just a moment',
        'captcha.perfdrive.com', 'radware captcha page', 'verificacion de seguridad',
        'verificación de seguridad', 'incapsula', 'challenge-platform',
    ))


class OfficialClient:
    """Only configured hosts, each hop DNS checked, bounded stream and retries.

    Environment proxies are disabled for the default session so public-host checks
    cannot silently send an otherwise approved URL through an internal proxy.
    """
    def __init__(self, session=None, *, resolver=None, sleep=None, max_html_bytes=2_000_000,
                 max_pdf_bytes=12_000_000, timeout=(4, 8), max_seconds=30,
                 max_redirects=4, retries=1, retry_state=None, clock=None, carm_interval=None):
        self.session = session if session is not None else requests.Session()
        self.session.trust_env = False
        self.resolver = resolver or socket.getaddrinfo
        self.sleep = sleep or time.sleep
        self.max_html_bytes = max_html_bytes
        self.max_pdf_bytes = max_pdf_bytes
        self.timeout = timeout
        self.max_seconds = max_seconds
        self.max_redirects = max_redirects
        self.retries = min(max(retries, 0), 2)
        self.retry_state = retry_state or os.environ.get('SOURCE_RETRY_STATE')
        self.clock = clock or time.time
        self.carm_interval = float(os.environ.get('CARM_MIN_REQUEST_INTERVAL', '0')
                                   if carm_interval is None else carm_interval)
        if not math.isfinite(self.carm_interval) or not 0 <= self.carm_interval <= 10:
            raise ValueError('Invalid CARM request interval')
        self._next_carm_request = 0

    def _pace_request(self, url, deadline):
        if _allowed_url(url).hostname != 'www.carm.es' or not self.carm_interval:
            return
        now = time.monotonic()
        delay = max(0, self._next_carm_request - now)
        if now + delay >= deadline:
            raise SourceError('Official request pacing exceeded time budget', 'time_limit')
        if delay:
            self.sleep(delay)
        self._next_carm_request = time.monotonic() + self.carm_interval

    def _browser_transport(self, url):
        value = _allowed_url(url)
        return (os.environ.get('OFFICIAL_SOURCE_TRANSPORT') == 'chromium'
                and value.scheme == 'https' and value.hostname == 'www.carm.es')

    def _retry_identity(self, url, kind, browser=False):
        return hashlib.sha256((('chromium:' if browser else '') + kind + ':' + canonical_url(url)).encode()).hexdigest()

    def _retry_entries(self):
        path = Path(self.retry_state)
        entries = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not isinstance(entries, dict) or len(entries) > 4096:
            raise ValueError('invalid_source_retry_state')
        for identity, entry in entries.items():
            if (not re.fullmatch('[a-f0-9]{64}', identity) or not isinstance(entry, dict)
                    or entry.get('error_code') not in TRANSIENT_SOURCE_ERRORS
                    or type(entry.get('failures')) is not int or not 1 <= entry['failures'] <= 5
                    or type(entry.get('next_attempt_at')) not in (int, float)
                    or not 0 <= entry['next_attempt_at'] <= 253402300799):
                raise ValueError('invalid_source_retry_state')
        return entries

    def check_retry(self, url, kind='html'):
        """Per-resource cooldown; never infer that another URL is inaccessible."""
        if not self.retry_state:
            return
        entries = self._retry_entries()
        browser = self._browser_transport(url)
        for scope in (False, True) if browser else (False,):
            entry = entries.get(self._retry_identity(url, kind, scope))
            if browser and not scope and entry and entry['error_code'] == 'access_challenge':
                continue  # A rejected HTTP client is not evidence against Chromium.
            if entry and entry['next_attempt_at'] > self.clock():
                error = SourceError('Official resource is awaiting its next retry', entry['error_code'])
                error.retry_deferred = True
                raise error

    def fetch(self, url, *, kind='html', etag=None):
        self.check_retry(url, kind)
        try:
            result = self._fetch(url, kind=kind, etag=etag)
        except SourceError as error:
            if error.code in TRANSIENT_SOURCE_ERRORS:
                self._save_retry(url, kind, error.code, getattr(error, 'retry_after', 0))
            raise
        self._save_retry(url, kind, None)
        return result

    def _save_retry(self, url, kind, error_code, retry_after=0):
        if not self.retry_state:
            return
        from .store import atomic_write
        entries = self._retry_entries()
        browser = self._browser_transport(url)
        identity = self._retry_identity(url, kind, browser and error_code == 'access_challenge')
        failures = min(5, entries.get(identity, {}).get('failures', 0) + 1)
        # Prune old failures, retaining only opaque identities and fixed codes.
        entries = {k: v for k, v in entries.items() if v['next_attempt_at'] > self.clock() - 7 * 86400}
        if error_code:
            entries[identity] = {'error_code': error_code, 'failures': failures,
                'next_attempt_at': self.clock() + max(retry_after, min(21600, 3600 * 2 ** (failures - 1)))}
        else:
            entries.pop(identity, None)
            if browser:
                entries.pop(self._retry_identity(url, kind, True), None)
        if len(entries) > 4096:
            raise ValueError('source_retry_capacity_exceeded')
        atomic_write(Path(self.retry_state), (json.dumps(entries, sort_keys=True) + '\n').encode())

    def _validate_dns(self, url):
        value = _allowed_url(url)
        try:
            answers = self.resolver(value.hostname, value.port or (443 if value.scheme == 'https' else 80),
                                    type=socket.SOCK_STREAM)
        except OSError as error:
            raise SourceError('Official origin DNS lookup failed', 'dns_error') from error
        if not answers:
            raise SourceError('Official origin has no DNS addresses', 'dns_error')
        for answer in answers:
            try:
                address = ipaddress.ip_address(answer[4][0])
            except ValueError as error:
                raise SourceError('Official origin returned an invalid DNS address', 'dns_error') from error
            if not address.is_global:
                raise SourceError('Official origin resolved to a non-public address', 'private_address')

    def _fetch(self, url, *, kind='html', etag=None):
        if kind not in ('html', 'pdf', 'rss'):
            raise ValueError('Unsupported fetch kind')
        _allowed_url(url)
        deadline = time.monotonic() + self.max_seconds
        limit = self.max_pdf_bytes if kind == 'pdf' else self.max_html_bytes
        request_headers = {'User-Agent': 'BolsaAbierta/1.0 (official publication monitor)',
                           'Accept': 'application/pdf' if kind == 'pdf' else 'text/html,application/rss+xml,application/xml'}
        if etag:
            request_headers['If-None-Match'] = etag
        for attempt in range(self.retries + 1):
            current = url
            retry_delay = 1
            try:
                for hop in range(self.max_redirects + 1):
                    if time.monotonic() >= deadline:
                        raise SourceError('Official request exceeded time budget', 'time_limit')
                    self._validate_dns(current)
                    self._pace_request(current, deadline)
                    remaining = max(0.1, deadline - time.monotonic())
                    # A validator belongs to one URL, including its pagination
                    # query; even an official redirect cannot transfer it.
                    scoped_headers = dict(request_headers)
                    if canonical_url(current) != canonical_url(url):
                        scoped_headers.pop('If-None-Match', None)
                    if self._browser_transport(current):
                        from .browser_source import browser_get
                        response = browser_get(current, headers=scoped_headers, limit=limit, deadline=deadline)
                    else:
                        response = self.session.get(current, headers=scoped_headers,
                                                    timeout=tuple(min(v, remaining) for v in self.timeout),
                                                    allow_redirects=False, stream=True)
                    try:
                        status = response.status_code
                        headers = dict(response.headers)
                        if status in (301, 302, 303, 307, 308):
                            if hop == self.max_redirects:
                                raise SourceError('Official request exceeded redirect budget', 'redirect_limit')
                            location = response.headers.get('Location')
                            if not location:
                                raise SourceError('Official redirect has no destination', 'invalid_redirect')
                            current = urljoin(current, location)
                            if urlsplit(current).hostname in ('validate.perfdrive.com', 'captcha.perfdrive.com'):
                                raise SourceError('Official origin requires browser verification', 'access_challenge')
                            _allowed_url(current)
                            continue
                        if status == 304:
                            if not scoped_headers.get('If-None-Match'):
                                raise SourceError('Unconditional response unexpectedly returned 304', 'http_error')
                            return FetchResult(url, current, b'', '', status, headers)
                        if status in (429, 500, 502, 503, 504):
                            retry_after = response.headers.get('Retry-After', '')
                            # A long cooldown is a failure for this run, not permission to retry early.
                            if retry_after:
                                try:
                                    retry_delay = max(1, int(retry_after))
                                except ValueError:
                                    try:
                                        retry_delay = max(1, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                                    except (ValueError, TypeError):
                                        retry_delay = self.max_seconds
                            error = SourceError(f'Official origin returned HTTP {status}', 'temporary_http')
                            error.retry_after = retry_delay
                            raise error
                        if status != 200:
                            raise SourceError(f'Official origin returned HTTP {status}', 'http_error')
                        length = response.headers.get('Content-Length')
                        if length:
                            try:
                                if int(length) > limit:
                                    raise SourceError('Official response exceeds byte limit', 'size_limit')
                            except ValueError:
                                raise SourceError('Invalid official content length', 'invalid_response')
                        chunks, size = [], 0
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            if time.monotonic() >= deadline:
                                raise SourceError('Official download exceeded time budget', 'time_limit')
                            size += len(chunk)
                            if size > limit:
                                raise SourceError('Official response exceeds byte limit', 'size_limit')
                            chunks.append(chunk)
                        body = b''.join(chunks)
                        content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                        if _challenge(body):
                            raise SourceError('Official origin requires browser verification', 'access_challenge')
                        if kind == 'pdf':
                            if not body.startswith(b'%PDF-') or content_type != 'application/pdf':
                                raise SourceError('Official PDF URL returned non-PDF content', 'invalid_pdf')
                        elif not body.strip() or content_type not in ('text/html', 'application/xhtml+xml', 'application/rss+xml', 'application/xml', 'text/xml'):
                            raise SourceError('Official page has empty or unsupported content', 'invalid_response')
                        return FetchResult(url, current, body, content_type, status, headers)
                    finally:
                        response.close()
            except requests.RequestException as error:
                failure = SourceError('Official request failed: ' + type(error).__name__, 'network_error')
            except SourceError as error:
                if error.code != 'temporary_http':
                    raise
                failure = error
            if attempt == self.retries or time.monotonic() + retry_delay >= deadline:
                raise failure
            self.sleep(retry_delay)
        raise SourceError('Official request failed', 'network_error')


def _date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if len(value) == 10:
            return parsed.date().isoformat()
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        pass
    match = re.search(r'(\d{2})[/-](\d{2})[/-](20\d{2})', value)
    if match:
        try:
            return datetime(int(match[3]), int(match[2]), int(match[1])).date().isoformat()
        except ValueError:
            pass
    return None


def _vacancies(title):
    value = _fold(title).replace('-', ' ')
    return (bool(re.search(r'\b(relacion|listado)\b', value))
            and 'vacantes sin cubrir' in value and 'secundaria' in value
            and 'otros cuerpos' in value)


def _recent(date, now):
    if not date:
        return False
    try:
        return (now - timedelta(days=14)).date() <= datetime.fromisoformat(date).date() <= now.date()
    except (ValueError, TypeError):
        return False


def _pdf_link(url):
    value = urlsplit(url)
    return value.path.lower().endswith('.pdf') or any('.pdf' in v.lower() for _, v in parse_qsl(value.query))


def _notice(url, title, date=None, **extra):
    return {'id': _identity(url), 'url': url, 'title': title.strip(), 'date': date,
            'pdf_urls': [], 'kind': 'vacancies' if _vacancies(title) else 'announcement', **extra}


def _feed_notices(body):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise SourceError('Feed declares unsupported XML entities', 'invalid_feed')
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise SourceError('Official RSS is malformed', 'invalid_feed') from error
    if root.tag != 'rss' or root.find('channel') is None:
        raise SourceError('Official feed is not RSS', 'invalid_feed')
    notices = []
    items = root.findall('./channel/item')
    if not items:
        raise SourceError('Official RSS has no expected publication entries', 'invalid_feed')
    for item in items[:200]:
        url, title = item.findtext('link'), item.findtext('title')
        if not url or not title:
            raise SourceError('Official RSS entry has no title or link', 'invalid_feed')
        try:
            _allowed_url(url)
        except SourceError:
            continue
        notices.append(_notice(url, title, _date(item.findtext('pubDate'))))
    return notices


def _html_notices(body, base):
    soup = BeautifulSoup(body, 'html.parser')
    content = soup.select_one('.eael-post-grid-container')
    if not content or 'servicio de personal docente' not in _fold(soup.get_text(' ', strip=True)):
        raise SourceError('Official index does not match the expected publication template', 'invalid_index')
    notices = []
    for anchor in content.select('a[href]'):
        url = urljoin(base, anchor['href'])
        title = anchor.get_text(' ', strip=True)
        try:
            value = _allowed_url(url)
        except SourceError:
            continue
        if (value.hostname != 'rrhheducacion.carm.es' or not title
                or any(part in value.path for part in ('/feed', '/author/', '/category/', '/tag/', '/wp-', '/comment'))
                or _pdf_link(url) or canonical_url(url) in (canonical_url(FEED_URL), canonical_url(INDEX_URL))):
            continue
        date = _date(title) or _date(value.path)
        if date or _vacancies(title):
            notices.append(_notice(url, title, date))
    if not notices:
        raise SourceError('Official index contains no expected announcements', 'invalid_index')
    return notices


def _announcement(body, notice, base):
    soup = BeautifulSoup(body, 'html.parser')
    heading = soup.select_one('h1')
    if heading:
        notice['title'] = heading.get_text(' ', strip=True)
    if not soup.get_text(strip=True):
        raise SourceError('Official announcement is empty', 'invalid_announcement')
    # Publication time is independent of the listing date in the title or PDF.
    published = soup.select_one('meta[property="article:published_time"], time[datetime]')
    date = _date(published.get('content') or published.get('datetime')) if published else None
    if not date:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or script.get_text())
                objects = data if isinstance(data, list) else data.get('@graph', [data])
                date = next((_date(obj.get('datePublished')) for obj in objects
                             if isinstance(obj, dict) and _date(obj.get('datePublished'))), None)
            except (ValueError, TypeError, AttributeError):
                continue
            if date:
                break
    if date:
        notice['date'] = date
    notice['kind'] = 'vacancies' if _vacancies(notice['title']) else 'announcement'
    urls = {}
    if notice['kind'] == 'vacancies':
        content = soup.select_one('.elementor-widget-theme-post-content, .entry-content, article') or soup
        for anchor in content.select('a[href]'):
            url = urljoin(base, anchor['href'])
            try:
                if _pdf_link(url):
                    urls.setdefault(canonical_url(url), url)
            except SourceError:
                continue
        if not urls:
            raise SourceError('Official vacancy announcement has no downloadable PDF', 'missing_pdf')
    notice['pdf_urls'] = list(urls.values())
    notice.pop('error', None)
    notice.pop('error_code', None)


def discover_notices(client, known_notices=()):
    """Discover candidates without fetching PDF bytes; failures never erase inventory."""
    now = datetime.now(timezone.utc)
    deadline = time.monotonic() + DISCOVERY_SECONDS
    inventory, checks, known_ids = {}, [], set()
    complete = True

    def merge(notice):
        key = _identity(notice['url'])
        previous = inventory.get(key)
        if previous:
            new_date = notice.get('date')
            if new_date and (not previous.get('date') or (len(previous['date']) == 10 and len(new_date) > 10)):
                previous['date'] = new_date
            if notice.get('pdf_urls'):
                previous['pdf_urls'] = notice['pdf_urls']
        else:
            inventory[key] = {**notice, 'id': key}

    for notice in known_notices:
        try:
            if notice.get('url'):
                known_ids.add(_identity(notice['url']))
                merge({**notice, **_notice(notice['url'], notice.get('title', ''), _date(notice.get('date')),
                                          pdf_urls=list(notice.get('pdf_urls') or []))})
        except (SourceError, AttributeError):
            continue
    for notice in KNOWN_ANNOUNCEMENTS:
        try:
            if notice.get('url'):
                merge(_notice(notice['url'], notice.get('title', ''), _date(notice.get('date')),
                              pdf_urls=list(notice.get('pdf_urls') or [])))
        except (SourceError, AttributeError):
            continue

    def check(url, operation, kind='html'):
        nonlocal complete
        entry = {'id': _identity(url), 'url': url, 'checked_at': datetime.now(timezone.utc).isoformat(),
                 'success': False, 'status': 'failed', 'error': None, 'error_code': None}
        try:
            if time.monotonic() >= deadline:
                raise SourceError('Discovery exceeded time budget', 'time_limit')
            result = client.fetch(url, kind=kind)
            operation(result)
            entry.update(success=True, status='ok', http_status=result.status, final_url=result.final_url)
        except SourceError as error:
            entry.update(error=str(error), error_code=error.code)
            complete = False
        checks.append(entry)
        return entry

    check(FEED_URL, lambda result: [merge(n) for n in _feed_notices(result.body)], kind='rss')
    check(INDEX_URL, lambda result: [merge(n) for n in _html_notices(result.body, result.final_url)])
    for notice in inventory.values():
        # Check overlapping recent publications and newly discovered evidence once.
        # Retained older inventory is outside this run's announced 14-day scope.
        notice['should_check'] = (_recent(notice['date'], now) or not notice['date'] or notice['id'] not in known_ids)
    candidates = [n for n in inventory.values() if n['should_check']]
    candidates.sort(key=lambda n: (n['kind'] != 'vacancies', -(datetime.fromisoformat(n['date']).date().toordinal() if n.get('date') else 0), n['id']))
    for offset, notice in enumerate(candidates):
        if offset >= MAX_ANNOUNCEMENTS:
            complete = False
            notice.update(error='Announcement read budget exceeded', error_code='discovery_limit')
            continue
        if _pdf_link(notice['url']):
            # RSS may point straight to an original PDF. Pipeline downloads it once.
            notice['pdf_urls'] = [notice['url']] if notice['kind'] == 'vacancies' else []
            continue
        entry = check(notice['url'], lambda result: _announcement(result.body, notice, result.final_url))
        if not entry['success']:
            notice.update(error=entry['error'], error_code=entry['error_code'])
    return {'notices': list(inventory.values()), 'checks': checks, 'complete': complete}
