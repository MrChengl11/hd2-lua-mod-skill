# 案例:把被删掉的「飞鹰地毯式空袭」搬回游戏(7 轮迭代)

> 目标:复现一个**从未发布**的战备 `StratagemType_CarpetBomb`(id `905054095`),
> 并且把箭头**已经删掉的投放载具**补回来。

这是目前踩坑最密集的一个案例 —— 离线全绿、实机连挂 7 次,每次的根因都不一样。
**每一轮都留下一件可复用的诊断产物**,这是能在第 7 轮收敛的真正原因。

---

## 轮 0:离线解包 —— 先问"有没有人已经解好了"

战备表 `generated_stratagem_settings.dl_bin` 不在 FileDiver 的 datalibrary 里,
但社区仓库 [shalzuth/HelldiversData](https://github.com/shalzuth/HelldiversData) 已经解成 JSON。
**先查这个,不要去啃 typelib。**

```powershell
Invoke-WebRequest -OutFile ref/generated_stratagem_settings.json `
  https://raw.githubusercontent.com/shalzuth/HelldiversData/master/data/settings/generated_stratagem_settings.json
```

挖到的关键事实:

| 项 | 值 |
|---|---|
| `type` / `id` | `StratagemType_CarpetBomb` / `905054095` |
| `selectable` | **0**(这就是"藏起来"的开关) |
| `uses` / 冷却 | 1 / **900 秒** |
| `origin_type` | `ClanStation`(全表只有 2 条) |
| `payload` | `[0x6CCB976676EF6CC6]` |
| 本地化 | 名字键 `1265258834`="CARPET BOMB" 还在;文案写着 `[NOT IMPLEMENTED]` |

### 打击实体:对照历史快照,被删的那条自己会跳出来

战备的 `payload` 指向独立 unit。把 **2024-06-13 的历史快照**与当前构建并排:

```
0x6CCB976676EF6CC6
  2024-06 : unit=shuttle_transport.bones  payload=EaglePayload_CarpetBombing
            pattern=_6Z  projectile=ProjectileType_Bomb_200kg  run_length=30
  当前构建: 哈希在整块 LDLD 里出现 0 次  ->  整个实体被删
```

**"被删掉的东西"最好的证据是历史快照的 diff** —— 比逐字段猜快得多。

---

## 轮 1:语法错误 —— 仿真器用了错的 Lua 版本

离线仿真全绿、打包校验全绿,实机 loader 直接:

```
mods/dsh/eagle_carpet_bomb: load failed:
  eagle_carpet_bomb.lua:917: unexpected symbol near '/'
```

根因:探测布局时写了 `local N = rem // EAGLE_RECSIZE`。
**`//`(整除)是 Lua 5.3+ 的语法,游戏是 LuaJIT(5.1)**;而 lupa 默认的 Lua 5.5 接受它。

修法(两条都要):
1. `from lupa.luajit21 import LuaRuntime` —— 仿真器换成游戏同款运行时;
2. 加**语法闸门**:打包前后各用 LuaJIT `load()` 编译一遍,并扫 `//` / `goto` /
   `math.type` / `string.pack` / `table.move`;配一条变异测试(把 `//` 放回去,闸门必须抓住)。

> 教训:**仿真器和游戏不是同一个 Lua,测试等于没测。**

---

## 轮 2~4:字段偏移反推不出来 —— 因为字段类型就错了

实机日志(每轮都有 `STATUS.txt` + 日志,这是能收敛的关键):

```
字段 uses          -> +80   命中 876/888
字段 cooldown      -> +104  命中 816/888
字段 origin        -> +112  命中 888/888
字段 ctype         -> +148  命中 888/888
字段 payload_count -> +152  命中 888/888
字段 selectable    -> +144  命中 684/888(第二 672)   <== 断层不够,拒绝写入
```

每一个能修的字段都 100% 复现了,只有 `selectable` 永远差一口气。
**"所有字段都对、只有一个对不上"说明那个字段的"类型/编码"假设错了,不是数据错了。**

### 权威答案在 `data/components/*.json`

社区仓库的 `data/components/StratagemInfo.json` 是**字段名 → 类型**的表:

```json
{ "mission_specific": { "type": "byte" },
  "selectable":      { "type": "byte" },
  "triggers_war":    { "type": "byte" },
  "cooldown_type":   { "type": "StratagemCooldownType" } }
```

**三个连续 byte。** 按 u32 反推它,从原理上就不可能对。
改成按字节扫之后,`byte == 1 + 2*selectable`(bit0 恒为 1、bit1 才是开关)
在 9/9 样本上唯一命中;按"独立 0/1 字节"匹配只有 6/9。

而且 **LuaJIT 没有位运算** —— 置位要用算术:`if b % 4 < 2 then b = b + 2 end`,只改那一位、
不碰同字节的其它标志(写 u32 会把 `triggers_war` 一起冲掉,这条专门配了变异测试)。

---

## 轮 5:补丁全部生效,但列表里还是没有它

`STATUS.txt` 已经 `OK - ... unlocked`,日志显示 12 份副本全打上了,列表里依然没有。

### 反查:把社区仓库**全部**数据文件 grep 一遍战备 id

```
扫了 1573 个 JSON
=== 引用了战备 id 的文件 ===
   settings\generated_stratagem_settings.json   [CarpetBomb, EagleAirstrike, ...]
```

**游戏数据里根本没有"玩家已解锁战备"这张表。** 列表条目来自账号解锁状态。

结论:**凭空给列表加一条,在数据层是做不到的。**
别人视频里能看到(而且他的列表里少了一条现役战备),正是**借壳**的特征:
把一条**已解锁、已在列表里**的战备原地改造成你要的那条。

```lua
hijack_id = 1685231450   -- 飞鹰烟幕:借它的槽位
-- 换掉:name_upper / name_cased / description / fluff(四连 u32)
--       payload[0] / package / uses / 冷却
-- 保留:origin_type / cooldown_type / icon / category / selectable  <== 那些才是"能用"的前提
```

---

## 轮 6:名字对了,卡面数字不对

借壳之后列表里出现了「地毯式轰炸」,但卡面显示 **2 次 / 178 秒**,而我写的是 1 次 / 300 秒。

两个坑叠在一起:

**① 借来的槽位会继承原战备的机制。** 飞鹰烟幕挂着
`additional_stratagem = StratagemType_EagleRearm`,游戏把它当鹰系战备:卡面那个数字是
"剩余次数内飞鹰再次可用的间隔",**真正的冷却在 `EagleRearm` 上、而且全鹰系共用**。
原版 CARPET BOMB 根本不是鹰系战备(`additional_stratagem = None` + `uses = 1`) ——
解法是**把挂架摘掉**:`depends_on` / `additional_stratagem` 清零。

**② 卡面 = 记录值 × 舰船升级系数。** 用**同族现役战备**标定(不要猜):

| 战备 | 记录里 | 卡面 | 结论 |
|---|---|---|---|
| 飞鹰500kg | 1 次 / 15s | 2 次 / **9s** | 次数 **+1** |
| 飞鹰空袭 | 2 次 / 15s | 3 次 / 9s | 次数 +1 |
| 飞鹰集束 | 4 次 / 15s | 5 次 / 9s | 次数 +1 |

三条都是 `15 × 0.6 = 9` ⇒ 系数 **0.6**。想显示 300 就写 `300 / 0.6 = 500`。

> 面板/卡面数字是**标定量**,不是事实 —— 让它反过来告诉你游戏怎么算。

---

## 轮 7:三架飞机变成一架、看不见飞机、弹太少

**① 同一个哈希重复会被去重。** payload 数组里三个相同的飞鹰实体 ⇒ 只出一架。
改用**三个不同**的"没人引用"的飞鹰实体(先 grep 一遍谁在引用);
但仍然只有一架 —— 因为**飞鹰在引擎里是单机 + 装填池**(`EagleRearm` 就是为它存在的)。
⇒ 不再纠结架数,**改成从单机弹量补偿**。

**② 看不见飞机。** 配方里 `strafing_run_fire_distance = 1000`(离目标 1000 米就开始投弹),
飞机还在天边就把弹放光了。正常飞鹰空袭是 350。同时 `attack_movespeed = 75` 太慢
(正常 300)—— 顺带造成"呼叫时间 13 秒"。改 `fire_distance=300` / `move_speed=200` /
`approach_height=300`。

**③ 弹太少(20 发 vs 目标 60 发)。** 用上一轮的观测值做标定:

```
投弹数量 ≈ fire_duration / bomb_interval
实测 4 / 0.25 = ~20 发   ⇒   目标 60 发 = bomb_interval 0.08
```

---

## 轮 8:社区大佬一句话点破(方向性纠正)

> "原版地毯式轰炸的**战备 ID 是 101**;把它装载的 **1、2 号装载物**改成常规飞鹰战备的装载物,
> 然后使用它,就能看到一排三架飞鹰。"

对照实机 dump:地毯式空袭记录的 **`+0` 字段就是 101**(= `StratagemType_CarpetBomb` 的枚举值)——
同一条记录。这一句纠正了两个我们想岔的地方:

**① "扩展位置不是空白"根本不是障碍。** 我们给自己加的安全检查(数组后面 16 字节必须为 0)
挡掉的,其实是**数组自己的 1、2 号槽位**。正确做法是**照写 + 把 count 改成 3**,
写前备份被覆盖的字节即可。为这一条我们绕掉了两轮。

**② 别用"没人用的实体",要用"常规战备在用的装载物"。** 之前挑的两个"没有任何战备引用"的
飞鹰实体,很可能 `package` 从来没被加载过,所以刷不出来。改用**一条现役战备自己的 payload 实体**
(先借壳把那条战备的槽位腾空,它的 payload 自然就空出来了)。

**教训:"没人引用"不等于"能用";能被生成的实体必须处在已加载的 package 里。**

## 轮 9:按大佬的配方照做,实机仍然只出 1 架(此路到此为止)

照配方把地毯记录**自己的 payload 数组**的 1、2 号槽位写成三个**不同的**现役飞鹰实体
(count 1 -> 3,写前备份),实机日志确认全部写进去了:

```text
[frame 2132] EagleComponentData 命中 3 个打击实体
[frame 2132] PATCHED EagleComponent @...: 23/23 字段
STATUS: payload_donor=2230051894 count=3 (已写入)   copies=5 patched=1
```

**结果:实机还是 1 架。** 结论(可复用的一条硬知识):

> **一次战备呼叫最多升空 1 架飞鹰,与 payload 数组长度无关。**
> 飞鹰在引擎里是「单机 + 装填池(EagleRearm)」的模型:数组的第 2、3 项只影响
> 生成尝试,不会变成编队。想让一次呼叫打出更多弹,唯一的杠杆是**单机弹量**,不是架数。

由此得到两条实践结论:

1. **别在架数上耗轮次**,把预算花在「单机弹量 / 投弹密度」上,并明确告诉用户这是引擎上限。
2. **自标定必须按「实际会飞的架数」反算**,而不是按你**希望**的架数:

```lua
-- 错:按 flight_size(=3)反算 -> interval = 5/20 = 0.25 -> 实机只投 20 发(用户: 弹数不对)
-- 对:按实机观测到的 1 架反算 -> interval = 5/60 = 0.083 -> 实机 60 发
bomb_planes  = 1     -- 实机标定量,与 flight_size 解耦
```

**教训:凡是「运行期观测到的现实」和「配置里的期望」不一致,标定公式要吃观测值。**

## 轮 10:冷却对齐同族战备 —— 别自己发明数字

用户最后的诉求是「把冷却设置成和别的飞鹰一样」。做法不是拍一个 300 秒,而是:

```text
其他飞鹰(空袭/集束/500kg)记录里 cooldown_duration_success = 15,卡面显示 9
=> 想让本战备和别的飞鹰一样,就在 CONFIG 里写「卡面 9 秒」,
   反算 9 / 0.60 = 15 -> 写进记录的值与同族逐位相同。
```

**教训:「和某个东西一样」要落到它的原始字段值上,而不是落到它在你屏幕上的显示值上 ——**
先把显示值反算回原始值再照抄,才能保证两者在任何舰船模块配置下都同步。

## 这一轮真正救命的三件事

### 1. 让 mod 自己 dump 实机内存(而不是靠猜)
在 addon 里放一个 watch-list,每次跑都把关键记录的**完整 400 字节**落盘:

```lua
local WATCH_IDS = { 905054095, 1238358532, 3837064536, 1685231450, ... }
-- 写完补丁后再 dump 一次(records_after_hex.txt),证明"我们写的 == 内存里真实存在的"
```

拿到 dump 之后,用 `逐偏移 × 逐字段` 的对齐脚本一次定死布局:

```
uses        -> u32 +80    9/9
origin_type -> u32 +112   9/9
triggers_war-> u32 +144   9/9
package     -> u64 +168   9/9
icon        -> u64 +176   仅地毯式空袭是 0(唯一异常 -> 就是它看不见的原因)
```

**"地毯式空袭 vs 一条正常在用的战备"逐字段 diff,只有 icon 是 0** ——
这一条 diff 直接指出了 UI 不显示的另一个原因(箭头把图标资源也删了)。

### 2. `STATUS.txt` 每次都给结论 + 关键参数
用户只看得懂第一行;把 `off_*= ` / `aircraft_per_call=` / `cooldown_written_base=` 全写进去,
远端排查时一个文件就够了。

### 3. 一次只改一件事 + 让用户回报标定量
每一轮只改一个变量,并让用户回报**面板数字 / 架数 / 弹数**。
7 轮里有 3 轮的结论直接来自用户回报的数字(174 秒、20 发、2 次)。

---

## 最终生效的参数(可直接抄)

```lua
hijack_id        = 1685231450   -- 借壳槽位(飞鹰烟幕)
cooldown_seconds = 9            -- 想要的卡面冷却(= 其他飞鹰;反算后基础值 15,与同族逐位相同)
upgrade_factor   = 0.60         -- 舰船升级系数(卡面 ÷ 记录值),换号要重标定
call_in_time     = 10.0         -- 呼叫时间:记录里 +92 那个 float,全表只有空袭是 10.0
projectile_type  = 192          -- 200KG BOMB(用名字查,别用旧枚举下标 139)
run_length       = 150          -- 轰炸走廊长度(米)
search_radius    = 50           -- 轰炸区宽度(米)
target_bombs     = 60           -- 这一发一共要多少枚(自标定,优先于 bomb_interval)
bomb_planes      = 1            -- ★ 按实机观测的架数反算(引擎只飞 1 架)
bomb_interval    = 0.08         -- 手动兜底;投弹数 ≈ fire_duration / bomb_interval
fire_duration    = 4.0
fire_distance    = 300          -- 离目标多远开始投弹(原版地毯 1000 -> 看不见飞机)
approach_height  = 300          -- 进场高度(原版 750)
move_speed       = 200          -- 进场速度(原版地毯 75 太慢)
```

## 复用清单

| 想做什么 | 抄哪一段 |
|---|---|
| 让隐藏战备出现在玩家列表 | 借壳(§12):换掉 名字/描述/payload/package/冷却,保留 origin/ctype/icon/selectable |
| 想改卡面数值 | 先拿同族现役战备标定系数,再反算 |
| 想凭空多生成几个实体 | 借一条没人用的战备的 payload 数组,别原地扩容 |
| 定位某条记录的字段 | watch-list dump + 逐偏移×逐字段对齐 |
| 判断某个字段是什么类型 | 社区仓库 `data/components/<组件>.json` |
| 不知道某个枚举的下标 | 用名字去本地化字符串表查,别抄社区枚举表 |
