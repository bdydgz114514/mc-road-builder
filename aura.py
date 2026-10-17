# -*- coding: utf-8 -*-
"""
常驻自卫：kill-aura 一直开着，不再"打完就关"。

诊断：
    [Meteor] Kill Aura Setting Entities is {..., entity.minecraft.zombie, ...}  设置正确
    {'name': 'kill-aura', 'active': False}                                      但模块没开

之前 defend() 结尾 aic.get('/module?m=kill-aura&on=false') 把它关掉了，
所以僵尸再来时玩家只会站着挨打 —— 用户看到的"不打僵尸"就是这个。

现在：
    ensure_aura()  确保 kill-aura 开着且只打敌对生物（不打别的玩家）
    passive_guard() 每轮调用一次，顺手补开
"""
import time

import aic
from defend import hostiles

_aura_on = False


def say(*a):
    print('  [aura]', *a)


def is_on():
    m = aic.get('/modules')
    mods = m.get('modules', [])
    for x in mods:
        if isinstance(x, dict) and x.get('name') == 'kill-aura':
            return bool(x.get('active'))
    return False


def ensure_aura(verbose=True):
    """确保 kill-aura 开着，并且只锁敌对生物（不打玩家，避免误伤别人）"""
    global _aura_on
    # 只打怪，不打玩家
    aic.cmd('.settings kill-aura entities monster')
    time.sleep(0.35)
    # 让 kill-aura 自己换武器：不然手上拿着镐（/dig 留下的）打僵尸，
    # 镐伤害 1~2，铁剑 6，等于白挨打
    for setting in ('auto-swap', 'auto-weapon', 'switch'):
        aic.cmd('.settings kill-aura %s true' % setting)
        time.sleep(0.2)
    for setting in ('auto-swap', 'auto-weapon'):
        aic.cmd('.settings kill-aura damage true')
        break
    time.sleep(0.2)
    if not is_on():
        aic.get('/module?m=kill-aura&on=true')
        time.sleep(0.5)
    on = is_on()
    if verbose and on != _aura_on:
        say('kill-aura %s' % ('ON' if on else 'FAILED'))
    _aura_on = on
    return on


def hold_weapon():
    """手上拿把能打的（镐子打僵尸很慢）"""
    s = aic.state()
    held = str((s.get('held') or {}).get('item') or '')
    if any(k in held for k in ('剑', '斧')):
        return held
    for w in ('铁剑', '石剑', '木剑', '铁斧'):
        r = aic.get('/hold?item=%s' % w)
        if 'holding' in str(r.get('result', '')):
            return w
    return None


def passive_guard(verbose=False, keep_held=False):
    """每轮调用：保证 aura 开着 + 手上有武器。

    keep_held=True 时不换手（正在挖矿，换了会拖慢挖掘）。
    """
    on = ensure_aura(verbose=verbose)
    if not keep_held:
        hold_weapon()
    return on


if __name__ == '__main__':
    ensure_aura()
    print('aura on:', is_on())
    print('weapon :', hold_weapon())
    s = aic.state()
    print('hp=%.0f at (%d,%d,%d)' % (s['health'], int(s['x']), int(s['y']), int(s['z'])))
