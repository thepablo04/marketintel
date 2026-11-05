"""ISM's own public press releases remain usable when its site asks for login."""
import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import marketintel_data as data


class November2026(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 5, 17, tzinfo=tz or timezone.utc)


class December2026(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 12, 5, 17, tzinfo=tz or timezone.utc)


def fixture(month='october', year=2026, sector='manufacturing', value=52.2):
    # Synthetic numbers; fixtures test provenance/periods, not today's result.
    period = f'{year}-{data._MONTH_NAMES.index(month)+1:02d}-01'
    previous_month = data._MONTH_NAMES[datetime.fromisoformat(data._shift_month(period, -1)).month-1]
    published = data._shift_month(period, 1)[:8] + '02T15:00:00Z'
    url = f'https://www.prnewswire.com/news-releases/{sector}-pmi-at-{str(value).replace(".","-")}-{month}-{year}-ism-{sector}-pmi-report-302123456.html'
    schema = {'@type': 'NewsArticle', 'headline': f'{sector.title()} PMI® at {value}%; {month.title()} {year} ISM® {sector.title()} PMI® Report',
              'mainEntityOfPage': {'@id': url}, 'datePublished': published}
    sentence = f'The {sector.title()} PMI® registered {value} percent in {month.title()}, compared to {previous_month.title()}\'s figure of 51.1 percent.'
    return url, period, schema, sentence


def page(schema, sentence, author='Institute for Supply Management'):
    return ('<meta content="' + author + '" name="author">'
            '<script type="application/ld+json">' + json.dumps(schema) + '</script>'
            '<h1>' + schema['headline'] + '</h1><p>' + sentence + '</p>')


class ISMReleaseTests(unittest.TestCase):
    def setUp(self):
        data._REMOTE_CACHE.clear()
        data._MACRO_LAST_GOOD.clear()
        self.clock = patch.object(data, 'datetime', November2026)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_login_redirect_uses_ism_authored_release_with_date_and_previous_month(self):
        url, period, schema, sentence = fixture()
        calls = []
        def read(_requests, target, **kwargs):
            calls.append(target)
            if 'ismworld.org' in target:
                return '<title>Sign in</title>'
            if '/search/news/' in target:
                return '<a href="'+url+'">Report</a>'
            self.assertEqual(target, url)
            return page(schema, sentence).replace('®', 'Â®')
        with patch.object(data, '_cached_text', side_effect=read):
            result = data.fetch_ism_snapshot(object())
        self.assertEqual((result['date'], result['display_value']), (period, 52.2))
        self.assertEqual(result['published_at'], '2026-11-02T15:00:00+00:00')
        self.assertEqual(result['source_url'], url)
        self.assertEqual(result['history'][0]['display_value'], 51.1)
        result['status'] = 'ok'
        data._enrich_macro_item('pmi', result)
        self.assertTrue(result['context_usable'])
        self.assertEqual(result['previous']['date'], '2026-09-01')
        self.assertEqual(result['publisher'], 'ISM')
        self.assertEqual(result['release_url_kind'], 'specific_release')
        self.assertEqual(result['publication_date_status'], 'verified')
        self.assertEqual(len(calls), 3)

    def test_discovery_follows_new_month_without_a_hardcoded_release_url(self):
        old = fixture()
        new = fixture(month='november', value=50.4)
        documents = {f[0]: page(f[2], f[3]) for f in (old, new)}
        links = ''.join('<a href="'+f[0]+'">Report</a>' for f in (old, new))
        with patch.object(data, 'datetime', December2026), patch.object(data, '_cached_text',
                side_effect=lambda _, url, **kwargs: links if '/search/news/' in url else documents[url]):
            result = data._fetch_ism_wire_snapshot(object())
        self.assertEqual((result['date'], result['display_value'], result['source_url']), ('2026-11-01', 50.4, new[0]))

    def test_services_must_match_the_requested_sector(self):
        url, period, schema, sentence = fixture(sector='services')
        result = data._parse_ism_wire_release(page(schema, sentence), url, period, services=True)
        self.assertEqual(result['id'], 'ISM-SERVICES')
        with self.assertRaises(ValueError):
            data._parse_ism_wire_release(page(schema, sentence), url, period)

    def test_wrong_issuer_period_identity_date_or_body_is_rejected(self):
        url, period, schema, sentence = fixture()
        variants = [page(schema, sentence, author='Another Research Company'),
                    page(schema, sentence.replace('52.2', '49.1')),
                    page(schema, 'No figure in this body.')]
        for key, value in [('headline', schema['headline'].replace('2026', '2025')),
                           ('mainEntityOfPage', {'@id': url.replace('302123456', '302999999')}),
                           ('datePublished', '2026-11-06T15:00:00Z'),
                           ('datePublished', '2026-10-15T15:00:00Z'),
                           ('datePublished', '2026-11-02'),
                           ('datePublished', '')]:
            other = copy.deepcopy(schema)
            other[key] = value
            variants.append(page(other, sentence))
        for document in variants:
            with self.subTest(document=document[:100]), self.assertRaises(ValueError):
                data._parse_ism_wire_release(document, url, period)

    def test_previous_reading_is_not_taken_from_another_component(self):
        url, period, schema, _ = fixture()
        sentence = 'The Manufacturing PMI registered 52.2 percent. The New Orders Index rose from September\'s figure of 45.5 percent.'
        result = data._parse_ism_wire_release(page(schema, sentence), url, period)
        self.assertEqual(len(result['history']), 1)
        invalid = copy.deepcopy(schema)
        invalid['headline'] = invalid['headline'].replace('52.2', '152.2')
        with self.assertRaises(ValueError):
            data._parse_ism_wire_release(page(invalid, sentence.replace('52.2', '152.2')), url, period)

    def test_discovery_never_requests_other_hosts_or_uses_old_year(self):
        url, _, schema, sentence = fixture()
        old = fixture(year=2025)[0]
        future = url.replace('october-2026', 'december-2026')
        links = ''.join('<a href="'+link+'">PMI</a>' for link in (old, future, url.replace('www.prnewswire.com', 'evil.example'),
                    url+'?redirect=elsewhere', url.replace('https://','http://'), url))
        calls = []
        def read(_, target, **kwargs):
            calls.append(target)
            return links if '/search/news/' in target else page(schema, sentence)
        with patch.object(data, '_cached_text', side_effect=read):
            result = data._fetch_ism_wire_snapshot(object())
        self.assertEqual(calls[-1], url)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['date'], '2026-10-01')

    def test_unverified_newer_report_does_not_make_an_older_reading_current(self):
        old, new = fixture(month='september'), fixture()
        links = ''.join('<a href="'+f[0]+'">Report</a>' for f in (old, new))
        documents = {old[0]: page(old[2], old[3]), new[0]: '<title>Sign in</title>'}
        with patch.object(data, '_cached_text', side_effect=lambda _, url, **kwargs: links if '/search/news/' in url else documents[url]):
            result = data._fetch_ism_wire_snapshot(object())
        self.assertEqual(result['date'], '2026-09-01')
        result['status'] = 'ok'
        data._enrich_macro_item('pmi', result)
        self.assertFalse(result['context_usable'])
        self.assertIn('posterior', result['period_warning'])

    def test_failure_of_both_sources_stays_unavailable(self):
        with patch.object(data, '_cached_text', side_effect=TimeoutError('fixture')):
            with self.assertRaisesRegex(ValueError, 'ISM-PMI:'):
                data.fetch_ism_snapshot(object())


if __name__ == '__main__':
    unittest.main()
