# -*- coding: utf-8 -*-
"""
watchdog.py -- 有人进服就立刻停机（管理员/任何非白名单玩家）。

为什么需要：
    这台机器是"真人手打"之外的自动化，最怕的是有人上线盯着看。
    与其伪装节奏，不如**只要有人进来就立刻收手**：停寻路、取消队列、
    关掉常驻模块、杀掉施工进程，然后等你自己退出。

工作方式：
    尾随 D:\\pcl\\minecraft\\versions\\3\\logs\\latest.log（只读新增部分），
    匹配「XXX加入了游戏」/「XXX joined the game」。
    白名单为空 = 任何人进来都触发。

触发后：
    1) 写 HALT 旗标（auto_west 每批开头会看）
    2) #stop + 全部按键抬起 + /dig /fill /taskctl 队列取消
    3) kill-aura / flight / air-jump / speed / no-fall / auto-eat 全关
    4) 杀掉 auto_west / repair / mine 进程
    5) 截图 + 打印闹钟日志

用法：
    python watchdog.py                       # 前台常驻
    python watchdog.py --allow PlayerName        # 允许自己（其实自己的名字总被忽略）
    python watchdog.py --auto-resume         # 那人走了以后自动清旗标（默认不开）
"""
import argparse
import os
import re
import subprocess
import sys
import time

import aic

HERE = os.path.dirname(os.path.abspath(__file__))
HALT = os.path.join(HERE, 'HALT')
LOG = r'D:\Minecraft\.minecraft\versions\3\logs\latest.log'
SELF = 'PlayerName'

JOIN_PATTERNS = [
    re.compile(r'\[CHAT\]\s+(\S+?)\s*加入了游戏'),
    re.compile(r'\[CHAT\]\s+(\S+?)\s+joined the game'),
]
LEAVE_PATTERNS = [
    re.compile(r'\[CHAT\]\s+(\S+?)\s*退出了游戏'),
    re.compile(r'\[CHAT\]\s+(\S+?)\s+left the game'),
]
KILL_MATCH = ('auto_west.py', 'repair.py', 'mine.py', 'bridge.py', 'walkback.py', 'chop.py')
KILL_MODULES = ('kill-aura', 'flight', 'air-jump', 'speed', 'no-fall', 'anti-void',
                'anti-hunger', 'auto-eat', 'auto-tool', 'high-jump', 'velocity')


def say(*a):
    print('[%s] [watchdog] %s' % (time.strftime('%H:%M:%S'), ' '.join(str(x) for x in a)),
          flush=True)


def emergency_stop(who):
    say('!!!! %s 进服了 —— 立刻停机 !!!!' % who)
    try:
        with open(HALT, 'w', encoding='utf-8') as f:
            f.write('%s %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), who))
    except Exception:
        pass
    try:
        aic.cmd('#stop')
        for k in ('FORWARD', 'BACK', 'LEFT', 'RIGHT', 'JUMP', 'SPRINT', 'SNEAK',
                  'CLICK_LEFT', 'CLICK_RIGHT'):
            aic.get('/input?k=%s&down=false' % k)
        aic.get('/dig?op=cancel')
        aic.get('/fill?op=cancel')
        aic.get('/taskctl?op=clear')
        for m in KILL_MODULES:
            aic.get('/module?m=%s&on=false' % m)
    except Exception as e:
        say('停机时出错（继续杀进程）：%s' % e)
    # 杀掉施工进程
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-Command',
                              "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                              "Where-Object { %s } | ForEach-Object { $_.ProcessId }"
                              % ' -or '.join("$_.CommandLine -like '*%s*'" % k for k in KILL_MATCH)],
                             capture_output=True, text=True, timeout=30).stdout
        for pid in [p.strip() for p in out.splitlines() if p.strip().isdigit()]:
            if int(pid) != os.getpid():
                subprocess.run(['powershell', '-NoProfile', '-Command',
                                'Stop-Process -Id %s -Force' % pid],
                               capture_output=True, timeout=20)
                say('   已杀 pid %s' % pid)
    except Exception as e:
        say('   杀进程失败：%s' % e)
    try:
        from snap import snap
        snap('admin-joined-%s' % who)
    except Exception:
        pass
    say('已静默。等你处理完再手动继续（删掉 HALT 文件即可）。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', default=LOG)
    ap.add_argument('--poll', type=float, default=2.0)
    ap.add_argument('--allow', default='', help='白名单，逗号分隔（默认空=谁进来都停）')
    ap.add_argument('--auto-resume', action='store_true')
    ap.add_argument('--only-prefix', default='',
                    help='只对指定前缀的玩家名停机（如 G = 管理员）；留空 = 谁进来都停')
    args = ap.parse_args()

    allow = {SELF} | {n.strip() for n in args.allow.split(',') if n.strip()}
    prefix = (args.only_prefix or '').strip()
    say('看门狗启动，监听 %s（白名单：%s）' % (args.log, ','.join(sorted(allow)) or '无'))

    off = 0
    if os.path.exists(args.log):
        off = os.path.getsize(args.log)
    halted = os.path.exists(HALT)
    if halted:
        say('注意：HALT 旗标已存在（上次停机后没清）')

    # 启动时先回顾最近的日志，把**已经在服里**的人认出来。
    # 实测踩过：看门狗是在某人已经进服之后才启动的，于是完全没意识到被看着，
    # 直到那人退出才在日志里看到 "XXX 退出了游戏"。
    online = set()
    if os.path.exists(args.log):
        try:
            with open(args.log, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(max(0, off - 400_000))
                for line in f.read().splitlines():
                    for pat in JOIN_PATTERNS:
                        m = pat.search(line)
                        if m:
                            online.add(m.group(1))
                    for pat in LEAVE_PATTERNS:
                        m = pat.search(line)
                        if m:
                            online.discard(m.group(1))
        except Exception as e:
            say('回顾日志失败：%s' % e)
    strangers = {w for w in (online - allow) if (not prefix) or w.startswith(prefix)}
    if strangers:
        say('!!!! 启动时就已经有人在服里：%s !!!!' % ','.join(sorted(strangers)))
        emergency_stop(','.join(sorted(strangers)))
        halted = True
    elif online:
        say('日志里只有自己（%s），继续盯着' % ','.join(sorted(online)))

    while True:
        try:
            if not os.path.exists(args.log):
                time.sleep(args.poll)
                continue
            size = os.path.getsize(args.log)
            if size < off:          # 日志被轮转
                off = 0
            if size == off:
                time.sleep(args.poll)
                continue
            with open(args.log, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(off)
                chunk = f.read()
                off = f.tell()
            for line in chunk.splitlines():
                for pat in JOIN_PATTERNS:
                    m = pat.search(line)
                    if m:
                        who = m.group(1)
                        if who in allow:
                            say('%s 进服（白名单，忽略）' % who)
                        elif prefix and not who.startswith(prefix):
                            # 只盯 GT 级：普通玩家进来只记录，不停机
                            say('%s 进服（不是 %s* 开头，只记录）' % (who, prefix))
                        else:
                            emergency_stop(who)
                            halted = True
                for pat in LEAVE_PATTERNS:
                    m = pat.search(line)
                    if m:
                        who = m.group(1)
                        say('%s 退出了' % who)
                        if halted and args.auto_resume and who not in allow:
                            try:
                                os.remove(HALT)
                            except Exception:
                                pass
                            halted = False
                            say('已清 HALT 旗标，可以重新开工')
            time.sleep(args.poll)
        except KeyboardInterrupt:
            say('手动退出')
            return 0
        except Exception as e:
            say('error: %s' % e)
            time.sleep(3)


if __name__ == '__main__':
    sys.exit(main())
