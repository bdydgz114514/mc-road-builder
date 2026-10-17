import math
# -*- coding: utf-8 -*-
"""
mine.py -- 采石，边采边给自己补镐。

实测数据：
    石镐耐久 131 次 → 大约挖 120 块石头就报废
    Baritone #mine stone 速度 ≈ 1 块/秒
所以每采 ~100 块就要补一把镐，否则会拿铁剑去挖（慢十倍还毁耐久）。

本脚本的循环：
    1. 检查手持是不是镐 → 不是就先补
    2. 采 90 秒
    3. 回读圆石数量
    4. 镐没了 → 现场放工作台造 2 把（造完把工作台收回）
    5. 重复，直到达到目标数量或出现危险
"""
import argparse
import sys
import time

import aic
import toolkit
import storage

def _fl(v):
    # Minecraft 的格坐标 = floor(坐标)；int() 在负数上是向零截断，会多算 1 格
    return math.floor(float(v))


MIN_HEALTH = 12.0   # 默认保守；--min-hp 可覆盖（已 /sethome 时死一次只值 10 秒）
# 顺序 = 优先手持顺序：耐久高的排前面（石镐只有 131，两轮就断）
PICK_NAMES = ('下界合金镐', '钻石镐', '铁镐', '石镐', '铜镐', '木镐', '金镐')


def say(*a):
    print('  [mine]', *a)


def picks():
    inv = aic.inventory()
    return sum(i['total'] for i in inv.get('items', []) if i['item'] in PICK_NAMES)


def ensure_sticks(n=4, verbose=True):
    """保证背包里有 n 个木棍；不够就用原木现造（2x2 随身可做，不需要工作台）"""
    have = aic.count_item('木棍')
    if have >= n:
        return True
    need_planks = (n - have) * 2          # 2 木板 -> 4 木棍，一炉出 4 个
    planks = aic.count_item('橡木木板')
    if planks < 2:
        logs = aic.count_item('橡木原木')
        if logs < 1:
            say('no logs to make planks')
            return False
        for _ in range(2):                # 1 原木 -> 4 木板，造两次保险
            r = toolkit.craft('橡木木板', 1)
            time.sleep(0.4)
            if verbose:
                say('craft planks: %s' % r)
            if aic.count_item('橡木木板') >= 2:
                break
    r = toolkit.craft('木棍', 1)
    time.sleep(0.4)
    if verbose:
        say('craft sticks: %s (now %d)' % (r, aic.count_item('木棍')))
    return aic.count_item('木棍') >= n


def make_picks(n=2):
    """现场造镐（走 toolkit 的统一链路：工作台可达性 + 木棍 + 铁镐优先）"""
    before = picks()
    ok = toolkit.ensure_tools(verbose=True)
    after = picks()
    if after > before:
        say('picks %d -> %d' % (before, after))
    elif not ok:
        say('ensure_tools failed (picks=%d)' % after)
    return after - before


def held_is_pick():
    """手持到底是不是镐 —— 必须读 state，不能相信 /hold 的返回值"""
    s = aic.state()
    held = str((s.get('held') or {}).get('item') or '')
    return any(k in held for k in PICK_NAMES), held


def hold_pick():
    for name in PICK_NAMES:
        r = aic.get('/hold?item=%s' % name)
        if 'holding' in str(r.get('result', '')) and name in str(r.get('result', '')):
            s = aic.state()
            if name in str((s.get('held') or {}).get('item')):
                return name
    return None


def main():
    global MIN_HEALTH
    ap = argparse.ArgumentParser()
    ap.add_argument('--want', type=int, default=400)
    ap.add_argument('--rounds', type=int, default=20)
    ap.add_argument('--min-hp', type=float, default=None)
    args = ap.parse_args()
    if args.min_hp is not None:
        MIN_HEALTH = float(args.min_hp)

    s = aic.state()
    say('start hp=%.0f cobble=%d picks=%d' % (s['health'], aic.count_item('圆石'), picks()))

    total0 = aic.count_item('圆石')
    for rnd in range(args.rounds):
        s = aic.state()
        if not s.get('alive'):
            say('dead, stop')
            break
        if s['health'] < MIN_HEALTH:
            say('health %.0f, stop' % s['health'])
            break
        got = aic.count_item('圆石')
        if got >= args.want:
            say('target reached (%d)' % got)
            break

        # 1) 手持必须是镐 —— 而且是**读 state 验证**过的镐
        ok, held = held_is_pick()
        if not ok:
            say('held=%s (not a pickaxe) -> making picks' % held)
            if picks() < 2:
                make_picks(2)
            if not hold_pick():
                say('cannot hold a pickaxe -> abort')
                break
            ok, held = held_is_pick()
            if not ok:
                say('still holding %s -> abort (不用斧头/空手砸石头)' % held)
                break

        # 1.5) 背包快满就先存/丢，否则挖出来捡不起来
        if storage.free_slots() < 4:
            say('pack nearly full (free=%d) -> making space' % storage.free_slots())
            storage.ensure_space(8)

        # 2) 采 90 秒。**每 3 秒查一次手持**：
        #    镐在这个窗口里断掉的话，Minecraft 的自动选工具会退到斧头/空手，
        #    然后就是"拿铁斧砸石头"—— 慢十倍还毁斧头。一发现不是镐立刻停。
        aic.cmd('#mine stone')
        t0 = time.time()
        broke = False
        bad_streak = 0
        while time.time() - t0 < 90:
            time.sleep(3)
            st = aic.state()
            if not st.get('alive') or st['health'] < MIN_HEALTH:
                break
            # 判据一：背包里还有没有镐。这是唯一确定"真断了"的证据。
            if picks() == 0:
                aic.cmd('#stop')
                time.sleep(0.8)
                say('背包里没有镐了 → 立刻停挖')
                broke = True
                break
            # 判据二：连续 2 次拿着斧/锹/剑/手 —— 那是真的在拿错工具砸石头。
            # 注意"变成圆石"不算：Meteor 的 AutoTool 在方块之间会瞬时切回原物品，
            # 按手持字符串一刀切会把正常挖矿误判成故障（实测连停 5 轮）。
            held = str((st.get('held') or {}).get('item') or '')
            if any(k in held for k in ('斧', '锹', '剑', '锄')) or held == '':
                bad_streak += 1
                if bad_streak >= 2:
                    aic.cmd('#stop')
                    time.sleep(0.8)
                    say('连续拿着 %s 挖石头 → 立刻停挖' % held)
                    broke = True
                    break
            else:
                bad_streak = 0
        aic.cmd('#stop')
        time.sleep(1.0)
        if broke:
            hold_pick() or make_picks(2)
            hold_pick()

        s = aic.state()
        cob = aic.count_item('圆石')
        say('round %2d: cobble=%d (+%d) picks=%d hp=%.0f y=%d'
            % (rnd + 1, cob, cob - total0, picks(), s['health'], _fl(s['y'])))
        if aic.count_item('圆石') < 12:
            say('no cobble gained -- stopping')
            break

    print()
    print('=== summary ===')
    print('  cobble %d -> %d' % (total0, aic.count_item('圆石')))
    print('  picks=%d' % picks())
    s = aic.state()
    print('  hp=%.0f at (%d,%d,%d)' % (s['health'], _fl(s['x']), _fl(s['y']), _fl(s['z'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
