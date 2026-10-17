# -*- coding: utf-8 -*-
"""roadscan.py -- 紧凑打印一段路的逐列状态（比 analyze.py 细，比 inspect_cols.py 快）。

用法：
    python roadscan.py -8160 -8130
"""
import sys
from worldmem import WorldMem

Z0, Z1 = 270, 274
AIR = ('空气', '洞穴空气', '虚空空气')


def solid(t):
    return t is not None and t not in AIR


def main():
    a, b = int(sys.argv[1]), int(sys.argv[2])
    x_lo, x_hi = min(a, b), max(a, b)   # 传反也要能用（往西扫是常态）
    deck = int(sys.argv[3]) if len(sys.argv) > 3 else 68

    # 分批 refresh（box 不能跨太大，否则超时读到旧文件）
    data = {}
    x = x_lo
    while x <= x_hi:
        chunk_hi = min(x + 16, x_hi)
        wm = WorldMem.refresh_near((x + chunk_hi) // 2, 272, rx=10,
                                   y_lo=deck - 8, y_hi=deck + 8)
        for xx in range(x, chunk_hi + 1):
            for z in range(Z0, Z1 + 1):
                data[(xx, z)] = (wm.block(xx, deck, z), wm.block(xx, deck - 1, z),
                                 wm.block(xx, deck + 1, z))
        x = chunk_hi + 1

    for xx in range(x_lo, x_hi + 1):
        row = []
        for z in range(Z0, Z1 + 1):
            t, below, above = data[(xx, z)]
            if not solid(t):
                c = '.'                       # deck 空
            elif '圆石' in str(t):
                c = '#'                       # 合格
            else:
                c = 'x'                       # 杂色
            if c != '.' and not solid(below):
                c = 'f'                       # 悬空
            row.append(c)
        up = sum(1 for z in range(Z0, Z1 + 1) if solid(data[(xx, z)][2]))
        flag = '' if all(c == '#' for c in row) and up == 0 else ' *'
        print('x=%6d  %s   above=%d%s' % (xx, ''.join(row), up, flag))
    return 0


if __name__ == '__main__':
    sys.exit(main())
