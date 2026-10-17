# -*- coding: utf-8 -*-
"""
keeplive.py -- 常驻守护：死了立刻点复活，顺便盯血量和昼夜。

用户要求："死了就要及时点击复活键"。
本进程每 0.8 秒查一次 /state，alive=false 就立刻点重生，
并把死因写进 shots/ 和日志，方便事后复盘。

用法（后台常驻）：
    python keeplive.py
    python keeplive.py --log keeplive.log
"""
import argparse
import os
import sys
import time

import aic
import revive

POLL = 0.8
LOCK_PORT = 25599        # 单实例锁：绑住这个本地端口


def single_instance():
    """只允许一个 keeplive 常驻。

    实测踩过的坑：历史上累计起了 4 个 keeplive 进程，同一秒里点了 4 次「重生」，
    日志里每行重复 3~4 遍，死亡计数各算各的，根本没法复盘。
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', LOCK_PORT))
        s.listen(1)
        return s            # 保持引用，进程活着端口就不释放
    except OSError:
        s.close()
        return None


def log(path, msg):
    line = '[%s] %s' % (time.strftime('%H:%M:%S'), msg)
    print(line, flush=True)
    if path:
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', default=r'D:\mc-road-builder\keeplive.log')
    ap.add_argument('--seconds', type=int, default=0, help='0 = forever')
    args = ap.parse_args()

    lock = single_instance()
    if lock is None:
        print('another keeplive is already running (port %d busy) -- exiting'
              % LOCK_PORT, flush=True)
        return 0

    log(args.log, '=== keeplive start (poll %.1fs) ===' % POLL)
    deaths = 0
    t0 = time.time()
    last_hp = None
    low_hp_warned = False

    while True:
        if args.seconds and time.time() - t0 > args.seconds:
            log(args.log, 'time limit reached, stop')
            break
        try:
            s = aic.state()
        except Exception as e:
            time.sleep(2)
            continue

        alive = s.get('alive')
        hp = s.get('health', 0)

        if not alive or hp <= 0:
            # 死了先把寻路和输入全部掐掉。
            # Baritone 的 goal 在重生后仍然生效 —— 不掐的话人一复活就自己走开，
            # 看起来就像机器人自己接上了（用户当场就发现了这点）。
            try:
                aic.cmd('#stop')
                for _k in ('FORWARD', 'BACK', 'LEFT', 'RIGHT', 'JUMP', 'SPRINT', 'SNEAK'):
                    aic.get('/input?k=%s&down=false' % _k)
            except Exception:
                pass
            deaths += 1
            d = revive.death_log()
            log(args.log, 'DEAD #%d: %s' % (deaths, d or '(no death message)'))
            try:
                revive.snap_death = None
            except Exception:
                pass
            ok = revive.respawn()
            s2 = aic.state()
            if ok:
                log(args.log, 'respawned -> hp=%.0f at (%d,%d,%d)'
                    % (s2.get('health', 0), int(s2.get('x', 0)),
                       int(s2.get('y', 0)), int(s2.get('z', 0))))
                # 立刻 /home 回工地（家每批都钉在前线，比死亡点干净）。
                # 不回的话会被扔在世界出生点（离工地几百格），一切都要重走。
                # /back 有 3 秒读条，期间移动就取消：先用潜行把浮动定住。
                try:
                    aic.get('/input?k=SNEAK&down=true')
                    time.sleep(3.0)
                    aic.get('/chat?m=/home')
                    time.sleep(6.0)
                    aic.get('/input?k=SNEAK&down=false')
                    s3 = aic.state()
                    log(args.log, '/home -> (%d,%d,%d) hp=%.0f'
                        % (int(s3.get('x', 0)), int(s3.get('y', 0)),
                           int(s3.get('z', 0)), s3.get('health', 0)))
                except Exception as e:
                    log(args.log, '/home 失败: %s' % e)
            else:
                log(args.log, 'RESPAWN FAILED -- retrying in 3s')
                time.sleep(3)
            last_hp = None
            low_hp_warned = False
            continue

        # 血量下降告警（不干预，只记录）
        if last_hp is not None and hp < last_hp - 2:
            log(args.log, 'hp drop %.0f -> %.0f at (%d,%d,%d)'
                % (last_hp, hp, int(s['x']), int(s['y']), int(s['z'])))
        if hp <= 6 and not low_hp_warned:
            log(args.log, 'LOW HP %.0f -- danger' % hp)
            low_hp_warned = True
        if hp > 12:
            low_hp_warned = False
        last_hp = hp

        time.sleep(POLL)

    log(args.log, '=== keeplive stop, %d death(s) handled ===' % deaths)
    return 0


if __name__ == '__main__':
    sys.exit(main())
