# hd2-lua-mod

一套给 **AI agent** 用的技能:**制作/修改《绝地潜兵2》「Lua 注入型」mod** ——
也就是靠 **Bingus Shared Loader** 载入游戏、运行时用 **LuaJIT FFI 读写游戏进程内存**的那一类。

**这不是一个 mod**,而是一份写给 AI 编码 agent 的工作流说明,外加让它跑得动的离线工具。

> English: [README.md](README.md)

---

## 覆盖什么

注入型 mod 和普通素材 mod 是两回事:你不是在替换 `data/` 里的贴图,而是在**运行中的进程里
找到一张数据表并改它**。这套技能把整条链路固化下来:

- **离线优先** —— 游戏的数据表在磁盘上是加密的,但 **FileDiver 的 Go 模块里打包着一份明文镜像**,
  连游戏自带的类型库一起。**大半的活根本不用开游戏。**
- **定位数据表** —— `LDLD` 块格式、两种实例布局、以及两个容易混淆的哈希函数
  (**类型哈希 = djb2**,**资源名哈希 = MurmurHash64A**)。
- **只读侦察** —— 怎么写出一个绝不写内存的侦察 addon,以及为什么它必须"扛得住自己出错"
  (Loader 没有热重载,改一行就要关游戏重开)。
- **运行时补丁** —— 校验 → 备份 → `VirtualProtect` → 写入 → 回读 → 复查 的标准套路。
- **离线仿真** —— 类型严格的假 FFI 环境(`lupa`)+ **变异测试**,这两样在上机前抓到过真 bug。

### 三个完整案例

| 案例 | 做了什么 |
|---|---|
| [爆裂铳射弹套主宰](skills/hd2-lua-mod/references/hd2-eruptor-dominator-案例.md) | 把 R-36 爆裂铳的射弹记录整体拷到 JAR-5 主宰上 |
| [双倍荡平者](skills/hd2-lua-mod/references/hd2-leveller-double-案例.md) | 让 EAT-411 荡平者一次空投**两根** —— **64 字节**的补丁,全程离线算出,一次实机验证通过 |
| [轨道激光取消次数限制](skills/hd2-lua-mod/references/hd2-orbital-laser-案例.md) | 取消每次任务的次数上限 + 冷却 300 → 180 秒。从**社区解好的明文 JSON** 起步;踩中「DLArray 在内存里是指针、在文件里是偏移」和「扫描器拖垮帧率」两个坑;最后靠**整表复现反推偏移**,并推翻了自己在离线阶段的推导 |

### 数据从哪来

FileDiver 的 `datalibrary/` 只覆盖游戏那 **57 个** `generated_*.dl_bin` 里的约 20 个。
其余的先看社区解好的明文 JSON:[shalzuth/HelldiversData](https://github.com/shalzuth/HelldiversData)
(`data/settings/`、`data/components/`、`data/entities/`、`data/enums/`、`data/translations/`)。
细节见 SKILL.md 第 0 节。

---

## 安装

把 `skills/hd2-lua-mod/` 整个复制到你的 agent 的技能目录,例如:

```bash
git clone https://github.com/MrChengl11/hd2-lua-mod-skill
cp -r hd2-lua-mod/skills/hd2-lua-mod ~/.dsh/skills/          # DeepSeek Harness / DSH
# 或者你所用 agent 读取技能的任意目录
```

技能是自包含的:`SKILL.md` + `references/`。任务匹配时 agent 会自动加载,
所以你平时只要**直接描述想改什么**就行。

## 前置条件

| 需要 | 用途 |
|---|---|
| **绝地潜兵2**(Steam)+ **Bingus Shared Loader v15+** + **HD2 Mod Manager** / **Arsenal** | 载入并运行 addon |
| **Python 3.10+** | 离线分析、打包、测试 |
| **Go 1.21+** + **FileDiver 源码** | 重新生成 typelib JSON(可选但强烈建议) |
| **`pip install lupa`** | 离线仿真 + 变异测试 |

## 先拿到游戏数据(第一步)

明文镜像是这套流程快的原因。FileDiver 把它嵌在自己的 Go 模块里:

```bash
go mod download github.com/xypwn/filediver
# -> <GOMODCACHE>/github.com/xypwn/filediver@<ver>/datalibrary/
#      generated_*.dl_bin        明文数据表(含 45 MB 的实体 blob)
#      dl_library.dl_typelib     游戏自带的类型库
#      *.go                      每个组件的字段名与注释
```

再把类型库导成 JSON,就能按名字查字段偏移:

```bash
# 把 tools/dump_typelib/ 放进 FileDiver 源码树,作为 cmd/dump_typelib/
go run ./cmd/dump_typelib -o typelib_all.json     # 1177 个类型
```

`typelib_all.json` 是「类型名 → size / alignment / members[].offset/size/type」。
**查偏移以它为准**,比任何社区结构体都权威。

> 游戏安装目录里的 `data/game/generated_*.dl_bin` **是加密的**(熵 ≈ 7.9998 bit/byte,
> 45 MB 里 `LDLD` 出现 **0** 次)。改不了,也不在 mod 管线里。

## 工具

| 工具 | 作用 |
|---|---|
| `tools/hd2_archive.py` | 读写 `.patch_N` 归档格式 |
| `tools/build_addon.py` | 把明文 `.lua` 打包成可安装 ZIP |
| `tools/inspect_patch.py` | 查看归档结构 + round-trip 自检 |
| `tools/dump_typelib/main.go` | `dl_library.dl_typelib` → JSON |
| `skills/hd2-lua-mod/references/ldld.py` | `LDLD` 表解析器(按类型名找表、切记录) |

```bash
pip install lupa
python verify.py                                     # 自检:确认这个 checkout 能用
python verify.py generated_entities.dl_bin mod.zip   # 再拿真实数据跑一遍
python tools/inspect_patch.py addon.patch_0          # 检查打包结果
python skills/hd2-lua-mod/references/ldld.py generated_entities.dl_bin HellpodRackComponentData
```

## 边界与限制

- **不适用于素材 mod。** 换模型/贴图/音效走常规 `data/` 管线,这套技能只管运行时内存。
- **游戏更新会失效。** 类型哈希、表大小、布局都可能变。技能要求**安全失败**
  (不写、记原因),而不是猜着写。
- **客户端本地改动。** HD2 是 P2P 且部分逻辑主机权威,本地多出来的东西**别的玩家未必看得见**。
- **有反作弊。** 游戏带 nProtect GameGuard。技能里明确写了:**
  不要从外部进程读游戏内存**,只在游戏内用只读 addon。

## 致谢

- **[Bingus Shared Loader](https://github.com/CowboyBingus)**(CowboyBingus)—— 所有用这套技能做出来的 mod 都依赖它。
- **[FileDiver](https://github.com/xypwn/filediver)**(xypwn)—— 明文数据表与生成的组件定义。
- 武器/战备数值用 **Helldivers Wiki** 交叉验证。
- 建立在 HD2 modding 社区的文件格式研究之上。

## 许可

MIT —— 见 [LICENSE](LICENSE)。