"""Read-only HTTP integration smoke against the isolated RGB benchmark server.

Not a browser performance result. Does not call robot or phase-control APIs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


def run(base):
    def get(params):
        started = time.monotonic()
        try:
            with urlopen(base + '/api/v1/media/rgb?' + urlencode(params), timeout=5) as r:
                content = r.read()
                return {'status': r.status, 'bytes': len(content), 'jpeg': content.startswith(b'\xff\xd8'),
                        'frame': json.loads(r.headers.get('X-HazardGuard-Frame', 'null')),
                        'server_timing': r.headers.get('Server-Timing'),
                        'elapsed_ms': (time.monotonic()-started)*1000}
        except HTTPError as exc:
            return {'status': exc.code, 'elapsed_ms': (time.monotonic()-started)*1000}

    def client(_):
        rows = []
        params = {'delivery': 'new-frame'}
        for i in range(3):
            r = get(params)
            assert r['status'] == 200 and r['jpeg'] and r['frame']
            if rows:
                assert r['frame']['s'] != rows[-1]['frame']['s'] or r['frame']['n'] > rows[-1]['frame']['n']
            rows.append(r)
            params.update(session=r['frame']['s'], after=r['frame']['n'])
        return rows

    with ThreadPoolExecutor(max_workers=12) as pool:
        clients = list(pool.map(client, range(12)))
    session = clients[0][-1]['frame']['s']
    future = get({'delivery': 'new-frame', 'session': session, 'after': 9007199254740991})
    assert future['status'] == 503 and future['elapsed_ms'] < 4000
    invalid = get({'delivery': 'new-frame', 'session': 'invalid', 'after': -1})
    assert invalid['status'] == 422
    restart = get({'delivery': 'new-frame', 'session': '0'*32, 'after': 9007199254740991})
    assert restart['status'] == 200
    reconnect = get({'delivery': 'new-frame'})
    assert reconnect['status'] == 200
    poll = get({'delivery': 'poll'})
    assert poll['status'] == 200
    return {'scope': 'HTTP integration only; dark scene; no performance or image-quality conclusion',
            'created_unix': time.time(), 'clients': clients, 'future_sequence_timeout': future,
            'invalid_query': invalid, 'old_session': restart, 'reconnect': reconnect, 'poll': poll}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = run(args.base.rstrip('/'))
    with Path(args.output).open('x', encoding='utf-8') as file:
        json.dump(result, file, indent=2)
    print('PASS: 12 clients x 3 fresh JPEGs, bounded timeout, validation, old session, reconnect, polling')
