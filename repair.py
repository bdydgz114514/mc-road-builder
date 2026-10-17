# -*- coding: utf-8 -*-
"""
repair.py -- 定点修补：缺格 / 杂色 / deck 以上冒头的地形 / 悬空。

复用 raise_deck.Raiser 的原语（整列居中的 blockmap box、眼→中心距离、异步 /dig 等空气、回读验证），
只把"往上抬一层"换成"把这一列修成干净的 5 格圆石路面"。

每一列做四件事：
    1. 削平：deck+1 .. deck+CUT 的非空气方块全挖掉（地形冒头）
    2. deck 上是别的实心方块 → 挖掉
    3. deck-1 是空气 → 填泥土（不许悬空）
    4. deck 是空气 → 放圆石，回读验证

用法：
    python repair.py -8232 -8023          # 全路扫一遍，只修不合格的列
    python repair.py -8110 -8080 --scan   # 只报告，不动手
"""
import argparse
import sys
import time

import aic
import aura
import defend
import storage
from snap import snap
from raise_deck import Raiser, solid, is_cobble, say

CREEPERS = ('苦力怕', '爬行者', 'creeper')

# 路面材料，可用 --deck-item 覆盖（泥土更快：锹挖土 ~0.15s/块，且削草方块本身掉土）
DECK_ITEM = '圆石'


def deck_ok(t):
    return t is not None and DECK_ITEM in str(t)


def creeper_near(radius=6):
    """苦力怕专项检查。

    实测死因：`PlayerName被苦力怕炸死了`。苦力怕近身就引爆，kill-aura 就算打死了它，
    爆炸也已经发生 —— 20 血 7 秒清零。盔甲才是根本解法（铁胸甲能砍掉一大半伤害），
    没有盔甲时唯一有效的办法是**在它引爆之前先退开**。
    """
    for f in defend.hostiles(radius=radius):
        name = str(f.get('name') or f.get('type') or '')
        if any(k in name for k in CREEPERS):
            return f
    return None


class Repairer(Raiser):
    def __init__(self, deck=68, z_centre=272, width=5, cut=6, subdepth=1,
                 batch_cut=False, desc=False, min_hp=None):
        Raiser.__init__(self, deck, z_centre, width, min_hp=min_hp)
        self.cut = cut
        self.cut_n = 0
        self.subdepth = max(1, subdepth)     # deck-1 .. deck-subdepth 都要垫实
        self.sub_n = 0
        self.batch_cut = batch_cut
        # desc=True 表示往西施工：站在已经铺好的 **x+1**（东侧）上往 x 放。
        # 往东施工（默认）则站 x-1。站错侧 = 站在没铺的地形上，离 deck 差十几格根本放不到。
        self.desc = desc

    def is_wet(self, x):
        """这一列是不是水面（deck 位置和下面 3 格都没有实心方块，且有水）"""
        if x is None:
            return False
        try:
            wm = self.refresh(x)
        except Exception:
            return False
        # 往下看到 6 格：实测水面段的"水"在 deck-6 附近（中间是空气），
        # 只看 3 格会漏判 —— is_wet(-470) 曾因此返回 False。
        wet = any('水' in str(wm.block(x, self.deck - d, z))
                  for z in range(self.z0, self.z1 + 1) for d in range(0, 7))
        solid_any = any(solid(wm.block(x, self.deck - d, z))
                        for z in range(self.z0, self.z1 + 1) for d in range(1, 7))
        return wet and not solid_any

    def diagnose(self, wm, x):
        """返回 (需挖的 deck 以上方块[(y,z,name)], 需挖的 deck 杂色[(z,name)],
                  缺的 deck 格, 悬空格)"""
        above = []
        for z in range(self.z0, self.z1 + 1):
            for y in range(self.deck + 1, self.deck + self.cut + 1):
                t = wm.block(x, y, z)
                if solid(t):
                    above.append((y, z, t))
        other, missing = [], []
        for z in range(self.z0, self.z1 + 1):
            t = wm.block(x, self.deck, z)
            if deck_ok(t):
                continue
            if solid(t):
                other.append((z, t))
            else:
                missing.append(z)
        floaty = [z for z in range(self.z0, self.z1 + 1)
                  if deck_ok(wm.block(x, self.deck, z))
                  and not solid(wm.block(x, self.deck - 1, z))]
        return above, other, missing, floaty

    def sink_to_deck(self, x, max_dig=12):
        """先把自己降到 deck 那一层。

        深山地形里：路面在 68，地面在 73~80。站在顶层削平后，deck 在脚下 5~6 格，
        `/place` 全部被距离拒绝（回读空气，failed=15）。**必须先下到坑底**。
        做法就是一级一级挖自己脚下那块（那一格永远在 4.5 格内），靠 no-fall 落地。
        """
        px, py, pz = self.feet()
        gap = py - (self.deck + 1)
        if gap <= 1:
            return True
        aic.get('/module?m=no-fall&on=true')
        for _ in range(max_dig):
            px, py, pz = self.feet()
            if py - (self.deck + 1) <= 1:
                return True
            tgt = (px, py - 1, pz)
            wm = self.refresh(px)
            t = wm.block(*tgt)
            if not solid(t):
                time.sleep(0.4)
                continue
            self.guard_tools(t)
            aic.get('/dig?x1=%d&y1=%d&z1=%d&x2=%d&y2=%d&z2=%d' % (tgt + tgt))
            for _ in range(8):
                time.sleep(0.45)
                if not self.refresh(px).is_solid(*tgt):
                    break
            time.sleep(0.5)
        px, py, pz = self.feet()
        say('降层完成：(%d,%d,%d) 目标 deck+1=%d' % (px, py, pz, self.deck + 1))
        return py - (self.deck + 1) <= 1

    def column(self, x):
        # 站在**已经铺好的那一侧**：往东施工站 x-1，往西施工站 x+1。
        first, second = (x + 1, x - 1) if self.desc else (x - 1, x + 1)
        # 水面那列**不能当站位**：走上去寻路就废（游泳状态 Baritone 会乱走），
        # 而且服务端会判"站在水里"。
        if self.is_wet(first):
            say('站位 %d 是水面 → 跳过' % first)
            first = None
        if self.is_wet(second):
            second = None
        if not ((first and self.stand(first)) or (second and self.stand(second))):
            px, py, pz = self.feet()
            return False, 'cannot stand near %d (player %d,%d,%d)' % (x, px, py, pz)
        self.sink_to_deck(x)
        # 不能站在**目标列**里放：那样每格都在自己脚下/身上，服务端判 body-block，
        # 5 格全失败（实测 x=-413 就是这么废掉的）。站进目标列就先挪到隔壁。
        px, py, pz = self.feet()
        if px == x:
            side = x + 1 if self.desc else x - 1
            say('站在目标列 x=%d 里 → 挪到 %d' % (x, side))
            self.stand(side)
        # z 也要回中线：站在 z=271（允许 ±1）时，z=270 那一格正好在自己侧后方，
        # 服务端拒绝，于是每列都缺北边一条（实测 -683..-685 全是 deck@270）。
        px, py, pz = self.feet()
        if pz != self.zc:
            say('z=%d 偏了 → 回中线 z=%d' % (pz, self.zc))
            self.stand(px)

        wm = self.refresh(x)
        above, other, missing, floaty = self.diagnose(wm, x)
        if not (above or other or missing or floaty):
            return True, 'ok already'

        # 1) 削平冒头
        if above:
            # 按**最多的那种材料**选工具：整列土就用锹，整列石就用镐
            kinds = {}
            for (_y, _z, name) in above:
                kinds[name] = kinds.get(name, 0) + 1
            main_mat = max(kinds.items(), key=lambda kv: kv[1])[0]
            if not self.guard_tools(main_mat):
                return False, 'no usable tool for %s' % main_mat
            if self.batch_cut and len(above) > 2:
                # 一次 /dig 挖整列（box 覆盖 deck+1..deck+cut 全 z）
                aic.get('/dig?x1=%d&y1=%d&z1=%d&x2=%d&y2=%d&z2=%d'
                        % (x, self.deck + 1, self.z0, x, self.deck + self.cut, self.z1))
                ok = False
                for _ in range(10):
                    time.sleep(1.2)
                    if not self.guard_hp():
                        return False, 'hp low'
                    wm = self.refresh(x)
                    if not any(solid(wm.block(x, y, z)) for (y, z, _n) in above):
                        ok = True
                        break
                if ok:
                    self.cut_n += len(above)
                else:
                    # 批量没挖干净 → 回落到逐格
                    for (y, z, _n) in above:
                        if not self.guard_hp():
                            return False, 'hp low'
                        if self.dig_cell(x, y, z):
                            self.cut_n += 1
            else:
                for (y, z, _n) in above:
                    if not self.guard_hp():
                        return False, 'hp low'
                    if self.dig_cell(x, y, z):
                        self.cut_n += 1
            wm = self.refresh(x)
            say('x=%d 削平 %d 格（%s）' % (x, len(above), main_mat))

        # 2) deck 杂色：**一次 /dig 挖整层**（原来逐格挖+逐格回读，5 格要 5 次导出）
        if other:
            if not self.guard_hp():
                return False, 'hp low'
            self.guard_tools(other[0][1])
            aic.get('/dig?x1=%d&y1=%d&z1=%d&x2=%d&y2=%d&z2=%d'
                    % (x, self.deck, self.z0, x, self.deck, self.z1))
            left = None
            for _ in range(8):
                time.sleep(0.8)
                wm = self.refresh(x)
                left = [z for (z, _n) in other if solid(wm.block(x, self.deck, z))]
                if not left:
                    break
            if left:
                # 批量没挖干净 → 逐格补挖
                for z in left:
                    if self.dig_cell(x, self.deck, z):
                        left.remove(z)
            wm = self.refresh(x)
            for (z, _n) in other:
                if not solid(wm.block(x, self.deck, z)):
                    missing.append(z)
                else:
                    self.failed += 1
                    say('x=%d z=%d deck 杂色挖不动' % (x, z))

        # 3+4) 补格：先一口气放（路基 + 圆石），再**统一回读一次**。
        #      原来每放一格就 refresh 一次，5 格要 10~15 次 blockmap 导出，
        #      单列 19 秒里一半耗在这上面。
        need = sorted(set(missing + floaty))

        # 3) 路基（deck-1 往下垫 subdepth 层）
        for z in need:
            if solid(wm.block(x, self.deck - 1, z)):
                continue
            for d in range(1, self.subdepth + 1):
                yy = self.deck - d
                if solid(wm.block(x, yy, z)) or self.dist_to(x, yy, z) > 4.4:
                    continue
                for alt in ('泥土', '安山岩', '花岗岩', '闪长岩', '圆石'):
                    if aic.count_item(alt) <= 0:
                        continue
                    aic.get('/place?x=%d&y=%d&z=%d&item=%s' % (x, yy, z, alt))
                    time.sleep(0.22)
                    if alt == '泥土':
                        self.dirt += 1
                    else:
                        self.sub_n += 1
                    break

        # 4) 一次性铺圆石（距离不够的先走近）
        for z in need:
            if self.dist_to(x, self.deck, z) > 4.0:
                if not self.approach(x, z):
                    say('x=%d z=%d 够不着' % (x, z))
                    continue
            aic.get('/place?x=%d&y=%d&z=%d&item=圆石' % (x, self.deck, z))
            time.sleep(0.22)

        # 5) 统一回读，只对没成的补一刀
        time.sleep(0.35)
        wm = self.refresh(x)
        bad = [z for z in need if not deck_ok(wm.block(x, self.deck, z))]
        if bad:
            for z in bad:
                aic.get('/place?x=%d&y=%d&z=%d&item=圆石' % (x, self.deck, z))
                time.sleep(0.25)
            time.sleep(0.3)
            wm = self.refresh(x)
            for z in bad:
                if is_cobble(wm.block(x, self.deck, z)):
                    self.placed += 1
                else:
                    self.failed += 1
                    say('x=%d z=%d 放置失败（回读 %s）' % (x, z, wm.block(x, self.deck, z)))
        self.placed += len([z for z in need if z not in bad])
        return True, 'fixed above=%d other=%d missing=%d float=%d' % (
            len(above), len(other), len(missing), len(floaty))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('x0', type=int)
    ap.add_argument('x1', type=int)
    ap.add_argument('--deck', type=int, default=68)
    ap.add_argument('--z', type=int, default=272)
    ap.add_argument('--cut', type=int, default=6)
    ap.add_argument('--subdepth', type=int, default=1)
    ap.add_argument('--batch', action='store_true', help='按列批量 /dig 削平（大段返工时必开）')
    ap.add_argument('--day-only', action='store_true',
                    help='只白天施工：入夜就收工（没盔甲时这是唯一可靠的保命办法）')
    ap.add_argument('--deck-item', default='圆石', help='路面材料（泥土更快）')
    ap.add_argument('--scan', action='store_true')
    ap.add_argument('--min-hp', type=float, default=None,
                    help='血量门槛（默认 12）。已 /sethome 时可以降到 5 —— 死一次只值 10 秒')
    args = ap.parse_args()
    global DECK_ITEM
    DECK_ITEM = args.deck_item

    r = Repairer(args.deck, args.z, cut=args.cut, subdepth=args.subdepth,
                 batch_cut=args.batch, desc=args.x0 > args.x1, min_hp=args.min_hp)
    say('scope x %d..%d deck=%d z=%d..%d  %s'
        % (args.x0, args.x1, r.deck, r.z0, r.z1,
           '往西（站 x+1）' if r.desc else '往东（站 x-1）'))
    if r.desc:
        xs = range(args.x0, args.x1 - 1, -1)
    else:
        xs = range(args.x0, args.x1 + 1)

    if args.scan:
        bad = 0
        for x in xs:
            wm = r.refresh(x)
            above, other, missing, floaty = r.diagnose(wm, x)
            if above or other or missing or floaty:
                bad += 1
                print('x=%6d  above=%s other=%s missing=%s float=%s'
                      % (x, above, other, missing, floaty))
        print('  %d bad column(s)' % bad)
        return 0

    t0 = time.time()
    if args.day_only:
        import daytime
        if not daytime.wait_for_day(max_wait=300):
            say('天黑了，收工（--day-only）')
            return 0
    r.travel(args.x0 + 1 if r.desc else args.x0 - 1)
    for x in xs:
        if args.day_only:
            import daytime
            if not daytime.is_day():
                say('入夜，收工于 x=%d（--day-only）' % x)
                break
        if aic.count_item('圆石') < 6:
            say('圆石不足，停在 x=%d' % x)
            snap('repair-out-of-cobble')
            break
        if storage.free_slots() < 2:
            storage.ensure_space(6)
        if defend.hostiles(radius=14):
            aura.hold_weapon()
            aura.ensure_aura()
            # 苦力怕先闪开：它一引爆就是 7 秒清血，没有盔甲时不退必死
            creep = creeper_near(6)
            if creep:
                say('苦力怕 %.1f 格 → 先退开' % creep.get('dist', 0))
                defend.retreat_to(x + 12, r.deck + 1, r.zc, timeout=20)
                aura.ensure_aura()
                time.sleep(2.0)
                if creeper_near(6):
                    say('苦力怕还在，换方向退')
                    defend.retreat_to(x + 12, r.deck + 1, r.zc + 12, timeout=20)
            # 低血量也照打：/sethome 已经钉在工地，死一次只值十几秒；
            # 而 fight_or_flee 的门槛是 SAFE_HP=16，HP 低的时候永远判"打不过"，
            # 于是整批直接中止 —— 实测就是这样卡在 -745 的。只有快死（<3）才撤。
            hp_now = aic.state().get('health', 0)
            if hp_now < 1:
                say('hp=%.0f 太低 → 退开回血' % hp_now)
                defend.retreat_to(x + 16, r.deck + 1, r.zc, timeout=15)
                defend.eat_to_full(verbose=False)
                break
            defend.defend(seconds=6.0, verbose=False)
            aura.ensure_aura()
        ok, why = r.column(x)
        if not ok:
            say('STOP x=%d : %s' % (x, why))
            snap('repair-%d' % x)
            break
        if why != 'ok already':
            say('x=%d %s' % (x, why))

    print()
    print('=== summary ===')
    print('  placed=%d cut=%d dirt=%d filler=%d failed=%d  %.1f min'
          % (r.placed, r.cut_n, r.dirt, r.sub_n, r.failed, (time.time() - t0) / 60.0))
    print('  cobble=%d dirt=%d' % (aic.count_item('圆石'), aic.count_item('泥土')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
