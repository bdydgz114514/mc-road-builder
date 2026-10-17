# -*- coding: utf-8 -*-
"""terrain_profile.py -- 看前方地形：走廊高度、水、崖，用来决定路面还是拱桥。

用法：python terrain_profile.py -8020 -7940
"""
import sys
from worldmem import WorldMem

Z0, Z1 = 270, 274
AIR = ('空气', '洞穴空气', '虚空空气')
WATER = ('水', '流动的水', 'water')


def solid(t):
    return t is not None and t not in AIR


def main():
    a, b = int(sys.argv[1]), int(sys.argv[2])
    x_lo, x_hi = min(a, b), max(a, b)      # 传反也要能用：往西扫才是常态
    deck = int(sys.argv[3]) if len(sys.argv) > 3 else 68

    data = {}
    x = x_lo
    while x <= x_hi:
        chunk_hi = min(x + 26, x_hi)
        wm = WorldMem.refresh_near((x + chunk_hi) // 2, 272, rx=14,
                                   y_lo=38, y_hi=82)
        for xx in range(x, chunk_hi + 1):
            for z in range(Z0, Z1 + 1):
                col = [(y, wm.block(xx, y, z)) for y in range(82, 37, -1)]
                data[(xx, z)] = col
        x = chunk_hi + 1

    print('x        tops(z270..274)        water  note')
    for xx in range(x_lo, x_hi + 1):
        tops, water = [], False
        for z in range(Z0, Z1 + 1):
            top = None
            for (y, t) in data[(xx, z)]:
                if any(k in str(t) for k in WATER):
                    water = True
                    continue
                if solid(t):
                    top = y
                    break
            tops.append('--' if top is None else str(top))
        spread = max(int(t) for t in tops if t != '--') - min(int(t) for t in tops if t != '--') \
            if any(t != '--' for t in tops) else -1
        note = []
        if water:
            note.append('WATER')
        if spread >= 3:
            note.append('ragged(%d)' % spread)
        if all(t == '--' for t in tops):
            note.append('VOID')
        print('x=%6d  %-24s %-5s %s' % (xx, ' '.join('%3s' % t for t in tops),
                                        'yes' if water else '-', ' '.join(note)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
