# -*- coding: utf-8 -*-
"""
shaft.py -- 从地下挖一条 1x1 竖井爬回地表。

为什么需要它：
    被扔到世界出生点后，人卡在 y=-36 的深板岩小空腔里 —— `air-jump` 能一次跳 0.65 格，
    但头顶是实心深板岩，跳不上去。只能「挖掉头顶那格 → 跳进去 → 再挖」。

要点：
    · 每格都回读确认变空气，不信 /dig 的返回值
    · 碰到水/岩浆/基岩立刻停（挖穿水层会被冲下去，基岩根本挖不动）
    · 手持必须是镐（按材料选：深板岩=镐）
    · air-jump + no-fall 常开，靠跳跃上升，不用垫方块

用法：
    python shaft.py --target 70
"""
import argparse
import math
import sys
import time

import aic
import toolkit

AIR = ('空气', '洞穴空气', '虚空空气')
BAD = ('水', '流动的水', '岩浆', '岩浆块', '基岩')


def say(*a):
    print('  [shaft]', *a, flush=True)


def solid(t):
    return t is not None and t not in AIR


def feet():
    s = aic.state()
    return (math.floor(float(s['x'])), math.floor(float(s['y'])),
            math.floor(float(s['z'])))


def cell(x, y, z):
    """读单格（用小盒子，够快）"""
    from worldmem import WorldMem
    wm = WorldMem.refresh(x, y, z, x, y, z)
    return wm.block(x, y, z)


def jump(n=2, hold=0.1, gap=0.22):
    for _ in range(n):
        aic.get('/input?k=JUMP&down=true')
        time.sleep(hold)
        aic.get('/input?k=JUMP&down=false')
        time.sleep(gap)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', type=int, default=70)
    ap.add_argument('--max-blocks', type=int, default=200)
    args = ap.parse_args()

    for m in ('air-jump', 'no-fall', 'anti-void'):
        aic.get('/module?m=%s&on=true' % m)
    s = aic.state()
    say('start (%d,%d,%d) hp=%.0f target y=%d'
        % (feet() + (s['health'], args.target)))
    if not toolkit.hold_tool('pick'):
        toolkit.ensure_tools()
        toolkit.hold_tool('pick')

    dug = 0
    stuck = 0
    while True:
        x, y, z = feet()
        s = aic.state()
        if not s.get('alive'):
            say('死了，停')
            return 1
        if s['health'] < 3:
            say('血 %.0f，太危险，停' % s['health'])
            return 1
        if y >= args.target:
            say('到达 y=%d（挖了 %d 格）' % (y, dug))
            return 0
        if dug > args.max_blocks:
            say('超过 %d 格上限，停' % args.max_blocks)
            return 1

        # 找**头顶第一格实心**（y+2 可能已经是空气 —— 2 格高的气泡里就是这种情况，
        # 以前只挖 y+2，于是一直判定"是空气"、反复跳、跳不上去就放弃）
        above = None
        t = None
        for dy in (2, 3, 4, 5):
            cand = (x, y + dy, z)
            tc = cell(*cand)
            if tc is None:
                say('读不到 (未加载)，停')
                return 1
            if any(k in str(tc) for k in BAD):
                say('头顶 y=%d 是 %s —— 停止挖掘' % (y + dy, tc))
                return 1
            if solid(tc):
                above, t = cand, tc
                break
        if above is None:
            # 5 格内全是空气：直接跳
            before = feet()[1]
            jump(3)
            if feet()[1] <= before:
                stuck += 1
                say('跳不上去 (y=%d)%s' % (before, ' —— 放弃' if stuck >= 5 else ''))
                if stuck >= 5:
                    return 1
                time.sleep(0.4)
            else:
                stuck = 0
            continue
        if solid(t):
            if not toolkit.hold_tool('pick'):
                say('没镐了，停')
                return 1
            aic.get('/dig?x1=%d&y1=%d&z1=%d&x2=%d&y2=%d&z2=%d'
                    % (above + above))
            ok = False
            for _ in range(8):
                time.sleep(0.45)
                if not solid(cell(*above)):
                    ok = True
                    break
            if not ok:
                say('( %d,%d,%d ) %s 挖不动' % (above[0], above[1], above[2], t))
                stuck += 1
                if stuck >= 4:
                    return 1
                continue
            dug += 1
            stuck = 0
        else:
            # 已经是空气：跳上去
            before = feet()[1]
            jump(3)
            if feet()[1] <= before:
                stuck += 1
                say('跳不上去 (y=%d)%s' % (before, ' —— 放弃' if stuck >= 5 else ''))
                if stuck >= 5:
                    return 1
                time.sleep(0.4)
            else:
                stuck = 0
        if dug and dug % 10 == 0:
            say('已挖 %d 格，现在 y=%d hp=%.0f' % (dug, feet()[1], aic.state()['health']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
