# The certification loop, end to end

One composition of the v0.5 certification plane (`docs/DESIGN-v0.5-certification-plane.md`): measure arms through an
OpenAI-compatible gateway, grade the answers, derive a per-task-type assignment, hand it to vLLM Semantic Router,
send traffic through the router, and ask whether the deployed assignment still holds.

Everything in this directory is the example's choice, not the mechanism's: the task (MMLU-Pro multiple choice, whose
categories are also the router's domain labels), the grader (`grade.py`), the arms and their prices
(`candidates.json`), and the floors (`declarations.json`). Replace any of them and the commands below do not change.

## What you need

* Python 3.10+ with this repository installed (`pip install .`) and `pyarrow` for the dataset sample.
* An OpenAI-compatible gateway that serves the arms in `candidates.json`, and its key in `TIERBOOK_API_KEY`.
* For the routed half: Docker and `pip install vllm-sr==0.4.0` on the machine that will run the router.

The prices in `candidates.json` are the per-MTok rates the gateway bills at, copied from its rate table; with the
gateway patch in `infra/patches/stratoclave/` applied they can be read from `GET /api/mvp/me/rates` instead.

## The loop

```bash
export GATEWAY_URL=https://your-gateway.example/v1
export TIERBOOK_API_KEY=sk-your-key
export DATA=$HOME/tierbook-data
mkdir -p "$DATA" && cd "$DATA"
curl -sL -o mmlu_pro_test.parquet https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro/resolve/main/data/test-00000-of-00001.parquet
EX=/path/to/tierbook/examples/certification_loop
python -I $EX/prepare_mmlu_pro.py --parquet mmlu_pro_test.parquet --categories biology,history,math,law --per-category 250 --seed 1 --out items-measure.jsonl
python -I $EX/prepare_mmlu_pro.py --parquet mmlu_pro_test.parquet --categories biology,history,math,law --per-category 40 --seed 1 --skip 250 --out items-routed.jsonl
python -I $EX/drive.py direct --items items-measure.jsonl --candidates $EX/candidates.json --base-url "$GATEWAY_URL" --out calls.jsonl --run m1 --max-tokens 1024
python -I $EX/grade.py --calls calls.jsonl --items items-measure.jsonl --out outcomes.jsonl
tierbook ingest --calls calls.jsonl --outcomes outcomes.jsonl --out obs.jsonl --source drive:measure
tierbook derive --observations obs.jsonl --candidates $EX/candidates.json --declarations $EX/declarations.json --out policy.json
```

`derive` prints one line per task type: its status, the arm, the held-out spend per accepted task, and why. Then the
router configuration, with the gateway's address filled in from a copy of the candidate file:

```bash
python -c "import json,os,sys; c=json.load(open(sys.argv[1])); [v['endpoint'].update(base_url=os.environ['GATEWAY_URL']) for v in c['candidates'].values()]; json.dump(c, open('candidates-live.json','w'), indent=2)" $EX/candidates.json
tierbook export-policy --policy policy.json --target vsr --candidates candidates-live.json --out vsr.yaml --signal biology=biology --signal history=history --signal math=math --signal law=law --signal-categories biology=biology --signal-categories history=history --signal-categories math=math --signal-categories law=law --management-bind 0.0.0.0 --management-port 18080
vllm-sr config validate --config vsr.yaml
vllm-sr serve --config vsr.yaml --minimal
```

`--management-bind 0.0.0.0` is the router's bind inside its own container, which vllm-sr 0.4.0's Docker stack
requires; the listener and the management API are published on the host's loopback only (`--listener-address`
defaults to `127.0.0.1`). `--management-port` moves the management API off 8080 when something else holds it.

Routed traffic, graded the same way, and the drift report:

```bash
python -I $EX/drive.py routed --items items-routed.jsonl --router http://127.0.0.1:8801/v1 --model tierbook/routed --out routed.jsonl --run routed-1 --max-tokens 1024
python -I $EX/grade.py --calls routed.jsonl --items items-routed.jsonl --out routed-outcomes.jsonl
tierbook ingest --calls routed.jsonl --outcomes routed-outcomes.jsonl --out routed-obs.jsonl --source router
tierbook drift --observations obs.jsonl --fresh routed-obs.jsonl --deployed policy.json --candidates $EX/candidates.json --declarations $EX/declarations.json --out drift.json --rederived-out policy-next.json
```

`drift` exits 3 when fresh traffic contradicts a deployed assignment. When the re-derived policy differs, export it and
hand it to the running router with `vllm-sr config apply --config vsr-next.yaml`.

## What the example measures and what it does not

The grader credits an answer only when it commits to one option letter, so an answer cut off at the output budget is
graded wrong; the observation keeps `finish_reason`, and the per-cell `cut_off_attempts` shows when that happened. The
floors are stand-ins for a business requirement and nothing in tierbook proposes them. The routed half observes only the
arm the router actually chose for each request, so an arm that is not serving is re-measured by running `drive.py
direct` again; `drift` lists those cells under `needs_measurement`.
