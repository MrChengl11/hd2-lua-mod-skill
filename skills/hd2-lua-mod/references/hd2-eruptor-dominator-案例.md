# 案例:R-36 爆裂铳的射弹 -> JAR-5 主宰

> 游戏构建 24826606 / exe 1.8.45317.0
> exe SHA-256 `A09FF52663E73B94FB0CAC0DCB5BA84FFD10ECF44F74A8921AC66AF923988CC3`

---

## 一、武器身份

| 武器 | 游戏内部名 | 资源 ID | 弹药名 |
|---|---|---|---|
| JAR-5 主宰 | `jet_rifle` | `0x80F1A156D9FA1E36` | `15x100mm STANDARD ROCKET` |
| R-36 爆裂铳 | `jet_rifle_phoenix` | `0x8DC91F277C6096EE` | `15x100mm HIGH EXPLOSIVE` |

判定依据:各自的 `.package.json` 里引用了独占的音频包
(`content/audio/wep_jar5_dominator` / `wep_jpr_eruptor`)。

**关键认知:两把枪共用同一款 15x100mm 弹壳**,质量/初速/阻力/重力/减速**完全相同**,
差别只在**弹头装药**和**爆炸**。它们的 bones/physics/state_machine 资源也是共用的。

---

## 二、数据结构(偏移已与游戏 typelib 逐项核对)

### ProjectileInfo —— 272 字节 x 343 条
| 偏移 | 类型 | 字段 |
|---|---|---|
| +0 | u32 | ProjectileType(**全表唯一**) |
| +4/+8/+12 | u32 | NameUpper / NameCased / ShortName(字符串表 id) |
| +16 | u64 | HudIcon |
| +24 | f32 | Calibre |
| +28 | u32 | NumProjectiles |
| +32 | f32 | Speed |
| +36 | f32 | Mass |
| +40 | f32 | Drag |
| +44 | f32 | GravityMultiplier |
| +56 | f32 | LifeTime |
| +60 | u32 | **DamageInfoType** -> 指向 DamageSettings |
| +64 | f32 | PenetrationSlowdown |
| +72 | u64 | ParticleThrusterEffectPath |
| +96 / +104 / +112 | u64 | 拖尾 / 消散 / 崩解 粒子 |
| +120 | u64 | HitDirectionHintEffect |
| +128 | u64 | ProjectileUnitPath |
| +136 | f32 | ExplosionThresholdAngle |
| +144 | u32 | **ExplosionTypeOnImpact**(枚举值!) |
| +148 / +152 | f32 | ExplosionProximity / ExplosionDelay |
| +156 | u32 | **ExplosionTypeExpire**(枚举值!) |
| +160 | f32 | ArmingDistance |
| +164 | f32 | DecalSize |

### ExplosionInfo —— 152 字节 x 413 条
| 偏移 | 类型 | 字段 |
|---|---|---|
| +0 | u32 | ExplosionType(**枚举值,不是数组下标**) |
| +4 | u32 | DamageType -> DamageSettings |
| +16 / +20 / +24 / +28 | f32 | InnerRadius / OuterRadius / StaggerRadius / ConeAngle |
| +56 | u64 | ParticleEffectPath(**爆炸外观**) |
| +64 | u32 | AudioEvent |
| +80 | u32 | **NumShrapnelProjectiles** |
| +84 | u32 | **ShrapnelProjectileType** |

### DamageInfo —— 76 字节 x 639 条
| 偏移 | 类型 | 字段 |
|---|---|---|
| +0 | u32 | DamageInfoType |
| +4 | i32 | **Damage**(注意:不是 +12) |
| +8 | i32 | DurableDamage |
| +12 | u32 x4 | ArmorPenetrationPerAngle |
| +28 / +32 / +36 | u32 | DemolitionStrength / ForceStrength / ForceImpulse |

**踩坑**:最初把 +12 的「穿甲角度数组」当成伤害值来解,全是 denormal 浮点,白折腾很久。

---

## 三、用 Wiki 数字锁定(决定性一步)

Wiki(helldivers.wiki.gg)的 "Detailed Weapon Statistics" 给出精确值,逐项匹配数据表:

### 爆裂铳撞击爆炸
| 参数 | Wiki | 爆炸枚举 155 |
|---|---|---|
| 伤害 | 225 | 225 ✅ |
| 破片数 | 30 | 30 ✅ |
| 内半径 | 4 m | 4.0 ✅ |
| 外半径 | 7 m | 7.0 ✅ |
| 拆迁力 | 20 | 20 ✅ |
| 硬直力 | 35 | 35 ✅ |
| 推力 | 40 | 40 ✅ |
| 穿甲 | Medium | 3 ✅ |

**413 条爆炸里只有这一条 8 项全中。**

### 爆裂铳破片弹 = 记录 296(ProjectileType 200)
mass 100g / 30 m/s / drag 40% / gravity 100% / 伤害 110 / Medium 穿甲 —— 与 Wiki 的 `SHRAPNEL_P` 逐项一致。

### 爆裂铳弹头 = 记录 261(ProjectileType 40,名字 `15x100 mm DETONANTE`)
mass 100 / speed 180 / drag 0 / gravity 0.30 / slowdown 0.25 / damageType 144(230·115·Heavy)/ 爆炸 155。

### 主宰自己的弹头 = 记录 258(ProjectileType 177,名字 `FOGUETE 15x100 mm PADRÃO`)
mass 100 / speed 180 / drag 0 / gravity 0.30 / slowdown 0.25 / damageType 148(275·90·Medium)。
与 Wiki 的 JAR-5 数据**一字不差** —— 证明定位正确。

---

## 四、最终实现

把记录 261 整条拷到记录 258,**保留目标自己的 Type 值**(维持全表唯一)。

改动前只需校验:表签名、`size==93312`、`count==343`、目标记录的 Type==177。

---

## 五、走过的弯路(按时间顺序)

1. **以为可以换素材** —— 查完武器 `.package.json` 才发现里面只有模型/动画/粒子,没有任何伤害/弹道字段。
2. **以为资源补丁能做** —— 检查用户已装的 146 个 mod 文件,目标目录 100% 落在 `data\`,没有进 `data\game\` 的。`.dl_bin` 不在 mod 管线范围内。
3. **磁盘直接读 `.dl_bin`** —— 加密,解不开。
4. **自检测(两次)** —— 扫描器找到自己构造的模式串。第一次是因为签名串在 Lua 堆;第二次是 ffi 缓冲里的 64 位哈希。
5. **64 位哈希精度丢失** —— 显示成 `...FA2000` 才发现。搜索模式串全程错。
6. **一次扫 64MB 把游戏卡在加载界面** —— 改成 `os.clock()` 时间切片。
7. **误以为射弹表不在内存** —— 其实是误报让扫描提前停了。加校验后才发现它一直 mmap 在那儿。
8. **把「枚举值」当成「数组下标」** —— 查索引 371 得空,查枚举值 371 才对。
9. **选错射弹记录** —— 先用空爆弹(会延迟爆炸),后用 8x60mm(是别的枪的弹)。
10. **只用 `+84`(破片类型)没看 `+80`(破片数量)** —— 数量为 0 就是不放破片。
11. **`table.concat` 把字节数字转成十进制文本** —— 会污染相邻记录,离线测试抓到。
12. **弹道其实是多余的** —— 两把枪弹道本来就一样,只要换弹头装药和爆炸。

---

## 六、离线测试抓到的真实 bug

| bug | 后果 | 抓法 |
|---|---|---|
| `ReadProcessMemory` 少 `ffi.cast` | 扫描全线失败 | 让测试桩要求指针必须是 cast 出来的对象 |
| `table.concat` 混入数字 | 写入 ~700 字节 ASCII,污染相邻记录 | 加 `#payload == REC_SIZE` 断言 |
| `payload` 定义前引用 | 逻辑失效 | 逐行走查 |
| `#state.run_list` 对 nil 取长度 | 直接报错 | 仿真运行触发 |

**变异测试**:把 bug 改回去,确认测试**确实失败**,否则测试无效。

---

## 七、本机环境

- 游戏:`<Steam库>\steamapps\common\Helldivers 2`
- mod 管理器:HD2 Mod Manager,状态文件 `data/activation-state.json`(记录全部已启用 mod 的来源路径)
- 侦察产物基线:`_baseline_build24826606/`(游戏更新后对照用)
