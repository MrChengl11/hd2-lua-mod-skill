# 案例:告别周期性掉帧与扫描风暴 —— 运行时生命周期治理完整记录

> 时间:2026-09-23。
> 用户反馈:使用轨道激光等自研 Mod 时，游戏**间歇性出现帧率突然减半、持续几十秒后自行恢复正常**的现象。
> 本文记录实机日志取证、根因定位、生命周期治理原则与全套修复方案。

---

## 0. 现象与实机日志取证(抓现行)

用户报「间歇性掉帧」，最先怀疑的就是 `_G.update` 中的扫描驱动。
直接打开 `%LOCALAPPDATA%/Hd2OrbitalLaserFree/OrbitalLaserFree.log`，查看 frame 时间戳与扫描轮次：

```text
[frame 0] orbital-laser-free-v6 armed; out_dir=C:\Users\...\Hd2OrbitalLaserFree
[frame 120] 第 1 轮:共 4121 个可读内存区
[frame 1394] 第 1 轮扫描结束:签名命中 11 处,8 个 StratagemSettings 区块,74 条策略记录
[frame 1394] PATCHED 轨道激光 record 0x2495669A840 (id 970450596)

[frame 36000] 定期全量重扫(兜底:副本可能被搬到别的地方)
[frame 36002] 第 2 轮:共 15055 个可读内存区
[frame 37642] 第 2 轮扫描结束:历时 1640 帧 (约 27 秒)

[frame 72000] 定期全量重扫(兜底:副本可能被搬到别的地方)
[frame 72002] 第 3 轮:共 28594 个可读内存区
[frame 74558] 第 3 轮扫描结束:历时 2556 帧 (约 42.6 秒)

[frame 108000] 定期全量重扫(兜底:副本可能被搬到别的地方)
[frame 108002] 第 4 轮:共 29347 个可读内存区
[frame 110614] 第 4 轮扫描结束:历时 2612 帧 (约 43.5 秒)
```

再看同目录下的 `STATUS.txt`:
```text
OK - patch applied
revision=orbital-laser-free-v6
phase=patched
rounds=4
copies=1
patched_writes=1
```

### 证据链直接闭环:
1. **周期完全吻合**: 36,000 帧 @ 60 FPS = **正好 600 秒(10 分钟)**。在游戏进行到第 10、20、30 分钟时，Mod 强行打回 `phase = "scanning"`。
2. **耗时完全吻合**: 第 4 轮遍历 29,347 个内存区，耗时长达 **2,612 帧(约 43 秒)**。
3. **帧率减半的力学成因**: 在这 40 秒内，`scan_step()` 每 2 帧占用 4ms~16ms CPU 预算遍历内存。60 FPS 游戏一帧的总预算仅 16.6ms，被 Mod 强占 4~8ms 后直接错失 VSync，**垂直同步下帧率瞬间跌至 30~40 FPS**。
4. **结束时自行恢复**: 2,600 帧跑完后，扫描终止，帧率立即弹回 60 FPS。
5. **最荒谬的现实**: 内存里自始至终只有 **1 份** 副本(`copies=1`)，重扫 4 轮找出来的还是原来那个地址，这几十秒的掉帧是 100% 的纯损耗。

---

## 1. 深入剖析五个根因

### 根因一: `deep_seconds = 600` 强行全量重扫(头号元凶)
在 Mod 的配置中盲目留了一句 `deep_seconds = 600` 或 `full_rescan_seconds = 600`，本意是“防止副本被地图重新加载到新地址”。
但全量扫描的代价是遍历 128TB 地址空间里的近 30,000 个内存区。在玩家激战正酣的第 10 分钟发起全量扫描，无异于在游戏中开启后台杀毒软件全盘扫描。

**规则**:
> 一旦数据已成功校验并打上补丁，**绝不进行无理由的周期性全量重扫**。
> 只有当被动复查发现已打补丁的副本全部失效(`alive == 0`，证明地图彻底卸载重载)时，才允许重新激活搜索流程。

### 根因二: `maintenance_scan()` 无 CPU 时间预算上限
部分 Mod 在每一轮检查中增加了对观察窗口的轻量扫描，但写成了无上限的循环:
```lua
for i = 1, #watch do
    while off < w.size do
        local buf = read_at(w.base + off, want)
        ...
    end
end
```
当 `watch` 合并出几 MB 内存时，这一帧会被同步耗尽，导致周期性的单帧大卡顿。

**修法**:
必须加上严格的 `deadline = os.clock() + 0.002`(2ms)，超预算直接 `break`，绝不在单帧内拖垮主循环。

### 根因三: 启动阶段单帧预算过大(16ms 暴击)
在地毯式轰炸中存在:
```lua
local SCAN_BUDGET_FAST = 0.016 -- 16ms
if state.frames < FAST_UNTIL_FRAME then due = true end
```
在开局前 400 帧每帧占用 16ms，相当于把 60 FPS 游戏的整个帧时间全吃光，造成游戏启动进图时严重冻结。

**修法**:
取消激进模式，统一限制单帧预算 `<= 2ms`，且保持 `SCAN_EVERY >= 2` 的步长，搜索过程完全静默无感知。

### 根因四: `_G.update` 包裹未做退钩守卫
在挂载 `update` 时，很多代码采用裸覆盖:
```lua
local original_update = update
function update(...)
    ...
    return original_update(...)
end
```
一旦某天想把 `update` 卸载退钩，若直接执行 `update = original_update`，会当场把**排在自身之后挂载的其他 Mod 的 update 链直接截断破坏**。

**修法**:
```lua
local original_update = update
local my_update
my_update = function(...)
    if state.retired then return original_update(...) end
    ...
    return original_update(...)
end
update = my_update

state.retire_hook = function()
    state.retired = true
    if update == my_update then
        update = original_update
    end
end
```
只有当自身依然是顶层包装者时才还原；否则仅置位 `state.retired = true` 旁路自身逻辑，保全整条钩子链。

### 根因五: 稳态下无意义的高频写盘
部分 Mod 每 900 帧（15 秒）甚至每 10 秒向磁盘同步打开、写入、关闭 `STATUS.txt`。频繁的磁盘 I/O 在机械硬盘或高负载环境下同样会引起微卡顿。

**修法**:
只在状态机发生实质变化（`state.status_phase ~= state.phase`）或初次打上补丁时写入一次，稳态运行期间禁止无意义写盘。

---

## 2. 理想生命周期收敛模型

一个健壮且轻量的注入型 Mod，其生命周期应当是**单向收敛**的:

```mermaid
flowchart TD
    INIT[1. INIT 初始化] --> SEARCH[2. SEARCH 匀速轻量搜索]
    SEARCH -- 未搜到 --> RETRY[退避慢速重试]
    RETRY --> SEARCH
    SEARCH -- 命中签名 --> VALIDATE[3. VALIDATE 严格校验]
    VALIDATE -- 校验失败 --> REFUSED[拒写并落盘]
    VALIDATE -- 校验通过 --> PATCH[4. PATCH 写入补丁]
    PATCH --> VERIFY[5. VERIFY 回读核验]
    VERIFY -- 核验通过 --> FINISH[6. FINISH 彻底收敛休眠]
    FINISH --> RECHECK[被动直读复查 5s 一次,耗时 1 微秒]
    RECHECK -- 副本依然健在 --> FINISH
    RECHECK -- 仅当全部副本失效 --> SEARCH
```

### 关键点:
1. **搜索时温和**: 预算 2ms，步长 2 帧，单次块 256KB。
2. **打完即休眠**: 释放 `regions` 列表与扫描缓存，不再执行内存遍历。
3. **复查用直读**: `recheck()` 仅根据已记录的 `rec.addr` 读取 400 字节，不搜内存，开销小于 1 微秒。
4. **失效才重搜**: 只要还有 1 份有效副本，绝不重新搜索。

---
153: 
154: ## 3. 实战进阶:消灭「微卡顿」与「帧生成曲线抖动」
155: 
156: 解决了 10 分钟一次的 40 秒大掉帧后，实机测试中可能仍会遇到**「有规律的周期性小卡顿（5s / 20s 掉一两帧）」**或**「帧生成时间曲线（Frametime）锯齿状波动」**。
157: 在对 380mm 火力网、双平荡者、飞鹰地毯式空袭、主宰系列进行全面排查后，我们总结出以下隐藏性能杀手：
158: 
159: ### 根因六: `recheck()` 内部重跑重型解析函数（10,144 次循环惨案）
160: **典型案例（380mm 火力网）**:
161: 虽然 `recheck()` 是每 5 秒才跑一次，但它调用了 `resolve_table()`，后者为了在 5,072 个偏移中寻找组件结构，每次都跑两轮完整循环（共计 10,144 次 pure Lua `u32` 解包）。
162: **后果**: 在第 5、10、15... 秒的瞬间，游戏主线程突然出现一个 4~10ms 的 Lua 同步尖峰，直接导致当前帧超时，引发规律性的顿挫。
163: **正解**: 初次 patch 时记录组件的绝对地址 `comp_address`。`recheck()` 时只需**直接读取该地址的 8 个字节（`comp_address + OFF_ROUNDS`）**，开销不足 0.5 微秒（300 纳秒）。绝不能在复查中重新运行任何遍历搜索！
164: 
165: ### 根因七: 「自相矛盾」的自毁判据（双平荡者无限重搜）
166: **典型案例（双平荡者）**:
167: 在 `resolve_rack()` 寻找可修改的武器架时，包含防歧义检查：若发现多于 1 个包含平荡者的架子，返回 `"ambiguous: 2 valid racks"`。
168: 但平荡者补丁的逻辑正是把第 1 槽位（slot 1）也改成平荡者！导致打完补丁后，第 0 槽和第 1 槽同时拥有平荡者物品。
169: 结果 5 秒后的 `recheck()` 再次调用 `resolve_rack()` 时，立刻命中歧义判定，误以为表格已失效，**清空地址缓存重置为 `scanning`**，从而在游戏过程中每隔几秒就重新发起一次全内存扫描！
170: **正解**: 
171: 1. 业务逻辑打上补丁后，目标状态已发生改变，绝不能再用初始的「空白未修改判据」去反查。
172: 2. 复查仅针对已知 `slot1_addr` 读取 8 字节目标哈希。若一致则瞬间返回。
173: 
174: ### 根因八: 飞鹰的 `maintain_seconds` 与飞船缺表重搜风暴
175: **典型案例（飞鹰地毯式空袭）**:
176: 部分表格（如 `EagleComponentData`）在飞船（大厅）阶段并未加载进内存，只有进任务才常驻。
177: 若 Mod 设定了 `maintain_seconds = 25` 无限重试，就会导致每隔 25 秒调用一次 `collect_regions()`（用 `VirtualQuery` 扫遍整个 128TB 进程地址空间），并启动 3ms/帧 的签名搜索。
178: **正解**:
179: 稳态下彻底禁用 `maintain_seconds`（设为 0），或至多重试 1~2 次后彻底挂起；全量补扫 `expand_seconds` 与全表复查 `sweep_seconds` 在稳态下均设为 0。
180: 
181: ### 根因九: 稳态下 Update 钩子步长未放宽
182: 很多 Mod 无论处于扫描期还是已打上补丁的稳态，`my_update` 都在无脑按每 2 帧（`SCAN_EVERY = 2`）调用 `pcall(tick)`。
183: 即使内部只做计数器判定，高频的 Lua 函数调用与上下文切换也会对高刷新率（144Hz / 240Hz）玩家的帧生成时间曲线造成微小的微震荡（Jitter）。
184: **正解**:
185: 动态步长：
186: ```lua
187: local cadence = (state.phase == "patched") and 60 or SCAN_EVERY
188: local due = (state.frames % cadence) == 0
189: ```
190: 稳态下每 60 帧（1 秒）才唤醒一次，CPU 负载降低 97%，彻底熨平帧生成曲线。
191: 
192: ### 根因十: 射弹表校验中的浮点数大量解码（主宰系列）
193: **典型案例（主宰爆裂铳 / 爆弹手枪）**:
194: 在 `verify()` 时，每次通过 `find_target_index()` 与 `find_source_index()` 遍历整张 350 条射弹表，并用 Lua 逐条解码 IEEE-754 单精度浮点数（速度、质量、阻力、重力），单次复查解码超千次浮点数。
195: **正解**:
196: `apply()` 成功后缓存 `state.dst_addr` 与 `state.payload`。`verify()` 仅需 `read_at(state.dst_addr, #state.payload)` 做单次内存比对，开销为 0.0003ms。仅当比对失败（如地图重载）时才回退至全量检索。
