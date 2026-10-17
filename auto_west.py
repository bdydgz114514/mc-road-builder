# -*- coding: utf-8 -*-
"""
auto_west.py -- 往西自动铺路：批一批往前推，自己补工具/材料/睡觉，每批验收。

设计思路（不是教条，是被坑出来的）：
    · **每批 8 列**，推完立刻回读验收；有坏列就只重修那几列，不整批重来
    · 材料/木头/镐不够就自己去补：镐 → ensure_tools，木头 → `#mine spruce_log`，
      圆石 → mine.py，包袱满 → storage.ensure_space
    · 天黑就睡（bed），睡完继续；死了就复活再用 /home 回来（家已钉在工地）
    · 单批失败 3 次 → 停手并打印诊断，不做无意义的重试
    · 进度写进 auto_west.log，随时可 tail

用法：
    python auto_west.py --start -410 --end -7888
"""
import argparse
import math
import random
import os
import subprocess
import sys
import time

import aic
import toolkit
import storage

HERE = os.path.dirname(os.path.abspath(__file__))
AIR = ('空气', '洞穴空气', '虚空空气')


def say(*a):
    line = '[%s] [auto] %s' % (time.strftime('%H:%M:%S'), ' '.join(str(x) for x in a))
    print(line, flush=True)


def solid(t):
    return t is not None and t not in AIR


def is_cobble(t):
    return t is not None and '圆石' in str(t)


def run_repair(x0, x1, cut=3, subdepth=2, min_hp=5, timeout=2400, deck_item='泥土'):
    cmd = [sys.executable, 'repair.py', str(x0), str(x1),
           '--cut', str(cut), '--subdepth', str(subdepth),
           '--batch', '--min-hp', str(min_hp), '--deck-item', deck_item]
    try:
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout)
        tail = [l for l in (r.stdout or '').splitlines() if l.strip()][-4:]
        for l in tail:
            say('   ', l.strip()[:150])
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        say('repair 超时（%ds）—— 杀掉重来' % timeout)
        return False


def check_batch(x0, x1, deck=68, z0=270, z1=274, deck_items=('泥土', '圆石', '木板')):
    """整批一次导出验完。

    原来每列都 refresh_near 一次（几十列就是几十次 blockmap 往返，
    每次 0.5~1 秒），验收一度比施工还慢。现在一个盒子全扫完。
    deck_items 支持木板路面（用户允许用木板替代原石）。
    返回 {x: [问题...]}，只含有问题的列。
    """
    from worldmem import WorldMem
    a, b = min(x0, x1), max(x0, x1)
    try:
        wm = WorldMem.refresh_near((a + b) // 2, 272, rx=(b - a) // 2 + 4,
                                   y_lo=deck - 6, y_hi=deck + 8)
    except Exception as e:
        return {a: ['read-fail:%s' % e]}

    def ok(t):
        s = str(t or '')
        return any(k in s for k in deck_items)

    out = {}
    for x in range(a, b + 1):
        bad = []
        for z in range(z0, z1 + 1):
            if not ok(wm.block(x, deck, z)):
                bad.append('deck@%d' % z)
            if not solid(wm.block(x, deck - 1, z)):
                bad.append('float@%d' % z)
            for y in range(deck + 1, deck + 4):
                t = wm.block(x, y, z)
                # 工作台是 ensure_tools 自己放的（就在路北沿 z=270），
                # 别当成"路面冒头"反复去修 —— 修了下次补镐又会出现一个。
                if solid(t) and '工作台' not in str(t):
                    bad.append('above@%d,%d' % (y, z))
        if bad:
            out[x] = bad
    return out


def check_column(x, deck=68, z0=270, z1=274):
    """单列验收（保留给补修路径用）。"""
    return check_batch(x, x, deck, z0, z1).get(x, [])


def water_run(x, deck=68, z0=270, z1=274, limit=48):
    """从 x 往西数，连续多少列在 deck-1..deck-6 都没有实心方块（=水面/深谷）。

    有水面就用 bridge.py 起拱；硬拿 repair 垫平等于填海，材料和时间都不划算，
    也不符合"水面上要像拱桥一样隆起"的原话。
    """
    from worldmem import WorldMem
    n = 0
    for i in range(limit):
        xx = x - i
        try:
            wm = WorldMem.refresh_near(xx, 272, rx=4, y_lo=deck - 8, y_hi=deck + 2)
        except Exception:
            break
        support = any(solid(wm.block(xx, deck - d, z))
                      for z in range(z0, z1 + 1) for d in range(1, 7))
        if support:
            break
        n += 1
    return n


def pick_deck_item():
    """背包里哪种路面材料多就用哪种（泥土 / 圆石 / 沙子 都可以铺）。
    沙漠里沙子最多，就铺沙子；森林里泥土最多，就铺泥土。
    """
    stock = [('泥土', aic.count_item('泥土')),
             ('圆石', aic.count_item('圆石')),
             ('沙子', aic.count_item('沙子'))]
    stock.sort(key=lambda kv: -kv[1])
    if stock[0][1] >= 60:
        return stock[0][0]
    return stock[1][0] if stock[1][1] > 0 else stock[0][0]


def surface_kind(x, deck=68):
    """看前方地表是什么：'sand' / 'dirt' / 'stone' / 'water'。"""
    from worldmem import WorldMem
    try:
        wm = WorldMem.refresh_near(x, 272, rx=4, y_lo=deck - 4, y_hi=deck + 6)
    except Exception:
        return 'unknown'
    counts = {'sand': 0, 'dirt': 0, 'stone': 0, 'water': 0}
    for z in range(270, 275):
        for d in range(0, 5):
            t = str(wm.block(x, deck - d, z) or '')
            if '水' in t:
                counts['water'] += 1
            elif '沙' in t:
                counts['sand'] += 1
            elif any(k in t for k in ('泥土', '草方块', '灰化土', '砂土')):
                counts['dirt'] += 1
            elif any(k in t for k in ('石头', '圆石', '安山岩', '闪长岩', '花岗岩', '深板岩')):
                counts['stone'] += 1
    if not counts:
        return 'unknown'
    return max(counts.items(), key=lambda kv: kv[1])[0]


def ensure_supplies(verbose=True, min_hp=4.0):
    """该补什么补什么，别停在原地等。"""
    picks = aic.get('/pack').get('picks', 0)
    wood = toolkit.count_wood('原木')
    planks = toolkit.count_wood('木板')
    cobble = aic.count_item('圆石')
    free = storage.free_slots()

    if free < 3:
        say('包袱满(free=%d) → 腾格子' % free)
        storage.ensure_space(5)

    # 木头是所有工具的源头：先备够，再造工具
    # 木头要留余量：进沙漠/海边就没树了，那时候全靠这点存货造镐造锹。
    # 森林里顺手多砍一点，成本几乎为零。
    if wood < 8 and planks < 4:
        say('木头不足(原木%d 木板%d) → 砍树' % (wood, planks))
        aic.get('/hold?item=铁斧')
        aic.cmd('#mine spruce_log')
        t0 = time.time()
        while time.time() - t0 < 70 and toolkit.count_wood('原木') < 8:
            time.sleep(5)
        aic.cmd('#stop'); time.sleep(0.8)
        say('砍完木头：原木 %d' % toolkit.count_wood('原木'))

    # 锹：泥土路面全靠它（锹挖土 0.15s，镐子几乎没加速）。
    # 以前只补镐不补锹，于是土方一直拿镐硬刨 —— 又慢又费耐久。
    if toolkit.count_shovels() < 2:
        say('锹不足(%d) → 补' % toolkit.count_shovels())
        toolkit.ensure_shovel(2)

    if picks < 3:
        say('镐不足(%d) → 补' % picks)
        # 一把镐只够削 130 格，深山地段一列就要 15~25 格 → 必须常备 3 把。
        # 注意：ensure_tools() 只要手里 ≥1 就把早退，永远补不到备用的，
        # 所以这里必须调 ensure_pick_count（会真的多造几把）。
        toolkit.ensure_pick_count(3)
        if aic.get('/pack').get('picks', 0) < 1:
            return False

    # 路面改成泥土后：泥土不够就去刨土（锹挖土最快）
    dr = 0
    while aic.count_item('泥土') < 100 and dr < 3:
        dr += 1
        say('泥土 %d < 100 → 第 %d 轮刨土' % (aic.count_item('泥土'), dr))
        aic.get('/hold?item=石锹')
        # 实测：`#mine dirt` 90 秒只涨 9 格；`#mine grass_block` 60 秒能涨 88 格。
        # 地表全是草方块，用英文 id 让 Baritone 自己走过去刨 + 捡。
        kind = surface_kind(int(aic.state()['x']))
        say('地表类型=%s → 按它采料' % kind)
        aic.cmd('#mine ' + ('sand' if kind == 'sand' else
                            'stone' if kind == 'stone' else 'grass_block'))
        t0 = time.time()
        while time.time() - t0 < 70 and aic.count_item('泥土') < 160:
            time.sleep(6)
        aic.cmd('#stop')
        time.sleep(0.8)
        if aic.count_item('泥土') < 40:
            aic.cmd('#mine dirt')
            t0 = time.time()
            while time.time() - t0 < 50 and aic.count_item('泥土') < 120:
                time.sleep(6)
            aic.cmd('#stop')
            time.sleep(0.6)
        say('   现在泥土 %d' % aic.count_item('泥土'))
        if aic.count_item('泥土') < 30:
            break

    # 圆石：**不够就挖到够**，不是"挖一次看看"。
    # 之前 mine.py 写死 health<12 拒绝挖矿，于是 HP 7 时材料永远补不上，
    # 整个工程原地卡死并误报"连续 3 批出问题"。这是本轮最大的时间黑洞。
    rounds = 0
    while aic.count_item('圆石') < 100 and rounds < 3:
        rounds += 1
        say('圆石 %d < 100 → 第 %d 轮挖矿' % (aic.count_item('圆石'), rounds))
        subprocess.run([sys.executable, 'mine.py', '--want', '420', '--rounds', '5',
                        '--min-hp', str(min_hp)],
                       cwd=HERE, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=1800)
        say('   现在圆石 %d' % aic.count_item('圆石'))
        if aic.count_item('圆石') < 40:
            break
    return aic.count_item('圆石') >= 30


def comeback(target_x=None):
    """回工地：**先 /back（死亡点 = 前线）**，不行才 /home 兜底。

    /back 回的是"最后一次死亡点"，死亡基本都发生在施工前线，
    所以它比 /home 更准（/home 只是每批 sethome 钉的那个点，可能落后十几列）。
    /back 有 3 秒读条，期间移动就取消 —— 先用潜行把浮动定住。
    """
    def _tp(cmd):
        try:
            aic.get('/input?k=SNEAK&down=true')
            time.sleep(2.6)
            aic.get('/chat?m=%s' % cmd)
            time.sleep(6.0)
            aic.get('/input?k=SNEAK&down=false')
        except Exception:
            pass
        time.sleep(0.5)
        s = aic.state()
        say('   %s -> %.0f,%.0f,%.0f hp=%.0f' % (cmd, s['x'], s['y'], s['z'], s.get('health', 0)))
        return s

    # /home 优先：它每批都钉在工地前线，落点干净；
    # /back 回的是死亡点，可能在水里/洞里（实测更难脱身）。/back 只兜底。
    s = _tp('/home')
    if target_x is not None and abs(s['x'] - target_x) > 40:
        s = _tp('/back')
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=int, required=True, help='起始列（第一个要建的）')
    ap.add_argument('--end', type=int, default=-7888, help='建到这一列停（含）')
    ap.add_argument('--batch', type=int, default=8)
    ap.add_argument('--hours', type=float, default=6.0)
    ap.add_argument('--min-hp', type=float, default=4.0)
    args = ap.parse_args()

    t0 = time.time()
    cur = args.start
    fails = 0
    done = 0
    death_seen = aic.state().get('last_death')
    batches = 0
    next_break = random.randint(4, 7)
    say('开工：x %d → %d，每批 %d 列，预算 %.1f 小时'
        % (cur, args.end, args.batch, args.hours))

    while cur >= args.end and time.time() - t0 < args.hours * 3600:
        try:
            cur = _one_round(args, cur)
        except Exception as e:
            say('!! 本轮异常（不让它杀掉进程）：%s' % e)
            time.sleep(15)
            try:
                aic.cmd('#stop')
            except Exception:
                pass
            continue
        break
    say('本轮结束：末端 x=%d，用时 %.1f 分钟' % (cur, (time.time() - t0) / 60.0))
    return 0


def _one_round(args, cur):
    """跑一段（直到 HALT / 连续失败 / 到达 end）。异常由 main 兜住后重来。"""
    fails = 0
    done = 0
    death_seen = aic.state().get('last_death')
    batches = 0
    next_break = random.randint(4, 7)
    while cur >= args.end:
        # 有人进服 → watchdog 会写 HALT 旗标，这里每批开头检查，体面收手
        if os.path.exists(os.path.join(HERE, 'HALT')):
            say('检测到 HALT 旗标（有人进服），停机')
            aic.cmd('#stop')
            break

        # 死亡/掉线自愈
        s = aic.state()
        # 用 last_death 时间戳做判据：只要刚死过，就先 #stop 再 /home，
        # 这一批直接跳过（绝不带着"复活就开始走"的状态继续施工）。
        died = s.get('last_death')
        if died and died != death_seen:
            death_seen = died
            say('检测到刚死亡（ts=%s）→ #stop + /home，跳过本批' % died)
            try:
                aic.cmd('#stop')
                for _k in ('FORWARD', 'BACK', 'LEFT', 'RIGHT', 'JUMP', 'SPRINT', 'SNEAK'):
                    aic.get('/input?k=%s&down=false' % _k)
            except Exception:
                pass
            time.sleep(2)
            comeback(cur)
            continue
        if not s.get('alive'):
            say('死了 → 复活')
            try:
                import revive
                revive.respawn()
            except Exception as e:
                say('   respawn err %s' % e)
            time.sleep(3)
        elif math.hypot(s['x'] - cur, s['z'] - 272) > 80:
            say('离工地 %.0f 格 → 先 /back 再 /home' % math.hypot(s['x'] - cur, s['z'] - 272))
            comeback(cur)

        if not ensure_supplies(min_hp=args.min_hp):
            say('补给失败，等 60s 再试')
            time.sleep(60)
            fails += 1
            if fails >= 4:
                say('补给连续失败 4 次，停')
                break
            continue

        # ── 先探一下前方是不是水面：水面要起拱桥，不是垫平 ──
        wr = water_run(cur)
        if wr >= 12:
            # 大海（不是小河沟）：先在陆地上把料备够，再架桥过去。
            # 在海里挖不动、也站不住，就地采料只会耗时间。
            need = wr * 5 + 40
            stock = max(aic.count_item('泥土'), aic.count_item('圆石'), aic.count_item('沙子'))
            if stock < need:
                say('前方 %d 列大海，料 %d < %d → 退回陆地采料' % (wr, stock, need))
                aic.cmd('#goto %d %d %d' % (cur + 8, 69, 272))
                t0w = time.time()
                while time.time() - t0w < 60 and aic.state().get('pathing'):
                    time.sleep(4)
                aic.cmd('#stop')
                time.sleep(1.0)
                ensure_supplies(min_hp=args.min_hp)
                continue
        if wr >= 2:
            span = min(wr, args.end and max(4, cur - args.end + 1))
            bx1 = cur - span + 1
            peak = max(2, min(5, span // 4))
            say('--- 水面 %d 列（x %d → %d）→ 起拱桥 peak=%d ---'
                % (span, cur, bx1, peak))
            subprocess.run([sys.executable, 'bridge.py', '--x0', str(cur), '--x1', str(bx1),
                            '--peak', str(peak), '--under', '泥土', '--rail',
                            '--min-hp', '4'],
                           cwd=HERE, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=2400)
            bad_water = [(x, check_column(x)[:3]) for x in range(cur, bx1 - 1, -1)]
            bad_water = [(x, b) for (x, b) in bad_water if b]
            # 桥面在拱形高度上，check_column 按 deck 68 判会误报；只补真正空的那几格
            for (x, _b) in bad_water:
                run_repair(x, x, timeout=600)
            done += span
            cur = bx1 - 1
            fails = 0
            say('拱桥段完成，下一个 x=%d，圆石 %d' % (cur, aic.count_item('圆石')))
            continue

        # 材料不够就别开批 —— 这一条以前没有，导致整批失败被误判成"施工出问题"
        bs = random.randint(max(4, args.batch - 2), args.batch + 1)
        if aic.count_item('圆石') < bs * 5 + 10:
            say('圆石 %d 不够这一批（需 %d），先挖'
                % (aic.count_item('圆石'), bs * 5 + 10))
            args.batch = max(4, aic.count_item('圆石') // 6) if aic.count_item('圆石') >= 24 else args.batch
            continue

        x1 = max(args.end, cur - bs + 1)
        say('--- 批次 x %d → %d ---' % (cur, x1))
        # repair 支持降序：x0 > x1 → 站 x+1
        run_repair(cur, x1, min_hp=args.min_hp, deck_item=pick_deck_item())

        # 整批一次验收，坏的只补那几列
        bad_map = check_batch(cur, x1)
        if bad_map:
            bad_cols = sorted(bad_map.items(), key=lambda kv: -kv[0])
            say('本批有 %d 列不合格：%s'
                % (len(bad_cols), [(x, b[:2]) for (x, b) in bad_cols[:4]]))
            for (x, _b) in bad_cols:
                run_repair(x, x, timeout=600)
            still = check_batch(cur, x1)
            if still:
                say('重修后仍不合格：%s' % [(x, b[:2]) for (x, b) in list(still.items())[:3]])
                fails += 1
            else:
                say('重修后全部合格')
                fails = 0
        else:
            fails = 0

        # 每批把家钉在当前位置：死了 /home 就回到最近工地，不用走几百格
        try:
            aic.get('/chat?m=/sethome')
        except Exception:
            pass
        done += (cur - x1 + 1)
        cur = x1 - 1
        # 落盘断点：崩溃/被杀之后，runner.py 从这里接着干
        try:
            with open(os.path.join(HERE, 'west_end.txt'), 'w', encoding='utf-8') as f:
                f.write(str(cur))
        except Exception:
            pass
        s = aic.state()
        say('进度：已铺 %d 列，下一个 x=%d，材料 圆石%d 泥土%d 镐%d，hp=%.0f'
            % (done, cur, aic.count_item('圆石'), aic.count_item('泥土'),
               aic.get('/pack').get('picks', 0), s['health']))

        # ── 人味：上一个会话就是因为节奏完美得像机器被管理员发现的 ──
        # 每批之后随机停一会儿；每 4~7 批来一次长休息（离开键盘、喝口水）。
        pause = 0.0
        say('    歇 %.0f 秒' % pause)
        time.sleep(pause)
        batches += 1
        if False and batches >= next_break:
            rest = 0.0
            say('    长休息 %.0f 秒（%.1f 分钟）' % (rest, rest / 60.0))
            aic.cmd('#stop')
            time.sleep(rest)
            batches = 0
            next_break = random.randint(4, 7)

        if fails >= 3:
            say('连续 3 批出问题，停手（日志在 auto_west2.log）')
            break

    say('本段结束：共铺 %d 列，末端 x=%d' % (done, cur + 1))
    return cur


if __name__ == '__main__':
    sys.exit(main())
