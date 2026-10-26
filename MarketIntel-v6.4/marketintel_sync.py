"""Opaque, authenticated sync snapshots in private Vercel Blob storage.

The browser holds the master/encryption key. This service receives only a
domain-separated bearer capability and encrypted bytes. Conditional writes
protect another device's changes; it never falls back to unconditional writes.
"""
import base64
from collections import OrderedDict, deque
import hashlib
import json
import os
import re
import threading
import time
from urllib.parse import quote, urlsplit

from flask import Blueprint, jsonify, request
import requests


MAX_PLAINTEXT_BYTES = 2 * 1024 * 1024
MAX_HTTP_BYTES = 3 * 1024 * 1024
_TOKEN = re.compile(r'^[A-Za-z0-9_-]{43}$')
_BASE64 = re.compile(r'^[A-Za-z0-9_-]+$')
_STORE = re.compile(r'^[A-Za-z0-9]+$')
_PATH = re.compile(r'^sync/v1/[a-f0-9]{64}\.json$')


class SyncError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def unavailable():
    return SyncError(503, 'unavailable', 'La sincronización no está disponible ahora. Tus cambios locales se conservan.')


def conflict():
    return SyncError(409, 'conflict', 'Otro dispositivo guardó cambios. Descarga la versión actual antes de volver a sincronizar.')


def _decode(value, expected=None, maximum=None):
    if not isinstance(value, str) or not _BASE64.fullmatch(value):
        raise ValueError('Invalid encoding')
    # Bound before decoding so invalid input cannot allocate an oversized copy.
    if maximum is not None and len(value) > (maximum * 4 + 2) // 3:
        raise ValueError('Encoded value too large')
    decoded = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
    if base64.urlsafe_b64encode(decoded).decode('ascii').rstrip('=') != value:
        raise ValueError('Non-canonical encoding')
    if expected is not None and len(decoded) != expected:
        raise ValueError('Wrong encoded length')
    if maximum is not None and len(decoded) > maximum:
        raise ValueError('Decoded value too large')
    return decoded


def validate_envelope(value):
    if not isinstance(value, dict) or set(value) != {'version', 'iv', 'ciphertext'}:
        raise ValueError('Invalid envelope')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Unsupported envelope version')
    _decode(value['iv'], expected=12)
    ciphertext = _decode(value['ciphertext'], maximum=MAX_PLAINTEXT_BYTES + 16)
    if len(ciphertext) < 16:
        raise ValueError('Missing authentication tag')
    return value


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value


def _read_json(raw):
    return json.loads(raw, object_pairs_hook=_unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON')))


def _valid_revision(value):
    return (isinstance(value, str) and 1 <= len(value) <= 256 and value != '*' and not value.startswith('W/')
            and ',' not in value and all(33 <= ord(char) <= 126 for char in value))


class BlobSnapshotStore:
    """Small synchronous adapter for the official Blob v12 HTTP protocol.

    Header names and consistent reads match @vercel/blob 2.8.0. Blob credentials
    belong only to this server; they are never returned to a requesting device.
    """
    def __init__(self, http=requests, environment=None):
        self.http = http
        self.environment = os.environ if environment is None else environment

    def _credentials(self):
        env = self.environment
        store_id = str(env.get('BLOB_STORE_ID', '')).removeprefix('store_')
        rw = env.get('BLOB_READ_WRITE_TOKEN') or env.get('VERCEL_BLOB_READ_WRITE_TOKEN')
        if not store_id and rw:
            parts = rw.split('_')
            store_id = parts[3] if len(parts) > 4 else ''
        if not _STORE.fullmatch(store_id):
            return None
        oidc = env.get('VERCEL_OIDC_TOKEN')
        tokens = [token for token in (oidc, rw) if isinstance(token, str) and token.strip()]
        return (store_id, list(dict.fromkeys(tokens))) if tokens else None

    @property
    def available(self):
        return self._credentials() is not None

    @staticmethod
    def _body(response):
        body = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            body.extend(chunk)
            if len(body) > MAX_HTTP_BYTES:
                raise unavailable()
        return bytes(body)

    def _request(self, method, pathname, *, body=None, revision=None, create=False):
        credentials = self._credentials()
        if not credentials or not _PATH.fullmatch(pathname):
            raise unavailable()
        store_id, tokens = credentials
        if method == 'GET':
            url = f'https://{store_id}.private.blob.vercel-storage.com/{pathname}?cache=0'
        else:
            url = 'https://vercel.com/api/blob/?pathname=' + quote(pathname, safe='')
        for index, token in enumerate(tokens):
            headers = {'Authorization': 'Bearer ' + token}
            if method == 'GET':
                # Compressed Blob responses carry a weak ETag (W/...), which
                # cannot satisfy a strong If-Match update. Request the stored
                # representation so reads return the actual write revision.
                headers['Accept-Encoding'] = 'identity'
            if method == 'PUT':
                headers.update({
                    'x-api-version': '12', 'x-vercel-blob-store-id': store_id,
                    'x-vercel-blob-access': 'private', 'x-add-random-suffix': '0',
                    'x-allow-overwrite': '0' if create else '1',
                    'x-content-type': 'application/json', 'Content-Type': 'application/json',
                })
                if not create:
                    headers['x-if-match'] = revision
            response = None
            try:
                response = self.http.request(method, url, headers=headers, data=body,
                                             timeout=(5, 20), stream=True, allow_redirects=False)
                status = response.status_code
                raw = self._body(response)
                if status in (401, 403) and index + 1 < len(tokens):
                    # A short-lived OIDC token can expire in a warm process.
                    # The connected store's server-only token is a valid fallback.
                    continue
                if method == 'GET' and status == 404:
                    raise SyncError(404, 'not_found', 'No existe una copia para esta clave de sincronización.')
                if not 200 <= status < 300:
                    try:
                        error = _read_json(raw).get('error', {})
                        code = error.get('code')
                        message = error.get('message', '')
                    except (ValueError, TypeError, AttributeError):
                        code, message = None, ''
                    if (status == 412 or code in {'precondition_failed', 'already_exists', 'blob_already_exists'}
                            or create and code == 'bad_request' and isinstance(message, str)
                            and 'already exists' in message.lower()):
                        raise conflict()
                    raise unavailable()
                if method == 'GET':
                    envelope = validate_envelope(_read_json(raw))
                    etag = response.headers.get('ETag')
                    if not _valid_revision(etag):
                        raise unavailable()
                    return envelope, etag
                etag = _read_json(raw).get('etag')
                if not _valid_revision(etag):
                    raise unavailable()
                return etag
            except SyncError:
                raise
            except Exception:
                # Provider errors can contain URLs/credentials. Keep them out of
                # API responses and logs; the client's data remains available offline.
                raise unavailable() from None
            finally:
                if response is not None:
                    response.close()
        raise unavailable()

    def read(self, pathname):
        return self._request('GET', pathname)

    def write(self, pathname, envelope, revision=None, create=False):
        if not create and not _valid_revision(revision):
            raise SyncError(428, 'precondition_required', 'Falta la versión que se quiere actualizar.')
        body = json.dumps(validate_envelope(envelope), separators=(',', ':')).encode('utf-8')
        return self._request('PUT', pathname, body=body, revision=revision, create=create)


class InstanceLimiter:
    """Bounded, process-local burst protection; not a distributed quota system."""
    def __init__(self, clock=time.monotonic, max_buckets=4096):
        self.clock, self.max_buckets = clock, max_buckets
        self.buckets, self.lock = OrderedDict(), threading.Lock()

    def allow(self, key, limit, seconds):
        now = self.clock()
        with self.lock:
            rows = self.buckets.pop(key, deque())
            while rows and rows[0] <= now - seconds:
                rows.popleft()
            permitted = len(rows) < limit
            if permitted:
                rows.append(now)
            self.buckets[key] = rows
            while len(self.buckets) > self.max_buckets:
                self.buckets.popitem(last=False)
            return permitted


def _allowed_origin(origin):
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        if (parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            return False
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            return False
        if origin == request.host_url.rstrip('/'):
            return True
        return parsed.hostname in {'localhost', '127.0.0.1', '::1'}
    except ValueError:
        return False


def create_sync_blueprint(store=None, *, enabled=None, limiter=None):
    backend = store if store is not None else BlobSnapshotStore()
    active = (store is not None or os.environ.get('VERCEL') == '1') if enabled is None else enabled
    guard = limiter if limiter is not None else InstanceLimiter()
    blueprint = Blueprint('marketintel_sync', __name__, url_prefix='/sync')

    def fail(status, code, message):
        response = jsonify({'code': code, 'error': message})
        response.status_code = status
        if status in (429, 503):
            response.headers['Retry-After'] = '60'
        return response

    @blueprint.before_request
    def protect_origin_and_preflight():
        if not _allowed_origin(request.headers.get('Origin')):
            return fail(403, 'origin_not_allowed', 'Origen no permitido para sincronizar.')
        if request.method == 'OPTIONS':
            wanted = request.headers.get('Access-Control-Request-Method', 'GET').upper()
            names = {name.strip().lower() for name in request.headers.get('Access-Control-Request-Headers', '').split(',') if name.strip()}
            if wanted not in {'GET', 'PUT'} or not names <= {'authorization', 'content-type', 'if-match', 'if-none-match', 'x-sync-if-match', 'x-sync-if-none-match'}:
                return fail(403, 'preflight_not_allowed', 'Solicitud de sincronización no permitida.')
            return '', 204

    @blueprint.after_request
    def sync_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        origin = request.headers.get('Origin')
        if origin and _allowed_origin(origin):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Methods'] = 'GET, PUT, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type, If-Match, If-None-Match, X-Sync-If-Match, X-Sync-If-None-Match'
            response.headers['Access-Control-Expose-Headers'] = 'ETag, Retry-After'
            response.headers['Access-Control-Max-Age'] = '600'
            response.vary.add('Origin')
        return response

    @blueprint.route('/status', methods=['GET', 'OPTIONS'])
    def status():
        return jsonify({'available': bool(active and backend.available), 'version': 1,
                        'max_plaintext_bytes': MAX_PLAINTEXT_BYTES})

    @blueprint.route('/data', methods=['GET', 'PUT', 'OPTIONS'])
    def data():
        # IP limits are a best-effort guard for this warm serverless instance.
        # Access isolation always relies on the 256-bit capability, not an IP.
        ip = request.remote_addr or 'unknown'
        if not guard.allow(('ip', ip), 120, 60):
            return fail(429, 'rate_limited', 'Demasiadas solicitudes. Vuelve a intentarlo en un minuto.')
        authorization = request.headers.get('Authorization', '')
        if not authorization.startswith('Bearer '):
            return fail(401, 'unauthorized', 'Falta una clave válida de sincronización.')
        token = authorization[7:]
        try:
            if not _TOKEN.fullmatch(token):
                raise ValueError('Invalid capability')
            _decode(token, expected=32)
        except ValueError:
            return fail(401, 'unauthorized', 'Falta una clave válida de sincronización.')
        if not active or not backend.available:
            error = unavailable()
            return fail(error.status, error.code, str(error))
        namespace = hashlib.sha256(token.encode('ascii')).hexdigest()
        if not guard.allow((request.method, namespace), 30 if request.method == 'PUT' else 60, 60):
            return fail(429, 'rate_limited', 'Demasiados cambios seguidos. Tus cambios locales se conservan.')
        pathname = 'sync/v1/' + namespace + '.json'
        try:
            # Flask automatically adds HEAD for GET routes. It must share the
            # read-only path even if a caller includes a body or preconditions.
            if request.method in {'GET', 'HEAD'}:
                envelope, revision = backend.read(pathname)
                response = jsonify({'envelope': envelope, 'revision': revision})
                response.headers['ETag'] = revision
                return response
            # Vercel's edge can interpret standard If-None-Match on a PUT as a
            # cache revalidation and replace the successful JSON with 304. Keep
            # browser preconditions in application headers; enforce the same CAS
            # here and forward the provider's official condition to private Blob.
            if (request.headers.get('X-Sync-If-None-Match') is not None and request.headers.get('If-None-Match') is not None
                    or request.headers.get('X-Sync-If-Match') is not None and request.headers.get('If-Match') is not None):
                return fail(428, 'precondition_required', 'Indica una sola versión anterior antes de guardar.')
            initial = request.headers.get('X-Sync-If-None-Match', request.headers.get('If-None-Match'))
            revision = request.headers.get('X-Sync-If-Match', request.headers.get('If-Match'))
            if (initial is None and revision is None) or (initial is not None and revision is not None):
                return fail(428, 'precondition_required', 'Indica la versión anterior antes de guardar.')
            if (initial is not None and initial != '*') or (revision is not None and not _valid_revision(revision)):
                return fail(400, 'invalid_precondition', 'La versión indicada no es válida.')
            if initial and not guard.allow(('create', ip), 8, 3600):
                return fail(429, 'rate_limited', 'Se crearon demasiados espacios de sincronización. Vuelve a intentarlo más tarde.')
            if request.mimetype != 'application/json':
                return fail(415, 'json_required', 'La sincronización requiere JSON cifrado.')
            if request.content_length is not None and request.content_length > MAX_HTTP_BYTES:
                return fail(413, 'too_large', 'La copia es demasiado grande para sincronizar.')
            raw = request.stream.read(MAX_HTTP_BYTES + 1)
            if len(raw) > MAX_HTTP_BYTES:
                return fail(413, 'too_large', 'La copia es demasiado grande para sincronizar.')
            try:
                envelope = validate_envelope(_read_json(raw))
            except (ValueError, TypeError, UnicodeError):
                return fail(400, 'invalid_envelope', 'La copia cifrada no tiene un formato válido.')
            etag = backend.write(pathname, envelope, revision=revision, create=initial == '*')
            response = jsonify({'revision': etag})
            response.headers['ETag'] = etag
            return response
        except SyncError as error:
            return fail(error.status, error.code, str(error))
        except Exception:
            error = unavailable()
            return fail(error.status, error.code, str(error))

    return blueprint
