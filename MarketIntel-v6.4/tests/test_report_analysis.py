import copy
import unittest
from marketintel_reports import explain_report


def snapshot():
    return {'kind':'opening','quotes':[
        {'ticker':'ES=F','label':'S&P 500','status':'ok','change_pct':.34},
        {'ticker':'NQ=F','label':'Nasdaq 100','status':'ok','change_pct':.73},
        {'ticker':'GC=F','label':'Oro','status':'ok','change_pct':-2.01}],
        'magnificent_seven':[{'ticker':symbol,'status':'ok','change_pct':change} for symbol,change in
            [('NVDA',1.88),('MSFT',-2.82),('AAPL',-.52),('AMZN',.76),('GOOGL',.05),('META',-1.56),('TSLA',.91)]],
        'breadth':[{'label':'S&P 500','total':503,'valid':148,'up':45,'down':103,'unchanged':0,'missing':355},
                   {'label':'Nasdaq 100','total':101,'valid':53,'up':25,'down':28,'unchanged':0,'missing':48}], 'macro':[]}


class ReportAnalysisTests(unittest.TestCase):
    def test_uploaded_report_explains_divergence_and_limits_without_extrapolating(self):
        data=snapshot();original=copy.deepcopy(data)
        report=explain_report(data)
        self.assertIn('avanzan',report['headline'])
        self.assertIn('van divididas',report['synthesis'])
        self.assertIn('4 de las siete suben, 3 bajan',report['seven_text'])
        self.assertIn('NVDA',report['seven_text']);self.assertIn('MSFT',report['seven_text'])
        self.assertIn('148/503',report['coverage_note'])
        self.assertIn('53/101',report['coverage_note'])
        self.assertIn('solo los valores observados',report['coverage_note'])
        self.assertEqual(data,original)

    def test_partial_seven_does_not_claim_full_group_direction(self):
        data=snapshot();data['magnificent_seven']=data['magnificent_seven'][:2]
        result=explain_report(data)
        self.assertIn('De 2 con datos',result['seven_text'])
        self.assertIn('Faltan 5',result['seven_text'])

    def test_missing_prices_cannot_become_market_direction(self):
        data=snapshot()
        for q in data['quotes']:q.update(status='unavailable',change_pct=None)
        data['magnificent_seven']=[]
        result=explain_report(data)
        self.assertIn('No hay cotizaciones',result['headline'])
        self.assertIn('No hay precios válidos',result['seven_text'])
        self.assertNotIn('índices suben',result['synthesis'])

    def test_macro_appears_only_when_supplied_and_does_not_invent_consensus(self):
        data=snapshot();self.assertFalse(any('CPI' in p['title'] for p in explain_report(data)['key_points']))
        data['macro']=[{'title':'CPI de hoy','actual':'0,2% mensual','consensus':None}]
        result=explain_report(data)
        self.assertEqual(result['key_points'][0]['title'],'CPI de hoy')
        self.assertIn('Sin consenso verificado',result['key_points'][0]['text'])
        self.assertEqual(len(result['key_points']),3)

    def test_uniform_decline_mixed_and_flat_indices_are_distinct(self):
        data=snapshot()
        for q in data['quotes'][:2]:q['change_pct']=-1
        self.assertIn('retroceden',explain_report(data)['headline'])
        data['quotes'][1]['change_pct']=1
        self.assertIn('movimientos distintos',explain_report(data)['headline'])
        for q in data['quotes'][:2]:q['change_pct']=0
        self.assertNotIn('avanzan',explain_report(data)['headline'])


if __name__=='__main__':unittest.main()
