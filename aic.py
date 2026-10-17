# -*- coding: utf-8 -*-
"""aic.py -- shared AIControl client helpers (import this instead of re-writing them)."""
import json
import urllib.parse
import urllib.request

BASE = 'http://127.0.0.1:25580'


def get(path, t=60):
    url = BASE + path
    if '?' in path:
        a, q = path.split('?', 1)
        ps = []
        for kv in q.split('&'):
            if '=' in kv:
                k, v = kv.split('=', 1)
                ps.append(k + '=' + urllib.parse.quote(v, safe=''))
            else:
                ps.append(kv)
        url = BASE + a + '?' + '&'.join(ps)
    with urllib.request.urlopen(url, timeout=t) as r:
        return json.loads(r.read().decode())


def state():
    return get('/state', t=15)


def cmd(c):
    return get('/exec?c=' + urllib.parse.quote(c), t=20)


def scan(blocks, r=48, limit=3000):
    return get('/scan?r=%d&blocks=%s&limit=%d' % (r, urllib.parse.quote(blocks), limit))


def dump(x0, y0, z0, x1, y1, z1, maxn=200000):
    r = get('/dump?x0=%d&y0=%d&z0=%d&x1=%d&y1=%d&z1=%d&max=%d' % (x0, y0, z0, x1, y1, z1, maxn))
    pal = r['palette']
    return {(b[0], b[1], b[2]): pal[b[3]] for b in r['blocks']}


def place(x, y, z, item=None):
    q = '/place?x=%d&y=%d&z=%d' % (x, y, z)
    if item:
        q += '&item=' + urllib.parse.quote(item)
    return get(q)


def inventory():
    return get('/inv')


def count_item(name):
    inv = inventory()
    for i in inv.get('items', []):
        if i['item'] == name:
            return i['total']
    return 0
