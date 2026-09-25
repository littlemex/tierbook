// tierbook TB-107 read-back verifier.
//
// This is not a schema check. It calls the real vLLM Semantic Router `config.Parse`, the same function the
// router's own binary calls at start-up, and prints back the two things TB-107 found disagreeing across the
// router's pre- and post-PR#3489 contracts: the default model and each decision's model references. A file
// that merely parses without error is not enough -- the post-PR#3489 shape parses on the pre-PR#3489 router
// too, with the default model silently empty. So this program always prints the values, and it is the
// caller's job (tierbook's test suite) to compare them against what tierbook intended, not just check the
// exit code.
//
// Built and run from inside the semantic-router checkout it is meant to verify, one commit at a time --
// never from an outer module -- because that checkout's own go.mod carries `replace` directives for its
// internal packages that only apply when it is the main module of the build.
package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/vllm-project/semantic-router/src/semantic-router/pkg/config"
)

type decisionRefs struct {
	Name      string   `json:"name"`
	ModelRefs []string `json:"model_refs"`
}

type result struct {
	Parsed       bool           `json:"parsed"`
	Error        string         `json:"error,omitempty"`
	DefaultModel string         `json:"default_model"`
	Decisions    []decisionRefs `json:"decisions"`
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: sr_readback <config-path>")
		os.Exit(2)
	}
	path := os.Args[1]

	out := result{}
	cfg, err := config.Parse(path)
	if err != nil {
		out.Parsed = false
		out.Error = err.Error()
		enc, _ := json.MarshalIndent(out, "", "  ")
		fmt.Println(string(enc))
		// A refused config is a successful run of this verifier: it answered the question. Exit 0 so the
		// caller reads the JSON rather than treating "the router refused this" as this program failing.
		os.Exit(0)
	}

	out.Parsed = true
	out.DefaultModel = cfg.DefaultModel
	for _, d := range cfg.Decisions {
		refs := decisionRefs{Name: d.Name}
		for _, mr := range d.ModelRefs {
			refs.ModelRefs = append(refs.ModelRefs, mr.Model)
		}
		out.Decisions = append(out.Decisions, refs)
	}
	enc, err := json.MarshalIndent(out, "", "  ")
	if err != nil {
		fmt.Fprintln(os.Stderr, "encode result:", err)
		os.Exit(1)
	}
	fmt.Println(string(enc))
}
