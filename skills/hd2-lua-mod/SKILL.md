---
name: hd2-lua-mod
description: 制作/修改《绝地潜兵2》「Lua 注入型」mod 的完整工作流 —— 依赖 Bingus Shared Loader、运行时用 FFI 读写游戏进程内存的那一类(如 P11-Self-Heal、CowboyBingus 系列)。**离线优先**:先用工具链里的明文 datalibrary + 游戏自带 typelib 把数据表解出来算出偏移,再上机做最小验证。涵盖 .patch_N 归档格式、addon 打包、只读侦察 addon 的写法、从运行时内存定位数据表、运行时补丁的「校验+备份+回读+复查」套路、以及一套能在上机前抓出致命 bug 的 lupa 离线仿真 + 变异测试法。涵盖「整表复现反推字段偏移」这套抗构建漂移的补丁校验法,以及社区明文 JSON 数据源。当用户要做 HD2 的注入型 mod、要往游戏内存里读写数据、要改武器/射弹/战备的次数与冷却/游戏参数、或要读懂 `9ba626afa44a3aa3.patch_*` 这类文件时使用。
whenToUse: 用户要做或修改绝地潜兵2 的注入型 mod、要改武器/射弹/战备参数、要在运行时读写游戏内存、要分析 9ba626afa44a3aa3.patch_N 归档,或要排查这类 mod 为什么没生效时。
---

# 绝地潜兵 2 · Lua 注入型 Mod 工作流

> 这类 mod 和普通 mod 完全不同:**不是换素材,是往游戏的 LuaJIT 虚拟机里塞 Lua 代码,
> 再用 FFI 直接读写游戏进程内存**。素材类改法(替换 `data/` 资源)对它无效。

## 0. 先离线,后上机(最重要的一条)

**游戏的数据表在磁盘上是加密的,但工具链里有一份明文镜像。**
先用它把大半的活干完,再决定要不要上机侦察 —— 上机一趟要重开游戏,成本很高。

| 明文资源 | 位置 | 用途 |
|---|---|---|
| `generated_entities.dl_bin`(45 MB) | filediver 模块缓存 `.../xypwn/filediver@<ver>/datalibrary/` | 全部实体 / 组件数据:武器、挂架、装备、库存、策略… |
| `generated_projectile_settings.dl_bin` 等 | 同上 | 射弹 / 伤害 / 爆炸 / 表面 各设置表 |
| `datalibrary/*.go` | 同上 | **每个组件每个字段的名字和注释** —— 由游戏自带 typelib 生成,比任何社区结构体权威 |
| `typelib_all.json` / `typelib_names.tsv` | 反编译产物 | 全部 ~1177 个类型的**字段偏移 / 大小 / 成员名** + 类型哈希↔名字对照 |

游戏安装目录的 `data/game/generated_*.dl_bin` **是加密的**(实测熵 7.9998 bit/byte,
45 MB 里 `LDLD` 出现 **0** 次),大小通常只比明文镜像多 48 字节。
**不要试图改磁盘文件** —— 改不出来,也不在 mod 管线里。

### 怎么拿到这些文件

FileDiver 的 `datalibrary` 用 `//go:embed` 把明文数据打包进了 Go 模块,**连 typelib 一起**:

```bash
go mod download github.com/xypwn/filediver    # 或直接 clone 源码树
# 文件在 <GOMODCACHE>/github.com/xypwn/filediver@<ver>/datalibrary/ :
#   generated_*.dl_bin        明文数据表(含 45 MB 的 generated_entities.dl_bin)
#   dl_library.dl_typelib     游戏自带的类型库
#   *.go                      每个组件的字段名与注释(由 typelib 生成)
```

再把 typelib 导成 JSON —— 用 `tools/dump_typelib/`,放进 FileDiver 源码树的 `cmd/` 下跑:

```bash
go run ./cmd/dump_typelib -o typelib_all.json    # 1177 个类型的字段偏移/大小/成员名
```

> `-o` 不是可选项:PowerShell 的 `>` 重定向会把 JSON 写成 UTF-16,Python 直接读不开。

### 还有一个明文来源:社区解好的 JSON(**先查这个**)

游戏 `data/game/` 里有 **57 个** `generated_*.dl_bin`,而 FileDiver 只打包了它实现了 parser 的那 ~20 个。
**缺的那些先别急着上机** —— 社区数据挖掘仓库已经把全部 `generated_*` 解成 JSON 了:

* [shalzuth/HelldiversData](https://github.com/shalzuth/HelldiversData) —— `data/settings/`、`data/components/`、
  `data/entities/`、`data/enums/`、`data/translations/`
* 路径规律:`data/settings/generated_<和游戏目录里同名的那个>.json`
* wiki 的 `Module:Decodedata-*` 模块是同一支血脉(取原文加 `?action=raw`)

```powershell
Invoke-WebRequest -OutFile ref/generated_stratagem_settings.json `
  https://raw.githubusercontent.com/shalzuth/HelldiversData/master/data/settings/generated_stratagem_settings.json
```

> **先问"这块数据有没有人已经解好了",再去啃 typelib。**
> 战备的次数/冷却就是靠这一步,从"至少两轮实机侦察"变成"离线直接出成品"。
> 列目录用 GitHub API 的 `contents/`(响应会被截断,要逐个目录钻)。
> 注意:这类 JSON 是**某个旧构建的快照**,和自己游戏版本之间会有数值漂移(见 6.15)。

顺序永远是:**离线查明文 → 离线算出偏移和值 → 再上机做最小验证**。

## 1. 两个哈希函数,别混

**类型哈希 = djb2**。`typelib_names.tsv` 里每个名字都能算出对应 LDLD 表的签名:

```python
def dlsum(name):                  # "HellpodRackComponentData" -> 0xA98BB156
    r = 5381
    for c in name:
        r = (r * 33 + ord(c)) & 0xFFFFFFFF
    return (r - 5381) & 0xFFFFFFFF
```

**资源名哈希 = MurmurHash64A(名字, seed=0)**,是另一套(见第 3 节表格)。
两者长得像但完全不同,混用会得到一堆"找不到"。

## 2. 数据表(LDLD)实例:两种布局,必须按内容验证

`references/ldld.py` 是现成的解析器。实例头之后就是数据,但**不同文件的数据起点不一样**:

| 来源 | 数据起点 |
|---|---|
| `generated_*_settings.dl_bin`(设置表) | magic **+40** |
| `generated_entities.dl_bin`(实体 blob) | magic **+24** |

**不要猜,用内容验证**:按候选起点解一条记录,看字段是否落在合理值域
(比如计数 ≤ 8、速度 1~5000、物品哈希能在资源名清单里查到)。

### 内存里的布局 == 磁盘镜像的布局

实测确认:`generated_entities.dl_bin` 在内存里与文件**逐字节一致**,
所以离线算出来的相对偏移可以直接用。**绝对地址每次运行都不一样(ASLR)**,
只能"按签名定位 + 相对偏移"。

### ⚠ 但 DLArray 的数组描述符在内存里会变形

**别把上面那条结论推广到"数组描述符"** —— 这里正好反过来:

| 形态 | DLArray 的第一个 u64 | 记录数组在哪 |
|---|---|---|
| **文件里**(FileDiver 的明文镜像) | **相对偏移**(通常是 16) | `magic + 24 + offset` |
| **内存里** | **绝对指针** | 就是这个地址本身 |

照文件形态写死"相对偏移",内存里读到的就是个几十 GB 的大地址 → `offset > size` → **整张表被拒**,
而普查又明明看得到它。**两种解释都试,用语义判定**(读出来的记录里那条唯一键对不对得上号),
不要用结构校验去判定。

同一张表在内存里还可能有**多个副本**(实测 37 个同类型哈希的块,36 条记录里 28 条认得出来)。
要么全打,要么明确选一个 —— 并且**要求目标记录唯一**,多于一条就拒绝。

## 3. 固定常量(不会变)

| 项 | 值 |
|---|---|
| 载体文件 | `data/9ba626afa44a3aa3.patch_<N>` |
| 资源名哈希 | `MurmurHash64A(名字, seed=0)` |
| 类型哈希 | `djb2(类型名)`(见第 1 节) |
| Lua 资源类型标记 | `0xA14E8DFA2CD117E2` |
| 数据表块魔数 | `LDLD` + u32 版本(=1) + u32 类型哈希 + u32 大小 |
| Loader 占用的资源 | `core/wwise/lua/wwise_flow_callbacks` = `0x7251FDD9BB62480A` |
| 共享日志目录 | `%LOCALAPPDATA%/CowboyBingus/Helldivers2/Logs` |
| Loader 日志 | 同目录 `BingusSharedLoader.log`;首行 `Bingus Shared Loader loader-v15; API 1`,还有一行 `Discovery: N declared entries`(列出本次发现的 addon) |
| "API 1" 是什么 | **loader 自己上报的 Lua API 等级**,不是另一个 mod。**API 1 从 loader v15 起才有,v14 是 API 0** |
| Loader 版本闸门 | loader 在 `_G.CowboyBingusModLoader` 里放 `= { api = 1, version = 16, modules = {} }`(v16 快照)。addon 开头读它就能判断环境够不够;读不到再退化去解析 `BingusSharedLoader.log` 首行 |
| 反作弊 | **nProtect GameGuard**(安装目录 `bin/GameGuard`) |

**GameGuard 意味着:不要从外部进程读游戏内存。**
别想用 Python/ctypes 挂 `OpenProcess` + `ReadProcessMemory` —— 那是最容易被抓的动作。
只在游戏内用只读 addon。

## 4. .patch_N 归档格式(已字节级验证)

```
+0    72 字节头部  <III20sQQ24s: magic 0xF0000011, 1, count, 20x0, totalSize(Q), 0, 24x0
+72   32 x types  <IIQIIII: 0, 0, typeHash, count, 0, 16, 16
+104  80 x count  <7Q6I: nameHash, typeHash, offset, 0,0,0,0, length, 0,0, 16, 16, index
数据区 = align16(104 + 80*count),每个资源 16 字节对齐
资源体 = u32 bodyLen + u32 version(=2) + body
```

**文件里**的数组描述符是**相对偏移**;**内存里**是**绝对指针** —— 这是必踩的坑之一。

## 5. Addon 约定

首行必须是(无 BOM、256 字节内、**必须是明文**):

```lua
-- HD2-Addon: mods/<作者>/<模块名>
```

编译成字节码会丢掉这行注释 → 自动发现失效。要让实现是字节码就打两个资源,
入口 `return require('..._impl')`。

```powershell
python tools/build_addon.py --name mods/<作者>/<名字> --entry x.lua ^
  --guid <稳定UUID> --display-name "名字" --output build/X.zip
```

**patch 编号不要写死**:HD2 Mod Manager 会自己分配/重排槽位(实测装一个新 mod 会让
其它 mod 挪号)。要手动装就挑当前最大号 +1,装上后按时间戳/大小认哪个是自己的。

Loader **只负责发现 + require + 日志,从不改内存**。真正干活的是 addon 自己的代码。

> 装在玩家机器上的 addon,只要**扫描**就要按 6.14 的规矩来:小步长 + 退避 + 终止状态。
> "没找到"是可以接受的结局,"一直找不到但一直在扫"不是。

## 6. 运行环境陷阱清单(全部真实踩过)

### 6.1 LuaJIT 数字只有 53 位精度
`0x80F1A156D9FA1E36` 存进 Lua number 会变成 `0x80F1A156D9FA2000`,搜索模式串直接错。

```lua
-- 正确:从十六进制字符对构造,全程不碰数字
local function le_bytes_from_hex(hex)
    return (hex:gsub("%x%x", function(p) return string.char(tonumber(p,16)) end)):reverse()
end
```
任何 >2^53 的 ID 都必须这样处理。

### 6.2 自检测 —— 扫描器会找到自己的模式串
模式串活在 Lua 堆里,扫描内存时会命中自己。**必须先取自身地址并跳过**:

```lua
local ok, p = pcall(function()
    return tonumber(ffi.cast("uintptr_t", ffi.cast("const char *", pattern)))
end)
-- 收集所有模式串地址;逐命中再判 +/-4096
```

### 6.3 table.concat 把数字按十进制文本拼接
`table.concat({65,66})` 得到 `6566` 而不是 `AB`。混合数字与字符串的字节表会静默产生错误长度,
**写入时污染相邻数据**。字节操作一律用纯字符串拼接。

### 6.4 FFI 指针参数必须 ffi.cast
传裸 number 会报 `cannot convert number to const void *`。
只有真 FFI 才暴露这个问题 —— 假桩测试必须**类型严格**才能抓到(见第 8 节)。

### 6.5 一次扫太多会把游戏饿死
64MB/帧会让游戏卡在加载界面。必须**时间切片**:
```lua
local deadline = os.clock() + 0.008   -- 每步最多 8ms CPU
while os.clock() < deadline do ... end
```
并按 region 大小**降序**扫描(大块更可能是数据表),启动推迟到第 120 帧。

### 6.6 枚举值 != 数组索引
字段里存的是**枚举值**,不是表内下标。查表要按记录自身的 type 字段匹配:
```lua
for i = 0, count-1 do if u32(rec + 0) == WANTED_TYPE then ... end end
```
曾按「数组索引 371」去查,结果为空;按「枚举值 371」才找到正确记录。

### 6.7 社区结构体可能过时,typelib 才是权威
FileDiver 里手写的 Go 结构体可能和当前构建对不上;
但 `datalibrary/*.go` 里**由 typelib 生成**的那批(带字段注释的)是可信的。
拿不准就查 `typelib_all.json` 的偏移,或直接读 `dl_library.dl_typelib`。

### 6.8 不是所有数据表都留在内存
用 `LDLD` 签名扫描做普查。实测:设置类表(射弹/伤害/爆炸)常驻;
实体 blob 里的组件表**在飞船里不一定在**,但**进了任务就在**
(荡平者挂架表就是第二轮扫描才找到的)。
**先普查、再决定策略,并且要给扫描留出"多轮"的时间。**

### 6.9 单点失败不要拖垮整个扫描
单个 region 读失败、单个模式扫挂,都必须 pcall 包住并跳过。
**每一层循环都要有 pcall**,否则一个命中就能让整轮白跑。

### 6.10 侦察 addon 只有一次机会
Loader 只在启动时 require 一次,**没有热重载** —— 改一行也要关游戏重开。
所以第一版就要做到"就算出问题也有产物落盘":
* **周期性落盘**(每 N 帧),不要只在扫完时写 —— 中途崩溃 = 一个字节都没有
* 出错时也落盘
* 日志带 `[frame N]` 前缀,才能分辨"飞船里加载的"和"任务里才加载的"
* 反复出错要**限流打印**,否则日志瞬间被刷爆

### 6.11 字段名别复用(今天的真事)
同一个表里 `hits = {}` 和 `hits = 0` 混用,`hits + 1` 直接抛
`attempt to perform arithmetic on field 'hits'`。**每一轮扫到第一个命中就整个中断,
census 也因此从来没落盘**,白跑一趟。Lua 不查类型,起名要狠。

### 6.12 dump 要从可读的地方开始
数据块的 `LDLD` 可能坐在分配区的 `+4` 处。从 `magic-64` 开始读会**读到区域外**,
`ReadProcessMemory` 返回 0 字节 —— dump 文件只有个头。**读取起点要钳到 region base,
失败要往后挪一点重试。**

### 6.13 数组描述符:文件里是偏移,内存里是指针
见第 2 节那个表。这是"一个 bug、两个症状"的典型:**补丁不生效 + 帧率被拖垮**
(因为解析全拒 → 每轮重扫)。凡遇到"普查里明明有、代码却说没有",先怀疑这一条。

### 6.14 "失败但一直在跑"的扫描器是帧率头号杀手
它比"扫得慢"糟得多:玩家一直卡,而日志里只有一行"0 个区块"。必须给它**终止状态**:

* **单次读取的块要小**(1 MB → 256 KB):`while os.clock() < deadline` 在两次检查之间
  **无法中断**,块越大越容易越界预算,帧尖峰越明显;
* 空手轮之间**指数退避**(2/4/8/16/30 秒),连续 N 轮空手就 `phase="gave_up"` 彻底停;
* **命中签名却解析不出记录 → 立刻停手 + 落盘原始字节**,绝不"下一轮再看看";
* 区块认出来了、只是记录数不够 → 同样停手,不留着重扫;
* 每轮都写一个 `census` 文件是**可以的**(几十 KB,一次写),但别每帧写日志。

### 6.15 判据要留"构建漂移"的余量
社区明文 JSON、wiki、typelib 都是**某个构建的快照**;游戏版本之间平衡性改动会让数值漂移
(实测:轨道磁轨炮在旧 JSON 里 210 秒、当前 wiki 写 180 秒;冷却字段只对上 70/76)。
要求"逐位 100% 吻合"会直接拒绝掉本来极强的证据。**用"断层"而不是"绝对比例"当判据**:

```
最高分 ≥ 65% 记录   AND   最高分 ≥ 3 × 第二高分   AND   最高分唯一(并列 == 1)
```

绝对比例只是下限;真正的保证来自**断层** —— 随机或凑巧的偏移给不出"70 命中 / 第二 0"这种形状。

### 6.16 发布层面的坑:manifest 的 `Name` 会被当文件夹名
mod manager 普遍拿 `manifest.json` 的 `Name` 当文件夹/文件名。
**里面出现 Windows 非法文件名字符就直接导入失败** —— 实测一个 **ASCII 冒号** 就毁掉了整个 mod
(`轨道激光:取消次数限制`),而同一个作者之前所有能正常导入的 mod,`Name` 全是纯 ASCII。
**`Name` 保持纯 ASCII,且不含 `\ / : * ? " < > |`**。
打包脚本里加一道自检(见 `tools/build_addon.py` 的 `check_display_name`),别再靠人肉记住。

**同一个 manifest 的 `Description` 也要自己写一遍。** 生态里流传的模板文案是
`"Requires Bingus Shared Loader v15 or newer / API 1. Enable both and deploy."`,
那句 "Enable **both**" 会让用户以为还要再装第二个 mod —— 实测真的有人这么来问。
写清楚:只要 loader 一个;"`API 1`" 是 loader 自己的 API 等级、写在 `BingusSharedLoader.log` 首行。
**面向用户的每一句文案都是支持成本。**

顺带两条分发相关的:
* 两个 addon 的 ZIP 里都带着 `Addon/9ba626afa44a3aa3.patch_0`。**管理器会在部署时重排编号**,
  用管理器装没问题;但用户**手动把 `Addon/` 拷进 `data/`** 就会互相覆盖 ——
  表现成"两个一起装总有一个不生效"。说明里必须明确写这一点。
* 装的人一多,失败模式就多。**必须给用户一个一眼能看懂的产物**:一个 `STATUS.txt`,
  第一行就是结论(`OK - patch applied` / `FAILED - ...`)。
  否则回收到的反馈全是"不生效",而你手里没有任何信息。日志是给开发者看的,状态文件是给用户看的。

### 6.17 同一张表在内存里有多份,而且会被重新加载
实测:同类型哈希的 LDLD 块在内存里有**几十个**;而且进任务 / 换图时游戏还会**再加载一份新的**。
"只挑第一个命中的记录来打补丁" = **一开始生效、过一会儿就失效** —— 你自己打的那份还在,
只是游戏改用另一份了,而复查逻辑还会认为一切正常。

正确做法:
1. **全部收集、全部打**(每份各自备份),别只挑第一个;
2. **持续维护,不是打一次就完**:
   * 每几秒逐份复查(被冲掉就重打,读不到就丢弃);
   * 每几十秒做一次**轻量维护扫描** —— 只扫"已知区块 ± 32 KB"合并出来的**观察窗口**(几 MB),
     抓新加载出来的副本,代价从"整个地址空间"降到几 MB;
   * 每十分钟做一次**全量重扫**兜底(副本万一被搬到别的地方);
3. 复查时必须用**当前**字节判定:从地址重读的记录其实是"从这条记录开始"的 N 字节,
   塞回原来的记录结构时要记得把**记录内偏移归 1**,否则判定会读越界并静默失败。

### 6.18 启动时先做**环境闸门**,不满足就立刻停手
loader 版本不够(实测:v14 = API 0)时,addon **照样会被加载、照样会跑** ——
它不会报错,只会安静地做不成事。如果你什么都不检查,用户看到的就是"一直在 working",
而真正的原因(loader 太旧)永远不会出现在任何日志里。

所以 addon 开头就该问一句:

```lua
local l = rawget(_G, "CowboyBingusModLoader")   -- { api = 1, version = 16 }
local api = type(l) == "table" and tonumber(l.api) or nil
if api and api < 1 then
    -- 写入 STATUS.txt 第一行,然后 return:不扫描、不写内存
end
```

读不到这个 global 时**不要直接拒绝**(将来可能有别的 loader),再退化去读
`%LOCALAPPDATA%/CowboyBingus/Helldivers2/Logs/BingusSharedLoader.log` 的首行 `loader-v(\d+); API (\d+)`,
同时还把版本号**写进状态文件**,以后每张支持工单都自带环境信息。

### 6.19 诊断要在设计时就假设"这次会失败"
"一次机会"的 addon,失败路径必须自带证据,**否则第二轮还是侦察**。两个救过场的产物:

| 产物 | 内容 | 救在哪 |
|---|---|---|
| `lld_census_roundN.txt` | 本轮扫到的**所有** `LDLD` 块地址/类型哈希/大小 | 一眼分清"表不在内存"和"解析错了" |
| `strat_blocks_roundN.hex` | 每个签名命中点的前 1024 字节原始 hex | 解析失败时直接给出真字节,离线就能定布局 |

### 6.20 仿真器必须用**游戏同款** Lua(LuaJIT),否则语法错误一路穿到实机

离线测试全绿、打包校验全绿,实机 loader 直接 `load failed: unexpected symbol near '/'`——
因为代码里写了 `rem // N`(**整除,5.3+ 才有**),而游戏是 LuaJIT(5.1);
lupa 默认的 Lua 5.5 接受它,所以测试抓不住。

```python
from lupa.luajit21 import LuaRuntime as LuaRuntime   # 不是 lupa.LuaRuntime
```

再配一道**语法闸门**(测试与打包校验各一次):用 LuaJIT `load()` 编译一遍成品,
并扫 `//` / `goto ` / `math.type` / `string.pack` / `table.move`;
**配一条变异测试**(把 `//` 放回去,闸门必须抓住),否则闸门本身没人验证。

### 6.21 字段的类型先查 `data/components/*.json`,不要靠猜

社区仓库里有**每个组件的字段名 → 类型**表(`data/components/<组件>.json`):

```json
"mission_specific": { "type": "byte" },
"selectable":      { "type": "byte" },
"triggers_war":    { "type": "byte" }
```

真实教训:按 u32 去反推 `selectable` 的偏移,**永远反推不出来** ——
它是 byte,而且和另外两个 byte 挤在一起。
**"其它字段全部 100% 复现、只有某一个对不上"时,先怀疑类型,再怀疑数据。**

### 6.22 一个字节里可能挤了好几个开关:多种编码规则都试,谁分高用谁

实测:某个构建里 `selectable` **不是独立的 0/1 字节**,而是某字节的 **bit1**
(bit0 恒为 1),即 `byte == 1 + 2*selectable` —— 9/9 样本唯一命中;
换成"独立 0/1 字节"去匹配只有 6/9。

* 判据:把候选规则各跑一遍**整表复现**,取分高的那条;
* **LuaJIT 没有位运算** —— 置位用算术:`if b % 4 < 2 then b = b + 2 end`,
  只动那一位,不碰同字节其它标志(写 u32 会把隔壁字段一起冲掉 —— 配一条变异测试守着);
* 回读判据也要按选中的规则来。

### 6.23 数据层的开关通常**不足以**让隐藏内容出现在玩家 UI 里 → 借壳

把 `selectable` 打开、名字图标描述全补齐,列表里依然没有它。
**反查方法:把社区仓库全部 JSON(1500+ 个)grep 一遍目标 id。**
实测只有 `generated_stratagem_settings.json` 提到战备 id ——
**游戏数据里没有"玩家已解锁"这张表**,条目来自账号/运行时状态。

⇒ 想"凭空多一条"在数据层做不到。可行做法是 **借壳**:
把一条**已经解锁、已经在列表里**的战备原地改造成目标内容(见 §12)。

**旁证**:别人演示里"战备列表少了一条现役战备、多出你要的那条",就是借壳特征。

### 6.24 借壳会**继承原战备的机制**,一定要摘干净

例:借飞鹰烟幕 ⇒ 槽位带着 `additional_stratagem = StratagemType_EagleRearm`,
游戏于是把它当"鹰系战备":卡面那个数字其实是"剩余次数内再次可用的间隔",
**真正的冷却在 `EagleRearm` 上,而且全族共用**。

解法:把 `depends_on` / `additional_stratagem` 清零(偏移靠实机 dump 对齐,别猜),
并**保留目标槽位自己的** `origin_type` / `cooldown_type` / `icon` / `category` ——
那些才是"能用、能看见"的前提。

### 6.25 卡面数字 = 记录值 × 舰船升级系数:用**同族现役战备**标定

写进去 1 次 / 300 秒,卡面是 2 次 / 178 秒 —— 不是没生效,是被升级改过。
标定方法(三条鹰系战备的记录值都是 15 秒,卡面都是 9 秒):

```
冷却系数 = 卡面值 ÷ 记录值 = 9 ÷ 15 = 0.6      -> 想显示 300 就写 500
次数     = 记录值 + 1(另一套模块)          -> 想显示 1 就写 0(有风险,谨慎)
```

**面板/卡面是标定量,不是事实。** 系数是玩家相关的(取决于已购模块),
做成 `CONFIG.upgrade_factor` 让用户能自己重标定。

### 6.26 枚举下标会被版本回收 → 用**本地化名字**查,别抄社区枚举表的下标

`ProjectileType_Bomb_200kg` 在旧枚举表里是 139,当前构建里 **139 变成了步枪弹**
(用 `NameUpper` 去本地化字符串表查,名字是 `5.5x50mm SUBSONIC`)。
照抄下标 = 让飞鹰丢步枪弹,而且**不报错、静默错**。

正确做法:遍历当前构建的射弹表,用 `NameUpper` / `NameCased` 去**本地化字符串**里
反查名字(例:名字就叫 `200KG BOMB`,Type = 192)。
**枚举名稳定、枚举下标不稳定。**

### 6.27 payload 数组:重复哈希对"物件"合法,对"载具"会被去重

* 语义:数组里**每一项生成一个实体**(地狱炸弹 = 炸弹 + 空投舱);
* 重复合法:补给战备是 `[A,B,A,B,A,B]` → 4 个补给舱 + 空投舱;
* 但**飞机这类**即使放 3 个**不同**哈希,引擎也只让一架升空
  (飞鹰是"单机 + 装填池",`EagleRearm` 就是为它存在的)⇒ 别再堆数量,改从单发弹量补偿;
* **数组的"1、2 号槽位"通常本来就在,只是 `count` 是 1。**
  实测地毯式空袭的 payload 数组后面那 16 字节"不是空白" —— 那**不是**别人的数据,
  而是**这个数组自己的容量**。此时**直接写满 + 把 `count` 改成 N** 就行(写前备份被覆盖的字节)。
  ⚠ **别自己加"扩展位置必须是空白"这种安全检查然后被它挡住** —— 这一条曾让我们绕了两轮远路。
* 只有在"数组确实不够长"时才需要**借数组**:找一条 payload 项数够多、且没有任何可选战备引用它的,
  写进去再**重指向描述符**(改 ptr + count 两个 u64),并备份原数组。
* **用"常规战备在用的装载物",别自造"没人用"的实体。**
  实测:挑两个"没有任何战备引用"的飞鹰实体塞进 payload,结果只有一架升空 ——
  很可能是它们的 `package` 从来没被加载过。换成**一条现役战备自己的 payload 实体**
  (例如先借壳把那条战备的槽位腾空,它的 payload 就空出来了)之后才正常。
* **"用现役实体写自己的数组"这条路也已经实测走完了(2026-09-22,实机):还是 1 架。**
  日志证明:三个不同的现役飞鹰实体、`payload count 1 -> 3`、三个打击实体的 23/23 字段全部写入、
  5 份战备副本复查通过 —— **引擎侧依然只升空一架**。
  ⇒ 架数这条路到此为止:一次呼叫的弹量 ≈ `fire_duration / bomb_interval`,要更多弹就压间隔,
  并且**明确告诉用户这是引擎上限**,别让他等一个不会出现的编队。

### 6.28 断层判据要留一个"相关性例外"

"最高分 ≥ 3 × 第二高分"这条在真实数据里会误拒:`origin_type` 与 `cooldown_type`
近乎完全相关(氏族站战备同时是 SharedClan),互为第二名。

例外条件:`score >= 0.85 × 记录数` **也**接受(近乎全中的列不可能是巧合),
再叠加"目标记录的原版值指纹"兜底。**相关性撞车本身通常无害**(两条字段要写的值相同)。

### 6.29 回读校验不要用**同一个编码器**再编一遍

f32 编码器写错了、回读时又用同一个编码器算期望值 ⇒ 永远相等,bug 测不出来。
(变异测试当场抓住了这一条。)解法:回读用**独立解码器**判数值(`|decoded - want| < eps`),
并在启动时做**自检**(几个已知值 → 已知位模式,对不上就拒绝运行)。

### 6.30 发布前把"诊断产物"一起交付

这一轮能收敛,靠的是 addon 每次都落盘:

| 产物 | 用途 |
|---|---|
| `STATUS.txt` | **给用户看**:第一行结论 + 关键参数(偏移、副本数、生效数值) |
| `<Mod>.log` | **给开发者看**:每个字段的反推得分、每步写入内容 |
| `records_hex.txt` | watch-list 记录的**完整原始字节**(补丁前) |
| `records_after_hex.txt` | **补丁后**再 dump 一次 —— 证明"我们写的 == 内存里真实存在的" |
| `original_*.hex` | 原始字节备份 |

再加一个**远端可用的对齐脚本**(逐偏移 × 逐字段匹配),拿到 dump 就能一次定死布局。
### 6.31 标定公式要吃"实机观测值",不是配置里的期望值

同一轮里往往有两个相近的数字,必须分开:

* `flight_size = 3` —— 我们**希望**的架数(决定写几项 payload);
* `bomb_planes = 1` —— 实机**观测到**的架数(决定投弹间隔怎么反算)。

一开始用期望值反算(3 架 → 每架 20 发 → interval 0.25),实机只飞 1 架 ⇒ 用户看到"弹数不对(约 20 发)";
改成吃观测值(1 架 → 60 发 → interval 0.083)才对。

**只要"观测到的现实"和"配置里的期望"不一致,就把它们拆成两个独立参数,别让标定公式读错的那一个。**

### 6.32 "和 X 一样"要落到 X 的**原始字段值**,不是屏幕上的显示值

用户说"把冷却设置成和别的飞鹰一样"。别的飞鹰记录里 `cooldown_duration_success = 15`、卡面显示 **9** ——
正确做法是**先反算回原始值再照抄**:

```text
目标 = 卡面 9 秒;upgrade_factor = 0.60  =>  写入值 = 9 / 0.60 = 15  ==  同族记录逐位相同
```

直接照抄"9"会得到 9 × 0.6 = 5.4 秒,**看着像但其实不一样**,换套舰船模块立刻露馅。

## 7. 工作流

### 第 0 步:离线把答案挖出来
0. **先查社区有没有解好的 JSON**(见第 0 节的第二个明文来源)。有的话就从 JSON 起步,
   连 FileDiver 没覆盖的 `generated_*` 也能直接拿到
1. 从明文镜像里按类型名 `dlsum` 找到目标表,解出全部记录
2. 用 `typelib_all.json` 拿字段偏移,用 `datalibrary/*.go` 拿字段含义
3. **找"同族对照"做差分** —— 比点杀更快更硬:
   今天要改的是"荡平者一次掉一根",而 EAT-17 和 EAT-700 都掉两根,
   三条挂架记录一摆出来,差异字段自己就跳出来了(`slot1` 空 + `SpawnPayloadSize`)
4. **优先抄"游戏里已经能用"的那一份,而不是自己编一组合适的值**:
   最终那 64 字节和 EAT-17 的 slot1 **逐字节一致**,只有 8 字节物品哈希不同。
   这不是巧合,是证据 —— 说明你复现的是引擎既有行为。

### 第 1 步:只读侦察 addon(只在离线算不出来时才需要)
写一个**绝不调用 WriteProcessMemory / VirtualProtect** 的 addon:
1. 时间切片扫描内存,按 `LDLD + 版本 + 类型哈希` 定位数据表
2. 顺手把**唯一 ID 哈希**(资源名哈希)也在内存里搜一遍,并 dump ±512 字节上下文 ——
   这样即使表头没找到,也能从对象本身定位
3. dump 成 hex 到 `%LOCALAPPDATA%/<你的目录>/`
4. 附带一份 **census**:内存里所有 `LDLD` 块的 地址/类型/大小/样本

**先只读、后写入,永远如此。**

### 第 2 步:离线解析 dump
用脚本解析,确认偏移和值域。**内存布局与文件镜像一致**的话,这一步就是纯验算。

### 第 3 步:用 Wiki 交叉验证 ★
`helldivers.wiki.gg` 的 "Detailed Weapon Statistics" 给出精确数值;
用这些数字去数据表里逐项匹配,命中多项即锁定。
例:爆裂铳的撞击爆炸按 Wiki 是 `225伤害 / 30破片 / 内径4m / 外径7m / 拆迁20 / 硬直35 / 推力40 / Medium穿甲`,
413 条爆炸里**只有一条 8 项全中**。

> 注意:Wiki 也会写"行为描述"(例:*"sent two at once like typical EAT-17"*),
> 这类句子能直接把你送到"同族对照"上,比自己逐字段比对快得多。

### 第 4 步:写运行时补丁
模板要点(这套一次通过实机):
- 用签名定位数据表,校验 `size` 等已知常量
- 用**唯一 ID** 找到目标记录,并且**要求它唯一**(多于一条也拒绝)
- 校验记录里一个**预期常量**(例:`SpawnPayloadSize == 2`)
- **字段偏移不要写死,让运行时反推**(最有价值的一条):把目标表的**全部记录原版数值**
  内置进 addon,在 `0..len-4` 每隔 4 字节当候选偏移算命中数,取"唯一 argmax + 断层"
  (判据见 6.15)。实测离线按 typelib/JSON 的字段顺序对齐**数错了一位**,
  写死就落到隔壁字段上 —— 冷却不动、还静默改坏另一个参数;反推则照样命中
- 目标记录允许**已经是打完补丁的值**(幂等),否则重启后自己认不出自己
- **目标记录的每一份副本都要打,而且要持续维护**(见 6.17)。只打"第一个命中"是
  "一开始生效、过一会儿失效"的标准成因
- 给用户留一个 `STATUS.txt`:第一行一句人话结论 + revision / phase / 偏移 / 副本数 / 拒绝次数(见 6.16)
- **写入前把原始字节备份到磁盘**
- 判断"是不是已经打过补丁"(幂等),避免重复写
- 目标是只读页时用 `VirtualProtect` 临时放开,写完**恢复原保护属性**
- **写完回读验证**(逐字段核对,不只是"写成功")
- 每 ~5 秒复查一次,被地图重载冲掉就自动重做
- 用 `_G.<ModName>` 做单例守卫
- 错误日志限流
- **任何校验不符就记日志拒绝写入**

## 8. 离线仿真测试(必做,而且能省一次实机往返)

用 `lupa`(pip 装)在 Python 里跑 Lua,给 addon 搭一个**假的内存空间**。

> ⚠ **仿真器必须选游戏同款运行时**:`from lupa.luajit21 import LuaRuntime`。
> 用 lupa 默认的 Lua 5.5 会让 `//`、位运算这类 5.3+ 语法通过测试,然后在实机 `load failed`(见 6.20)。
> 顺带注意 LuaJIT 与 5.x 的另一处差别:**没有位运算**,置位/清位要用算术。

**测试桩必须类型严格**,否则抓不到 6.4 这类 bug:
```lua
function ffi.cast(ctype, v)
    if ctype:find("%*") then
        if type(v) == "number" then return { __ptr = v } end   -- 指针是特殊对象
        if type(v) == "table" and v.__ffi then return { __ptr = v } end
        error("ffi.cast(" .. ctype .. "): cannot cast " .. type(v))
    end
    return v
end
function kernel.ReadProcessMemory(proc, address, buf, size, count)
    address = as_pointer(address, "ReadProcessMemory")       -- 传 number 直接报错
    ...
end
```

**再跑变异测试**:把已修的 bug 改回去,确认测试**确实会失败**。否则测试没有意义。

### lupa 排障三连(今天全踩了)
| 症状 | 原因 / 解法 |
|---|---|
| `cannot open ...: Illegal byte sequence` | **Lua 的 fopen 打不开含中文的路径**。夹具文件放 `%TEMP%`(纯 ASCII) |
| `too many registers (limit is 255)` | 一个 `string.char(...)` 塞了几万个参数。按 200 个一组切块 |
| `UnicodeDecodeError` 读回来 | **lupa 默认按 UTF-8 解 Lua 字符串**,二进制会炸。让 Lua 侧返回 **hex 字符串** |

### 夹具用真实 dump,不要手搓
今天的夹具直接是**从实机抓下来的内存 dump**,所以偏移是拿真字节验的。
再配几个诱饵:
* 一份"看起来合法但关键字段不对"的表(测你的校验有没有用)
* 自己模式串所在的假堆区(测自检测)
* **诱饵要注意扫描顺序**:region 按大小降序扫,想让诱饵先生效就把它做大

**变异没被抓住时,先怀疑夹具,再怀疑代码。** 今天 `SpawnPayloadSize` 校验的变异没被抓住,
查下去是夹具自己把诱饵挂架放错了偏移 —— 说明这套测试真的在检查东西。

### 夹具的维度 = (值的多样性) × (容器形态的多样性)

只造"值不一样"的夹具是不够的。轨道激光那次,夹具只覆盖了**文件形态**
(`DLArray` 放相对偏移、记录紧跟描述符),于是"内存里其实是绝对指针"这个 bug 一路穿到实机。
**你每声称支持一种容器布局,就得有一个那样形态的夹具,并且各配一条变异测试**
(例:砍掉 `abs` 那一支 → 该夹具必须失败)。

顺带几条本次验证有效的夹具设计:
* **描述符多报条数**(真实游戏里确实出现 `count=36 hits=28`)——测"垃圾尾巴会不会被丢掉";
* **一部分记录的数值故意对不上**(模拟构建漂移)——测判据的余量够不够;
* 用**确定性伪随机**填充未用字段,否则"某一列恰好全中"会变成假阳性;
* 夹具文件放 `%TEMP%`(见下面的 lupa 排障)。

## 9. 工具链

| 位置 | 用途 |
|---|---|
| `tools/hd2_archive.py` | .patch_N 读写(已验证 round-trip) |
| `tools/build_addon.py` | .lua -> 可安装 ZIP |
| `tools/inspect_patch.py` | 归档结构查看 + 自动 round-trip 校验 |
| `tools/projectile_settings.py` | generated_projectile_settings.dl_bin 解析器 |
| `tools/dump_typelib/` | typelib → JSON(放进 FileDiver 源码树里跑) |
| `tools/ljd/` | LuaJIT 字节码反编译器,读别人的 mod —— **第三方**,见上游 |
| `tools/filediver/` + `filediver-src/` | 社区解包工具 + **明文 datalibrary + 字段名 Go 源码** —— **第三方**,见上游 |
| `tools/go/` | 便携 Go(只有 dump typelib 才需要) |
| `references/ldld.py` | **LDLD 表解析器**(dlsum / 找实例 / 解记录) |
| `references/hd2data.py` | **离线数据读取层**:typelib 布局 + entities blob 组件表(entity hash -> 组件记录 / 字段) |
| `data/components/<组件>.json`(社区仓库) | **字段名 → 类型** 权威表(byte / enum / array …),查类型先来这里 |
| `data/enums/<枚举>.json`(社区仓库) | 枚举**名字**列表 |
| [shalzuth/HelldiversData](https://github.com/shalzuth/HelldiversData) | **社区解好的明文 JSON**(全部 `generated_*`);FileDiver 没覆盖的表先来这里找。**枚举名可信、枚举下标不可信**(见 6.26) |
| `_baseline_<build>/` | 实机内存 dump 基线(游戏更新后对照用) |

实机前先核对游戏构建:`helldivers2.exe` 的版本号与 SHA-256。
**构建没变 = 旧的 dump、偏移、census 全部还能用**,能省一整轮侦察。

## 10. 安全与合规

- 先做**只读**侦察,确认数据位置后再写
- 写入前校验值域,写入后回读;不匹配就拒绝并记日志
- 校验游戏版本(exe/dll 的 SHA-256),版本不符就拒绝写入
- **不要从外部进程读内存**(见第 3 节 GameGuard)
- 改游戏行为在联机时可能与队友表现不一致,并有反作弊风险 —— **主动提醒用户**,
  并明确说清"客户端本地改动,别的玩家多半看不到"
- 所有改动只在内存中,禁用 mod + Purge 即可完全还原

## 11. 实例

| 案例 | 内容 |
|---|---|
| `references/hd2-eruptor-dominator-案例.md` | 把 R-36 爆裂铳的射弹套到 JAR-5 主宰上(纯内存改射弹表) |
| `references/hd2-leveller-double-案例.md` | **让 EAT-411 荡平者一次空投两根** —— 离线全解 + 一次实机侦察 + 64 字节补丁 |
| `references/hd2-orbital-laser-案例.md` | **轨道激光取消次数限制 + 冷却 300→180 秒** —— 社区明文 JSON 起步;踩中「DLArray 内存里是指针」+「扫描器拖垮帧率」;最终靠**整表复现反推字段偏移**,并推翻了自己离线推导的偏移 |
| `references/hd2-carpet-bomb-案例.md` | **把从未发布、且投放载具已被删掉的「飞鹰地毯式空袭」搬回游戏(7 轮迭代)** —— 踩满:仿真器 Lua 版本 / 字段是 byte 且位打包 / UI 列表闸门不在数据里(必须借壳)/ 借壳继承原战备机制 / 卡面数值是标定量 / 枚举下标被回收 / payload 数组语义与借数组。**想知道"怎么让隐藏内容被玩家看见",先看这篇** |
## 12. 借壳法:把未发布 / 隐藏内容搬进玩家 UI

数据层开关(`selectable` 之类)通常只决定"这条记录能不能被选用";
而**列表里有没有这一格来自账号解锁状态,不在 `data/` 里**(见 6.23)。
所以要"凭空多一条",只能借一条已经解锁、已经在列表里的战备,把它改造成目标。

### 步骤

0. **先反查确认**:把社区仓库全部 JSON grep 一遍目标 id。
   只有 `generated_stratagem_settings.json` 命中 ⇒ 没有解锁表 ⇒ 必须借壳。
1. **选槽位**:挑一条用户一定有、且不心疼的现役战备(**问用户**,别自己决定)。
2. **找记录**:按 id 定位(§7 第 4 步);同一张表在内存里有多份副本,全部都要打。
3. **改这些**(偏移一律整表复现反推,别写死):
   * 身份:`name_upper` / `name_cased` / `description` / `fluff`
     —— 实测这四个 u32 是连续的,从 `description` 往前 8 字节起一次写 16 字节;
   * 行为:`payload` / `package` / `uses` / `cooldown_duration_success`;
   * 摘机制(见 6.24):`additional_stratagem` / `depends_on` 清零。
4. **保留**原槽位自己的 `origin_type` / `cooldown_type` / `icon` / `category` / `selectable`
   —— 那些才是"能用、能看见"的前提。
5. **回读校验 + 备份 + 每轮复查重打**(被地图重载冲掉是常态)。

### 两个必查(否则会出现"名字对了但其他地方不对")

* **字符串键要有对应的本地化**:目标的 名字/描述 键如果在当前构建的本地化表里查不到,
  界面上就是空的。换成一个**内容合适且确实存在**的键
  (实测:名字键还在、描述键已悬空 ⇒ 把描述指到另一条同义文案上)。
* **图标可能被清成 0**:很多未发布记录的 `icon` 是 0,而列表按图标渲染。
  从一条正常在用的同族战备抄一个过去(实测字段偏移 = `package + 8`)。

> **找"缺什么"最快的办法:把目标记录和一条正常在用的战备逐字段 diff,只找一个异常值。**
> 这一条 diff 在实战里同时指出了 `icon == 0` 和 `package == 0` 两个缺口。

### 代价必须跟用户讲清楚

借壳 = **那条现役战备没了**。说明里要写明,并给出可换槽位的配置项(`CONFIG.hijack_id`)。

