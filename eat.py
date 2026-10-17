# -*- coding: utf-8 -*-
"""
eat.py -- 真正能吃进去的吃东西。

为什麽不用 defend.eat_to_full() / #use：
    实测两者都吃不到东西（food 5 -> 5）。能吃进去的唯一路径是
    Baritone 的输入覆盖 CLICK_RIGHT：
        /input?k=CLICK_RIGHT&down=true → 按住右键
        /input?k=CLICK_RIGHT&down=false → 松开
    一口要 1.6 秒（进食动画），所以两次之间至少 sleep 1.7。

用法：
    python eat.py              吃到 19
    python eat.py --target 18
"""
import argparse
import sys
import time

import aic


def say(*a):
    print('  [eat]', *a, flush=True)


FOODS = ('熟牛排', '熟猪排', '面包', '熟鸡肉', '熟羊肉', '烤马铃薯',
         '苹果', '生鸡肉', '生牛肉', '生猪肉', '腐肉', '胡萝卜')


def use_right_click(hold=0.15):
    aic.get('/input?k=CLICK_RIGHT&down=true')
    time.sleep(hold)
    aic.get('/input?k=CLICK_RIGHT&down=false')


def eat(target=19, verbose=True):
    s = aic.state()
    if s.get('food', 0) >= target:
        return True
    have = [f for f in FOODS if aic.count_item(f) > 0]
    if not have:
        say('没有食物')
        return False
    for food in have:
        r = aic.get('/hold?item=%s' % food)
        time.sleep(0.4)
        cur = str((aic.state().get('held') or {}).get('item') or '')
        if food not in cur:
            continue
        if verbose:
            say('吃 %s' % food)
        for _ in range(6):
            use_right_click()
            time.sleep(1.7)
            s = aic.state()
            if s.get('food', 0) >= target:
                if verbose:
                    say('food=%d hp=%.0f' % (s['food'], s.get('health', 0)))
                return True
            if aic.count_item(food) <= 0:
                break
        if verbose:
            say('%s 吃完后 food=%d' % (food, aic.state().get('food', 0)))
    return aic.state().get('food', 0) >= target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', type=int, default=19)
    args = ap.parse_args()
    s = aic.state()
    say('before: food=%d hp=%.0f' % (s.get('food', 0), s.get('health', 0)))
    ok = eat(args.target)
    s = aic.state()
    say('after : food=%d hp=%.0f -> %s' % (s.get('food', 0), s.get('health', 0),
                                            'ok' if ok else 'still hungry'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
