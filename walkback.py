# -*- coding: utf-8 -*-
"""
walkback.py -- 长途行军：把玩家从任意位置走回某个坐标，带自动补发和保命。

为什麽需要它：
    `/back` 只回**最后一次**死亡点；`/home` 只回 /sethome 的地方。
    一旦「带床走 → 睡完拆床」把重生点废掉，死一次就会被扔回世界出生点
    （实测：-7910 淹死 → 直接出现在 (0,4,0)，离家 7900 格）。

行为：
    · 每 12 秒检查一次；`pathing=False` 就重新下发 `#goto`
    · 血量 < 10 就停下接战（kill-aura），血不够就吃
    · 到了就退出；可设 --minutes 上限

用法：
    python walkback.py --x -7910 --y 69 --z 272 --minutes 60
"""
import argparse
import math
import sys
import time

import aic
import aura
import defend


def say(*a):
    print('[%s] [walk]' % time.strftime('%H:%M:%S'), *a, flush=True)


def pos():
    s = aic.state()
    return (float(s['x']), float(s['y']), float(s['z'])), s


def dist(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--x', type=float, required=True)
    ap.add_argument('--y', type=float, required=True)
    ap.add_argument('--z', type=float, required=True)
    ap.add_argument('--minutes', type=float, default=60)
    ap.add_argument('--tolerance', type=float, default=6.0)
    ap.add_argument('--poll', type=float, default=12.0)
    args = ap.parse_args()

    goal = (args.x, args.y, args.z)
    t0 = time.time()
    last_d = None
    stuck = 0
    while time.time() - t0 < args.minutes * 60:
        try:
            p, s = pos()
            if not s.get('alive'):
                say('死了，等 keeplive 复活后重发')
                time.sleep(8)
                aic.cmd('#goto %d %d %d' % (args.x, args.y, args.z))
                continue
            d = dist(p, goal)
            if d <= args.tolerance:
                aic.cmd('#stop')
                say('到达 (%.0f,%.0f,%.0f)，剩余 %.1f' % (p[0], p[1], p[2], d))
                return 0
            if s.get('health', 20) < 10:
                aic.cmd('#stop')
                aura.ensure_aura()
                defend.defend(seconds=8.0)
                defend.eat_to_full()
            if not s.get('pathing'):
                stuck += 1
                if stuck % 3 == 1:
                    aic.cmd('#goto %d %d %d' % (args.x, args.y, args.z))
            if last_d is None or abs(d - last_d) > 2:
                say('剩余 %.0f 格  (%.0f,%.0f,%.0f) hp=%.0f' % (d, p[0], p[1], p[2], s.get('health', 0)))
                last_d = d
            time.sleep(args.poll)
        except Exception as e:
            say('error: %s' % e)
            time.sleep(5)
    say('超时退出')
    return 1


if __name__ == '__main__':
    sys.exit(main())
