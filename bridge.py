# -*- coding: utf-8 -*-
"""
bridge.py -- 拱桥：跨水面时不铺平路，而是隆起的单峰拱。

水面/谷地实测（terrain_profile.py）：
    x -8016..-8014   谷底 y=63（平路要垫 5 层）
    x -8013..-8009   山脊 y=72..73（平路要削 4~5 层）
    x -7982..-7967   **河**，水面 y≈62，河床 y=57
    x -7966 起        回到陆地 y=63..67

拱形用抛物线：h(x) = round(peak * (1 - (d/half)^2))，d = |x - 桥心|
17 列跨河、peak=4 时的高度序列：
    68 69 70 70 71 71 72 72 72 72 72 71 71 70 70 69 68
—— 只有一个峰，符合"100 格之内只允许一个起伏点"。

每一列（从西岸往东岸推进，永远站在刚建好的 x-1 上）：
    1. 目标高度 h 上若是别的实心方块 → 挖掉
    2. h-1 是空气 → 垫一层（默认圆石，bridge 结构比泥土好看）
    3. h 上放圆石 → **回读验证**
    4. 可选：两侧 z0/z1 在 h+1 处加矮护栏

用法：
    python bridge.py --x0 -7982 --x1 -7966 --peak 4
    python bridge.py --x0 -7982 --x1 -7966 --peak 4 --rail
"""
import argparse
import math
import sys
import time

import aic
import aura
import defend
from snap import snap
from worldmem import WorldMem
from raise_deck import Raiser, solid, is_cobble, say


class Bridge(Raiser):
    def __init__(self, deck=68, z_centre=272, width=5, peak=4,
                 under='圆石', rail=False, desc=False, min_hp=None):
        Raiser.__init__(self, deck, z_centre, width, min_hp=min_hp)
        self.peak = peak
        self.under = under
        self.rail = rail
        self.rail_n = 0
        # desc=True：往西建桥（x0 是东岸，x1 是西岸），站在已铺好的 **x+1** 上往 x 放。
        # 原来的实现只会往东建（站 x-1），往西会站到没铺的河面上。
        self.desc = desc

    # ---------- 拱形 ----------
    def heights(self, x0, x1):
        a, b = min(x0, x1), max(x0, x1)
        mid = (a + b) / 2.0
        half = max(1.0, (b - a) / 2.0)
        out = {}
        for x in range(a, b + 1):
            d = abs(x - mid)
            out[x] = self.deck + int(round(self.peak * (1.0 - (d / half) ** 2)))
        return out

    # ---------- 站位（高度是变的，不能再用固定的 self.deck） ----------
    def stand_at(self, x, y_feet, tries=3, timeout=10.0):
        for _ in range(tries):
            px, py, pz = self.feet()
            if px == x and abs(pz - self.zc) <= 1 and py >= y_feet:
                return True
            aic.cmd('#goto %d %d %d' % (x, y_feet, self.zc))
            t0 = time.time()
            while time.time() - t0 < timeout:
                time.sleep(0.45)
                px, py, pz = self.feet()
                if px == x and abs(pz - self.zc) <= 1 and py >= y_feet:
                    aic.cmd('#stop')
                    return True
                if not aic.state().get('pathing'):
                    break
            aic.cmd('#stop')
        px, py, pz = self.feet()
        return px == x and py >= y_feet

    def refresh_h(self, x, h, pad=6):
        return WorldMem.refresh_near(x, self.zc, rx=pad,
                                     y_lo=h - 8, y_hi=h + 8)

    def dist_h(self, x, y, z):
        s = aic.state()
        return math.hypot(x + 0.5 - float(s['x']),
                          y + 0.5 - (float(s['y']) + 1.62),
                          z + 0.5 - float(s['z']))

    # ---------- 一列 ----------
    def column(self, x, h, h_prev):
        yf = (h_prev if h_prev is not None else h) + 1
        side = x + 1 if self.desc else x - 1
        if not self.stand_at(side, yf):
            px, py, pz = self.feet()
            return False, 'cannot stand at %d,%d (player %d,%d,%d)' % (side, yf, px, py, pz)

        wm = self.refresh_h(x, h)
        todo = []
        for z in range(self.z0, self.z1 + 1):
            t = wm.block(x, h, z)
            if is_cobble(t):
                self.skipped += 1
                continue
            todo.append(z)

        # 目标高度上的杂色先挖掉
        for z in list(todo):
            if solid(wm.block(x, h, z)):
                if not self.guard_tools():
                    return False, 'no pickaxe'
                if not self.dig_cell_at(x, h, z):
                    todo.remove(z)
                    self.failed += 1
                    say('x=%d z=%d h=%d 挖不动' % (x, z, h))
        if todo:
            wm = self.refresh_h(x, h)

        for z in todo:
            if not self.guard_hp():
                return False, 'hp low'
            if self.dist_h(x, h, z) > 4.0:
                if not self.approach_at(x, h, z):
                    self.failed += 1
                    say('x=%d z=%d h=%d 够不着' % (x, z, h))
                    continue

            # 桥板下层：h-1 是空气就垫一层，别做成纸片桥
            if not solid(wm.block(x, h - 1, z)):
                if aic.count_item(self.under) > 0 and self.dist_h(x, h - 1, z) <= 4.4:
                    aic.get('/place?x=%d&y=%d&z=%d&item=%s'
                            % (x, h - 1, z, self.under))
                    time.sleep(0.28)
                    wm = self.refresh_h(x, h)
                    if solid(wm.block(x, h - 1, z)):
                        self.dirt += 1

            aic.get('/place?x=%d&y=%d&z=%d&item=圆石' % (x, h, z))
            time.sleep(0.3)
            wm = self.refresh_h(x, h)
            if is_cobble(wm.block(x, h, z)):
                self.placed += 1
            else:
                aic.get('/place?x=%d&y=%d&z=%d&item=圆石' % (x, h, z))
                time.sleep(0.35)
                wm = self.refresh_h(x, h)
                if is_cobble(wm.block(x, h, z)):
                    self.placed += 1
                else:
                    self.failed += 1
                    say('x=%d z=%d h=%d 放置失败' % (x, z, h))

        # 护栏
        if self.rail:
            for z in (self.z0, self.z1):
                if self.dist_h(x, h + 1, z) > 4.0:
                    self.approach_at(x, h, z)
                if solid(wm.block(x, h + 1, z)):
                    continue
                aic.get('/place?x=%d&y=%d&z=%d&item=圆石' % (x, h + 1, z))
                time.sleep(0.25)
                wm = self.refresh_h(x, h)
                if is_cobble(wm.block(x, h + 1, z)):
                    self.rail_n += 1
        return True, 'ok'

    def dig_cell_at(self, x, y, z, tries=6):
        for _ in range(tries):
            wm = self.refresh_h(x, y)
            if not solid(wm.block(x, y, z)):
                return True
            aic.get('/dig?x1=%d&y1=%d&z1=%d&x2=%d&y2=%d&z2=%d' % (x, y, z, x, y, z))
            time.sleep(0.6)
        return not solid(self.refresh_h(x, y).block(x, y, z))

    def approach_at(self, x, y, z):
        for _ in range(2):
            if self.dist_h(x, y, z) <= 4.0:
                return True
            aic.cmd('#goto %d %d %d' % (x + 1, y + 1, z))
            t0 = time.time()
            while time.time() - t0 < 5:
                time.sleep(0.35)
                if self.dist_h(x, y, z) <= 4.0:
                    aic.cmd('#stop')
                    return True
                if not aic.state().get('pathing'):
                    break
            aic.cmd('#stop')
        return self.dist_h(x, y, z) <= 4.5

    # ---------- 主流程 ----------
    def run(self, x0, x1):
        hs = self.heights(x0, x1)
        a, b = min(x0, x1), max(x0, x1)
        say('方向: %s   桥面列 x %d..%d' % ('往西（站 x+1）' if self.desc else '往东（站 x-1）', a, b))
        say('拱高: %s' % ' '.join(str(hs[x]) for x in range(a, b + 1)))
        say('成本: 桥面 %d 格圆石 + 下层 %s + 护栏 %s'
            % (5 * (b - a + 1), self.under, 'yes' if self.rail else 'no'))
        order = range(x0, x1 - 1, -1) if self.desc else range(x0, x1 + 1)
        start_side = x0 + 1 if self.desc else x0 - 1
        self.travel(start_side)
        prev = hs.get(x0 + 1 if self.desc else x0 - 1)
        for x in order:
            if aic.count_item('圆石') < 8:
                say('圆石不足，停在 x=%d' % x)
                return x
            if defend.hostiles(radius=14):
                aura.hold_weapon()
                aura.ensure_aura()
                if not defend.fight_or_flee(safe_spot=(x + (8 if self.desc else -8),
                                                       hs[x] + 1, self.zc)):
                    say('打不过，撤')
                    return x
            ok, why = self.column(x, hs[x], prev)
            if not ok:
                say('STOP x=%d : %s' % (x, why))
                snap('bridge-%d' % x)
                return x
            say('x=%d h=%d ok  placed=%d under=%d rail=%d cobble=%d'
                % (x, hs[x], self.placed, self.dirt, self.rail_n, aic.count_item('圆石')))
            prev = hs[x]
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--x0', type=int, required=True)
    ap.add_argument('--x1', type=int, required=True)
    ap.add_argument('--deck', type=int, default=68)
    ap.add_argument('--z', type=int, default=272)
    ap.add_argument('--peak', type=int, default=4)
    ap.add_argument('--under', default='圆石')
    ap.add_argument('--rail', action='store_true')
    ap.add_argument('--min-hp', type=float, default=None)
    args = ap.parse_args()

    b = Bridge(args.deck, args.z, peak=args.peak, under=args.under,
               rail=args.rail, desc=args.x0 > args.x1, min_hp=args.min_hp)
    stop = b.run(args.x0, args.x1)
    print()
    print('=== summary ===')
    print('  placed=%d under=%d rail=%d skipped=%d failed=%d'
          % (b.placed, b.dirt, b.rail_n, b.skipped, b.failed))
    print('  cobble=%d' % aic.count_item('圆石'))
    if stop is not None:
        print('  stopped at x=%d' % stop)
    return 0


if __name__ == '__main__':
    sys.exit(main())
