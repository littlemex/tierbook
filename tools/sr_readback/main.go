// tierbook TB-107 read-back verifier.
//
// This is not a schema check. It calls the real vLLM Semantic Router `config.Parse`, the same function the
// router's own binary calls at start-up, and prints back the three things TB-107 found disagreeing across
// the router's pre- and post-PR#3489 contracts: the default model, each decision's model references, and
// each provider model's backend refs (name, endpoint, and the parsed provider/backend kind). A file that
// merely parses without error is not enough -- the post-PR#3489 shape parses on the pre-PR#3489 router too,
// with the default model silently empty, and a key rename that the parser accepts but resolves to the wrong
// backend kind would not show up in a schema check either. So this program always prints the values, and it
// is the caller's job (tierbook's test suite) to compare them against what tierbook intended, not just check
// the exit code.
//
// Built and run from inside the semantic-router checkout it is meant to verify, one commit at a time --
// never from an outer module -- because that checkout's own go.mod carries `replace` directives for its
// internal packages that only apply when it is the main module of the build.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"

	"github.com/vllm-project/semantic-router/src/semantic-router/pkg/config"
)

type decisionRefs struct {
	Name      string   `json:"name"`
	ModelRefs []string `json:"model_refs"`
}

// backendRef is one endpoint the router resolved for one provider model, after canonicalisation -- so its
// Type is the router's own idea of the backend kind, read back through whichever YAML key (`type` or
// `provider`) the target's shape used to write it, not the key name itself.
type backendRef struct {
	Model    string `json:"model"`
	Name     string `json:"name"`
	Endpoint string `json:"endpoint"`
	Type     string `json:"type"`
}

type result struct {
	Parsed       bool           `json:"parsed"`
	Error        string         `json:"error,omitempty"`
	DefaultModel string         `json:"default_model"`
	Decisions    []decisionRefs `json:"decisions"`
	BackendRefs  []backendRef   `json:"backend_refs"`
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
	// One row per resolved endpoint, not per configured model: a model with more than one backend_ref would
	// otherwise collapse to whichever the router happened to pick. Sorted so the caller can compare by value
	// without depending on the router's own internal ordering, which this program does not claim to verify.
	for _, ep := range cfg.VLLMEndpoints {
		out.BackendRefs = append(out.BackendRefs, backendRef{
			Model:    ep.Model,
			Name:     ep.Name,
			Endpoint: fmt.Sprintf("%s:%d", ep.Address, ep.Port),
			Type:     ep.Type,
		})
	}
	sort.Slice(out.BackendRefs, func(i, j int) bool {
		if out.BackendRefs[i].Model != out.BackendRefs[j].Model {
			return out.BackendRefs[i].Model < out.BackendRefs[j].Model
		}
		return out.BackendRefs[i].Name < out.BackendRefs[j].Name
	})
	enc, err := json.MarshalIndent(out, "", "  ")
	if err != nil {
		fmt.Fprintln(os.Stderr, "encode result:", err)
		os.Exit(1)
	}
	fmt.Println(string(enc))
}
