# mc-road-builder · 让真实玩家角色自动修一条几千格的路

> 在 **Minecraft Java 1.21.11 / Fabric** 上，用 Meteor + Baritone 的 HTTP 桥，
> 驱动一个**真实登录的玩家角色**自动削山、填方、架拱桥，铺出 5 格宽、跨数千格的连续路面。
> 没有任何「假玩家」「服务端插件」「地图编辑器」—— 一切动作都是这个角色自己走过去、自己挖、自己放。

---

## 它到底在造什么

```
目标：一条 z = 270..274（5 格宽）、路面高度 y = 68 的连续道路
      遇山削平（cut 3 格够走就行），遇水起拱桥（单峰 + 护栏），陆地即路
长度：数千格（本项目实际推进到 1000+ 格，东西两段合计仍在施工）
```

设计上的三条硬约束（都是用户定的）：

1. **路必须平**，只有桥才隆起。
2. **铺路不能站在要填的那一格上** —— 服务端会判 body-block，整列 5 格全失败。
3. **水面不站人** —— 站在水里 Baritone 的寻路会失效，人会乱走。

---

## 架构

```
┌──────────────┐   HTTP(127.0.0.1:25580)   ┌─────────────────────────┐
│  Python 脚本 │ ────────────────────────> │ 游戏内 Fabric 模组 AIControl │
│  (本仓库)    │ <──────────────────────── │  /state /place /dig /craft  │
└──────────────┘      回读世界方块数据        └─────────────────────────┘
        │                                              │
        │ 子进程                                        │ mc.execute() 切主线程
        ▼                                              ▼
   runner.py  守护                             Baritone API / Meteor 模块
   auto_west.py 驱动器
   repair.py   削平+铺装
   bridge.py   拱桥
```

**核心信条：所有动作 API 都会"报假成功"。** `/place` 说 `placed 圆石 at ...`，格子可能是空气；
`/fill` 说 `queued 15 cells`，超出 4.5 格的部分被静默丢弃。
所以本仓库的每个写操作后面都跟一次**独立回读**（`worldmem.py` 读二进制方块图），
校验不过就重试，绝不信任返回值。

---

## 模块一览

| 文件 | 职责 |
|---|---|
| `aic.py` | HTTP 桥客户端（`/state` `/place` `/dig` `/craft` `/container` `/module` `/input`） |
| `worldmem.py` | 方块数据回读：调 `/blockmap` 落盘成二进制，mmap 读取，**校验返回的 box 是否匹配请求** |
| `toolkit.py` | 合成与工具链：木板/棍/镐/锹/工作台，物种无关（云杉/橡木都认），合成前腾格子 |
| `raise_deck.py` | 建造基类：站位、降层、挖格、血量守卫、**长途传送（不走路）** |
| `repair.py` | 主力：逐列削平 + 铺 5 格 + 补路基，批量 `/dig`，`--deck-item` 可换路面材料 |
| `bridge.py` | 抛物线拱桥：单峰、带护栏、桥下填方，支持正/反两个方向施工 |
| `auto_west.py` | 驱动器：分批推进、整批回读验收、缺料自动补、水面自动转桥、**死亡检查点** |
| `runner.py` | 通宵守护：驱动器崩了重启、游戏崩了重开进服、断点久不动就点「回到游戏」除卡 |
| `keeplive.py` | 守命：检测死亡 → 先 `#stop` 抬键 → 复活 → `/home` 回工地 |
| `watchdog.py` | 有人进服就停机（可只盯指定前缀的管理员），写 `HALT` 旗标让全链静默 |
| `shots_daemon.py` | 每 15 秒一帧落盘，供事后回查（最小化窗口会静默复制旧帧，用 sha256 检测） |

---

## 快速开始

```powershell
# 0) 前置：游戏已启动、已进服，模组桥在 127.0.0.1:25580
python -c "import aic; print(aic.get('/ping'))"

# 1) 探一下路在哪、缺什么
python roadscan.py --x0 -1000 --x1 -1100
python inspect_cols.py -1046 -1060

# 2) 修一段（从 x0 到 x1，往西 = x0 > x1）
python repair.py -1046 -1060 --cut 3 --subdepth 2 --batch --min-hp 2 --deck-item 泥土

# 3) 起拱桥（跨水）
python bridge.py --x0 -463 --x1 -482 --peak 4 --under 泥土 --rail

# 4) 全自动推进（推荐）
python auto_west.py --start -1046 --end -7888 --batch 14 --hours 6 --min-hp 2

# 5) 通宵：用守护跑它
python runner.py --start -1046 --end -7888 --hours 9 --batch 14 --min-hp 2

# 6) 有人进服自动停机（另开一个窗）
python watchdog.py --poll 2 --only-prefix G --allow SomeFriend --auto-resume
```

`ps1/resume.ps1` 是以上全家的合成版：探桥 → 清旗标 → 读断点 → 拉起 watchdog / shots / keeplive / runner。

> 仓库里的绝对路径（`D:\mc-road-builder`、`D:\Minecraft`）是脱敏后的占位，跑之前改成你自己的。

---

## 实测数据

| 场景 | 速率 |
|---|---|
| 平地（cut≈0） | 5~6 列/分钟（每列 5 格铺装 + 验收） |
| 丘陵（cut 10~25） | 3~4 列/分钟 |
| 深山削方（cut 30+） | 1.5~2 列/分钟 |

代价（血的教训）：一把石镐 131 耐久 ≈ 只够削 **6 列**深山 → 必须常备 3 把，否则一半时间在合成。

---

## 经验教训

分两部分，都写成可复用的条目：

- [`docs/LESSONS.md`](docs/LESSONS.md) — 本项目踩过的 20 条坑（距离/AABB/异步队列/回读/材料/死亡/管理员/长跑稳定性）
- [`docs/HANDOVER.md`](docs/HANDOVER.md) — 第五、六版交接书原文，含事故复盘与逐条修改理由

---

## 边界

- 这是**客户端侧**的自动化：不做服务端插件，不改服务端逻辑，不伪造发包。
- 所有动作都是这个账号自己走过去做的，速度受 4.5 格交互距离与 6-tick 挖掘冷却限制。
- 代码面向「自己玩的服务器 / 有授权的环境」。上线前自己确认当地规则与服务器条款。

## License

MIT
