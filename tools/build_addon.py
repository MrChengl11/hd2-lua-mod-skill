"""Package a plaintext Lua addon into an Arsenal / HD2MM ZIP.

Mirrors BingusSharedLoader scripts/build_addon.py + scripts/archive.py, but is
self-contained (no game inputs required).

Usage:
    python tools/build_addon.py --name mods/<author>/<mod> --entry <file.lua> \
        --guid <UUID> --display-name "My Mod" --output out/My-Mod.zip
"""
import argparse
import json
import os
import re
import sys
import uuid
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hd2_archive as A

NAME_RE = re.compile(r"mods/[A-Za-z0-9_]+/[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*")


def entry_source(name: str, source: bytes) -> bytes:
    if not NAME_RE.fullmatch(name):
        raise ValueError("name must match mods/<author>/<mod>[ /<sub>], letters/digits/underscore only")
    if name == "mods/codex/loader":
        raise ValueError("mods/codex/loader is reserved")
    if source.startswith((b"\xef\xbb\xbf", b"\x1b")) or b"\0" in source:
        raise ValueError("entry must be plaintext UTF-8 Lua, no BOM, no bytecode")
    source.decode("utf-8")
    marker = ("-- HD2-Addon: " + name + "\n").encode("utf-8")
    if len(marker) > 256:
        raise ValueError("declaration must fit in the first 256 bytes")
    if source.startswith(b"-- HD2-Addon:"):
        line, sep, rest = source.partition(b"\n")
        if not sep or line.rstrip(b"\r") != marker[:-1]:
            raise ValueError("existing declaration does not match the resource name")
        source = rest
    return marker + source


def build_package(name, entry_path, guid, output, display_name=None, extra=None):
    """extra: optional {resource_name: lua_bytes} packaged alongside the entry."""
    body = entry_source(name, open(entry_path, "rb").read())
    resources = {name: A.envelope(body)}
    for extra_name, extra_body in (extra or {}).items():
        resources[extra_name] = A.envelope(entry_source(extra_name, extra_body))
    archive = A.make_archive(resources)

    guid = str(uuid.UUID(guid))
    title = display_name or name
    description = "Requires Bingus Shared Loader v15 or newer / API 1. Enable both and deploy."
    manifest = {
        "Version": 1,
        "Guid": guid,
        "Name": title,
        "Description": description,
        "Options": [{"Name": title, "Description": description, "Include": ["Addon"]}],
    }
    files = {
        "manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
        "Addon/" + A.ARCHIVE_NAME: archive,
        "Addon/" + A.ARCHIVE_NAME + ".stream": b"",
        "Addon/" + A.ARCHIVE_NAME + ".gpu_resources": b"",
    }
    out = os.path.abspath(output)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path, content in sorted(files.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, content)
    return out, archive


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--entry", required=True)
    ap.add_argument("--guid", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--display-name")
    a = ap.parse_args()
    out, archive = build_package(a.name, a.entry, a.guid, a.output, a.display_name)
    print("Built " + out)
    print("  archive bytes: %d" % len(archive))
    print("  resource hash: 0x%016X" % A.resource_hash(a.name))


if __name__ == "__main__":
    main()
