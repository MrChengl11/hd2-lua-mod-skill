# -*- coding: utf-8 -*-
"""HD2 离线数据读取层:typelib 布局 + entities blob 组件表。"""
import struct, os, re, json, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF  = os.path.join(ROOT, "ref")

BLOB = None; TL = None; H2N = None; N2H = None; NAMES = None
INSTANCES = None; _LAYOUT = {}; _ENT = None; _E = {}

def dlsum(name):
    r = 5381
    for ch in name:
        r = (r * 33 + ord(ch)) & 0xFFFFFFFF
    return (r - 5381) & 0xFFFFFFFF

def load():
    global BLOB, TL, H2N, N2H, NAMES, INSTANCES
    if BLOB is not None: return
    BLOB = open(os.path.join(REF, "generated_entities.dl_bin"), "rb").read()
    TL = json.load(open(os.path.join(REF, "typelib_all.json"), encoding="utf-8"))
    H2N = {}
    for line in open(os.path.join(REF, "typelib_names.tsv"), encoding="utf-8"):
        p = line.rstrip("\n").split("\t")
        if len(p) >= 3: H2N[int(p[0], 16)] = p[2]
    N2H = {}
    for h, n in H2N.items(): N2H.setdefault(n, h)
    NAMES = {}
    for line in open(os.path.join(REF, "asset_list.txt"), encoding="utf-8", errors="replace"):
        m = re.match(r"^(.*?),\s*0x([0-9a-f]{16})\.0x([0-9a-f]{16})", line.strip())
        if m: NAMES.setdefault(int(m.group(2), 16), m.group(1).strip())
    INSTANCES = []
    i = BLOB.find(b"LDLD")
    while i >= 0:
        if i + 16 <= len(BLOB):
            v, t, s = struct.unpack_from("<III", BLOB, i + 4)
            if v == 1 and t != 0 and 0 < s < 100_000_000: INSTANCES.append((i, t, s))
        i = BLOB.find(b"LDLD", i + 1)
    INSTANCES.sort()

def type_name(h):
    if H2N is None: load()
    return H2N.get(h) or ("0x%08X" % h)

def desc(name):
    if TL is None: load()
    d = TL.get(name)
    if d: return d
    if name.endswith("Data"):
        d = TL.get(name[:-4])
        if d: return d
    return None

def wrappers(name):
    """如果是 XxxComponentData 包装体,返回 (index_type, record_type)"""
    d = desc(name)
    if d and len(d["members"]) >= 2 and d["members"][0]["type"] == "ComponentIndexData":
        return d["members"][0]["type"], d["members"][1]["type"]
    return None, None

def record_size(type_hash):
    """LDLD 块类型 -> 单条记录字节数"""
    if type_hash in _E: return _E[type_hash]
    n = type_name(type_hash)
    _, rt = wrappers(n)
    if rt and rt in TL:
        _E[type_hash] = TL[rt]["size"]
        return _E[type_hash]
    d = desc(n)
    _E[type_hash] = d["size"] if d else None
    return _E[type_hash]

def detect_layout(magic, size, E):
    base = magic + 24
    best = None
    for A in range(1, size // 16):
        rem = size - A * 16
        if rem <= 0: break
        if rem % E: continue
        N = rem // E
        if N <= 0: continue
        ok = True; mx = -1; used = 0
        for k in range(A):
            hv, ix, pad = struct.unpack_from("<QII", BLOB, base + k * 16)
            if pad != 0: ok = False; break
            if hv == 0:
                if ix != 0: ok = False; break
            else:
                if ix >= N: ok = False; break
                used += 1
                if ix > mx: mx = ix
        if not ok: continue
        score = (abs(A - 2 * N), max(0, N - 1 - mx), -used)
        if best is None or score < best[0]: best = (score, A, N)
    if best is None: return None
    return best[1], best[2]

def layout(magic):
    if magic in _LAYOUT: return _LAYOUT[magic]
    v, t, s = struct.unpack_from("<III", BLOB, magic + 4)
    E = record_size(t)
    r = detect_layout(magic, s, E) if E else None
    if r: r = (r[0], r[1], E)
    _LAYOUT[magic] = r
    return r

def build_entities():
    global _ENT
    if _ENT is not None: return _ENT
    load()
    ent = collections.defaultdict(dict)
    for magic, t, s in INSTANCES:
        L = layout(magic)
        if not L: continue
        A, N, E = L
        base = magic + 24
        recbase = base + A * 16
        name = type_name(t)
        for k in range(A):
            hv, ix, pad = struct.unpack_from("<QII", BLOB, base + k * 16)
            if hv == 0: continue
            rec = BLOB[recbase + ix * E: recbase + (ix + 1) * E]
            if len(rec) == E: ent[hv][name] = rec
    _ENT = ent
    return ent

def ent_get(h): return build_entities().get(h) or {}
def ent_has(h): return h in build_entities()
def ent_count(): return len(build_entities())

def nm(h):
    if NAMES is None: load()
    return NAMES.get(h) or ("0x%016X" % h)

def fields(rec, name):
    """把一条记录解成 {字段名: 值};字节串字段保留 hex"""
    n = name
    d = desc(n)
    _, rt = wrappers(n)
    if rt:
        n = rt; d = TL.get(rt)
    if not d: return None
    out = {}
    for m in d["members"]:
        off, sz = m["offset"], m["size"]
        tf = m["type_flags"]; atom = tf["atom"]; st = tf["storage"]
        if atom == "POD" and st in ("F32", "F64"):
            out[m["name"]] = struct.unpack_from("<f" if st == "F32" else "<d", rec, off)[0]
        elif atom == "POD" and st in ("U8","U16","U32","U64","I8","I16","I32","I64"):
            fmt = {"U8":"<B","U16":"<H","U32":"<I","U64":"<Q","I8":"<b","I16":"<h","I32":"<i","I64":"<q"}[st]
            out[m["name"]] = struct.unpack_from(fmt, rec, off)[0]
        elif atom == "POD" and st == "BOOL":
            out[m["name"]] = rec[off]
        else:
            out[m["name"]] = rec[off:off+sz].hex()
    return out

def dump_type(type_hash):
    n = type_name(type_hash)
    d = desc(n); it, rt = wrappers(n)
    print("## %s (0x%08X)" % (n, type_hash))
    if it:
        print("   包装体 -> 索引=%s  记录=%s(size=%s)" % (it, rt, TL[rt]["size"] if rt in TL else "?"))
        d = TL.get(rt)
    if not d:
        print("   (无布局)"); return
    print("   size=%d members=%d" % (d["size"], len(d["members"])))
    for m in d["members"]:
        tf = m["type_flags"]
        print("   +%-5d size=%-4d %-8s %-14s %-38s %s" % (
            m["offset"], m["size"], tf["atom"], tf["storage"], m["type"], m["name"]))

if __name__ == "__main__":
    load()
    print("instances=%d types=%d assets=%d" % (len(INSTANCES), len(TL), len(NAMES)))
    for a in sys.argv[1:]:
        print(); dump_type(int(a, 16))
