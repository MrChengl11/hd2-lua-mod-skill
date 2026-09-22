# 案例:一次游戏更新打掉四个 mod —— 完整抢修记录

> 时间:2026-09-22。游戏从 **1.8.45317.0 / build 24826606** 更新到 **1.8.45850.0**。
> 五个自研 mod,四个失效(只有轨道激光活着,因为它本来就是运行时反推的)。
> 本文是**排查顺序 + 每个坑的实测数据 + 修法**,可以直接当 checklist 用。

## 0. 最先看的三眼(成本最低,收益最高)

1. **游戏到底更新了没?** \`data/game/generated_*.dl_bin\` 有 **54 个**,它们的 mtime 就是更新时间戳。
   再看 \`bin/helldivers2.exe\` 的文件版本号。构建没变 = 旧的 dump / 偏移 / census 全都还能用。
2. **mod 到底加载了没?** \`%LOCALAPPDATA%/CowboyBingus/Helldivers2/Logs/BingusSharedLoader.log\`
   的 \`Discovery\` 列表,逐个看 \`loaded\` / \`not installed\`。**这一步救过一次大返工**(见 §5)。
3. **mod 自己留下了什么?** 每个 mod 的 \`STATUS.txt\` 第一行 + \`.log\` 的尾部。
   本次就是靠 \`candidate 0x… rejected: size 5120\` 和 \`scan finished without finding … (2639 MB searched)\`
   定位到根因的。

## 1. 根因一:写死的表大小 / 记录数闸门静默失效(打掉 2 个)

| 表 | 旧构建 | 新构建 | 代码里的闸门 |
|---|---|---|---|
| \`BombardmentComponentData\` | 4672 | **5120** | \`if size ~= 4672 then return false\` |
| \`ProjectileSettings\` | 93312 / 343 | **95216 / 350** | \`if size ~= 93312 or cnt ~= 343 then return nil\` |

结果:每个候选区块都被拒 → **一个字节都不写**,而日志只有一行 reject 原因。

**离线先预测出来**(不用开游戏):游戏文件比 FileDiver 明文多 48 字节,

```
新构建表数据大小 = 游戏文件大小 - 76
```

未改动的小表差值恰好 48;射弹表 \`95292 - 76 = 95216 = 16 + 350 × 272\` —— 后来被实机
\`count=350 stride=272 size=95216\` 逐字证实。

**修法**:闸门只留 \`LDLD + 版本 + 类型哈希\`;步长从 DLArray 描述符反推 \`(size-16)/count\`;
组件表用内容指纹定位记录,不假设 bucket 数 / 组件数 / 组件步长。

## 2. 根因二:枚举下标回收(静默写错,最危险)

| 枚举 | 旧构建 | 新构建(实测) |
|---|---|---|
| \`ProjectileType 201\` | 爆弹手枪弹头 speed 350 / drag 0 / grav 0.30 / dmg 151 | **完全另一个射弹** speed 30 / drag 0.40 / grav 1.00 / dmg 189 |
| \`ProjectileType 237\` | 500kg 炸弹 mass 500 / cal 50 / expl 189 | 无法保证 |

可怕之处是它**不报错**:mod 打印 \`APPLIED: … Bolt Pistol round (record 301) -> Dominator (record 262)\`,
用户看到"成功了",实际主宰打的是另一个东西。

**修法**:枚举 id 只当提示。先按 id 取记录 → 用**稳定指纹**校验 → 不过就全表按内容找。
稳定的东西:**\`name_upper\` 哈希(本地化键的哈希)+ 物性(calibre / mass / drag / gravity / speed)**。

## 3. 根因三:判据本身成了故障源(打掉另外 2 个)

\`DamageInfoType\` 也会漂移:**144(旧)→ 149(新)**。而两个 mod 都把它当硬 pin:

```
主宰:  最佳候选 record 256: name=0x095D6C88 speed=180 mass=100 drag=0 grav=0.3 dmg=149 -> 得分 6
       内容识别失败: R-36 Eruptor round 在表里找不到 (最佳得分 6, 并列 2)
地毯:  弹头表 magic=0x11A56F20004 count=350 stride=272 via abs      ← 表找对了
       这张表没用: 最高分只有 10/16,不到阈值 14(候选清单已落盘)
```

两句日志的共同点:**数据完全正确,是判据把它拒了。** 打分掉的 6 分/6 分,正好是 damage+explosion
这两个枚举项漂移掉的分数。

而 mod 的行为是「判据不过就拒绝写入」——安全网在正确数据上开火,用户看到的是「没生效」,
真正的错误只藏在一行打分日志里。**这就是"安全的失败"最贵的地方:它掩盖了自己。**

**修法(判据分层)**:

| 层级 | 字段 | 权重 |
|---|---|---|
| 主键 | \`name_upper\` | 必须命中 |
| 硬判据 | speed / mass / calibre / drag / gravity | 各 2~3 分,物性,留容差 |
| 弱提示 | damage / explosion | 各 1 分,**只在同分时参考,不参与否决** |

通过条件:「硬判据 ≥ 4/5 **且** 总分 ≥ 阈值 **且** 唯一最高分」。

## 4. 根因四:FFI 类型双关被 LuaJIT 缓存(最难查的一个)

```lua
local u32_scratch = ffi.new("uint32_t[1]")
local f32_view = ffi.cast("float *", u32_scratch)   -- 别名
local function f32_at(s, i) u32_scratch[0] = bits; return tonumber(f32_view[0]) end
```

单次调用永远正确(日志里 \`mass=100.0 speed=350.0\` 都对),但**在 343 条记录的扫描循环里**,
LuaJIT 把那次 float 读缓存进寄存器,导致部分字段返回陈旧值 → 正确记录被打成 6 分。
症状是"同一个函数连续调用,结果时对时错"。

**修法**:纯 Lua IEEE-754 解码 + 启动自检(见 SKILL §6.36)。
插曲:自检常量我们第一次就写错了(\`0x0000803E\` vs \`0x3E800000\`),**自检把自检自己拦住了** ——
这恰好证明了自检值得写。

## 5. 非技术根因:mod manager 把 mod 删了

用户报「荡平者变成一根了」。查了半天补丁逻辑,真因是:

```
Discovery: 4 declared entries
mods/dsh/dominator_eruptor: loaded
mods/dsh/double_barrage: loaded
mods/dsh/orbital_laser_free: loaded
mods/dsh/eagle_carpet_bomb: loaded
        ← mods/dsh/double_leveller 根本不在列表里
```

管理器重新 Deploy 时把它丢了,并且**把槽位全重排了**(32~38 变号 + 出现重复槽位)。
我们之前直接改 \`data/patch_N\` 的部署全被覆盖。

**教训**:交付必须走管理器的 zip 导入;直接写 \`data/\` 只当临时验证手段,且要提醒用户
"下次 Deploy 会盖回去"。

## 6. 三个"做对了"的决定

1. **只在游戏进程内部读内存**。用户主动提出可以用 Cheat Engine MCP 从外部读,
   但 GameGuard 在跑,那条路是反作弊的首要特征。最后用 mod 自己 dump 拿到了同样的数据。
2. **宁可拒绝也不写错**。正因为有这道闸门,枚举回收那次才没有静默写坏别的武器
   (对比:早先版本的 mod 就是把错的射弹拷了上去并报告成功)。
   *但*这道闸门必须建立在**稳定判据**上,否则它自己就是故障源(§3)。
3. **加了一次性整表 dump**(§6.39)。它把"猜新构建的数值"直接变成"对答案",
   而且是所有运行时识别逻辑的通用地基。

## 7. 一份可复用的排查顺序

```
1. generated_*.dl_bin 的 mtime / exe 版本   → 游戏更新了没?
2. loader 日志的 Discovery 列表             → mod 加载了没?槽位对不对?
3. 各 mod 的 STATUS.txt 第一行 + log 尾部   → 它自己说失败在哪一步?
4. 要是"表没找到" → 先看是不是 size/count 闸门(§1),再看扫描策略(6.14)
5. 要是"表找到了但记录认不出" → 判据分层(§3)+ 枚举回收(§2)+ float 解码(§4)
6. 要是"报成功但无效" → 它是不是打到了没人用的副本(6.17)?枚举值是不是被回收了(§2)?
7. 要是"以前好用突然不好用" → 先怀疑引擎侧/管理器侧,别急着改代码(§5)
```

## 8. 本次留下的工具

- \`projectile_table.txt\`:定位到射弹表后一次性导出 350 条的
  \`idx / type_id / name_upper / calibre / speed / mass / drag / gravity / damage / expl_impact\`。
- \`lld_census_roundN.txt\`:每轮扫描的**所有**签名命中与拒绝理由 —— 一眼分清"表不在内存"和"解析错了"。
- \`warhead_candidates.txt\` / \`refused_dump.txt\`:判据不通过时的候选清单与原始字节。
- 假内存桩的两个坑(\`tools\` 里那套 lupa 夹具):
  * \`CreateDirectoryA\` 桩返回成功但目录不存在 → **日志一个字都没落盘**,排查了半天;
  * \`VirtualQuery\` 必须建模成 \`[base, base+size)\` 区间,只对等于 base 的地址返回区域,
    会让 \`is_writable_data\` 误判、写入被拒。
