import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hd2_archive as A

for p in sys.argv[1:]:
    data = open(p, "rb").read()
    a = A.parse(data)
    print("=" * 70)
    print(p)
    print(f"  size={a['size']} declared={a['total']} resources={a['count']}")
    for e in a["entries"]:
        body = e["body"]
        first = body.split(b"\n", 1)[0][:90].decode("utf-8", "replace")
        print(f"  #{e['index']} hash=0x{e['name']:016X} type=0x{e['type']:016X} "
              f"off={e['offset']} len={e['length']} ver={e['version']} blen={e['body_len']}")
        print(f"      head: {first}")
    # round trip
    rebuilt = A.make_archive({str(e["name"]): A.envelope(e["body"]) for e in a["entries"]})
    print("  round-trip:", "IDENTICAL" if rebuilt == data else f"DIFFERS ({len(rebuilt)} vs {len(data)})")
