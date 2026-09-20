// dump_typelib —— 把游戏自带的 dl_library.dl_typelib 导成 JSON。
//
// 放到 FileDiver 源码树里跑:
//     go run ./cmd/dump_typelib -o typelib_all.json
//
// 不带 -o 就写到 stdout(注意:PowerShell 的 > 重定向会写成 UTF-16,JSON 会打不开,
// 所以推荐直接用 -o)。
//
// 产出以**类型名**为键:
//     { "HellpodRackComponentData": { "name": ..., "size": 42568, "alignment": 8,
//         "members": [ { "offset": 0, "size": 2240, "type": 2801583916, "name": ..., "type_flags": {...} } ] } }
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"

	datalib "github.com/xypwn/filediver/datalibrary"
)

func main() {
	out := flag.String("o", "", "output file (default: stdout)")
	pretty := flag.Bool("pretty", false, "indent the JSON")
	flag.Parse()

	tl, err := datalib.ParseTypeLib(nil)
	if err != nil {
		panic(err)
	}

	types := make(map[string]datalib.DLTypeDesc, len(tl.Types))
	for _, t := range tl.Types {
		if t.Name == "" {
			continue
		}
		types[t.Name] = t
	}

	var w io.Writer = os.Stdout
	if *out != "" {
		f, err := os.Create(*out)
		if err != nil {
			panic(err)
		}
		defer f.Close()
		w = f
	}

	enc := json.NewEncoder(w)
	if *pretty {
		enc.SetIndent("", "  ")
	}
	if err := enc.Encode(types); err != nil {
		panic(err)
	}
	fmt.Fprintf(os.Stderr, "types=%d dumped=%d enums=%d\n", len(tl.Types), len(types), len(tl.Enums))
}
