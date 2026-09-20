# -*- coding: utf-8 -*-
"""LDLD 数据表解析器 —— 绝地潜兵2 的运行时数据表就是这种块。

用法:

    from ldld import dlsum, find_instance, instance_header, read_records, iter_instances

    blob = open("generated_entities.dl_bin", "rb").read()
    magic = find_instance(blob, "HellpodRackComponentData")
    hdr   = instance_header(blob, magic)
    print(hdr)                       # {'version':1,'type':0xA98BB156,'size':42568,...}
    recs  = read_records(blob, magic, hdr["data_off"], 568, 71)

要点(实测确认):

* **类型哈希 = djb2**(见 dlsum)。资源名哈希是 MurmurHash64A,是另一套,别混。
* 数据起点**因文件而异**:设置表在 magic+40,实体 blob 在 magic+24。
  用 DATA_OFF_BY_KIND 里的候选值解一条记录再看值域,不要猜。
* 实例前面还有 4 字节前缀(常是类型哈希自己),所以 magic 可能坐在分配区 +4 处。
  读取时要从 region/分配区起点钳一下,否则 ReadProcessMemory 会返回 0 字节。
"""
import struct

MAGIC = b"LDLD"

# 数据起点候选(相对 LDLD 魔数)。解一条记录、看字段是否落在合理值域来选。
DATA_OFF_BY_KIND = {
    "settings": 40,   # generated_*_settings.dl_bin
    "entities": 24,   # generated_entities.dl_bin
}
DATA_OFF_CANDIDATES = (24, 40, 28, 36, 32)


def dlsum(name):
    """类型哈希: "HellpodRackComponentData" -> 0xA98BB156"""
    r = 5381
    for ch in name:
        r = (r * 33 + ord(ch)) & 0xFFFFFFFF
    return (r - 5381) & 0xFFFFFFFF


def signature(type_name):
    """内存/文件里定位该表用的字节串: LDLD + 版本1 + 类型哈希(LE)"""
    return MAGIC + struct.pack("<II", 1, dlsum(type_name))


def find_instance(blob, type_name, start=0):
    """返回 LDLD 魔数在 blob 中的偏移;找不到返回 -1。"""
    return blob.find(signature(type_name), start)


def iter_instances(blob, start=0, limit=None):
    """遍历 blob 里所有 LDLD 实例 -> (magic_offset, type32, size)"""
    out = []
    i = blob.find(MAGIC, start)
    while i >= 0:
        if i + 16 <= len(blob):
            ver, typ, size = struct.unpack_from("<III", blob, i + 4)
            if ver == 1 and typ != 0:
                out.append((i, typ, size))
                if limit is not None and len(out) >= limit:
                    return out
        i = blob.find(MAGIC, i + 1)
    return out


def instance_header(blob, magic, data_off=None):
    """读实例头。data_off 给 None 时按两种已知布局各试一次,返回能用的那个。"""
    ver, typ, size = struct.unpack_from("<III", blob, magic + 4)
    is64 = blob[magic + 16]
    hdr = {"magic": magic, "version": ver, "type": typ, "size": size, "is64": is64,
           "u32_before_magic": struct.unpack_from("<I", blob, magic - 4)[0] if magic >= 4 else None}
    if data_off is None:
        hdr["data_off_candidates"] = list(DATA_OFF_CANDIDATES)
    else:
        hdr["data_off"] = data_off
    return hdr


def read_records(blob, magic, data_off, record_size, count):
    """按固定记录大小切记录。data_off 是相对 magic 的偏移。"""
    base = magic + data_off
    end = base + record_size * count
    if end > len(blob):
        raise ValueError("需要 %d 字节但只有 %d" % (end - base, len(blob) - base))
    return [blob[base + i * record_size: base + (i + 1) * record_size] for i in range(count)]


def looks_sane(records, checks):
    """checks: [(offset, 'u32'|'u64'|'f32', low, high), ...] —— 全部命中才认为布局对。

    典型用法(射弹表): [(0,'u32',1,1<<20), (28,'u32',1,100), (32,'f32',1,5000)]
    """
    for rec in records:
        for off, kind, lo, hi in checks:
            if kind == "u32":
                v = struct.unpack_from("<I", rec, off)[0]
            elif kind == "u64":
                v = struct.unpack_from("<Q", rec, off)[0]
            else:
                v = struct.unpack_from("<f", rec, off)[0]
                if v != v:      # NaN
                    return False
            if not (lo <= v <= hi):
                return False
    return True


def pick_data_off(blob, magic, record_size, count, checks):
    """在候选起点里挑第一个能通过 looks_sane 的。"""
    for off in DATA_OFF_CANDIDATES:
        try:
            recs = read_records(blob, magic, off, record_size, count)
        except ValueError:
            continue
        if looks_sane(recs, checks):
            return off, recs
    return None, None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print(__doc__)
        print("用法: python ldld.py <blob.dl_bin> <TypeName>")
        raise SystemExit(0)
    blob = open(sys.argv[1], "rb").read()
    name = sys.argv[2]
    m = find_instance(blob, name)
    print("type hash 0x%08X" % dlsum(name))
    if m < 0:
        print("NOT FOUND in", sys.argv[1])
    else:
        print("magic at", m)
        print(instance_header(blob, m))
    print("\n该 blob 里所有实例:")
    for off, typ, size in iter_instances(blob)[:40]:
        print("  +%-10d type=0x%08X size=%d" % (off, typ, size))
