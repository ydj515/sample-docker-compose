"""Verify HTTP retry counts, timeout scopes and POST replay against real counters."""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:4000').rstrip('/')


def request(path, params, method='GET'):
    url = BASE + path + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method, data=b'{}' if method == 'POST' else None,
                                 headers={'Content-Type': 'application/json'})
    start = time.monotonic()

    try:
        response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc

    with response:
        text = response.read().decode()

        try:
            body = json.loads(text)
        except ValueError:
            body = text

        return response.status, body, time.monotonic() - start


def check(name, path, failures, expected_status, expected_attempts, method='GET', delay=0, status=503):
    # Read the backend's counter for this request; the final status alone hides retries.
    identifier = uuid.uuid4().hex
    code, body, elapsed = request(path, {'id': identifier, 'failures': failures, 'delay': delay, 'status': status}, method)
    _, counts, _ = request('/resilience/stats', {'id': identifier})
    assert code == expected_status, (name, code, body)

    actual = counts['attempts']
    if isinstance(expected_attempts, tuple):
        assert expected_attempts[0] <= actual <= expected_attempts[1], (name, actual)
    else:
        assert actual == expected_attempts, (name, actual)

    if expected_status == 200:
        assert body['attempt'] == actual and body['method'] == method, (name, body)

    print(f'PASS: {name}: HTTP {code}, attempts={actual}, elapsed={elapsed:.3f}s')

    return elapsed


check('two failures then success', '/resilience/retry', 2, 200, 3)
# Pinned v1.6.0 performs four deliveries for attempts=3, including the initial one.
check('retry exhausted (v1.6.0 observed count)', '/resilience/retry', 10, 503, 4)
check('unlisted status is not retried', '/resilience/retry', 10, 400, 1, status=400)
check('POST is replayed when retries enabled', '/resilience/retry', 2, 200, 3, method='POST')
check('POST without retry policy', '/resilience/no-retry', 2, 503, 1, method='POST')
elapsed = check('backend timeout', '/resilience/timeout', 0, 504, 1, delay=1500)
assert elapsed < 1.3, 'Backend timeout did not return before delayed response'

elapsed = check('total timeout bounds retries', '/resilience/budget', 20, 504, (1, 4), delay=150)
assert elapsed < 1.3, 'Total request budget was not enforced'
print('PASS: all retry/timeout scenarios; timings are local observations, not an SLA')
