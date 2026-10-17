# -*- coding: utf-8 -*-
"""
march.py -- 韧性长途行军：往目标走，死了就复活 + /back 回死亡点接着走。

为什么这么设计：
    `/back` 把玩家传回**最后一次死亡点**。于是"死"不再是惩罚，而是
    **推进的检查点** —— 死得越靠西，`/back` 之后起点就越靠西。
    所以这条路线的容错策略是：不躲怪、不绕路，死了就复活回死亡点继续。

用法：
    python march.py --x -570 --y 69 --z 272 --minutes 90
"""
import argparse
import math
import sys
import time

import aic
import aura
import defend


def say(*a):
    print('[%s] [march] %s' % (time.strftime('%H:%M:%S'), ' '.join(str(x) for x in a)), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--x', type=float, required=True)
    ap.add_argument('--y', type=float, required=True)
    ap.add_argument('--z', type=float, required=True)
    ap.add_argument('--minutes', type=float, default=90)
    ap.add_argument('--poll', type=float, default=12)
    ap.add_argument('--tol', type=float, default=10)
    args = ap.parse_args()

    goal = (args.x, args.y, args.z)
    aic.cmd('#set allowBreak true')
    aura.ensure_aura()
    say('目标 (%.0f,%.0f,%.0f)' % goal)

    t0 = time.time()
    best = 1e9
    deaths = 0
    backoff_ok = True
    while time.time() - t0 < args.minutes * 60:
        try:
            s = aic.state()
            p = (float(s['x']), float(s['y']), float(s['z']))
            d = math.hypot(p[0] - goal[0], p[2] - goal[2])

            if not s.get('alive'):
                deaths += 1
                say('死了(#%d) 在 (%.0f,%.0f,%.0f) → 复活 + /back' % (deaths, p[0], p[1], p[2]))
                try:
                    import revive
                    revive.respawn()
                except Exception:
                    pass
                time.sleep(2.5)
                if backoff_ok:
                    # /back 有 3 秒读条，**期间移动就取消**。
                    # 复活点常常在水里（实测 "传送已取消——你移动了"），
                    # 所以先按住潜行把浮动停住，再发传送。
                    aic.get('/input?k=SNEAK&down=true')
                    time.sleep(3.0)
                    aic.get('/chat?m=/back')
                    time.sleep(6.5)
                    aic.get('/input?k=SNEAK&down=false')
                s2 = aic.state()
                say('   回到 (%.0f,%.0f,%.0f)' % (s2['x'], s2['y'], s2['z']))
                # 不自动续跑：死了就停手。
                # Baritone 的 goal 在重生后仍然生效，脚本再补一发 #goto 的结果就是
                # 「一复活自己就走开」—— 用户一眼看出来"死了寻路还在跑"。
                aic.cmd('#stop')
                say('   已停手（不自动续跑）。要继续就重新运行 march.py')
                return 2

            if d < args.tol:
                aic.cmd('#stop')
                say('到达 (%.0f,%.0f,%.0f)，剩余 %.1f' % (p[0], p[1], p[2], d))
                return 0

            if d < best - 3:
                best = d
                say('剩余 %.0f 格  (%.0f,%.0f,%.0f) hp=%.0f' % (d, p[0], p[1], p[2], s['health']))

            if not s.get('pathing'):
                aic.cmd('#goto %d %d %d' % goal)
            time.sleep(args.poll)
        except Exception as e:
            say('error: %s' % e)
            time.sleep(5)

    say('超时退出，最近最好成绩 %.0f 格' % best)
    return 1


if __name__ == '__main__':
    sys.exit(main())
