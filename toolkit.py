import math
# -*- coding: utf-8 -*-
"""
toolkit.py -- self-repairing tools. Carry a workbench, rebuild on the spot.

The gap this closes: /craft existed but nothing ever called it. A pickaxe would break
and the pipeline would just keep issuing /dig and /place with empty hands, silently
doing nothing. Now every worker calls ensure_tools() first.

Everything happens where the player stands:
    1. if no pickaxe: make sure a workbench exists (craft one if needed)
    2. place it next to the player, right-click it, craft the pickaxe
    3. pick the workbench back up so it stays in the pack

Usage:
    python toolkit.py --check          show the pack snapshot
    python toolkit.py --ensure         repair tools if needed
    from toolkit import ensure_tools   call it from any worker loop
"""
import argparse
import sys
import time

import aic

def _fl(v):
    # Minecraft 的格坐标 = floor(坐标)；int() 在负数上是向零截断，会多算 1 格
    return math.floor(float(v))


# cost of one pickaxe, in raw materials
# 优先铁镐：耐久 250（石镐 131），挖得也快；背包里铁锭够就直接上铁
PICK_RECIPES = ['铁镐', '石镐']

# ── 工具分类 ────────────────────────────────────────────────────────────
# 用错工具不是"也能挖"，是**白白烧耐久**：石镐 131 次、石锹 131 次，
# 拿镐子挖泥土既不加速又照扣耐久。实测背包里一把锹都没有，
# 于是整段草方块/泥土都是拿镐子硬挖的（用户一眼看出来"不要用镐子挖土"）。
PICK_NAMES = ('下界合金镐', '钻石镐', '铁镐', '石镐', '铜镐', '木镐', '金镐')
SHOVEL_NAMES = ('下界合金锹', '钻石锹', '铁锹', '石锹', '铜锹', '木锹', '金锹')
AXE_NAMES = ('下界合金斧', '钻石斧', '铁斧', '石斧', '铜斧', '木斧', '金斧')

SOFT_MATS = ('泥土', '草方块', '沙', '沙砾', '黏土', '雪', '菌丝', '耕地',
             '泥巴', '灵魂沙', '灰化土', '根土', '苔藓', '砂土', '粗泥')
WOOD_MATS = ('原木', '木板', '工作台', '箱子', '栅栏', '门', '台阶', '梯子',
             '告示牌', '活板门', '木')


def tool_kind(block):
    """这块方块该用什么：'shovel' / 'axe' / 'pick'。"""
    b = str(block or '')
    if any(k in b for k in SOFT_MATS):
        return 'shovel'
    if any(k in b for k in WOOD_MATS):
        return 'axe'
    return 'pick'


def _count(names):
    inv = aic.inventory()
    return sum(i['total'] for i in inv.get('items', []) if i['item'] in names)


# ── 树种无关的木材计数 ──────────────────────────────────────────────────
# 模组的合成表写的是「橡木」，但在云杉林里造出来的产物叫「云杉木板」。
# aic.count_item 是精确匹配 → 造成功了也数不到（实测 7 个云杉原木被判成
# "no planks, no logs"，一把镐都造不出来）。
WOOD_SUFFIX = ('木板', '原木', '木棍', '台阶', '栅栏', '告示牌', '门', '活板门')


def wood_key(item):
    """把「橡木木板」这类名字压成树种无关的键：木板 / 原木 / 木棍 …"""
    for k in WOOD_SUFFIX:
        if str(item).endswith(k):
            return k
    return str(item)


def count_wood(key):
    """按树种无关的键数背包里的东西。key 传 '木板' / '原木' / '木棍' 或具体物品名。"""
    total = 0
    for i in aic.inventory().get('items', []):
        name = i['item']
        if wood_key(name) == key or name == key:
            total += i['total']
    return total


def count_shovels():
    return _count(SHOVEL_NAMES)


def count_axes():
    return _count(AXE_NAMES)


def ensure_shovel(n=2, verbose=True):
    """保证有锹。没有锹时挖土 = 拿镐子硬挖，纯亏耐久。"""
    if count_shovels() >= n:
        return True
    bench = ensure_workbench()
    if not bench:
        if verbose:
            say('no workbench -> cannot make a shovel')
        return False
    ensure_sticks(4 * n, verbose=verbose)
    if count('圆石') < n:
        if verbose:
            say('no cobble for a shovel')
        return False
    for _ in range(n + 1):
        if count_shovels() >= n:
            break
        res = craft_clean(bench, '石锹', 1, verbose=False)
        if verbose:
            say('石锹: %s' % res)
        if not res.startswith('crafted'):
            break
    return count_shovels() >= n


def hold_tool(kind='pick'):
    """按用途切手持。返回实际持到的物品名（失败返回 None）。"""
    names = {'pick': PICK_NAMES, 'shovel': SHOVEL_NAMES, 'axe': AXE_NAMES}.get(kind, PICK_NAMES)
    for name in names:
        r = aic.get('/hold?item=%s' % name)
        if 'holding' in str(r.get('result', '')):
            held = str((aic.state().get('held') or {}).get('item') or '')
            if name in held:
                return name
    return None


def pack():
    return aic.get('/pack')


def count(name):
    return aic.count_item(name)


def free_slots():
    inv = aic.inventory()
    used = set()
    for i in inv['items']:
        used.update(i['slots'])
    return inv['slots'] - len(used)


def say(*a):
    print('  [toolkit]', *a)


def craft(item, n=1):
    r = aic.get('/craft?item=%s&n=%d' % (item, n))
    return str(r.get('result', ''))


def craft_clean(bench, item, n=1, verbose=True):
    """干净的合成：**先关掉界面再重开**，然后用物品数量变化判定成败。

    实测踩的坑（代价 60 块圆石）：某个配方缺料失败时，mod 已经把材料摆进了
    3x3 网格，失败分支直接 return，网格和光标上的东西就留在那儿。
    下一次合成被上一次的残留污染 —— 表现是 craft('铁镐') 之后
    背包里的圆石整组消失、槽位被别的物品占了，而返回值还写着 crafted。

    所以：
        1. 每次合成前 /container?op=close + open_at(bench)，网格必定是空的
        2. 不看 'crafted' 字样，只信 count() 有没有真的变多
    """
    try:
        aic.get('/container?op=close')
    except Exception:
        pass
    time.sleep(0.25)
    # 背包满 36/36 时，shift-click 取不出成品 —— 结果槽会一直挂着那张镐，
    # 返回值还写 "crafted 1 x 石镐"。所以合成前必须先腾格子。
    try:
        import storage as _storage
        if _storage.free_slots() < 2:
            _storage.ensure_space(4)
    except Exception:
        pass
    opened = open_at(bench)
    if 'interacted' not in str(opened):
        return 'cannot-open:%s' % opened
    time.sleep(0.8)
    before = count_wood(wood_key(item))
    res = craft(item, n)
    time.sleep(0.7)
    after = count_wood(wood_key(item))
    if after == before:
        # 实测：/craft 有时把成品留在输出槽（shift-click 没生效），
        # 网格里的材料也还在 —— 表现是"crafted 1 x 石镐"但背包一件没多。
        # 直接把 slot 0（输出槽）快速移动一次就能取出来。
        aic.get('/container?op=move&slot=0')
        time.sleep(0.6)
        after = count_wood(wood_key(item))
    aic.get('/container?op=close')
    time.sleep(0.2)
    if after > before:
        return 'crafted %d x %s' % (after - before, item)
    return 'failed:%s (count %d -> %d)' % (res, before, after)


def craft_any(item, n=1, verbose=True):
    """不需要工作台的**干净**合成（木板/木棍/工作台这类 2x2 就能做的）。

    为什么不能直接 craft()：
        mod 的 craftItem 把材料摆进网格后**不会清网格**。连着做「木板→工作台」时，
        第二步把木板摆进了还留着原木的脏格子 → 配方不成立 → 输出槽空 →
        返回 "missing-material"，看起来像缺料。实测就是这么卡住的。
    做法：每次合成前 /container?op=close（关界面会把网格里的东西退回背包），
    然后用**数量变化**判定成败；数量没涨就 move slot=0 把输出槽的成品取出来。
    """
    try:
        aic.get('/container?op=close')
    except Exception:
        pass
    time.sleep(0.3)
    key = wood_key(item)
    before = count_wood(key)
    res = craft(item, n)
    time.sleep(0.7)
    after = count_wood(key)
    if after == before:
        aic.get('/container?op=move&slot=0')
        time.sleep(0.5)
        after = count_wood(key)
    try:
        aic.get('/container?op=close')
    except Exception:
        pass
    time.sleep(0.2)
    if after > before:
        return 'crafted %d x %s' % (after - before, item)
    return 'failed:%s (count %d -> %d)' % (res, before, after)


def ensure_sticks(need=4, verbose=True):
    """保证背包里有 need 根木棍。镐子的真正瓶颈一直是木棍，不是石头/铁。"""
    have = count('木棍')
    if have >= need:
        return True
    # 木棍 = 2 木板 -> 4 根，所以每 4 根要 2 块木板
    want_planks = max(2, ((need - have + 3) // 4) * 2)
    while count_wood('木板') < want_planks:
        if count_wood('原木') < 1:
            if verbose:
                say('no logs left for planks')
            return False
        r = craft_any('橡木木板', 1, verbose=verbose)
        time.sleep(0.5)
        if verbose:
            say('craft planks: %s (planks=%d)' % (r, count_wood('木板')))
        if 'crafted' not in r and count_wood('木板') < want_planks:
            break
    for _ in range(4):
        if count('木棍') >= need:
            break
        r = craft('木棍', 1)
        time.sleep(0.5)
        if verbose:
            say('craft sticks: %s (sticks=%d)' % (r, count('木棍')))
    return count('木棍') >= need


def find_spots(limit=8):
    """候选放置点，按"离得近但别贴脸"排序。

    以前只返回**一个**候选，`/place` 报 cannot-place-here 就整条链断了
    （地下矿道里实测就是这样：造不出工作台 → 造不出镐 → 挖矿白跑一整轮）。
    现在按距离 2 → 3 → 1 排出一串，调用方逐个试。
    """
    s = aic.state()
    px, py, pz = _fl(s['x']), _fl(s['y']), _fl(s['z'])
    g = aic.dump(px - 3, py - 1, pz - 3, px + 3, py + 2, pz + 3, maxn=20000)
    out = []
    for dist in (2, 3, 1):
        for dz in range(-dist, dist + 1):
            for dx in range(-dist, dist + 1):
                if max(abs(dx), abs(dz)) != dist:
                    continue
                for dy in (0, -1, 1):
                    pos = (px + dx, py + dy, pz + dz)
                    if pos in g:
                        continue
                    if (pos[0], pos[1] - 1, pos[2]) not in g:
                        continue          # 下方没有依托，放不住
                    out.append(pos)
                    if len(out) >= limit:
                        return out
    return out


def find_empty_spot():
    """兼容旧调用：返回第一个候选点。"""
    spots = find_spots(1)
    return spots[0] if spots else None



def place_block(pos, item):
    """Place, then READ BACK. A placement return value is not evidence."""
    r = aic.get('/place?x=%d&y=%d&z=%d&item=%s'
                % (pos[0], pos[1], pos[2], item))
    res = str(r.get('result', ''))
    time.sleep(0.3)
    g = aic.dump(pos[0], pos[1], pos[2], pos[0], pos[1], pos[2], maxn=4)
    now = g.get((pos[0], pos[1], pos[2]))
    if now is not None and item in str(now):
        return 'placed+confirmed'
    return 'place said "%s" but the cell holds %s' % (res, now)


# 服务端判的是「眼 → 方块中心 ≤ 4.5」，留点余量按 4.0
INTERACT_RANGE = 4.0


def reachable(pos):
    """这个方块现在点得到吗（眼→中心距离）"""
    s = aic.state()
    ex = float(s['x'])
    ey = float(s['y']) + 1.62
    ez = float(s['z'])
    d = math.hypot(pos[0] + 0.5 - ex, pos[1] + 0.5 - ey, pos[2] + 0.5 - ez)
    return d <= INTERACT_RANGE, d


def walk_to(pos, timeout=12):
    """走到方块旁边（不够近就先走过去，再判断能不能点）"""
    aic.cmd('#goto %d %d %d' % (pos[0], pos[1], pos[2]))
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.6)
        ok, _ = reachable(pos)
        if ok:
            aic.cmd('#stop')
            return True
        if not aic.state().get('pathing'):
            break
    aic.cmd('#stop')
    return reachable(pos)[0]


def ensure_workbench(verbose=True):
    """Return (x,y,z) of a **reachable** workbench, placing one if necessary.

    以前的坑：只要 dump 里看到「工作台」就直接返回，哪怕它在 5.9 格外。
    结果是 /craft 一路 needs-crafting-table，而调用方只看到「造不出来」。
    """
    s = aic.state()
    px, py, pz = _fl(s['x']), _fl(s['y']), _fl(s['z'])
    g = aic.dump(px - 4, py - 3, pz - 4, px + 4, py + 3, pz + 4, maxn=30000)
    found = [(x, y, z) for (x, y, z), t in g.items() if '工作台' in str(t)]
    for pos in sorted(found, key=lambda p: reachable(p)[1]):
        ok, d = reachable(pos)
        if ok:
            return pos
        say('workbench at %s is %.1f away -> walking' % (pos, d))
        if walk_to(pos):
            return pos

    if count('工作台') == 0:
        # 背包满 36/36 时合成产物取不出来（结果槽挂着、count 永远 0），
        # 表现就是 "craft workbench: missing-material"，看着像缺料其实是缺格子。
        try:
            import storage as _storage
            if _storage.free_slots() < 3:
                _storage.ensure_space(5)
        except Exception:
            pass
        planks = count_wood('木板')
        if planks < 4:
            logs = count_wood('原木')
            if logs < 1:
                say('no planks, no logs -- cannot build a workbench')
                return None
            craft_any('橡木木板', 1, verbose=False)
            time.sleep(0.5)
        made = craft_any('工作台', 1, verbose=False)
        say('craft workbench:', made)
        time.sleep(0.5)
        if count('工作台') == 0:
            return None

    spots = find_spots(8)
    if not spots:
        say('no room to place a workbench')
        return None
    for spot in spots:
        res = place_block(spot, '工作台')
        say('place workbench at %s -> %s' % (spot, res))
        time.sleep(0.6)
        if 'placed' in res:
            return spot
    return None


def open_at(pos):
    r = aic.get('/container?op=open&x=%d&y=%d&z=%d' % pos)
    return str(r.get('result', ''))


def ensure_pick_count(n=3, verbose=True):
    """把镐补到 n 把（ensure_tools 只要手里 ≥1 就把早退了，永远补不到备用的）。

    一把石镐 131 耐久，深山段一列要削 15~25 格 → 大概 6 列就废一把。
    所以必须**常备 3 把**，否则每 6 列就停一次去合成，白白浪费一半时间。
    """
    cur = pack().get('picks', 0)
    if cur >= n:
        return True
    need = n - cur
    if verbose:
        say('补镐：现有 %d，目标 %d' % (cur, n))
    bench = ensure_workbench()
    if not bench:
        return False
    ensure_sticks(need * 2 + 2, verbose=verbose)
    for _ in range(need + 1):
        if pack().get('picks', 0) >= n:
            break
        res = craft_clean(bench, '石镐', 1, verbose=False)
        if verbose:
            say('  石镐: %s' % res)
        if not res.startswith('crafted'):
            break
    return pack().get('picks', 0) > cur


def ensure_tools(verbose=True):
    """Guarantee at least one pickaxe in the pack. Returns True when usable."""
    p = pack()
    if not p.get('ok'):
        if verbose:
            say('pack unavailable')
        return False
    picks = p.get('picks', 0)
    if picks > 0:
        if verbose:
            say('pickaxes on hand: %d' % picks)
        return True

    if verbose:
        say('NO PICKAXE -- rebuilding')
    bench = ensure_workbench()
    if not bench:
        return False
    opened = open_at(bench)
    if verbose:
        say('open workbench:', opened)
    if 'interacted' not in str(opened):
        if verbose:
            say('cannot open workbench at %s' % (bench,))
        return False
    time.sleep(1.0)

    # 先把木棍备够 —— 以前 missing-material 的真因一直是它
    ensure_sticks(6, verbose=verbose)

    # 一次多造几把：石镐耐久只有 131，挖两轮就断，断了又得重新找工作台
    for recipe in PICK_RECIPES:
        for _ in range(2):
            res = craft_clean(bench, recipe, 1, verbose=False)
            if verbose:
                say('%s: %s' % (recipe, res))
            if not res.startswith('crafted'):
                # 缺料就别硬试第二次了（每次失败都会脏网格/烧材料）
                break
        if pack().get('picks', 0) > 0:
            break

    aic.get('/container?op=close')
    time.sleep(0.3)
    return pack().get('picks', 0) > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--ensure', action='store_true')
    args = ap.parse_args()

    p = pack()
    print('=== pack snapshot ===')
    print('  day=%s ticks=%s  picks=%s swords=%s  bench_near=%s' % (
        p.get('day'), p.get('ticks'), p.get('picks'), p.get('swords'), p.get('bench_near')))
    items = p.get('items', {})
    for k in sorted(items, key=lambda k: -items[k])[:14]:
        print('    %-12s %d' % (k, items[k]))
    print('  free slots: %d' % free_slots())

    if args.ensure:
        print()
        ok = ensure_tools()
        print('  result:', 'tools ready' if ok else 'could not restore tools')
        return 0 if ok else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
