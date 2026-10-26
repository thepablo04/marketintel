import json
import tempfile
import unittest
from unittest.mock import patch
import servidor
from marketintel_storage import LocalStore, MODEL_VERSION


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=LocalStore(self.temp.name)
        self.payload={'version':2,'localStorage':{'pf_portfolios':'[]','watchlist':'["SPY"]'}}

    def test_versions_restore_exact_strings_and_survive_new_store_instance(self):
        first=self.store.save_backup(self.payload,'browser-test')
        self.payload['localStorage']['watchlist']='["QQQ"]'
        second=self.store.save_backup(self.payload,'browser-test','before-import')
        self.assertNotEqual(first['id'],second['id']);reopened=LocalStore(self.temp.name)
        self.assertEqual(reopened.read_backup(first['id'])['localStorage']['watchlist'],'["SPY"]')
        self.assertEqual(len(reopened.list_backups()),2)

    def test_unchanged_auto_backup_does_not_fill_disk(self):
        first=self.store.save_backup(self.payload,'browser-test');second=self.store.save_backup(self.payload,'browser-test')
        self.assertEqual(first['id'],second['id']);self.assertEqual(second['status'],'unchanged')
        self.assertEqual(len(self.store.list_backups()),1)

    def test_notes_and_heatmap_groups_restore_exactly_alongside_older_backups(self):
        old_payload = dict(self.payload['localStorage'])
        first = self.store.save_backup(self.payload, 'browser-test')
        groups = {'sectors': {'Tecnología e inversión 📈': ['AAPL', 'BRK-B']}}
        self.payload['localStorage'].update({
            'note_AAPL': 'Tesis: márgenes sólidos.\nRevisar después de resultados 📈',
            'ficha_note_AAPL': 'Riesgo: concentración de clientes; revisión en español.',
            'note_BRK-B': 'Acción clase B',
            'ficha_note_^GSPC': 'Índice de referencia',
            'note_EURUSD=X': 'Exposición al euro €',
            'ficha_note_BRK.B': 'Símbolo con punto',
            'hm_custom': json.dumps(groups, ensure_ascii=False),
        })
        second = self.store.save_backup(self.payload, 'browser-test')
        reopened = LocalStore(self.temp.name)
        self.assertEqual(reopened.read_backup(first['id'])['localStorage'], old_payload)
        self.assertEqual(reopened.read_backup(second['id'])['localStorage'], self.payload['localStorage'])
        self.assertEqual(reopened.read_backup(second['id'])['version'], 2)

    def test_invalid_note_and_heatmap_keys_are_rejected_atomically(self):
        invalid_keys = [
            'note_', 'ficha_note_', 'note_aapl', 'ficha_note_aapl',
            'note_AAPL extra', 'note_AAPL\n', 'note_AAPL/USD', 'note_AAPL_suffix',
            'note_' + 'A' * 16, 'ficha_note_' + 'A' * 16,
            'note_ÁAPL', 'note_AAPL<script>', 'hm_custom_extra', 'hm_custom_token',
            'note_TOKEN', 'ficha_note_SECRET',
        ]
        for key in invalid_keys:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.store.save_backup({
                    'localStorage': {'note_AAPL': 'Valid note', key: 'invalid'}
                }, 'browser-test')
        self.assertEqual(self.store.list_backups(), [])

    def test_api_saves_and_retrieves_notes_and_heatmap_groups(self):
        self.payload['localStorage'].update({
            'note_BRK-B': 'Diversificación y disciplina 📈',
            'ficha_note_^GSPC': 'Referencia del índice',
            'note_EURUSD=X': 'Revisar cotización €',
            'hm_custom': '{"sectors":{"Mis favoritas":["BRK-B"]}}',
        })
        client = servidor.app.test_client()
        with patch.object(servidor, 'local_store', self.store):
            headers = {'X-MarketIntel-Token': client.get('/local-state').get_json()['token']}
            response = client.post('/local-backups', headers=headers, json={
                'profile': 'browser-test', 'snapshot': self.payload,
            })
            self.assertEqual(response.status_code, 200)
            saved = response.get_json()
            restored = client.get('/local-backups/' + str(saved['id']), headers=headers)
            self.assertEqual(restored.status_code, 200)
            self.assertEqual(restored.get_json()['localStorage'], self.payload['localStorage'])

    def test_credentials_and_foreign_keys_are_rejected_atomically(self):
        for key in ['marketbot_apikey','mi_token','unrelated','__proto__']:
            with self.assertRaises(ValueError):self.store.save_backup({'localStorage':{key:'secret'}},'browser-test')
        self.assertEqual(self.store.list_backups(),[])

    def test_api_requires_local_origin_and_token(self):
        client=servidor.app.test_client()
        with patch.object(servidor,'local_store',self.store):
            token=client.get('/local-state').get_json()['token']
            self.assertEqual(client.post('/local-backups',json={}).status_code,403)
            headers={'X-MarketIntel-Token':token};payload={'profile':'browser-test','snapshot':self.payload}
            self.assertEqual(client.post('/local-backups',headers=headers,json=payload).status_code,200)
            self.assertEqual(client.get('/local-backups',headers={**headers,'Origin':'https://example.com'}).status_code,403)
            self.assertEqual(client.get('/local-state',headers={'Host':'evil.example'}).status_code,403)
            self.assertEqual(client.get('/local-state',environ_overrides={'REMOTE_ADDR':'192.168.1.8'}).status_code,403)
            self.assertEqual(client.get('/local-backups',headers=headers).get_json()['backups'][0]['id'],1)
            self.assertEqual(client.get('/local-backups/999',headers=headers).status_code,404)

    def test_older_backup_pages_remain_accessible(self):
        for _ in range(105):
            self.store.save_backup(self.payload,'browser-test','manual')
        client=servidor.app.test_client()
        with patch.object(servidor,'local_store',self.store):
            headers={'X-MarketIntel-Token':client.get('/local-state').get_json()['token']}
            first=client.get('/local-backups',headers=headers).get_json()
            second=client.get('/local-backups?before='+str(first['next_before']),headers=headers).get_json()
            self.assertEqual(len(first['backups']),100)
            self.assertEqual([row['id'] for row in second['backups']],[5,4,3,2,1])
            self.assertIsNone(second['next_before'])
            self.assertEqual(client.get('/local-backups?before=invalid',headers=headers).status_code,400)

    def test_journal_export_includes_more_than_100_observations(self):
        from datetime import date, timedelta
        with self.store.connect() as db:
            for index in range(105):
                day=(date(2026,1,1)+timedelta(days=index//10)).isoformat()
                db.execute('INSERT INTO signals(model,day,bucket,recorded_at,data_at,score,label,reference) VALUES(?,?,?,?,?,?,?,?)',
                           (MODEL_VERSION,day,index%10,day+'T15:00:00Z',day+'T14:59:00Z',65,'Sesgo alcista',100))
        self.assertEqual(len(self.store.signal_history()['observations']),100)
        client=servidor.app.test_client()
        with patch.object(servidor,'local_store',self.store):
            headers={'X-MarketIntel-Token':client.get('/local-state').get_json()['token']}
            exported=client.get('/signal-history',headers=headers).get_json()
            self.assertEqual(len(exported['observations']),105)
            self.assertEqual(exported['summary']['total'],105)


if __name__=='__main__':unittest.main()
