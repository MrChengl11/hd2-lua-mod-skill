# 案例:轨道激光 取消次数限制 + 冷却 300 → 180 秒

> 游戏构建 exe 1.8.45317.0 / SHA-256 `A09FF52663E73B94FB0CAC0DCB5BA84FFD10ECF44F74A8921AC66AF923988CC3`
> 产物:`Orbital-Laser-Free.zip`,改 **8 字节**;离线全解 + 两次实机(v1 暴露容器布局 bug,v2 一次通过)

---

## 一、问题

轨道激光(Orbital Laser)每次任务只有 **3 次**,冷却 **300 秒**。
要的是:次数限制取消、冷却降到 180 秒。

## 二、离线阶段

### 2.1 这次的数据**不在** entities blob 里

先把 `generated_entities.dl_bin` 的 270 张表全部普查了一遍 `LDLD` 实例,
按 `dlsum` 还原类型名找"策略/轨道"相关的:

| 表 | 记录数 | 内容 |
|---|---|---|
| `OrbitalAbilityComponentData` | 3 | 轨道能力(激光 / 磁轨炮 …) |
| `StratagemFiresupportComponentData` | 16 | 一个 u32,不是冷却 |
| `OrbitalShipComponentData` | 528 | 1 字节的 flag |
| `LoadoutPackageComponentData` | 520 | 实体 → `packages/generated/loadout/*.package` |

轨道激光的实体是 `0xEC3575E7A93793BB`,它一共只有 4 个组件。
`OrbitalAbilityComponent` 里 +460 是 `limit`(激光=25、磁轨炮=2)、+472 是 `search_radius`
(激光=50、磁轨炮=30)—— 和 Wiki 对得上,**但就是没有 cooldown**。

**冷却和次数是"策略级"属性,不在组件表里。**

### 2.2 新的明文镜像来源(这条应该提到最前面)

`data/game/` 里有 **57 个** `generated_*.dl_bin`,而 FileDiver 只打包了它实现了 parser 的那 ~20 个。
缺的那些在社区数据挖掘仓库里有**已经解好的 JSON**:

* [shalzuth/HelldiversData](https://github.com/shalzuth/HelldiversData) —— `data/settings/`、`data/components/`、
  `data/entities/`、`data/enums/`、`data/translations/`,覆盖游戏目录里的全部 `generated_*`
* 文件路径规律:`data/settings/generated_<和游戏目录里同名的那个>.json`
* wiki 的 `Module:Decodedata-*` 模块是同一支血脉(取原文加 `?action=raw`)

本次需要的是 `generated_stratagem_settings.dl_bin`(79344 字节):

```powershell
Invoke-WebRequest -OutFile ref/generated_stratagem_settings.json `
  https://raw.githubusercontent.com/shalzuth/HelldiversData/master/data/settings/generated_stratagem_settings.json
```

> **教训:先问"这块数据有没有人已经解好了",再去啃 typelib。**
> 这一条把这次任务从"至少两轮实机侦察"直接压成"离线出成品"。
> 列目录用 GitHub API 的 `contents/`(注意响应可能被截断,逐个目录钻);
> `raw.githubusercontent.com` 用 PowerShell 的 `Invoke-WebRequest` 能直接下。

### 2.3 结构

```
LDLD 块类型 = djb2("StratagemSettings") = 0x30EB6399
  +0     "LDLD" | version(1) | typeHash | size | is64=1 | 7 字节 pad
  +24    DLArray { u64 offset, u64 count }        StratagemSettings 只有一个 ARRAY 成员
  +24+offset   StratagemInfo[count]               每条 400 字节
```

JSON 里一共 **12 个块、103 条策略**。字段名靠"typelib 成员顺序 ↔ JSON 键顺序"对齐:

| 偏移 | 字段 | 原版值(轨道激光) |
|---|---|---|
| +4 | `id`(唯一标识) | `970450596` = `StratagemType_OrbitalLaser` |
| +80 | `uses`(次数上限) | 3 |
| +10x | `cooldown_duration_success` | 300.0 |

**这个对齐方法后来被证明不可靠 —— 见第四节。**

### 2.4 "无限次"不用自己编

JSON 里 **85 条**策略的 `uses` 就是 `4294967295`(`0xFFFFFFFF`):
补给背包、轨道精准打击、哨戒炮、全部团队武器…… 游戏自己就是这么编码"无限"的。
所以"取消次数限制" = 写 `0xFFFFFFFF`,而不是 999 之类。

> 这条和"优先抄游戏里已经能用的那一份"是同一条经验,只是换了个字段。

## 三、第一版:容器布局假设错了

第一版把"只读普查 + 运行时补丁"放在同一个 addon 里(所有校验失败路径都落盘)。
实机日志:

```
[frame 692] 第 1 轮扫描结束:0 个 StratagemSettings 区块,0 条策略记录
[frame 692] LDLD 普查(共 200 项):
[frame 692]    0x1F01740 type=0x30EB6399 size=7016
[frame 692]    0x1F032C0 type=0x30EB6399 size=3808
...
```

**块就在那儿(37 个),却一个都解析不出来。** 原因是踩到了 `LDLD` 的 DLArray 描述符:

> 在**文件里**它是 `{u64 相对偏移, u64 条数}`(偏移相对数组头,记录紧跟在后面);
> 在**内存里**第一个 u64 是**指向记录数组的绝对指针**。

FileDiver 的明文镜像是文件形态(`offset = 16`),照它写死"相对偏移" → 内存里那个字段是个大地址
→ `offset > size` → 全拒 → 0 个区块 → 每轮重扫 → **那 4 ms/帧的扫描开销一直挂着**。

**一个 bug,两个症状:补丁不生效 + 帧生成时间严重不稳。**

### 顺带:普查救了这一轮

如果不是每轮把**所有** `LDLD` 块的类型哈希和大小落盘,
这次的日志就只剩"0 个区块"—— 完全看不出是"表不在内存"还是"解析错了"。
普查一眼给出答案:**表在,是解析错了**。

## 四、第二版:一次通过,并推翻了离线推导

### 4.1 改法

1. **两种解释都试**(`{ptr,count}` / `{magic+24+rel,count}` / `{magic+rel,count}` / 交换字段),
   判定标准不是结构校验而是**语义**:读出来的记录里 `+4` 的 id 有 ≥60% 落在已知的 103 个策略 id 里;
2. **签名命中却解析不出记录 → 立刻停手**,把命中点前 1024 字节原始 hex 落盘,不再循环重扫;
3. 扫描块 1 MB → 256 KB,每帧预算 8 ms → 4 ms,空手轮之间指数退避,连续若干轮空手就彻底停手。

### 4.2 实机日志

```
[frame 1196] 第 1 轮扫描结束:签名命中 13 处,9 个 StratagemSettings 区块,76 条策略记录
[frame 1196] uses     候选偏移 +80,命中 75/76(第二 0),并列 1
[frame 1196] cooldown 候选偏移 +104,命中 70/76(第二 0),并列 1
[frame 1196] 校验通过:uses=+80, cooldown=+104,目标 record=0x1D9D770A840
[frame 1196] PATCHED 轨道激光 record ... uses +80 : 3 -> 4294967295 / cooldown +104 : 300.0 -> 180.0
```

### 4.3 三个必须记住的点

**① 冷却实测 +104,不是离线推的 +100。**
400 字节记录里连着 7 个 `f32`,而 JSON 只列了 6 个浮点字段,
多出来的那一个在哪个位置**无法从纯文本判断** —— 我按 typelib 顺序对齐就少算了一位。
要是按 +100 写死:180.0 会落进隔壁字段,冷却照样 300 秒,**同时还静默改坏一个没人看的参数**。

> 结论:字段顺序的"文本对齐"只能当**假设**,不能当**结论**。
> 离线推导的正确用法是把它当候选,让运行时用数据把它敲定。

**② 只认出 76/103 条。** 12 个块里有 3 个解析不出来;有些块读到的条数比真实条数多
(`count=36 hits=28`、`count=11 hits=10`)。靠"记录里的 id 认不认识"当过滤器,
垃圾尾巴自动被丢掉,剩下的仍然够用。

**③ 冷却只对上 70/76。** 社区明文 JSON 是**某个旧构建的快照**,版本之间的平衡性改动
会让一部分数值漂移(那份 JSON 里 Orbital Railcannon 是 210 秒,当前 wiki 写 180 秒)。
要求"逐位 100% 吻合"会直接拒绝 —— 而 70/76 配"第二名 0"本来是极强的证据。

### 4.4 因此把判据改成"断层"而不是"绝对比例"

```
最高分 ≥ 65% 记录   AND   最高分 ≥ 3 × 第二高分   AND   最高分唯一(并列 == 1)
```

绝对比例只是下限,留给构建漂移当余量;**真正的保证来自断层** ——
随机或凑巧的偏移给不出"70 命中 / 第二 0"这种形状。

## 五、沉淀成套路

### 5.1 用"整表复现"反推字段偏移(本次最有价值的一条)

不要从 typelib / JSON 的字段顺序去**算**偏移 —— 让运行时**推**:

1. 把目标表的**全部记录原版数值**内置进 addon(本次 103 条 `{id → uses, cooldown 位模式}`);
2. 用记录里一个**稳定的唯一键**(`+4` 的 id)把内存记录和原版表对上号;
3. 在 `0 … len-4` 每隔 4 字节当候选偏移,统计"复现原版值"的记录数;
4. 判据 = **唯一 argmax + 断层**(见 4.4),不是"必须全中";
5. 目标记录允许**已经是打完补丁的值**(幂等),否则重启后自己会认不出自己。

代价只是几十行 Lua + 一张常量表;换来的是**离线推导错了也照样能命中**。

### 5.2 容器布局也要当"未知"处理

同一个结构在文件形态和内存形态下可以长得不一样。凡是"描述符/偏移/指针"这类字段,
**两种解释都试,用语义(id 认不认识、值域合不合理)而不是结构去判定**。

### 5.3 扫描器必须有**终止状态**

"失败但一直在跑"的后台扫描是帧率的头号杀手 —— 它比"扫得慢"糟得多,
因为玩家会一直卡,而日志里只有一行"0 个区块"。所以:

* 单次读取的**块大小**要小(1 MB → 256 KB):`while os.clock() < deadline` 在两次检查之间
  无法中断,块越大越容易越界预算,帧尖峰越明显;
* 空手轮之间**指数退避**(2/4/8/16/30 秒),连续 N 轮空手就 `phase = "gave_up"` 彻底停;
* **命中签名却解析不出来 = 立刻停手 + 落盘原始字节**,绝不"下一轮再看看";
* 区块已经认出来、只是记录数不够 → 同样停手,不留着重扫。

### 5.4 诊断要在设计时就假设"这次会失败"

本次两个直接救场的产物,都值得抄进任何"一次机会"的 addon:

| 产物 | 内容 | 救在哪 |
|---|---|---|
| `lld_census_roundN.txt` | 本轮扫到的**所有** `LDLD` 块的地址 / 类型哈希 / 大小 | 一眼看出"表在,是解析错了",而不是"表不在" |
| `strat_blocks_roundN.hex` | 每个签名命中点的前 1024 字节原始 hex | 解析失败时直接给出真字节,离线就能定布局 |

### 5.5 仿真夹具要覆盖**容器布局**维度

第一版的 lupa 夹具只造了**文件形态**(`offset` 相对偏移,记录紧跟描述符)——
所以"内存里是绝对指针"这个 bug 一路穿到实机。
第二版补了 `layout="mem"` 的夹具(描述符放绝对指针,记录数组单独放在别处),
再用变异测试确认"砍掉 abs 分支"会被抓住。

> 这条是"变异没被抓住时先怀疑夹具"的第二个实例:
> 第一次是**诱饵摆错偏移**,这次是**夹具只覆盖了一种布局**。
> 夹具的维度 = (值的多样性) × (容器形态的多样性),缺一维就会漏 bug。

### 5.6 "失败也留下证据"能让第二轮变成修复,而不是又一轮侦察

第一版(失败)落盘的 `lld_census` 直接指出了问题;
第二版(成功)落盘的日志又指出了 `+104` 和构建漂移。
**两次实机都不是白跑的**,因为它们都被设计成"无论如何都有产物"。

## 六、最终数据

| 项 | 值 |
|---|---|
| 数据表 | `generated_stratagem_settings.dl_bin`(磁盘加密,社区 JSON 明文可解) |
| 块类型哈希 | `djb2("StratagemSettings")` = `0x30EB6399` |
| 结构 | `+24` DLArray → `StratagemInfo[count]`,每条 400 字节 |
| 目标记录 | `id @ +4 == 970450596`(`StratagemType_OrbitalLaser`) |
| 实机偏移 | `uses` @ **+80**、`cooldown_duration_success` @ **+104**(运行时反推,不写死) |
| 写入 | `uses: 3 → 0xFFFFFFFF`;`cooldown: 300.0f → 180.0f`(共 8 字节) |
| 校验 | 整表 103 条原版值复现,唯一 argmax + 断层;写前备份整条 400 字节;写完回读;每 5 秒复查 |

## 七、文件

| 路径 | 作用 |
|---|---|
| `mods/orbital_laser_free.lua` | addon 本体(明文);`-- HD2-Addon: mods/dsh/orbital_laser_free` |
| `mods/orbital_laser_free.lua.tmpl` | 模板;`--@@GROUND@@` 由生成脚本填入 103 条原版数值 |
| `analysis/gen_mod.py` | 从明文 JSON 生成 addon 源码 |
| `analysis/dl_strat_harness.lua` | 类型严格的假内存 + ffi 桩 |
| `analysis/test_orbital_laser_free.py` | 8 组功能测试 + 11 组变异测试 |
| `analysis/verify_build.py` | 安装包结构 / 资源哈希 / 归档 round-trip |
| `analysis/01…19_*.py` | 离线侦察过程(表普查、typelib 布局、策略设置解析) |
