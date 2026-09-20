"""Helldivers 2 Lua patch archive (.patch_N) reader/writer.

Format (little-endian), matching BingusSharedLoader scripts/archive.py:

  offset 0   72-byte header   <III20sQQ24s
                magic   = 0xF0000011
                unk     = 1
                count   = resource count
                20 bytes zero
                total   = total archive size (Q)
                zero    (Q)
                24 bytes zero
  offset 72  32 bytes per type table  <IIQIIII
                0, 0, TYPE, count, 0, 16, 16
  offset 104 80 bytes per resource entry  <7Q6I
                name_hash, TYPE, offset, 0,0,0,0, length, 0, 0, 16, 16, index
  data       resource bodies, each 16-byte aligned:
                u32 body_length, u32 version(=2), body[body_length], pad to 16
"""
import struct

MAGIC = 0xF0000011
TYPE = 0xA14E8DFA2CD117E2          # archive "lua" type marker
ENVELOPE_VERSION = 2
FAMILY = "9ba626afa44a3aa3"
ARCHIVE_NAME = FAMILY + ".patch_0"

_M = (1 << 64) - 1
_MIX = 0xC6A4A7935BD1E995


def resource_hash(name: str) -> int:
    """Seed-zero MurmurHash64A over the UTF-8 resource path."""
    data = name.encode("utf-8")
    value = len(data) * _MIX & _M
    end = len(data) // 8 * 8
    for (word,) in struct.iter_unpack("<Q", data[:end]):
        word = word * _MIX & _M
        word ^= word >> 47
        value = (value ^ (word * _MIX & _M)) * _MIX & _M
    if data[end:]:
        value = (value ^ int.from_bytes(data[end:], "little")) * _MIX & _M
    value ^= value >> 47
    value = value * _MIX & _M
    return value ^ (value >> 47)


def parse(data: bytes):
    """Return (entries, resources) where entries are dicts and resources name->body."""
    magic, unk, count = struct.unpack_from("<III", data, 0)
    total, = struct.unpack_from("<Q", data, 32)
    if magic != MAGIC:
        raise ValueError("invalid archive magic 0x%08X" % magic)
    type_count, = struct.unpack_from("<I", data, 8) if False else (0,)
    types, = struct.unpack_from("<I", data, 4) if False else (0,)
    # real field order: magic, unk(=1), count at 0/4/8
    n_types, res_count = 1, count
    table_start = 72 + 32 * n_types
    entries = []
    for i in range(res_count):
        row = data[table_start + i * 80: table_start + (i + 1) * 80]
        name, rtype, offset, a, b, c, d = struct.unpack_from("<7Q", row, 0)
        length, e, f, g, h, index = struct.unpack_from("<6I", row, 56)
        entries.append(dict(name=name, type=rtype, offset=offset, length=length, index=index))
    out = []
    for e in entries:
        env = data[e["offset"]: e["offset"] + 8]
        body_len, ver = struct.unpack("<II", env)
        body = data[e["offset"] + 8: e["offset"] + 8 + body_len]
        e = dict(e, body_len=body_len, version=ver, body=body)
        out.append(e)
    return dict(total=total, count=res_count, entries=out, size=len(data))


def make_archive_raw(pairs) -> bytes:
    """pairs: iterable of (name_hash, envelope_bytes), already in final order."""
    pairs = list(pairs)
    if not pairs:
        raise ValueError("an archive needs at least one resource")
    count = len(pairs)
    offset = (104 + 80 * count + 15) & ~15
    entries, body = bytearray(), bytearray(offset)
    for index, (name_hash, resource) in enumerate(pairs):
        entries += struct.pack("<7Q6I", name_hash, TYPE, offset,
                               0, 0, 0, 0, len(resource), 0, 0, 16, 16, index)
        body += resource
        body += b"\0" * (-len(body) % 16)
        offset = len(body)
    header = struct.pack("<III20sQQ24s", MAGIC, 1, count, b"", offset, 0, b"")
    types = struct.pack("<IIQIIII", 0, 0, TYPE, count, 0, 16, 16)
    body[:104 + len(entries)] = header + types + entries
    return bytes(body)


def make_archive(resources: dict) -> bytes:
    """resources: {resource_name: envelope_bytes} (envelope = u32 len + u32 2 + body)."""
    return make_archive_raw((resource_hash(n), r) for n, r in sorted(resources.items()))


def envelope(body: bytes) -> bytes:
    return struct.pack("<II", len(body), ENVELOPE_VERSION) + body
