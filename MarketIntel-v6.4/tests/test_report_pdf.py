"""Optional text-level PDF checks: install pypdf as a development dependency."""
from io import BytesIO
import copy
import unittest
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader=None

from marketintel_reports import render_report_pdf, explain_report
from test_report_analysis import snapshot


def report():
    data=snapshot()
    data.update(title='Reporte de apertura',session_date='2026-11-18',cutoff_at='2026-11-18T14:18:00+00:00',warnings=[],notes=[],watchlist_reports=[],watchlist=[])
    for q,price,change in zip(data['quotes'],[7384.25,27273.75,3786.5],[25.25,198.25,-77.7]):
        q.update(price=price,change=change,previous=price-change,unit='pts',as_of='2026-11-18T14:13:00+00:00',source='Yahoo Finance')
    for q in data['magnificent_seven']:
        q.update(price=159.08,previous=156.14,change=2.94,as_of='2026-11-18T14:15:00+00:00',source='Yahoo Finance',name=q['ticker'])
    return data


@unittest.skipUnless(PdfReader,'Optional PDF reader not installed')
class ReportPDFTests(unittest.TestCase):
    def read(self,data):return PdfReader(BytesIO(render_report_pdf(data)))

    def test_three_page_report_retains_snapshot_values_and_partial_coverage(self):
        data=report();original=copy.deepcopy(data)
        pdf=self.read(data);text='\n'.join(p.extract_text() for p in pdf.pages)
        self.assertEqual(len(pdf.pages),3)
        for value in ('7.384,25','27.273,75','+25,25','+2,94','29,4%','52,5%','09:18 NY','09:15 NY'):
            self.assertIn(value,text)
        self.assertIn('van divididas',text)
        self.assertIn('muestra',text)
        self.assertNotIn('CPI de hoy',text)
        self.assertEqual(data,original,'Export must not modify the report snapshot')

    def test_macro_page_is_conditional_and_preserves_unknown_consensus(self):
        data=report();data['macro']=[{'title':'CPI de hoy','actual':'0,2% mensual','consensus':None,'previous':'0,4% mensual',
            'published_at':'2026-11-18T13:30:00+00:00','explanation':'Los precios subieron menos que el mes anterior.',
            'market_reaction_note':'No hay una ventana verificada anterior y posterior.'}]
        pdf=self.read(data)
        self.assertEqual(len(pdf.pages),4)
        text='\n'.join(p.extract_text() for p in pdf.pages)
        for value in ('CPI de hoy','0,2% mensual','0,4% mensual','Sin consenso verificado','Qué cambió en el mercado'):
            self.assertIn(value,text)

    def test_large_watchlist_paginates_and_keeps_late_events_pending(self):
        data=report();data['kind']='closing';data['title']='Reporte de sesión'
        data['watchlist']=['NVDA','AAPL']
        data['watchlist_reports']=[{'ticker':'NVDA','title':'Resultados de una empresa '*8,'status':'published',
            'published_at':'2026-11-18T21:30:00+00:00','summary':'Detalle verificado del comunicado. '*8,
            'source':'Fuente','source_url':'https://example.com/report','post_price':170,'post_change_pct':2,'post_as_of':'2026-11-18T21:58:00+00:00'} for _ in range(8)]
        data['watchlist_reports'].append({'ticker':'AAPL','status':'pending','summary':'Previsto a las 17:30 NY; aún no publicado.'})
        pdf=self.read(data);text='\n'.join(p.extract_text() for p in pdf.pages)
        self.assertGreater(len(pdf.pages),4)
        self.assertEqual(' '.join(text.split()).count('Detalle verificado del comunicado.'),64)
        self.assertIn('Pendientes de tu watchlist',text)
        self.assertIn('17:30 NY',text)
        self.assertNotIn('continuación · continuación',text)

    def test_zero_is_a_real_count_and_missing_prices_do_not_become_zero(self):
        data=report();data['quotes'][0].update(price=None,change=None,change_pct=None,status='unavailable')
        pdf=self.read(data);text='\n'.join(p.extract_text() for p in pdf.pages)
        self.assertIn('Sin dato',text)
        self.assertIn('SIN CAMBIO',text)
        self.assertIn('\n0\n',text)

    def test_pending_only_watchlist_keeps_every_company_without_claiming_results(self):
        data=report();data['kind']='closing'
        data['watchlist']=['NVDA','AAPL','MSFT','TSLA']
        data['watchlist_reports']=[{'ticker':ticker,'status':'pending','summary':ticker+' pendiente a las 17:30 NY.'}
                                   for ticker in data['watchlist']]
        pdf=self.read(data);text=' '.join('\n'.join(p.extract_text() for p in pdf.pages).split())
        for ticker in data['watchlist']:
            self.assertIn(ticker+' pendiente a las 17:30 NY.',text)
        self.assertIn('Agenda de tu watchlist',text)
        self.assertNotIn('Resultados en tu watchlist',text)

    def test_provider_markup_and_non_http_links_are_never_executed(self):
        data=report()
        data['macro']=[{'title':'<script>alert(1)</script>','actual':'<img src=x>','explanation':'Texto del proveedor',
            'source':'Untrusted','source_url':'javascript:alert(1)'}]
        pdf=self.read(data)
        self.assertIn('<script>alert(1)</script>','\n'.join(p.extract_text() for p in pdf.pages))
        for page in pdf.pages:
            for ann in page.get('/Annots',[]):
                action=ann.get_object().get('/A',{})
                self.assertNotIn('javascript:',str(action.get('/URI','')))


if __name__=='__main__':unittest.main()
