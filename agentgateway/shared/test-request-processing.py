"""Check transformations against bounded backend receipt records, including mirrors."""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:4000').rstrip('/')


def request(path, identifier, data=None, headers=None):
    req = urllib.request.Request(BASE + path + '?id=' + identifier + '&keep=yes',
                                 data=data, headers=headers or {})
    start = time.monotonic()

    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc

    with response:
        body = response.read().decode()

        try:
            body = json.loads(body)
        except ValueError:
            pass

        return response.status, body, response.headers, time.monotonic() - start


def fresh(path, data=None, headers=None):
    identifier = uuid.uuid4().hex
    return identifier, request(path, identifier, data, headers)


_, (code, body, headers, _) = fresh('/processing/headers', headers={
    'x-policy-common': 'original', 'x-policy-winner': 'client', 'x-policy-route': 'remove-me'})
assert code == 200 and body['headers']['x-policy-winner'] == 'gateway', body
assert body['headers']['x-policy-common'] == 'original, appended', body
assert 'x-policy-route' not in body['headers'], body
assert headers['x-policy-winner'] == 'response-policy' and headers['x-policy-backend'] == 'added'
assert 'x-policy-common' not in headers
print('PASS: request/response header add, set, remove')

_, (code, body, _, _) = fresh('/processing/body', b'original body', {'x-policy-common': 'sample'})
assert code == 200 and body['body'] == 'Hello sample' and body['method'] == 'POST', body
print('PASS: request body CEL transformation')

_, (code, body, headers, _) = fresh('/processing/response')
assert code == 200 and body == 'Response code: 200' and headers['content-type'] == 'text/plain', body
print('PASS: response body CEL transformation')

_, (code, body, _, _) = fresh('/rewrite-source')
assert code == 200 and body['path'] == '/processing/rewritten' and body['query'] == 'yes', body
print('PASS: full path rewrite preserves query')

# These are limitation checks, NOT proof that full-body mirroring works.
for path in ['/processing/mirror', '/processing/mirror-buffered']:
    payload = 'mirror payload 한글'.encode()
    identifier, (code, primary, _, _) = fresh(path, payload)
    assert code == 200 and primary['count'] == 1 and primary['body'] == payload.decode(), primary

    for _ in range(50):
        _, mirrored, _, _ = request('/processing/mirror/stats', identifier)
        if mirrored['count']:
            break

        time.sleep(0.1)

    assert mirrored['count'] == 1 and mirrored['method'] == 'POST', mirrored
    assert mirrored['path'] == path and mirrored['query'] == 'yes', mirrored
    assert mirrored['body'] == '', ('Recheck upstream body mirroring support', mirrored)

    time.sleep(0.3)
    assert request('/processing/mirror/stats', identifier)[1]['count'] == 1
    print(f'LIMITATION CONFIRMED: {path}: primary body intact, mirror body empty, mirror 503 isolated')

identifier, (code, _, _, _) = fresh('/processing/mirror-buffered', b'x' * 65537)
assert code == 413, code

# No primary or mirror delivery after failClosed rejects the oversized body.
time.sleep(0.3)
for stats in ['/processing/stats', '/processing/mirror/stats']:
    assert request(stats, identifier)[1]['count'] == 0, stats

print('PASS: explicit buffer rejects oversized body before either backend')

_, (code, body, _, elapsed) = fresh('/processing/delay')
assert code == 200 and elapsed >= 0.17, (code, elapsed)
print(f'PASS: injected delay, elapsed={elapsed:.3f}s')

identifier, (code, body, _, elapsed) = fresh('/processing/delay-timeout')
assert code == 504 and elapsed < 0.45, (code, body, elapsed)

time.sleep(0.6)
assert request('/processing/stats', identifier)[1]['count'] == 0
print(f'PASS: request timeout interrupts injected delay before backend, elapsed={elapsed:.3f}s')
