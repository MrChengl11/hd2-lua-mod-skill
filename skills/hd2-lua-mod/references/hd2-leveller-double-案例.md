# 案例:EAT-411 荡平者一次空投两根

> 游戏构建 24826606 / exe 1.8.45317.0
> exe SHA-256 `A09FF52663E73B94FB0CAC0DCB5BA84FFD10ECF44F74A8921AC66AF923988CC3`
> 产物:`Double-Leveller.zip`,改 **64 字节**,一次实机侦察 + 一次实机验证即通过。

---

## 一、问题

EAT-411 Leveller(**荡平者**,Siege Breakers 通行证 P2,85 奖章)基础冷却 140 秒,
一次呼叫**只掉一根**。它的空投舱模型明显有两个槽位。

**决定性线索来自 Wiki 的一句话**,EAT-700 页面原文:
*"...the awkward nature of being **sent two at once like typical EAT-17**..."* ——
也就是说 **EAT-17 和 EAT-700 本来就是一次掉两根**,只有荡平者是特例。

> 教训:Wiki 的"行为描述"常常比数值表更有用,它能直接把你送到"同族对照"上。

## 二、离线阶段(这一步做完,大半的活就干完了)

**游戏的数据表在磁盘上加密,但工具链里有明文镜像:**

* `.../xypwn/filediver@<ver>/datalibrary/generated_entities.dl_bin`(45 MB,全部组件数据)
* 同目录 `datalibrary/*.go` —— 每个组件的**字段名和注释**(由游戏 typelib 生成)
* `typelib_all.json` / `typelib_names.tsv` —— 类型哈希↔名字 + 字段偏移/大小

对照验证:游戏安装目录 `data/game/generated_entities.dl_bin` 只比明文镜像**大 48 字节**,
且**是加密的**(熵 7.9998 bit/byte,45 MB 里 `LDLD` 出现 **0** 次)。改磁盘这条路直接封死。

用类型名算哈希(`dlsum` = djb2)就能定位任何一张表:

```
dlsum("HellpodRackComponentData") == 0xA98BB156
```

## 三、数据结构(偏移全部来自游戏 typelib,不是社区结构体)

### HellpodRackComponentData —— 42568 字节,71 条挂架

```
+0      LDLD | version(1) | typeHash(0xA98BB156) | size(42568) | is64 | pad7
+24     ComponentIndexData[140]   (2240 字节 = 140 × 16)
+2264   HellpodRackComponent[71]  (568 字节 × 71 = 40328)
```

### HellpodRackComponent —— 568 字节

| 偏移 | 类型 | 字段 |
|---|---|---|
| +0 | RackAttach[8] | **Payloads**(每个 64 字节) |
| +512 | f32 | LastRetractDelay |
| +516 | bool | DisableRetract |
| +520 | u64 | MapIcon |
| +528 | u32 | MapName |
| +532 / +536 / +540 | u32 | Rack 部署/收回/门收回 音效 |
| +544 / +548 | u32 | DeployAbility / LastRetractAbility |
| +552 | u32 | RandomPayloadSize |
| +556 | u32 | **SpawnPayloadSize** ← 关键 |
| +560 | bool | DisableInitialInteraction |

### RackAttach —— 64 字节

| 偏移 | 类型 | 字段 |
|---|---|---|
| +0 | u64 | **Item**(资源名哈希) |
| +8 | u32 | **Node**(挂点) |
| +12 | Vec3 | Offset |
| +24 | Vec3 | RotationOffset |
| +36 / +40 / +44 | u32 | 部署/收回动画事件、收回音效 |
| +48 | u8 | ApplyDeltas |
| +52 | u32 | **RackSide**(0=None 1=Right 2=Left) |
| +56 | u8 | UnknownBool |

## 四、定位:用同族对照做差分

把 71 条挂架全解出来,只看这三条:

| 挂架 | 物品 | slot0 | slot1 | SpawnPayloadSize |
|---|---|---|---|---|
| 25 | `expendable_machinegun` | 左 ✅ | 右 ✅ | 2 |
| **26** | **`expendable_massive_rocket_launcher`(荡平者)** | 左 ✅ | **空 ❌** | **2** |
| 27 | `expendable_napalm_launcher`(EAT-700) | 左 ✅ | 右 ✅ | 2 |
| 44 | `lat_oneshot`(EAT-17) | 左 ✅ | 右 ✅ | 2 |

**结论一目了然:荡平者的 `SpawnPayloadSize` 本来就是 2** —— 游戏自己就打算生成两个载荷,
只是 slot1 的物品哈希是 0。落地生成逻辑碰到空槽就停
(FileDiver 的 `ToSimple` 里那句 `if payload.Item.Value == 0 { break }` 就是同一行为)。

**同族对照比逐字段比对 Wiki 数值快得多,也更硬。**

物品资源哈希(来自解包出的资源名清单):

| 物品 | 资源名哈希 |
|---|---|
| 荡平者 | `0x7617642765AC38C7` |
| EAT-17 | `0x80932FA0ED6901D3` |
| EAT-700 | `0xB2B5E0D185605F9E` |

## 五、最终实现:抄"游戏里已经能用"的那一份

**不自己编数值,直接复制 EAT-17 的排布。** 实测 EAT-17 的 slot1 与我们写进去的 64 字节
**只差开头 8 字节的物品哈希**,其余逐字节一致:

| 偏移 | 字段 | 值 |
|---|---|---|
| +0 | Item | `0x7617642765AC38C7`(同 slot0) |
| +8 | Node | `0x76C6D1E3`(左)→ **`0x7FE13CFF`(右)** |
| +12 | Offset | (0.00, 0.15, -0.15)(同 slot0) |
| +24 | RotationOffset | (0.0, 90.0, 0.0)(同 slot0) |
| +36 | DeployAnimationEvent | 0x12CDF9E3(同 slot0) |
| +52 | RackSide | 2(Left)→ **1(Right)** |

**相对偏移:slot0 = 表 magic + 17032,slot1 = 表 magic + 17096**(24 + 2240 + 26×568 + 64)。

## 六、实机侦察

只读侦察 addon 同时做三件事:

1. `LDLD + 版本 + 类型哈希` 找表并 dump
2. **按物品资源名哈希搜内存**,dump ±512 字节上下文(表头没找到时也能从对象定位)
3. 全内存 `LDLD` 普查

结果:**表常驻内存,而且布局与文件镜像逐字节一致**。第 1 轮(飞船里)没找到,
**第 2 轮(进任务后)才找到** —— 所以侦察要给"多轮"留时间。

```
[frame 666] PATCHED rack 26: table=0x2966C722616 slot1=0x2966C7268DE node_ok=true side_ok=true
```

`0x2966C7268DE - 0x2966C722616 = 17096` ✓ 与离线算的一致。**绝对地址每次运行都变(ASLR)。**

### 侦察 addon 踩的三个坑(全部代价惨重)

1. **字段名复用**:`hits = {}` 和 `hits = 0` 混用 → 第一轮扫到第一个命中就抛
   `attempt to perform arithmetic on field 'hits'`,**整轮中断,census 也从来没落盘**。
2. **dump 起点越界**:`LDLD` 在分配区 +4 处,从 `magic-64` 读会读到区域外 →
   `ReadProcessMemory` 返回 0 字节,dump 文件只有个头(133 字节)。
3. **只在扫完时落盘**:因为 1,产物目录里几乎什么都没有。

> **Loader 只在启动时 require 一次,没有热重载。改一行 = 关游戏重开。**
> 所以必须:每层循环 pcall、周期性落盘、出错也落盘、日志带 frame 号、错误限流。

## 七、离线仿真 + 变异测试

`lupa` + 类型严格的假 ffi,**夹具直接用实机抓下来的真实 dump**。

| 测试 | 结果 |
|---|---|
| 基线:定位 → 写 64 字节 → 回读 → 与 EAT-17 排布逐字节比对 | PASS |
| 抹掉补丁后 5 秒内自动重打 | PASS |
| 变异:去掉 `ReadProcessMemory` 的 `ffi.cast` | 抓住 |
| 变异:去掉 `WriteProcessMemory` 的 `ffi.cast` | 抓住 |
| 变异:漏掉 ComponentIndexData 段偏移 | 抓住 |
| 变异:去掉 SpawnPayloadSize 校验 | 抓住 |
| 变异:不改 RackSide | 抓住 |
| 变异:误写 slot0 | 抓住 |

### lupa 排障三连

| 症状 | 原因 |
|---|---|
| `cannot open ...: Illegal byte sequence` | **Lua 的 fopen 打不开含中文的路径** → 夹具放 `%TEMP%` |
| `too many registers (limit is 255)` | 一个 `string.char(...)` 塞几万个参数 → 按 200 个切块 |
| `UnicodeDecodeError` | lupa 按 UTF-8 解 Lua 字符串 → Lua 侧**返回 hex** |

> `SpawnPayloadSize` 那条变异一开始"没被抓住",查下去是**夹具自己**把诱饵挂架放错了偏移。
> **变异没被抓住时,先怀疑夹具,再怀疑代码。**

## 八、走过的弯路

1. 差点直接上机侦察 —— 其实明文镜像里全都有。
2. 以为要改冷却来"变相加强",其实改 64 字节就够。
3. 试过从外部进程读内存 —— 游戏带 **nProtect GameGuard**(`bin/GameGuard`),这条路不该走。
4. 侦察 addon 第一版因为一个 Lua 类型错误白跑一整趟实机。
5. 误判"实体 blob 在内存里是整块映射" —— blob 目录确实在,但**组件表要进任务才加载**。

## 九、结论:这类改动的通用套路

1. **离线**:明文镜像 + typelib → 找到表、找到记录、**找同族对照做差分**
2. **抄现成的**:优先复制"游戏里已经能用"的那一份字节,而不是自己编数值
3. **最小侦察**:只验证"表在不在内存、地址怎么算",别把分析搬上机
4. **上机前仿真**:真实 dump 当夹具 + 变异测试
5. **补丁要保守**:签名定位 → 校验常量 → 唯一性校验 → 备份 → VirtualProtect → 写 → 回读 → 复查
