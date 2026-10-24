"""Verify first-match, fallback, and no-match behavior on HTTP routes."""

import sys
import urllib.error
import urllib.request

base = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:4000').rstrip('/')
cases = [
    ('/policy-order/admin', 403, 'first-admin-rule'),
    ('/policy-order/admin/users', 403, 'first-admin-rule'),
    ('/policy-order/public', 200, 'second-general-rule'),
    ('/policy-fallback/matched', 200, 'matched-rule'),
    ('/policy-fallback/other', 418, 'fallback-rule'),
    ('/policy-no-fallback/blocked', 403, 'blocked-rule'),
    # The sample MCP server returns this JSON for an unknown HTTP path.
    ('/policy-no-fallback/other', 404, '{"error":"Not found"}'),
]
for path, expected_status, expected_body in cases:
    try:
        response = urllib.request.urlopen(base + path, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc

    with response:
        body = response.read().decode()
        assert response.status == expected_status, (path, response.status, body)
        assert body == expected_body, (path, body)

    print(f'PASS: {path} -> {expected_status} {expected_body}')

print('PASS: first matching rule wins; fallback runs; unmatched policy reaches backend')
