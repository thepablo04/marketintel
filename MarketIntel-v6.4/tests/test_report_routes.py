"""The PDF must represent the same report snapshot without trusting client data."""
import base64
import sys
import types
import unittest
from unittest.mock import Mock, patch

import servidor


class ReportRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = servidor.app.test_client()
        self.module = types.ModuleType('marketintel_reports')
        self.module.build_report = Mock(return_value={'session_date': '2026-11-16', 'kind': 'closing'})
        self.module.render_report_pdf = Mock(return_value=b'%PDF-1.4\nfixture')

    def test_pdf_uses_the_exact_server_snapshot_and_normalized_watchlist(self):
        with patch.dict(sys.modules, {'marketintel_reports': self.module}):
            response = self.client.post('/reports/closing', json={'watchlist': [' nvda ', 'NVDA', 'AAPL']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['report'], self.module.build_report.return_value)
        self.module.render_report_pdf.assert_called_once_with(self.module.build_report.return_value)
        self.assertEqual(self.module.build_report.call_args.args, ('closing', ['NVDA', 'AAPL']))
        self.assertEqual(base64.b64decode(response.json['pdf_base64']), b'%PDF-1.4\nfixture')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_invalid_inputs_do_not_query_providers(self):
        with patch.dict(sys.modules, {'marketintel_reports': self.module}):
            for body in (None, [], {'watchlist': 'NVDA'}, {'watchlist': [None]},
                         {'watchlist': ['https://example.com']}, {'watchlist': ['A']*201}):
                response = self.client.post('/reports/opening', json=body)
                self.assertEqual(response.status_code, 400, body)
            self.assertEqual(self.client.post('/reports/unknown', json={}).status_code, 404)
        self.module.build_report.assert_not_called()

    def test_window_error_is_actionable_without_a_fake_pdf(self):
        self.module.build_report.side_effect = ValueError('Disponible a las 17:00 NY.')
        with patch.dict(sys.modules, {'marketintel_reports': self.module}):
            response = self.client.post('/reports/closing', json={'watchlist': []})
        self.assertEqual(response.status_code, 409)
        self.assertIn('17:00', response.json['error'])
        self.assertNotIn('pdf_base64', response.json)

    def test_provider_exception_does_not_expose_credentials(self):
        self.module.build_report.side_effect = RuntimeError('apikey=fixture-should-stay-private')
        with patch.dict(sys.modules, {'marketintel_reports': self.module}):
            response = self.client.post('/reports/closing', json={})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('apikey', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
