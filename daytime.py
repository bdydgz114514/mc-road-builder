# -*- coding: utf-8 -*-
"""
daytime.py -- 只在白天干活，天黑就收工。

实测：蜘蛛是夜里来的，一次把血从 20 打到 0。
/time 端点直接给 ticks / day / phase，不用自己算。

用法：
    from daytime import wait_for_day, is_day, night_left_seconds
    wait_for_day()          # 若夜间则等到天亮（有上限，不会无限等）
"""
import time

import aic

DAY_START = 0
DAY_END = 12300
NIGHT_END = 23850
TICKS_PER_SEC = 20.0


def now():
    r = aic.get('/time')
    return int(r.get('ticks', 0)), bool(r.get('day')), str(r.get('phase', '?'))


def is_day():
    t, d, _ = now()
    return d


def night_left_seconds():
    t, d, _ = now()
    if d:
        return 0
    remain = (NIGHT_END - t) % 24000
    return remain / TICKS_PER_SEC


def try_sleep(verbose=True):
    """天亮的最快办法：铺床睡一觉（带床走，不用回家）。失败返回 False。"""
    try:
        import bed
        return bed.sleep_cycle(verbose=verbose)
    except Exception as e:
        if verbose:
            print('  [day] sleep failed: %s' % e)
        return False


def wait_for_day(max_wait=300, verbose=True, use_bed=True):
    """若在夜里就想办法到天亮：**先试睡觉**，睡不了再硬等。

    返回 True 表示现在（或处理完后）是白天。
    """
    t, d, ph = now()
    if d:
        return True
    if use_bed:
        if verbose:
            print('  [day] night (t=%d) -- 先试试铺床睡' % t)
        if try_sleep(verbose=verbose):
            return True
    t, d, ph = now()
    if d:
        return True
    left = night_left_seconds()
    if verbose:
        print('  [day] still night (t=%d), %.0f s until dawn' % (t, left))
    if left > max_wait:
        if verbose:
            print('  [day] dawn is %.0f s away, longer than max_wait=%d -- not waiting'
                  % (left, max_wait))
        return False
    t0 = time.time()
    while time.time() - t0 < left + 15:
        time.sleep(5)
        tt, dd, pp = now()
        if dd:
            if verbose:
                print('  [day] dawn reached after %.0f s (t=%d)' % (time.time() - t0, tt))
            return True
    tt, dd, pp = now()
    if verbose:
        print('  [day] still %s after waiting (t=%d)' % (pp, tt))
    return dd


def guard(max_wait=300):
    """干活前的守门：不是白天就不要动手。"""
    return wait_for_day(max_wait=max_wait)


if __name__ == '__main__':
    t, d, ph = now()
    print('ticks=%d day=%s phase=%s' % (t, d, ph))
    if not d:
        print('night left: %.0f s' % night_left_seconds())
    print('wait_for_day ->', wait_for_day())
