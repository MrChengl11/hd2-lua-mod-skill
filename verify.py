# -*- coding: utf-8 -*-
"""Self-test: check that a fresh clone can actually use the bundled tools.

    python verify.py [generated_entities.dl_bin] [some-mod.zip]

Both arguments are optional; missing pieces are skipped with a note.
Get the .dl_bin from FileDiver (see README "Getting the game data").
"""
import os, sys, zipfile, tempfile
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ok = True


def check(label, cond, extra=""):
    global ok
    ok = ok and bool(cond)
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  " + extra) if extra else ""))


print("1. imports")
import importlib.util
spec = importlib.util.spec_from_file_location(
    "ldld", os.path.join(HERE, "skills", "hd2-lua-mod", "references", "ldld.py"))
ldld = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ldld)
sys.path.insert(0, os.path.join(HERE, "tools"))
import hd2_archive as A
check("ldld.py loads", True)
check("hd2_archive.py loads", True)

print("\n2. type hash")
check("dlsum('HellpodRackComponentData') == 0xA98BB156",
      ldld.dlsum("HellpodRackComponentData") == 0xA98BB156,
      "got 0x%08X" % ldld.dlsum("HellpodRackComponentData"))
check("dlsum('ProjectileSettings') == 0xBD4042C2",
      ldld.dlsum("ProjectileSettings") == 0xBD4042C2)

print("\n3. resource hash")
check("resource_hash('mods/dsh/double_leveller') == 0xB26F455725B61AEB",
      A.resource_hash("mods/dsh/double_leveller") == 0xB26F455725B61AEB,
      "got 0x%016X" % A.resource_hash("mods/dsh/double_leveller"))

if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    print("\n4. LDLD table parse")
    blob = open(sys.argv[1], "rb").read()
    m = ldld.find_instance(blob, "HellpodRackComponentData")
    check("found HellpodRackComponentData", m >= 0, "magic at %d" % m)
    if m >= 0:
        hdr = ldld.instance_header(blob, m)
        check("declared size == 42568", hdr["size"] == 42568, "got %s" % hdr["size"])
        recs = ldld.read_records(blob, m, 24 + 2240, 568, 71)
        check("71 rack records", len(recs) == 71)
        lev = [i for i, r in enumerate(recs)
               if ldld.struct.unpack_from("<Q", r, 0)[0] == 0x7617642765AC38C7]
        check("the Leveller rack is #26", lev == [26], "got %s" % lev)
        if lev:
            check("its SpawnPayloadSize == 2",
                  ldld.struct.unpack_from("<I", recs[lev[0]], 556)[0] == 2)
else:
    print("\n4. LDLD table parse -- SKIPPED (pass a generated_entities.dl_bin)")

if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
    print("\n5. .patch_N archive parse")
    data = open(sys.argv[2], "rb").read()
    if data[:2] == b"PK":                       # it is a manager ZIP: dig out the archive
        z = zipfile.ZipFile(sys.argv[2])
        data = z.read("Addon/" + A.ARCHIVE_NAME)
    info = A.parse(data)
    check("archive parses", info["count"] >= 1, "%d resource(s)" % info["count"])
    for e in info["entries"]:
        first = e["body"].split(b"\n")[0].decode("utf-8", "replace")
        check("resource 0x%016X has an HD2-Addon header" % e["name"],
              first.startswith("-- HD2-Addon:"), first)
else:
    print("\n5. .patch_N archive parse -- SKIPPED (pass a packaged mod .zip)")

print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
sys.exit(0 if ok else 1)
