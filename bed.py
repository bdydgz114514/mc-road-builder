# -*- coding: utf-8 -*-
"""
bed.py -- 带床走：造床 → 就地放 → 睡到早上 → 把床拆回背包。

为什么不做"回家睡觉"：
    工地离家 300+ 格，来回一趟 4~6 分钟，而且夜里路上正是被僵尸/苦力怕杀的高发段。
    带一张床在身上，走到哪睡到哪，睡醒拆掉带走 —— 只多占 1 个格子。

硬要求（Minecraft 规则）：
    · 床占两格：脚 + 头。头放在玩家**面朝**的方向，所以放之前要把 yaw 摆正。
    · 周围 8 格内不能有怪物，否则"你现在不能休息"。所以要先用 kill-aura 清场。
    · 睡醒（进入白天）才算成功；只靠返回值不可信，必须看 /time。

用法：
    python bed.py --status        现在有没有床 / 附近有没有床
    python bed.py --craft         造床（3 白色羊毛 + 3 橡木木板，需工作台）
    python bed.py --sleep         就地铺床 → 睡 → 拆床（一整个周期）
"""
import argparse
import math
import sys
import time

import aic
import toolkit
from worldmem import WorldMem

BED = '床'
# ⚠️ 物品名是「白色床」不是「床」，而 aic.count_item 是**精确匹配** ——
# 造床成功后 count_item('床') 仍然是 0，白折腾半天。一律用包含匹配。
BED_MATCH = '床'
DEFAULT_BED_ITEM = '白色床'
AIR = ('空气', '洞穴空气', '虚空空气')
# 放床时优先试的方向：先沿路方向找空地
DIRS = ((1, 0, -90.0), (-1, 0, 90.0), (0, 1, 0.0), (0, -1, 180.0))


def say(*a):
    print('  [bed]', *a, flush=True)


def solid(t):
    return t is not None and t not in AIR


def feet():
    s = aic.state()
    return (math.floor(float(s['x'])), math.floor(float(s['y'])),
            math.floor(float(s['z'])))


def bed_item_name():
    """背包里那张床的**真实**物品名（白色床 / 红色床 …）。"""
    for i in aic.inventory().get('items', []):
        if BED_MATCH in i['item']:
            return i['item']
    return DEFAULT_BED_ITEM


def have_bed():
    """按包含匹配数床 —— 别用 count_item('床')。"""
    return sum(i['total'] for i in aic.inventory().get('items', [])
               if BED_MATCH in i['item'])


def ensure_bed(verbose=True):
    """没有床就现造。3 白色羊毛 + 3 橡木木板，需要工作台（羊毛在第 1 行第 3 列，
    2x2 随身合成装不下，所以必须是真工作台）。"""
    if have_bed() > 0:
        return True
    if aic.count_item('白色羊毛') < 3:
        if verbose:
            say('没有白色羊毛（需要 3）—— 去剪/杀羊或回家取')
        return False
    if toolkit.count_wood('木板') < 3:
        if verbose:
            say('木板不够（需要 3）')
        return False
    bench = toolkit.ensure_workbench()
    if not bench:
        if verbose:
            say('没有工作台')
        return False
    res = toolkit.craft_clean(bench, BED, 1, verbose=verbose)
    if verbose:
        say('造床: %s' % res)
    return have_bed() > 0

def scan_bed(radius=12):
    """在附近找床（返回 [(x,y,z), ...]）。"""
    px, py, pz = feet()
    try:
        wm = WorldMem.refresh_near(px, pz, rx=radius, y_lo=py - 4, y_hi=py + 3)
    except Exception as e:
        say('scan failed: %s' % e)
        return []
    out = []
    for (bx, by, bz), t in wm.blocks.items():
        if BED_MATCH in str(t):
            out.append((bx, by, bz))
    return out


def place_bed(verbose=True):
    """就地铺床。返回床的坐标（脚那一格）或 None。"""
    if have_bed() <= 0 and not ensure_bed(verbose=verbose):
        return None
    px, py, pz = feet()
    try:
        wm = WorldMem.refresh_near(px, pz, rx=8, y_lo=py - 3, y_hi=py + 3)
    except Exception as e:
        say('place: cannot read world (%s)' % e)
        return None

    for (dx, dz, yaw) in DIRS:
        foot = (px + dx * 2, py, pz + dz * 2)
        head = (px + dx * 3, py, pz + dz * 3)
        if any(not wm.in_box(*c) for c in (foot, head)):
            continue
        if solid(wm.block(*foot)) or solid(wm.block(*head)):
            continue
        if not solid(wm.block(foot[0], foot[1] - 1, foot[2])):
            continue
        if not solid(wm.block(head[0], head[1] - 1, head[2])):
            continue
        aic.get('/look?yaw=%.0f&pitch=20' % yaw)
        time.sleep(0.4)
        item = bed_item_name()
        r = aic.get('/place?x=%d&y=%d&z=%d&item=%s' % (foot[0], foot[1], foot[2], item))
        res = str(r.get('result', ''))
        time.sleep(0.6)
        got = scan_bed(10)
        if got:
            if verbose:
                say('床放好了 %s（%s）' % (got[0], res[:40]))
            return got[0]
        if verbose:
            say('放床失败 foot=%s: %s' % (foot, res[:60]))
    if verbose:
        say('附近找不到能放床的 2 格空地')
    return None


def sleep_until_morning(bedpos, timeout=40, verbose=True):
    """右键床直到天亮。返回 True 表示真的到早上了。"""
    aic.get('/look?yaw=%.0f&pitch=25' % 0)      # 先把视线摆低，右键更容易命中
    t0 = time.time()
    t, day, _ = _time()
    while time.time() - t0 < timeout:
        # 对准床
        s = aic.state()
        dx = (bedpos[0] + 0.5) - float(s['x'])
        dz = (bedpos[2] + 0.5) - float(s['z'])
        dy = (bedpos[1] + 0.5) - (float(s['y']) + 1.62)
        horiz = math.hypot(dx, dz)
        yaw = math.degrees(math.atan2(-dx, dz))
        pitch = math.degrees(math.atan2(-dy, horiz))
        aic.get('/look?yaw=%.1f&pitch=%.1f' % (yaw, pitch))
        time.sleep(0.25)
        aic.get('/input?k=CLICK_RIGHT&down=true')
        time.sleep(0.15)
        aic.get('/input?k=CLICK_RIGHT&down=false')
        time.sleep(1.2)
        tt, dd, _ = _time()
        if dd or tt < t or (t > 12000 and tt < 12000):
            if verbose:
                say('睡到早上了（t=%d）' % tt)
            return True
    if verbose:
        say('没能睡着（可能周围有怪物/没对准/白天了）')
    return False


def _time():
    r = aic.get('/time')
    return int(r.get('ticks', 0)), bool(r.get('day')), str(r.get('phase', '?'))


def pickup_bed(verbose=True):
    """把床拆回背包（两格都要挖）。"""
    cells = scan_bed(10)
    if not cells:
        return True
    before = have_bed()
    for c in cells:
        aic.get('/dig?x1=%d&y1=%d&z1=%d&x2=%d&y2=%d&z2=%d' % (c + c))
        time.sleep(0.8)
    time.sleep(0.8)
    after = have_bed()
    if verbose:
        say('拆床 %d 格，床 %d -> %d' % (len(cells), before, after))
    return after >= 1


def sleep_cycle(verbose=True):
    """一整个周期：铺床 → 睡 → 拆床。返回是否睡到了早上。"""
    tt, dd, ph = _time()
    if dd:
        if verbose:
            say('现在是白天，不用睡')
        return True
    # 清场：8 格内有怪睡不了
    import defend
    import aura
    if defend.hostiles(radius=10):
        aura.hold_weapon()
        aura.ensure_aura()
        defend.defend(seconds=8.0)
    bedpos = place_bed(verbose=verbose)
    if not bedpos:
        return False
    ok = sleep_until_morning(bedpos, verbose=verbose)
    pickup_bed(verbose=verbose)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--craft', action='store_true')
    ap.add_argument('--sleep', action='store_true')
    args = ap.parse_args()

    if args.status or not (args.craft or args.sleep):
        tt, dd, ph = _time()
        print('time   ticks=%d day=%s phase=%s' % (tt, dd, ph))
        print('bed    %d' % have_bed())
        print('wool   %d   planks %d' % (aic.count_item('白色羊毛'), toolkit.count_wood('木板')))
        print('nearby beds: %s' % (scan_bed(12)[:4] or 'none'))
        return 0
    if args.craft:
        print('craft ->', ensure_bed())
        return 0
    if args.sleep:
        print('sleep cycle ->', sleep_cycle())
        return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
