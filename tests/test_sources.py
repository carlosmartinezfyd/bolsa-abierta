import socket
import unittest
from unittest.mock import Mock

import requests

from bolsa_abierta.sources import (
    FEED_URL, INDEX_URL, OfficialClient, SourceError, FetchResult,
    canonical_url, discover_notices,
)


NOTICE_URL = 'https://rrhheducacion.carm.es/30-09-2026-relacion-de-vacantes-sin-cubrir-secundaria-y-otros-cuerpos/'
TITLE = '30/09/2026-Relación de vacantes sin cubrir Secundaria y otros cuerpos'
PDF_URL = 'https://www.carm.es/documentos?ID=123&ARCHIVO=vacantes.pdf'


def response(body=b'<html><body>Official page</body></html>', status=200, headers=None):
    result = Mock(status_code=status, headers=headers or {'Content-Type': 'text/html'})
    result.iter_content.return_value = iter([body])
    return result


def public_dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', port))]


class ClientTests(unittest.TestCase):
    def client(self, responses, **kwargs):
        session = Mock()
        session.get.side_effect = responses
        return OfficialClient(session=session, resolver=public_dns, sleep=lambda _: None, **kwargs), session

    def test_pdf_magic_and_raw_headers_preserved(self):
        client, session = self.client([response(b'%PDF-1.7\nbytes', headers={'Content-Type': 'application/pdf', 'ETag': 'abc'})])
        result = client.fetch(PDF_URL, kind='pdf')
        self.assertEqual(result.body, b'%PDF-1.7\nbytes')
        self.assertEqual(result.headers['ETag'], 'abc')
        self.assertEqual(result.url, PDF_URL)
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])

    def test_html_challenge_is_not_pdf_even_200_and_is_not_retried(self):
        client, session = self.client([response(b'<html>Verifying your browser <script src="/challenge.js"></script></html>')])
        with self.assertRaises(SourceError) as caught:
            client.fetch(PDF_URL, kind='pdf')
        self.assertEqual(caught.exception.code, 'access_challenge')
        self.assertEqual(session.get.call_count, 1)

    def test_official_html_challenge_is_rejected(self):
        client, _ = self.client([response(b'<html><title>Just a moment...</title>cf-chl-platform</html>')])
        with self.assertRaisesRegex(SourceError, 'verification'):
            client.fetch(INDEX_URL)

    def test_legitimate_page_newsletter_captcha_error_string_is_not_challenge(self):
        body = b'<html><h1>Servicio de Personal Docente</h1><script>var messages={"elp_invalid_captcha":"Robot verification failed"};</script><p>Official announcement</p></html>'
        client, _ = self.client([response(body)])
        self.assertEqual(client.fetch(INDEX_URL).body, body)

    def test_radware_captcha_page_is_access_challenge(self):
        body = b'<html><head><title>Radware Captcha Page</title><link href="https://captcha.perfdrive.com/captcha-public/css/style.css"></head></html>'
        client, _ = self.client([response(body)])
        with self.assertRaises(SourceError) as caught:
            client.fetch(PDF_URL, kind='pdf')
        self.assertEqual(caught.exception.code, 'access_challenge')

    def test_pdf_mime_and_magic_required(self):
        for body, mime in [(b'<html>No</html>', 'application/pdf'), (b'%PDF-1.7 bytes', 'text/html')]:
            client, _ = self.client([response(body, headers={'Content-Type': mime})])
            with self.assertRaises(SourceError) as caught:
                client.fetch(PDF_URL, kind='pdf')
            self.assertEqual(caught.exception.code, 'invalid_pdf')

    def test_redirect_cannot_escape_allowlist(self):
        client, session = self.client([response(status=302, headers={'Location': 'http://127.0.0.1/x'})])
        with self.assertRaises(SourceError) as caught:
            client.fetch(INDEX_URL)
        self.assertEqual(caught.exception.code, 'forbidden_url')
        self.assertEqual(session.get.call_count, 1)

    def test_all_dns_answers_must_be_public_and_redirect_revalidates_dns(self):
        client, session = self.client([response(status=302, headers={'Location': PDF_URL})])
        client.resolver = Mock(side_effect=[public_dns('', 443), [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', 443))]])
        with self.assertRaises(SourceError) as caught:
            client.fetch(INDEX_URL)
        self.assertEqual(caught.exception.code, 'private_address')
        self.assertEqual(session.get.call_count, 1)

    def test_size_limit_closes_response(self):
        item = response(b'x' * 11)
        client, _ = self.client([item], max_html_bytes=10)
        with self.assertRaises(SourceError) as caught:
            client.fetch(INDEX_URL)
        self.assertEqual(caught.exception.code, 'size_limit')
        item.close.assert_called_once()

    def test_retry_bound_and_timeout(self):
        client, session = self.client([requests.Timeout('slow'), requests.Timeout('slow')])
        with self.assertRaises(SourceError) as caught:
            client.fetch(INDEX_URL)
        self.assertEqual(caught.exception.code, 'network_error')
        self.assertEqual(session.get.call_count, 2)

    def test_conditional_304_does_not_pretend_to_have_bytes(self):
        client, session = self.client([response(b'', status=304)])
        result = client.fetch(PDF_URL, kind='pdf', etag='old')
        self.assertEqual(result.status, 304)
        self.assertEqual(result.body, b'')
        self.assertEqual(session.get.call_args.kwargs['headers']['If-None-Match'], 'old')

    def test_unsafe_urls_rejected_before_http(self):
        for url in ['https://rrhheducacion.carm.es.evil.org/a', 'file:///etc/passwd', 'https://user@www.carm.es/a', 'https://www.carm.es:8443/a']:
            client, session = self.client([])
            with self.assertRaises(SourceError):
                client.fetch(url)
            session.get.assert_not_called()

    def test_allowed_redirect_dns_is_checked_and_raw_query_kept(self):
        client, session = self.client([response(status=302, headers={'Location': PDF_URL}), response(b'%PDF-1.7\n', headers={'Content-Type':'application/pdf'})])
        client.resolver = Mock(side_effect=public_dns)
        result = client.fetch(INDEX_URL, kind='pdf')
        self.assertEqual(result.final_url, PDF_URL)
        self.assertEqual(session.get.call_args.args[0], PDF_URL)
        self.assertEqual(client.resolver.call_count, 2)

    def test_retry_after_long_cooldown_is_respected_without_sleeping(self):
        client, session = self.client([response(status=429, headers={'Retry-After':'3600'})])
        client.sleep = Mock()
        with self.assertRaises(SourceError):
            client.fetch(INDEX_URL)
        client.sleep.assert_not_called()
        self.assertEqual(session.get.call_count, 1)

    def test_mixed_public_and_private_dns_fails_before_fetch(self):
        client, session = self.client([])
        client.resolver = lambda *a, **k: public_dns('', 443) + [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1', 443))]
        with self.assertRaises(SourceError):
            client.fetch(INDEX_URL)
        session.get.assert_not_called()


class DiscoveryTests(unittest.TestCase):
    def client(self, mapping):
        client = Mock()
        def fetch(url, **kwargs):
            value = mapping.get(url, SourceError('unavailable', 'network_error'))
            if isinstance(value, Exception):
                raise value
            return FetchResult(url, url, value.encode(), 'text/html', 200, {})
        client.fetch.side_effect = fetch
        return client

    def roots(self, feed='', index=''):
        default_feed = f'<rss><channel><item><title>{TITLE}</title><link>{NOTICE_URL}</link><pubDate>Wed, 30 Sep 2026 14:45:42 +0000</pubDate></item></channel></rss>'
        content = index or f'<a href="{NOTICE_URL}">{TITLE}</a>'
        return {FEED_URL:feed or default_feed, INDEX_URL:f'<html><title>Servicio de Personal Docente</title><div class="eael-post-grid-container">{content}</div></html>'}

    def test_rss_index_merge_keep_announced_date_and_only_vacancies_get_pdfs(self):
        feed = f'<rss><channel><item><title>{TITLE}</title><link>{NOTICE_URL}</link><pubDate>Wed, 30 Sep 2026 14:45:42 +0000</pubDate></item><item><title>Convocatoria urgente de interinos Secundaria</title><link>https://rrhheducacion.carm.es/urgente/</link><pubDate>Wed, 30 Sep 2026 15:00:00 +0000</pubDate></item></channel></rss>'
        mapping = self.roots(feed, f'<a href="{NOTICE_URL}">{TITLE}</a>')
        mapping[NOTICE_URL] = f'<html><h1>{TITLE}</h1><a href="{PDF_URL.replace("&", "&amp;")}">Relación de vacantes</a></html>'
        mapping['https://rrhheducacion.carm.es/urgente/'] = f'<h1>Convocatoria urgente de interinos Secundaria</h1><a href="{PDF_URL}">Descargar</a>'
        result = discover_notices(self.client(mapping))
        vacancies = [n for n in result['notices'] if n['kind'] == 'vacancies']
        self.assertEqual(len(vacancies), 1)
        self.assertEqual(vacancies[0]['pdf_urls'], [PDF_URL])
        self.assertEqual(vacancies[0]['date'], '2026-09-30T14:45:42+00:00')
        other = [n for n in result['notices'] if n['kind'] == 'announcement'][0]
        self.assertEqual(other['pdf_urls'], [])
        self.assertTrue(result['complete'])

    def test_failed_page_retains_known_notice_and_prior_links(self):
        known = {'id':'old', 'url':NOTICE_URL, 'title':TITLE, 'date':'2026-09-30', 'kind':'vacancies', 'pdf_urls':[PDF_URL]}
        result = discover_notices(self.client(self.roots()), [known])
        self.assertFalse(result['complete'])
        notice = next(n for n in result['notices'] if n['url'] == NOTICE_URL)
        self.assertEqual(notice['pdf_urls'], [PDF_URL])
        self.assertEqual(notice['error_code'], 'network_error')
        self.assertTrue(any(not c['success'] for c in result['checks']))

    def test_malformed_feed_and_empty_html_are_partial(self):
        result = discover_notices(self.client(self.roots('<rss><broken>', '<html></html>')))
        self.assertFalse(result['complete'])
        self.assertTrue(any(c['error_code'] == 'invalid_feed' for c in result['checks']))

    def test_empty_feed_and_200_maintenance_page_cannot_advance_complete_success(self):
        mapping = {FEED_URL:'<rss><channel></channel></rss>', INDEX_URL:'<html><h1>Maintenance</h1><p>Please try again.</p></html>',
                   NOTICE_URL:f'<h1>{TITLE}</h1><a href="{PDF_URL}">Listado</a>'}
        result = discover_notices(self.client(mapping))
        self.assertFalse(result['complete'])
        roots = {c['url']:c for c in result['checks']}
        self.assertEqual(roots[FEED_URL]['error_code'], 'invalid_feed')
        self.assertEqual(roots[INDEX_URL]['error_code'], 'invalid_index')

    def test_no_generic_vacancies_or_primary_titles_can_be_parsed(self):
        titles = ['Relación de vacantes sin cubrir Maestros', 'Convocatoria urgente para cubrir vacantes Secundaria', 'Resultados de adjudicación Secundaria']
        index = ''.join(f'<a href="https://rrhheducacion.carm.es/30-09-2026-{i}/">30/09/2026 {t}</a>' for i, t in enumerate(titles))
        mapping = self.roots(index=index)
        for i, title in enumerate(titles):
            mapping[f'https://rrhheducacion.carm.es/30-09-2026-{i}/'] = f'<h1>{title}</h1><a href="{PDF_URL}">PDF</a>'
        result = discover_notices(self.client(mapping))
        self.assertFalse(any(n['kind'] == 'vacancies' for n in result['notices'] if n['url'] != NOTICE_URL))

    def test_query_order_identity_preserves_fetch_url(self):
        self.assertEqual(canonical_url('https://www.carm.es/x?b=2&a=1#part'), canonical_url('https://www.carm.es/x?a=1&b=2'))

    def test_direct_pdf_feed_candidate_is_preserved_without_html_request(self):
        feed = f'<rss><channel><item><title>{TITLE}</title><link>{PDF_URL.replace("&", "&amp;")}</link><pubDate>Wed, 30 Sep 2026 14:45:42 +0000</pubDate></item></channel></rss>'
        client = self.client(self.roots(feed))
        result = discover_notices(client)
        direct = next(n for n in result['notices'] if n['url'] == PDF_URL)
        self.assertEqual(direct['pdf_urls'], [PDF_URL])
        self.assertFalse(any(c.args[0] == PDF_URL for c in client.fetch.call_args_list))

    def test_html_publication_timestamp_and_body_scope(self):
        mapping = self.roots()
        mapping[NOTICE_URL] = f'<html><h1>{TITLE}</h1><script type="application/ld+json">{{"@graph":[{{"datePublished":"2026-09-30T16:45:42+02:00"}}]}}</script><article><a href="{PDF_URL}">Listado</a></article><footer><a href="https://www.carm.es/other.pdf">Other</a></footer></html>'
        result = discover_notices(self.client(mapping))
        notice = next(n for n in result['notices'] if n['url'] == NOTICE_URL)
        self.assertEqual(notice['date'], '2026-09-30T14:45:42+00:00')
        self.assertEqual(notice['pdf_urls'], [PDF_URL])

    def test_new_announcement_without_pdf_is_retained_as_partial(self):
        mapping = self.roots(index=f'<a href="{NOTICE_URL}">{TITLE}</a>')
        mapping[NOTICE_URL] = f'<html><h1>{TITLE}</h1><p>Unavailable</p></html>'
        result = discover_notices(self.client(mapping))
        notice = next(n for n in result['notices'] if n['url'] == NOTICE_URL)
        self.assertFalse(result['complete'])
        self.assertEqual(notice['error_code'], 'missing_pdf')

    def test_read_budget_and_skip_comment_feeds(self):
        index = ''.join(f'<a href="https://rrhheducacion.carm.es/30-09-2026-{i}/">30/09/2026 {TITLE}</a>' for i in range(30))
        index += f'<a href="{NOTICE_URL}feed/">30/09/2026 {TITLE}</a>'
        mapping = self.roots(index=index)
        client = self.client(mapping)
        result = discover_notices(client)
        self.assertLessEqual(client.fetch.call_count, 22)
        self.assertFalse(any('/feed/' in c.args[0] and c.args[0] != FEED_URL for c in client.fetch.call_args_list))
        self.assertFalse(result['complete'])

    def test_21_known_old_vacancies_keep_metadata_without_consuming_read_budget(self):
        known = [{'url':f'https://rrhheducacion.carm.es/01-01-2025-old-{i}/',
                  'title':TITLE, 'date':'2025-01-01', 'pdf_urls':[PDF_URL],
                  'document_id':f'doc-{i}', 'status':'incorporated', 'hash':'retained'} for i in range(21)]
        mapping = self.roots()
        mapping[NOTICE_URL] = f'<html><h1>{TITLE}</h1><a href="{PDF_URL}">Listado</a></html>'
        client = self.client(mapping)
        result = discover_notices(client, known)
        self.assertTrue(result['complete'])
        self.assertEqual(client.fetch.call_count, 3)
        old = [n for n in result['notices'] if '/01-01-2025-' in n['url']]
        self.assertEqual(len(old), 21)
        self.assertTrue(all(n['should_check'] is False and n['status'] == 'incorporated' and n['hash'] == 'retained' for n in old))
        self.assertEqual(old[0]['document_id'], 'doc-0')


if __name__ == '__main__':
    unittest.main()
