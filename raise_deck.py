# -*- coding: utf-8 -*-
"""
raise_deck.py -- 把 y=67 的旧路段**整体抬高一层**到 deck=68。

为什么不用 unify.py：
    unify 是"逐列削平/补齐"，遍历方向是 x 递增（往西会先站到没铺的格子上）。
    抬升的正确姿势是从东往西退着铺 —— 站在刚铺好的 x+1 上，往 x 那一列放，
    这样脚下永远有实心 deck，不会掉下去。

流程（每一列 x）：
    1. 站到 (x+1, deck+1, zc)      —— 站在已抬好的相邻列
    2. 逐 z 检查 deck 那一格：
         - 已经是圆石        → 跳过
         - 是别的实心方块    → 先挖掉，等真的变空气
         - deck-1 是空气     → 先填泥土（不能铺悬空）
    3. 放圆石 → **回读验证**（/place 会报假成功）
    4. 每格查血量 / 每列查怪，石头不够就停

用法：
    python raise_deck.py --start -8160 --end -8232
"""
import argparse
import math
import sys
import time

import aic
import aura
import defend
import storage
from snap import snap
from worldmem import WorldMem

WIDTH = 5
AIR = ('空气', '洞穴空气', '虚空空气')
PICK_NAMES = ('石镐', '铁镐', '铜镐', '木镐', '金镐', '钻石镐', '下界合金镐')
MIN_HP = 12.0


def say(*a):
    print('  [raise]', *a, flush=True)


def solid(t):
    return t is not None and t not in AIR


def is_cobble(t):
    return t is not None and '圆石' in str(t)


class Raiser:
    def __init__(self, deck=68, z_centre=272, width=WIDTH, min_hp=None):
        self.deck = deck
        self.zc = z_centre
        self.z0 = z_centre - width // 2
        self.z1 = z_centre + width // 2
        # 血量门槛可调：有 /sethome 之后死亡只值 10 秒，白天又开着 kill-aura + no-fall，
        # 为了等回血而停工不划算。默认仍按 12 保守。
        self.min_hp = MIN_HP if min_hp is None else float(min_hp)
        self.placed = self.skipped = self.failed = self.dirt = self.dug = 0
        self._tool_kind = None
        self._tool_ok = False

    # ---------- 玩家位置 ----------
    def feet(self):
        s = aic.state()
        return (math.floor(float(s['x'])), math.floor(float(s['y'])),
                math.floor(float(s['z'])))

    def dist_to(self, x, y, z):
        s = aic.state()
        ex = float(s['x'])
        ey = float(s['y']) + 1.62
        ez = float(s['z'])
        return math.hypot(x + 0.5 - ex, y + 0.5 - ey, z + 0.5 - ez)

    def refresh(self, x, pad=6):
        # box 以目标列为中心 —— 绝不掺玩家坐标（否则 /blockmap 超时 → 旧数据）
        return WorldMem.refresh_near(x, self.zc, rx=pad,
                                     y_lo=self.deck - 10, y_hi=self.deck + 8)

    def stand(self, x, tries=3):
        """站到 (x, deck+1, zc) 上。返回是否站稳。"""
        for _ in range(tries):
            px, py, pz = self.feet()
            if px == x and abs(pz - self.zc) <= 1 and py >= self.deck + 1:
                return True
            aic.cmd('#goto %d %d %d' % (x, self.deck + 1, self.zc))
            t0 = time.time()
            while time.time() - t0 < 9:
                time.sleep(0.5)
                px, py, pz = self.feet()
                if px == x and abs(pz - self.zc) <= 1 and py >= self.deck + 1:
                    aic.cmd('#stop')
                    return True
                if not aic.state().get('pathing'):
                    break
            aic.cmd('#stop')
        px, py, pz = self.feet()
        return px == x and py >= self.deck + 1

    def approach(self, x, z):
        """距离 > 4.0 时走近一点（服务端判的是眼→方块中心 4.5）"""
        for _ in range(2):
            if self.dist_to(x, self.deck, z) <= 4.0:
                return True
            aic.cmd('#goto %d %d %d' % (x + 1, self.deck + 1, z))
            t0 = time.time()
            while time.time() - t0 < 5:
                time.sleep(0.35)
                if self.dist_to(x, self.deck, z) <= 4.0:
                    aic.cmd('#stop')
                    return True
                if not aic.state().get('pathing'):
                    break
            aic.cmd('#stop')
        return self.dist_to(x, self.deck, z) <= 4.5

    # ---------- 工具/安全闸 ----------
    def guard_tools(self, block=None):
        """挖掘前的工具闸。

        block 给了就按材料选工具：泥土/草方块/沙 → 锹，木头 → 斧，其余 → 镐。
        以前这里无条件切镐，于是挖土也拿镐子（既慢又白烧耐久）。
        """
        import mine as _mine
        import toolkit
        kind = toolkit.tool_kind(block) if block else 'pick'
        if kind == self._tool_kind and self._tool_ok:
            return True          # 同一批材料，别每次都去切/去造
        ok = False
        if kind == 'shovel':
            if not toolkit.ensure_shovel(2):
                say('没有锹，退回用镐挖土（不理想）')
            else:
                ok = bool(toolkit.hold_tool('shovel'))
                if ok:
                    self._tool_kind, self._tool_ok = kind, True
                    return True
        elif kind == 'axe':
            ok = bool(toolkit.hold_tool('axe'))
            if ok:
                self._tool_kind, self._tool_ok = kind, True
                return True
        if _mine.picks() == 0:
            say('没有镐，现造')
            _mine.make_picks(2)
        # 手持必须**读 state 验证**过是镐：镐断掉后自动选工具会退到斧头，
        # 之前就是拿铁斧砸石头（慢十倍还毁斧头）
        ok, held = _mine.held_is_pick()
        if not ok:
            say('held=%s -> 切镐' % held)
            _mine.hold_pick()
            ok, held = _mine.held_is_pick()
        if not ok:
            say('切不到镐（held=%s），不挖' % held)
        self._tool_kind, self._tool_ok = kind, ok
        return ok

    def forget_tool(self):
        """工具可能断了 —— 下次重新判断，别信缓存。"""
        self._tool_kind, self._tool_ok = None, False

    def guard_hp(self):
        """死亡检查 + 血量门槛。

        以前这里直接调 defend.check_alive()，而它内部写死 retreat_below=12 ——
        于是 --min-hp 5 根本不起作用，hp 7 照样被判 'hp low' 停工。
        现在只有"死没死"用 check_alive 的思路，门槛完全由 self.min_hp 决定。
        """
        s = aic.state()
        if not s.get('alive') or s.get('health', 0) <= 0:
            # 先掐掉寻路/输入，再复活。
            # Baritone 的 goal 不会因为死亡失效 —— 不掐的话人一复活就自己走开，
            # 用户两次指出"死了还在寻路"。
            try:
                aic.cmd('#stop')
                for _k in ('FORWARD', 'BACK', 'LEFT', 'RIGHT', 'JUMP', 'SPRINT', 'SNEAK'):
                    aic.get('/input?k=%s&down=false' % _k)
            except Exception:
                pass
            try:
                import revive
                revive.respawn()
            except Exception:
                pass
            return False
        return s.get('health', 0) >= self.min_hp

    def dig_cell(self, x, y, z, tries=6):
        """挖一格并**等到真的变空气**（/dig 是异步队列，breakBlock 只是"开始挖"）

        每个目标先读它的方块类型 → 按类型切工具（土用锹、石用镐、木用斧）。
        """
        for attempt in range(tries):
            wm = self.refresh(x)
            t = wm.block(x, y, z)
            if not solid(t):
                return True
            self.guard_tools(t)
            aic.get('/dig?x1=%d&y1=%d&z1=%d&x2=%d&y2=%d&z2=%d'
                    % (x, y, z, x, y, z))
            time.sleep(0.6)
            if attempt >= 1:
                self.forget_tool()      # 挖两下没动，可能是工具断了 —— 重新判断
        wm = self.refresh(x)
        return not solid(wm.block(x, y, z))

    # ---------- 一列 ----------
    def column(self, x):
        if not self.stand(x + 1):
            px, py, pz = self.feet()
            return False, 'cannot stand at %d (player %d,%d,%d)' % (x + 1, px, py, pz)

        wm = self.refresh(x)
        todo = []
        for z in range(self.z0, self.z1 + 1):
            t = wm.block(x, self.deck, z)
            if is_cobble(t):
                self.skipped += 1
                continue
            todo.append(z)

        if not todo:
            return True, 'nothing to do'

        # deck 上是别的实心方块 → 先挖掉
        for z in list(todo):
            if solid(wm.block(x, self.deck, z)):
                if not self.guard_tools():
                    return False, 'no pickaxe'
                if not self.dig_cell(x, self.deck, z):
                    self.failed += 1
                    todo.remove(z)
                    say('x=%d z=%d deck 挖不动，跳过' % (x, z))
        if todo:
            self.dug += 1
            wm = self.refresh(x)

        for z in todo:
            if not self.guard_hp():
                return False, 'hp low'

            if self.dist_to(x, self.deck, z) > 4.0:
                if not self.approach(x, z):
                    self.failed += 1
                    say('x=%d z=%d 够不着(%.2f)' % (x, z, self.dist_to(x, self.deck, z)))
                    continue

            # 路基：deck-1 是空气就先填泥土
            if not solid(wm.block(x, self.deck - 1, z)):
                aic.get('/place?x=%d&y=%d&z=%d&item=泥土'
                        % (x, self.deck - 1, z))
                time.sleep(0.3)
                wm = self.refresh(x)
                if solid(wm.block(x, self.deck - 1, z)):
                    self.dirt += 1

            aic.get('/place?x=%d&y=%d&z=%d&item=圆石' % (x, self.deck, z))
            time.sleep(0.3)
            wm = self.refresh(x)
            if is_cobble(wm.block(x, self.deck, z)):
                self.placed += 1
            else:
                # 再试一次（第一次可能是 AABB 或距离边界）
                aic.get('/place?x=%d&y=%d&z=%d&item=圆石' % (x, self.deck, z))
                time.sleep(0.35)
                wm = self.refresh(x)
                if is_cobble(wm.block(x, self.deck, z)):
                    self.placed += 1
                else:
                    self.failed += 1
                    say('x=%d z=%d 放置失败（回读仍是 %s）'
                        % (x, z, wm.block(x, self.deck, z)))
        return True, 'ok'

    # ---------- 主循环 ----------
    def travel(self, x, timeout=150):
        """到达起点附近。

        **几百格的距离一律传送，不走路**（用户明确要求"不要走动"）：
        走路又慢又招怪，还会在服务端留下一个"来回长途移动"的显眼轨迹。
        顺序：/home（家每批都钉在工地）→ 还远就用 /back（死亡点在前线）→
        最后才退回 Baritone 走。
        """
        px, py, pz = self.feet()
        if px == x and py >= self.deck + 1:
            return True

        dist = abs(px - x)
        if dist > 40:
            for cmd in ('/home', '/back'):
                say('travel 距离 %d 格 → 试 %s（不走路）' % (dist, cmd))
                try:
                    aic.get('/input?k=SNEAK&down=true')
                    time.sleep(2.6)
                    aic.get('/chat?m=%s' % cmd)
                    time.sleep(6.0)
                    aic.get('/input?k=SNEAK&down=false')
                except Exception:
                    pass
                px, py, pz = self.feet()
                if abs(px - x) <= 40:
                    say('  %s 到位 (%d,%d,%d)' % (cmd, px, py, pz))
                    break
                dist = abs(px - x)

        if abs(px - x) <= 40 and py >= self.deck + 1:
            aic.cmd('#goto %d %d %d' % (x, self.deck + 1, self.zc))
            t0 = time.time()
            while time.time() - t0 < 40:
                time.sleep(0.8)
                px, py, pz = self.feet()
                if px == x and py >= self.deck + 1:
                    aic.cmd('#stop')
                    return True
                if not aic.state().get('pathing'):
                    break
            aic.cmd('#stop')
            px, py, pz = self.feet()
            return px == x and py >= self.deck + 1

        say('travel from (%d,%d,%d) to (%d,%d,%d)' % (px, py, pz, x, self.deck + 1, self.zc))
        aura.ensure_aura()
        aic.cmd('#goto %d %d %d' % (x, self.deck + 1, self.zc))
        t0 = time.time()
        last_move = time.time()
        last_px = px
        while time.time() - t0 < timeout:
            time.sleep(1.0)
            st = aic.state()
            px, py, pz = self.feet()
            if px == x and py >= self.deck + 1:
                aic.cmd('#stop')
                time.sleep(0.5)
                say('arrived (%d,%d,%d) hp=%.0f' % (px, py, pz, st.get('health', 0)))
                return True
            if st.get('health', 20) < max(6, self.min_hp - 5):
                aic.cmd('#stop')
                say('travel 中血量 %.0f → 停下接战' % st.get('health', 0))
                defend.defend(seconds=8.0)
                if aic.state().get('health', 0) < 10:
                    defend.eat_to_full()
                aic.cmd('#goto %d %d %d' % (x, self.deck + 1, self.zc))
                t0 = time.time()
                continue
            if px != last_px:
                last_px = px
                last_move = time.time()
            if not st.get('pathing') and time.time() - last_move > 4:
                aic.cmd('#goto %d %d %d' % (x, self.deck + 1, self.zc))
                last_move = time.time()
        aic.cmd('#stop')
        px, py, pz = self.feet()
        say('travel timed out at (%d,%d,%d)' % (px, py, pz))
        return False

    def run(self, x_start, x_stop):
        stop = None
        rng = range(x_start, x_stop - 1, -1) if x_start > x_stop else range(x_start, x_stop + 1)
        first = x_start + 1 if x_start > x_stop else x_start - 1
        self.travel(first)
        n = 0
        for x in rng:
            if aic.count_item('圆石') < 6:
                say('圆石不足，停在 x=%d' % x)
                stop = x
                break
            if storage.free_slots() < 2:
                say('背包满，腾格子')
                storage.ensure_space(6)
            if defend.hostiles(radius=14):
                aura.hold_weapon()
                aura.ensure_aura()
                if not defend.fight_or_flee(safe_spot=(x + 8, self.deck + 1, self.zc)):
                    stop = x
                    say('打不过，撤')
                    break
            ok, why = self.column(x)
            n += 1
            if not ok:
                say('STOP x=%d : %s' % (x, why))
                snap('raise-%d' % x)
                stop = x
                break
            if n % 8 == 0:
                s = aic.state()
                say('x=%d  placed=%d dirt=%d skipped=%d failed=%d cobble=%d hp=%.0f'
                    % (x, self.placed, self.dirt, self.skipped, self.failed,
                       aic.count_item('圆石'), s.get('health', 0)))
        return stop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=int, required=True)
    ap.add_argument('--end', type=int, required=True)
    ap.add_argument('--deck', type=int, default=68)
    ap.add_argument('--z', type=int, default=272)
    ap.add_argument('--minutes', type=float, default=0)
    args = ap.parse_args()

    r = Raiser(args.deck, args.z)
    s = aic.state()
    say('player (%d,%d,%d) hp=%.0f cobble=%d dirt=%d  %d -> %d'
        % (math.floor(float(s['x'])), math.floor(float(s['y'])),
           math.floor(float(s['z'])), s['health'],
           aic.count_item('圆石'), aic.count_item('泥土'), args.start, args.end))
    t0 = time.time()
    stop = r.run(args.start, args.end)
    print()
    print('=== summary ===')
    print('  placed=%d dirt=%d skipped=%d failed=%d  %.1f min'
          % (r.placed, r.dirt, r.skipped, r.failed, (time.time() - t0) / 60.0))
    print('  cobble=%d dirt=%d' % (aic.count_item('圆石'), aic.count_item('泥土')))
    if stop is not None:
        print('  stopped at x=%d' % stop)
    return 0


if __name__ == '__main__':
    sys.exit(main())
