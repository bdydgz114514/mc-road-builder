# -*- coding: utf-8 -*-
"""
storage.py -- 背包满了就原地造箱子存起来，然后继续干活。

用户指出的问题：背包 36/36 满了以后，挖出来的圆石掉在地上捡不起来，
但 Baritone 还在挖 —— 全是白挖。

本模块提供：
    free_slots()        还剩几个空格
    make_chest()        现场造一个箱子（8 木板，需要工作台）
    stash(item, keep)   把某样东西存进最近的箱子，只留 keep 个
    ensure_space(minf)  保证至少有 minf 个空格；不够就先存
"""
import time

import aic
import toolkit


def free_slots():
    inv = aic.inventory()
    used = set()
    for i in inv.get('items', []):
        used.update(i['slots'])
    return inv['slots'] - len(used)


def say(*a):
    print('  [storage]', *a)


def near_chest(radius=24):
    """找一个能走到的箱子"""
    r = aic.scan('箱子', radius, 60)
    blocks = r.get('blocks', [])
    if not blocks:
        return None
    blocks.sort(key=lambda b: b['dist'])
    for b in blocks[:5]:
        # 检查玩家能否走到它旁边（不真的走，先按距离筛）
        if b['dist'] <= 4.0:
            return (b['x'], b['y'], b['z'])
    return None


def make_chest():
    """现场造一个箱子并放下。返回箱子坐标或 None。"""
    if aic.count_item('箱子') == 0:
        planks = toolkit.count_wood('木板')
        if planks < 8:
            logs = toolkit.count_wood('原木')
            if logs < 2:
                say('no planks/logs for a chest')
                return None
            for _ in range(3):
                toolkit.craft('橡木木板', 1)
                time.sleep(0.4)
                if toolkit.count_wood('木板') >= 8:
                    break
        if toolkit.count_wood('木板') < 8:
            say('still not enough planks (%d/8)' % toolkit.count_wood('木板'))
            return None
        bench = toolkit.ensure_workbench()
        if not bench:
            say('no workbench for chest')
            return None
        toolkit.open_at(bench)
        time.sleep(1.0)
        r = toolkit.craft('箱子', 1)
        time.sleep(0.6)
        aic.get('/container?op=close')
        time.sleep(0.3)
        # 工作台收回
        aic.get('/dig?x1=%d&y1=%d&z1=%d&x2=%d&y2=%d&z2=%d&only=工作台'
                % (bench[0], bench[1], bench[2], bench[0], bench[1], bench[2]))
        time.sleep(1.0)
        say('craft chest: %s (now %d)' % (r, aic.count_item('箱子')))
        if aic.count_item('箱子') == 0:
            return None

    # 放箱子：找 2-3 格外的空地
    spot = None
    s = aic.state()
    px, py, pz = int(s['x']), int(s['y']), int(s['z'])
    from worldmem import WorldMem
    wm = WorldMem.refresh(px - 4, py - 2, pz - 4, px + 4, py + 3, pz + 4)
    for dist in (2, 3, 1):
        for dz in range(-dist, dist + 1):
            for dx in range(-dist, dist + 1):
                if max(abs(dx), abs(dz)) != dist:
                    continue
                for dy in (0, -1):
                    pos = (px + dx, py + dy, pz + dz)
                    if (pos[0], pos[1], pos[2]) not in wm.blocks and \
                       wm.is_solid(pos[0], pos[1] - 1, pos[2]):
                        spot = pos
                        break
                if spot:
                    break
            if spot:
                break
        if spot:
            break
    if not spot:
        say('no room to place a chest')
        return None

    r = aic.get('/place?x=%d&y=%d&z=%d&item=箱子' % spot)
    res = str(r.get('result', ''))
    time.sleep(0.4)
    g = aic.dump(spot[0], spot[1], spot[2], spot[0], spot[1], spot[2], maxn=4)
    now = g.get(spot)
    if now and '箱子' in str(now):
        say('chest placed at %s' % (spot,))
        return spot
    say('chest placement failed: %s (cell=%s)' % (res[:40], now))
    return None


def stash(item, keep=0, chest=None, allow_make=True):
    """把 item 存进箱子，只留 keep 个。返回存进去的数量。"""
    if aic.count_item(item) <= keep:
        return 0
    pos = chest or near_chest() or (make_chest() if allow_make else None)
    if not pos:
        say('no chest available')
        return 0
    before = aic.count_item(item)
    r = aic.get('/container?op=open&x=%d&y=%d&z=%d' % pos)
    if 'interacted' not in str(r.get('result', '')):
        say('cannot open chest: %s' % r.get('result'))
        return 0
    time.sleep(1.0)
    aic.get('/container?op=put&item=%s' % item)
    time.sleep(0.6)
    aic.get('/container?op=close')
    time.sleep(0.3)
    after = aic.count_item(item)
    say('stashed %d x %s (at %s)' % (before - after, item, pos))
    return before - after


def withdraw(item, n=64, chest=None):
    """从箱子里取东西（put 的反向）。返回实际取到的数量。"""
    pos = chest or near_chest() or None
    if not pos:
        say('no chest in reach to withdraw from')
        return 0
    before = aic.count_item(item)
    r = aic.get('/container?op=open&x=%d&y=%d&z=%d' % pos)
    if 'interacted' not in str(r.get('result', '')):
        say('cannot open chest %s: %s' % (pos, r.get('result')))
        return 0
    time.sleep(1.0)
    res = aic.get('/container?op=take&item=%s&n=%d' % (item, n))
    time.sleep(0.6)
    aic.get('/container?op=close')
    time.sleep(0.3)
    after = aic.count_item(item)
    say('withdrew %d x %s (at %s) %s' % (after - before, item, pos, res.get('result', '')[:40]))
    return after - before


# 建造时**不能**被存走的东西：这是路面材料和路基材料，存走了就铺不动
BUILD_MATERIALS = ('圆石', '泥土')

# 纯垃圾，背包紧的时候优先扔掉
JUNK = ('安山岩', '花岗岩', '闪长岩', '沙砾', '腐肉', '小麦种子', '玩家的头', '火药', '青金石', '虞美人', '蒲公英', '沙子', '重质测重压力板', '甘蔗',
        '羽毛', '矢车菊', '橡树树苗', '白桦树苗', '生鸡肉')


def ensure_space(minfree=4, verbose=True, protect=BUILD_MATERIALS):
    """保证至少 minfree 个空格。

    以前的坑：挖完一轮就把 331 块圆石整组塞进箱子（只剩 110），
    然后铺路时"材料不足"。**建造材料不该被当杂物囤起来**。
    而且造箱子要 8 木板，建造期经常没有 —— 缺料时它会去现造箱子、失败、
    再失败一次，白白烧掉一分钟。现在只在有现成箱子时才存东西。
    """
    f = free_slots()
    if f >= minfree:
        return True
    if verbose:
        say('pack full (free=%d), making space' % f)

    # 1) 先扔纯杂物
    for item in JUNK:
        if free_slots() >= minfree:
            return True
        if aic.count_item(item) <= 0:
            continue
        aic.get('/drop?item=%s&all=true' % item)
        time.sleep(0.7)
        if verbose:
            say('dropped a stack of %s' % item)
    if free_slots() >= minfree:
        return True

    # 2) 只用**现成的**箱子，不现造
    if '泥土' not in protect:
        stash('泥土', keep=64, allow_make=False)
    if free_slots() >= minfree:
        return True
    if '圆石' not in protect:
        if verbose:
            say('still tight (free=%d) -> stashing cobble, keeping 192' % free_slots())
        stash('圆石', keep=192, allow_make=False)

    if free_slots() < minfree and verbose:
        say('still full (free=%d) -- 继续干活，放置会腾出格子' % free_slots())
    return free_slots() >= minfree
