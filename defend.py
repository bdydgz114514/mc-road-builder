# -*- coding: utf-8 -*-
"""
自卫 + 高频血量检查。

诊断（keeplive 日志）：
    12:36:20 hp 20→18    僵尸开始攻击
    12:36:33 hp  3→1
    12:36:34 被僵尸杀死
13 秒里玩家一直站着挨打，因为：
    a) unify 只在**每列开头**查一次血量，一列要削 10 格（约 3 秒），太稀疏
    b) kill-aura 默认只打玩家（技能库第 5 条：entities 默认 [Player]），不会打僵尸

本模块：
    defend()     临时开 kill-aura 打死身边的怪（entities=monster）
    check_alive() 血量/存活检查，低就撤
"""
import time

import aic

MIN_HP = 12.0


def say(*a):
    print('  [defend]', *a)


def hostiles(radius=10):
    e = aic.get('/entities?r=%d' % radius)
    out = []
    for x in e.get('entities', []):
        name = str(x.get('name') or x.get('type') or '')
        if any(k in name for k in ('僵尸', '骷髅', '蜘蛛', '苦力怕', '爬行者',
                                    '女巫', '末影人', '溺尸', '尸壳', '岩浆怪',
                                    'zombie', 'skeleton', 'spider', 'creeper',
                                    'witch', 'enderman', 'drowned', 'husk')):
            out.append(x)
    return out


def defend(seconds=6.0, verbose=True):
    """开 kill-aura 打身边的怪。返回打死期间的最低血量。"""
    foes = hostiles()
    if not foes:
        return None
    if verbose:
        say('hostiles: %s' % ', '.join('%s(%.1f)' % (f.get('name') or f.get('type'), f.get('dist', 0))
                                        for f in foes[:4]))
    # kill-aura 必须改成打怪（默认只打玩家）
    aic.cmd('.settings kill-aura entities monster')
    time.sleep(0.4)
    # 切武器
    for w in ('铁剑', '石剑', '木剑'):
        r = aic.get('/hold?item=%s' % w)
        if 'holding' in str(r.get('result', '')):
            break
    aic.get('/module?m=kill-aura&on=true')
    lowest = 99
    t0 = time.time()
    while time.time() - t0 < seconds:
        time.sleep(0.4)
        s = aic.state()
        lowest = min(lowest, s.get('health', 0))
        if not s.get('alive'):
            break
        if not hostiles(radius=8):
            break
    # 打完**不要**关 kill-aura。
    # 原代码这里写 on=false，于是"打完这一只 → 下一只来了不还手 → 被僵尸杀"，
    # 交接书 §4.11 记的 6 次死亡就是这么来的。aura.ensure_aura() 才是正确收尾。
    try:
        import aura as _aura
        _aura.ensure_aura()
    except Exception:
        aic.get('/module?m=kill-aura&on=true')
    left = hostiles(radius=8)
    if verbose:
        say('done, lowest hp=%.0f, %d hostile(s) left' % (lowest if lowest < 99 else 0, len(left)))
    return lowest


def check_alive(retreat_below=MIN_HP):
    """血量检查。低于阈值返回 False，调用方应当撤。"""
    s = aic.state()
    if not s.get('alive') or s.get('health', 0) <= 0:
        import revive
        revive.respawn()
        return False
    if s['health'] < retreat_below:
        return False
    return True


def safe_guard(retreat_below=MIN_HP):
    """干活前调用：先清怪，再看血。"""
    if hostiles(radius=10):
        defend(seconds=6.0)
    return check_alive(retreat_below)


# ─────────────────────────────────────────────────────────────
# 被动撤退：血量不够就不接战
# ─────────────────────────────────────────────────────────────
SAFE_HP = 16.0
RETREAT_HP = 10.0


def retreat_to(x, y, z, timeout=60):
    """退到指定安全点"""
    import time
    aic.cmd('#goto %d %d %d' % (x, y, z))
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2)
        if not aic.state().get('pathing'):
            break
    aic.cmd('#stop')
    return True


def eat_to_full(verbose=True):
    """吃食物回血，最多试 6 次"""
    import time
    from humaninput import HumanInput
    try:
        hi = HumanInput()
        hi.find_window()
        hi.ensure_in_game()
    except Exception:
        hi = None
    for food in ('熟牛排', '熟猪排', '面包', '熟鸡肉', '苹果', '生鸡肉'):
        if aic.count_item(food) <= 0:
            continue
        if verbose:
            say('eating %s' % food)
        for _ in range(6):
            s = aic.state()
            if s.get('health', 0) >= 19:
                return True
            aic.get('/hold?item=%s' % food)
            time.sleep(0.35)
            if hi:
                hi.right_click(hold=0.35)
            else:
                aic.cmd('#use')
            time.sleep(1.8)
        break
    return aic.state().get('health', 0) >= 16


def fight_or_flee(safe_spot=None, verbose=True):
    """遇怪时的统一决策。返回 True 表示可以继续干活。"""
    import time
    s = aic.state()
    hp = s.get('health', 0)
    foes = hostiles(radius=14)
    if not foes:
        return hp >= RETREAT_HP
    if hp >= SAFE_HP:
        # 血够，清掉
        defend(seconds=8.0, verbose=verbose)
        return aic.state().get('health', 0) >= RETREAT_HP
    # 血不够：撤
    if verbose:
        say('hp=%.0f < %.0f with %d foe(s) -> retreat' % (hp, SAFE_HP, len(foes)))
    if safe_spot:
        retreat_to(*safe_spot)
    # 边撤边吃
    eat_to_full(verbose=verbose)
    return aic.state().get('health', 0) >= SAFE_HP

