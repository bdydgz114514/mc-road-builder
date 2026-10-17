# -*- coding: utf-8 -*-
"""inspect_cols.py -- 打印若干列的方块剖面，看清路面到底铺在哪一层、什么材料。

用法：
    python inspect_cols.py -8220 -8160
"""
import sys
from worldmem import WorldMem

Z0, Z1 = 270, 274
AIR = ('空气', '洞穴空气', '虚空空气')


def main():
    x_lo = int(sys.argv[1]) if len(sys.argv) > 1 else -8232
    x_hi = int(sys.argv[2]) if len(sys.argv) > 2 else -8200
    step = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    for x in list(range(x_lo, x_hi + 1, step)):
        wm = WorldMem.refresh_near(x, 272, rx=8, y_lo=58, y_hi=76)
        print('--- x = %d ---' % x)
        for y in range(74, 60, -1):
            cells = [str(wm.block(x, y, z))[:8].ljust(8) for z in range(Z0, Z1 + 1)]
            print('  y=%2d  ' % y + ' | '.join(cells))
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
