"""Encrypted sync transport: isolated capabilities and conditional writes."""
import base64
import copy
import hashlib
import json
import unittest
from unittest.mock import Mock

from flask import Flask
from flask_cors import CORS
import requests

from marketintel_sync import (
    BlobSnapshotStore, InstanceLimiter, MAX_HTTP_BYTES, MAX_PLAINTEXT_BYTES,
    SyncError, create_sync_blueprint,
)


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


TOKEN = b64(bytes(range(32)))
OTHER_TOKEN = b64(bytes(range(1, 33)))
AUTH = {'Authorization': 'Bearer ' + TOKEN}
ENVELOPE = {'version': 1, 'iv': b64(b'i' * 12), 'ciphertext': b64(b'encrypted snapshot' + b't' * 16)}
PATH = 'sync/v1/' + hashlib.sha256(TOKEN.encode()).hexdigest() + '.json'


class MemoryStore:
    available = True

    def __init__(self):
        self.rows = {}
        self.writes = 0

    def read(self, pathname):
        if pathname not in self.rows:
            raise SyncError(404, 'not_found', 'No existe una copia para esta clave.')
        return copy.deepcopy(self.rows[pathname])

    def write(self, pathname, envelope, revision=None, create=False):
        previous = self.rows.get(pathname)
        if (create and previous) or (not create and (not previous or revision != previous[1])):
            raise SyncError(409, 'conflict', 'Otro dispositivo guardó cambios.')
        self.writes += 1
        current = '"revision-' + str(self.writes) + '"'
        self.rows[pathname] = (copy.deepcopy(envelope), current)
        return current


def client_for(store=None, **kwargs):
    app = Flask(__name__)
    # The production app also has a broad Flask-CORS extension. Exercise their
    # interaction so a denial does not acquire permissive fallback headers.
    CORS(app, resources={r'/*': {'origins': ['http://localhost:5050']}})
    app.register_blueprint(create_sync_blueprint(store if store is not None else MemoryStore(), **kwargs))
    app.testing = True
    return app.test_client()


class SyncApiTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.client = client_for(self.store)

    def put(self, envelope=ENVELOPE, headers=None):
        return self.client.put('/sync/data', data=json.dumps(envelope), content_type='application/json',
                               headers={**AUTH, 'If-None-Match': '*', **(headers or {})})

    def test_configuration_status_has_no_credentials_and_local_can_be_disabled(self):
        result = self.client.get('/sync/status')
        self.assertEqual(result.json, {'available': True, 'version': 1,
                                       'max_plaintext_bytes': MAX_PLAINTEXT_BYTES})
        disabled = client_for(self.store, enabled=False)
        self.assertFalse(disabled.get('/sync/status').json['available'])
        self.assertEqual(disabled.get('/sync/data', headers=AUTH).status_code, 503)

    def test_only_canonical_256_bit_bearer_capabilities_are_accepted(self):
        for value in ['', TOKEN, 'Basic ' + TOKEN, 'Bearer ' + TOKEN + '=',
                      'Bearer ' + 'a' * 42, 'Bearer ' + 'a' * 44,
                      'Bearer ' + TOKEN[:-1] + '9', 'Bearer ' + TOKEN + ' ']:
            with self.subTest(value=value):
                result = self.client.get('/sync/data', headers={'Authorization': value})
                self.assertEqual(result.status_code, 401)
                self.assertNotIn(TOKEN, result.get_data(as_text=True))
        self.assertEqual(self.store.writes, 0)

    def test_creation_reads_and_capability_isolation(self):
        created = self.put()
        self.assertEqual(created.status_code, 200)
        read = self.client.get('/sync/data', headers=AUTH)
        self.assertEqual(read.json, {'envelope': ENVELOPE, 'revision': created.json['revision']})
        self.assertEqual(read.headers['ETag'], created.json['revision'])
        self.assertEqual(read.headers['Cache-Control'], 'no-store')
        self.assertEqual(set(self.store.rows), {PATH})
        isolated = self.client.get('/sync/data', headers={'Authorization': 'Bearer ' + OTHER_TOKEN})
        self.assertEqual(isolated.status_code, 404)
        self.assertEqual(isolated.json['code'], 'not_found')
        self.assertNotIn(TOKEN, str(self.store.rows))

    def test_two_devices_cannot_overwrite_each_other_or_recreate_existing_vault(self):
        first = self.put().json['revision']
        updated = {**ENVELOPE, 'iv': b64(b'n' * 12)}
        a = self.client.put('/sync/data', json=updated, headers={**AUTH, 'If-Match': first})
        b = self.client.put('/sync/data', json=ENVELOPE, headers={**AUTH, 'If-Match': first})
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 409)
        self.assertEqual(b.json['code'], 'conflict')
        self.assertEqual(self.put().status_code, 409)
        self.assertEqual(self.store.read(PATH), (updated, a.json['revision']))
        self.assertEqual(self.store.writes, 2)

    def test_conditional_write_is_mandatory_and_wildcard_overwrite_rejected(self):
        cases = [({}, 428), ({'If-Match': '"a"', 'If-None-Match': '*'}, 428),
                 ({'If-Match': '*'}, 400), ({'If-Match': 'W/"a"'}, 400), ({'If-None-Match': '"a"'}, 400),
                 ({'If-Match': '"a", "b"'}, 400)]
        for extra, expected in cases:
            with self.subTest(extra=extra):
                result = self.client.put('/sync/data', json=ENVELOPE, headers={**AUTH, **extra})
                self.assertEqual(result.status_code, expected)
        self.assertEqual(self.store.writes, 0)

    def test_edge_safe_preconditions_keep_atomic_writes_and_support_local_cors(self):
        headers = {**AUTH, 'Origin': 'http://localhost:5050', 'X-Sync-If-None-Match': '*'}
        created = self.client.put('/sync/data', json=ENVELOPE, headers=headers)
        self.assertEqual(created.status_code, 200)
        revision = created.json['revision']
        update = {**AUTH, 'X-Sync-If-Match': revision}
        self.assertEqual(self.client.put('/sync/data', json=ENVELOPE, headers=update).status_code, 200)
        self.assertEqual(self.client.put('/sync/data', json=ENVELOPE, headers=update).status_code, 409)
        ambiguous = self.client.put('/sync/data', json=ENVELOPE, headers={**headers, 'If-None-Match': '*'})
        self.assertEqual(ambiguous.status_code, 428)
        preflight = self.client.options('/sync/data', headers={
            'Origin': 'http://localhost:5050', 'Access-Control-Request-Method': 'PUT',
            'Access-Control-Request-Headers': 'authorization,content-type,x-sync-if-match,x-sync-if-none-match'})
        self.assertEqual(preflight.status_code, 204)
        self.assertIn('X-Sync-If-Match', preflight.headers['Access-Control-Allow-Headers'])

    def test_head_never_writes_even_with_body_and_creation_precondition(self):
        self.put()
        result = self.client.open('/sync/data', method='HEAD', json=ENVELOPE,
                                  headers={**AUTH, 'If-None-Match': '*'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, b'')
        self.assertEqual(self.store.writes, 1)

    def test_invalid_envelopes_and_duplicate_fields_are_rejected_before_storage(self):
        invalid = [None, [], {**ENVELOPE, 'plaintext': 'secret'}, {**ENVELOPE, 'version': True},
                   {**ENVELOPE, 'iv': b64(b'i' * 11)}, {**ENVELOPE, 'iv': ENVELOPE['iv'] + '='},
                   {**ENVELOPE, 'ciphertext': b64(b'x' * 15)}]
        for envelope in invalid:
            with self.subTest(envelope=envelope):
                self.assertEqual(self.put(envelope).status_code, 400)
        # A separate client/limiter avoids conflating format and creation limits.
        client = client_for(self.store)
        duplicate = json.dumps(ENVELOPE)[:-1] + ',"version":1}'
        result = client.put('/sync/data', data=duplicate, content_type='application/json',
                            headers={**AUTH, 'If-None-Match': '*'})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.store.writes, 0)

    def test_size_and_content_type_limits(self):
        too_big = {**ENVELOPE, 'ciphertext': b64(b'x' * (MAX_PLAINTEXT_BYTES + 17))}
        self.assertEqual(self.put(too_big).status_code, 400)
        result = self.client.put('/sync/data', data=b' ' * (MAX_HTTP_BYTES + 1),
                                 content_type='application/json', headers={**AUTH, 'If-None-Match': '*'})
        self.assertEqual(result.status_code, 413)
        result = self.client.put('/sync/data', data=json.dumps(ENVELOPE),
                                 content_type='text/plain', headers={**AUTH, 'If-None-Match': '*'})
        self.assertEqual(result.status_code, 415)
        self.assertEqual(self.store.writes, 0)

    def test_only_same_origin_and_loopback_origins_may_read_or_preflight(self):
        for origin in ['http://localhost:5050', 'http://127.0.0.1:8765', 'https://localhost:5500',
                       'http://[::1]:5050', 'http://localhost']:
            with self.subTest(origin=origin):
                result = self.client.options('/sync/data', headers={
                    'Origin': origin, 'Access-Control-Request-Method': 'PUT',
                    'Access-Control-Request-Headers': 'authorization,content-type,if-match'})
                self.assertEqual(result.status_code, 204)
                self.assertEqual(result.headers['Access-Control-Allow-Origin'], origin)
                self.assertNotIn('Access-Control-Allow-Credentials', result.headers)
        for origin in ['null', 'https://evil.example', 'http://localhost.evil.example',
                       'http://localhost:5050/path', 'http://user@localhost:5050',
                       'http://localhost:99999', 'file://localhost']:
            with self.subTest(origin=origin):
                result = self.client.get('/sync/status', headers={'Origin': origin})
                self.assertEqual(result.status_code, 403)
                self.assertNotIn('Access-Control-Allow-Origin', result.headers)
        live = self.client.get('/sync/status', base_url='https://marketintel-nu.vercel.app',
                               headers={'Origin': 'https://marketintel-nu.vercel.app'})
        self.assertEqual(live.status_code, 200)

    def test_preflight_cannot_introduce_other_methods_or_headers(self):
        for method, headers in [('DELETE', 'Authorization'), ('PUT', 'X-Extra')]:
            result = self.client.options('/sync/data', headers={
                'Origin': 'http://localhost:5050', 'Access-Control-Request-Method': method,
                'Access-Control-Request-Headers': headers})
            self.assertEqual(result.status_code, 403)

    def test_backend_errors_keep_details_and_credentials_out_of_response(self):
        self.store.read = Mock(side_effect=RuntimeError('provider-secret-' + TOKEN))
        result = self.client.get('/sync/data', headers=AUTH)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.headers['Retry-After'], '60')
        self.assertNotIn(TOKEN, result.get_data(as_text=True))

    def test_creation_bursts_are_bounded(self):
        for count in range(8):
            token = b64(bytes([count]) * 32)
            self.assertEqual(self.put(headers={'Authorization': 'Bearer ' + token}).status_code, 200)
        result = self.put()
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.headers['Retry-After'], '60')


def response(status=200, payload=None, headers=None, raw=None):
    value = Mock(status_code=status, headers=headers or {})
    value.iter_content.return_value = [raw if raw is not None else json.dumps(payload).encode()]
    return value


class BlobAdapterTests(unittest.TestCase):
    def setUp(self):
        self.http = Mock()
        self.store = BlobSnapshotStore(self.http, {'BLOB_STORE_ID': 'store_abc123',
                                                  'VERCEL_OIDC_TOKEN': 'server-only-oidc'})

    def test_create_and_compare_and_swap_use_private_fixed_paths_and_no_redirects(self):
        self.http.request.return_value = response(payload={'etag': '"first"'})
        self.assertEqual(self.store.write(PATH, ENVELOPE, create=True), '"first"')
        args, kwargs = self.http.request.call_args
        self.assertEqual(args, ('PUT', 'https://vercel.com/api/blob/?pathname=' + PATH.replace('/', '%2F')))
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer server-only-oidc')
        self.assertEqual(kwargs['headers']['x-vercel-blob-access'], 'private')
        self.assertEqual(kwargs['headers']['x-add-random-suffix'], '0')
        self.assertEqual(kwargs['headers']['x-allow-overwrite'], '0')
        self.assertNotIn('x-if-match', kwargs['headers'])
        self.store.write(PATH, ENVELOPE, revision='"first"')
        headers = self.http.request.call_args.kwargs['headers']
        self.assertEqual(headers['x-allow-overwrite'], '1')
        self.assertEqual(headers['x-if-match'], '"first"')

    def test_reads_bypass_provider_cache_and_validate_ciphertext_and_revision(self):
        self.http.request.return_value = response(payload=ENVELOPE, headers={'ETag': '"first"'})
        self.assertEqual(self.store.read(PATH), (ENVELOPE, '"first"'))
        self.assertEqual(self.http.request.call_args.args, ('GET',
                         'https://abc123.private.blob.vercel-storage.com/' + PATH + '?cache=0'))
        self.assertEqual(self.http.request.call_args.kwargs['headers']['Accept-Encoding'], 'identity')
        for value in [response(payload=ENVELOPE), response(payload=ENVELOPE, headers={'ETag': 'W/"first"'}),
                      response(payload={'plaintext': 'secret'}, headers={'ETag': '"x"'}),
                      response(raw=b'x' * (MAX_HTTP_BYTES + 1), headers={'ETag': '"x"'})]:
            self.http.request.return_value = value
            with self.assertRaises(SyncError) as caught:
                self.store.read(PATH)
            self.assertEqual(caught.exception.status, 503)
            value.close.assert_called_once()

    def test_provider_conflict_is_never_retried_as_unconditional_write(self):
        for status, code, message in [(412, 'precondition_failed', ''), (400, 'precondition_failed', ''),
                                       (400, 'bad_request', 'Blob already exists')]:
            self.http.request.reset_mock()
            self.http.request.return_value = response(status, {'error': {'code': code, 'message': message}})
            with self.assertRaises(SyncError) as caught:
                self.store.write(PATH, ENVELOPE, create=True)
            self.assertEqual(caught.exception.status, 409)
            self.http.request.assert_called_once()

    def test_transient_errors_invalid_success_and_missing_conditional_write_fail_closed(self):
        for value in [response(429, {'error': {'code': 'rate_limited'}}),
                      response(403, {'error': {'code': 'store_suspended'}}),
                      response(payload={'url': 'not-an-etag'})]:
            self.http.request.return_value = value
            with self.assertRaises(SyncError) as caught:
                self.store.write(PATH, ENVELOPE, create=True)
            self.assertEqual(caught.exception.status, 503)
        self.http.reset_mock()
        with self.assertRaises(SyncError) as caught:
            self.store.write(PATH, ENVELOPE)
        self.assertEqual(caught.exception.status, 428)
        self.http.request.assert_not_called()
        self.http.request.side_effect = requests.Timeout('credentials must not leak')
        with self.assertRaises(SyncError) as caught:
            self.store.read(PATH)
        self.assertNotIn('credentials', str(caught.exception))

    def test_not_found_is_distinct_from_unavailable_and_invalid_path_never_requested(self):
        self.http.request.return_value = response(404, {})
        with self.assertRaises(SyncError) as caught:
            self.store.read(PATH)
        self.assertEqual(caught.exception.code, 'not_found')
        self.http.request.reset_mock()
        with self.assertRaises(SyncError):
            self.store.read('https://attacker.example/')
        self.http.request.assert_not_called()

    def test_expired_oidc_can_only_fall_back_to_server_token(self):
        token = 'vercel_blob_rw_abc123_serversecret'
        store = BlobSnapshotStore(self.http, {'BLOB_READ_WRITE_TOKEN': token, 'VERCEL_OIDC_TOKEN': 'expired'})
        self.http.request.side_effect = [response(401, {}), response(payload=ENVELOPE, headers={'ETag': '"x"'})]
        self.assertEqual(store.read(PATH), (ENVELOPE, '"x"'))
        self.assertEqual([call.kwargs['headers']['Authorization'] for call in self.http.request.call_args_list],
                         ['Bearer expired', 'Bearer ' + token])
        self.assertTrue(store.available)
        self.assertFalse(BlobSnapshotStore(environment={}).available)


class LimiterTests(unittest.TestCase):
    def test_window_expires_and_memory_is_bounded(self):
        clock = Mock(return_value=0)
        guard = InstanceLimiter(clock=clock, max_buckets=2)
        self.assertTrue(guard.allow('a', 1, 60))
        self.assertFalse(guard.allow('a', 1, 60))
        clock.return_value = 60
        self.assertTrue(guard.allow('a', 1, 60))
        guard.allow('b', 1, 60)
        guard.allow('c', 1, 60)
        self.assertEqual(len(guard.buckets), 2)


if __name__ == '__main__':
    unittest.main()
