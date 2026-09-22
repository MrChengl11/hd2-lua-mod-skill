# hd2-lua-mod

An agent skill for building **Helldivers 2 "Lua injection" mods** — the kind that load inside
the running game through **Bingus Shared Loader** and use **LuaJIT FFI to read and write game
process memory** at runtime.

This is **not a mod**. It is a set of instructions for an AI coding agent, plus the offline
tooling that makes the workflow practical.

> 中文说明见 [README.zh-CN.md](README.zh-CN.md).

---

## What it covers

Helldivers 2 injection mods are a different discipline from ordinary asset-replacement mods:
you are not swapping textures out of `data/`, you are finding a data table in the running
process and changing it. The skill encodes the whole loop:

- **Offline first** — the game's data tables are encrypted on disk, but a **plaintext mirror
  ships inside FileDiver's Go module**, along with the game's own type library. Most of the
  work can be finished before you ever launch the game.
- **Locating data tables** — the `LDLD` block format, the two instance layouts, and the two
  different hash functions (type hashes are **djb2**; resource hashes are **MurmurHash64A**).
- **Read-only recon** — how to write a recon addon that never writes memory, and why it has to
  survive its own mistakes (the loader has no hot-reload).
- **Runtime patching** — the validate → back up → `VirtualProtect` → write → read-back →
  re-check loop that a patch addon should follow.
- **Offline simulation** — a type-strict fake-FFI harness for `lupa`, plus **mutation testing**,
  which between them caught real bugs before they ever reached the game.

### Four worked case studies

| Case | What it does |
|---|---|
| [Eruptor round on the Dominator](skills/hd2-lua-mod/references/hd2-eruptor-dominator-案例.md) | Copies the R-36 Eruptor's projectile record onto the JAR-5 Dominator |
| [Double Leveller](skills/hd2-lua-mod/references/hd2-leveller-double-案例.md) | Makes one EAT-411 Leveller call-in drop **two** launchers — a **64-byte** patch, found entirely offline and verified in one game session |
| [Orbital Laser: unlimited uses](skills/hd2-lua-mod/references/hd2-orbital-laser-案例.md) | Removes the per-mission use cap and cuts the cooldown 300 → 180 s. Started from a **community-decoded JSON**; hit the "DLArray is a pointer in memory, an offset on disk" trap and a scanner that wrecked frame pacing; ends with **whole-table self-calibration**, which overturned the offset derived offline |
| [Eagle Carpet Bombing Run](skills/hd2-lua-mod/references/hd2-carpet-bomb-案例.md) | Restores a stratagem that **never shipped**, whose delivery vehicle was deleted from the game. Seven in-game iterations: wrong Lua runtime in the simulator, a field that is a **bit-packed `byte`**, the fact that the **loadout list's gate is not in the game data** (so you must hijack an unlocked slot), inherited mechanics from the hijacked slot, card values being *calibrated* numbers, recycled enum indices, and payload-array semantics. **Read this first if your goal is "make hidden content visible to players"** |

### Where to get the data

FileDiver's `datalibrary/` covers about 20 of the game's **57** `generated_*.dl_bin` files.
For the rest, start with the community's decoded JSON —
[shalzuth/HelldiversData](https://github.com/shalzuth/HelldiversData) (`data/settings/`, `data/components/`,
`data/entities/`, `data/enums/`, `data/translations/`). See SKILL.md §0.

---

## Install

Copy `skills/hd2-lua-mod/` into your agent's skills directory, for example:

```bash
git clone https://github.com/MrChengl11/hd2-lua-mod-skill
cp -r hd2-lua-mod/skills/hd2-lua-mod ~/.dsh/skills/          # DeepSeek Harness / DSH
# or wherever your agent reads skills from
```

The skill is self-contained: `SKILL.md` plus a `references/` folder. The agent loads it when
the task matches, so you normally just describe what you want to change.

## Prerequisites

| Thing | Needed for |
|---|---|
| **Helldivers 2** (Steam) + **Bingus Shared Loader v15+** + **HD2 Mod Manager** / **Arsenal** | loading and running addons |
| **Python 3.10+** | offline analysis, addon packaging, tests |
| **Go 1.21+** + **FileDiver source** | regenerating the typelib JSON (optional but recommended) |
| **`pip install lupa`** | the offline simulation + mutation tests |

## Getting the game data (do this first)

The plaintext mirror is what makes this workflow fast. FileDiver embeds it in its Go module:

```bash
go mod download github.com/xypwn/filediver
# -> <GOMODCACHE>/github.com/xypwn/filediver@<ver>/datalibrary/
#      generated_*.dl_bin        plaintext data tables (incl. the 45 MB entities blob)
#      dl_library.dl_typelib     the game's own type library
#      *.go                      per-component field names and comments
```

Then turn the type library into JSON so you can look up field offsets by name:

```bash
# drop tools/dump_typelib/ into the FileDiver source tree as cmd/dump_typelib/
go run ./cmd/dump_typelib -o typelib_all.json     # 1177 types
```

`typelib_all.json` maps type name → `size`, `alignment` and `members[].offset/size/type`.
That is the authoritative source for offsets — better than any community struct.

> The game install's own `data/game/generated_*.dl_bin` is **encrypted** (entropy ≈ 7.9998
> bits/byte, zero `LDLD` occurrences in 45 MB). It cannot be edited, and it is not part of the
> mod pipeline anyway.

## Tools

| Tool | What it does |
|---|---|
| `tools/hd2_archive.py` | read/write the `.patch_N` archive format |
| `tools/build_addon.py` | package a plaintext `.lua` addon into an installable ZIP |
| `tools/inspect_patch.py` | dump an archive's structure + round-trip self-check |
| `tools/dump_typelib/main.go` | export `dl_library.dl_typelib` to JSON |
| `skills/hd2-lua-mod/references/ldld.py` | `LDLD` table parser (find a table by type name, slice records) |

```bash
pip install lupa
python verify.py                                     # self-test the checkout
python verify.py generated_entities.dl_bin mod.zip   # ...also against real data
python tools/inspect_patch.py addon.patch_0          # sanity-check a packaged addon
python skills/hd2-lua-mod/references/ldld.py generated_entities.dl_bin HellpodRackComponentData
```

## Scope and limitations

- **It is not for asset mods.** Replacing models, textures or sounds goes through the normal
  `data/` pipeline; this skill is about runtime memory.
- **Game updates break everything.** Type hashes, table sizes and layouts change between
  builds. The skill insists on failing safely (write nothing, log why) rather than guessing.
- **Client-side only.** HD2 is peer-to-peer and partly host-authoritative, so a locally
  patched object may not be visible to other players.
- **Anti-cheat applies.** HD2 ships nProtect GameGuard. The skill's own rule is: never read
  game memory from an external process; stay inside the game with a read-only addon.

## Credits

- **[Bingus Shared Loader](https://github.com/CowboyBingus)** by CowboyBingus — the addon
  framework every mod built with this skill depends on.
- **[FileDiver](https://github.com/xypwn/filediver)** by xypwn — the data-library extracts and
  the generated component definitions this workflow reads.
- Weapon and stratagem numbers cross-checked against the **Helldivers Wiki**.
- Built on the file-format research of the Helldivers 2 modding community.

## License

MIT — see [LICENSE](LICENSE).