import unittest
from datetime import datetime, timezone
from marketintel_reports import _bls_release


class BLSReportTests(unittest.TestCase):
    def test_cpi_negative_monthly_change_and_comparable_previous(self):
        page = '''Information embargoed until 8:30 a.m. (ET) Tuesday, November 10, 2026
        CONSUMER PRICE INDEX - OCTOBER 2026
        The Consumer Price Index for All Urban Consumers (CPI-U) decreased 0.2 percent
        on a seasonally adjusted basis in October after rising 0.4 percent in September.'''
        cutoff = datetime(2026,11,10,14,tzinfo=timezone.utc)
        item = _bls_release(page, cutoff, 'CPI')
        self.assertIn('-0.2% mensual', item['actual'])
        self.assertIn('0.4% mensual', item['previous'])
        self.assertIsNone(item['consensus'])
        self.assertEqual(item['period'], '2026-10-01')
        self.assertIsNone(_bls_release(page, datetime(2026,11,10,13,tzinfo=timezone.utc), 'CPI'))
        self.assertIsNone(_bls_release(page, datetime(2026,11,11,14,tzinfo=timezone.utc), 'CPI'))

    def test_nfp_release_number_between_embargo_and_time_and_revised_previous(self):
        page = '''Information embargoed until USDL-26-1632 8:30 a.m. (ET) Friday, November 6, 2026
        THE EMPLOYMENT SITUATION - OCTOBER 2026
        Total nonfarm payroll employment fell by 15,000 in October.
        The change in total nonfarm payroll employment for August was revised up by 53,000,
        from +133,000 to +186,000, and the change for September was revised up by 31,000,
        from +29,000 to +60,000.'''
        item = _bls_release(page, datetime(2026,11,6,14,tzinfo=timezone.utc), 'NFP')
        self.assertIn('-15,000 puestos', item['actual'])
        self.assertIn('+60,000 puestos', item['previous'])
        self.assertIn('revisada', item['previous'])


if __name__ == '__main__':
    unittest.main()
