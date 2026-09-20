"""Drive the Ops example against two real backends, so the loop's numbers are billed rather than invented.

**What this adds over `examples/opencode_ops/tests`.** Those tests drive the loop with a fake agent, deliberately: a test
that has to average over a real model's variance cannot say whether the loop moved traffic or the model did. This runs
the same loop against a served box and a metered API, which is the only way to find out whether the four legs the example
records are the four legs that actually get billed.

The prices are supplied rather than typed here, and where each comes from is the point:

* the **box** price is derived -- an instance's on-demand hourly rate divided by a measured token rate. It is an *upper*
  bound, because the rate it divides is a lower bound on the throughput;
* the **API** price is a published list price, which is a different kind of fact and is why the two are separate
  arguments rather than one price card.

Nothing here decides anything. It supplies facts the example's own policy reads.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "src")
sys.path.insert(0, ".")

from examples.opencode_ops import policy as P              # noqa: E402
from examples.opencode_ops.adapter import Reply            # noqa: E402
from examples.opencode_ops.ops import Ops                  # noqa: E402
from examples.opencode_ops.state import World              # noqa: E402
from tierbook import throughput as th                      # noqa: E402


def _call(url: str, body: dict, headers: dict, timeout: float = 120.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode())
    req.add_header("content-type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read()[:300].decode(errors="replace")}


def live_agent(*, box_url: str, box_model: str, api_url: str, api_model: str, api_key: str):
    """The example's `Agent` seam, wired to a served box and a metered endpoint.

    The acceptance signal is the crude one the example documents: whether an answer came back with content. A real
    deployment replaces it with a test suite passing or a patch applying, and the loop does not change -- it only ever
    asks whether the answer was taken.
    """
    def agent(body: dict, *, candidate: str) -> Reply:
        if candidate == P.CHEAP:
            url, model, headers = box_url, box_model, {}
        else:
            url, model, headers = api_url, api_model, {"x-api-key": api_key}
        status, out = _call(url, {**body, "model": model, "max_tokens": 64}, headers)
        usage = out.get("usage") or {}
        text = ""
        if out.get("choices"):
            text = (out["choices"][0].get("message") or {}).get("content") or ""
        # **A 4xx is not a bad answer.** The endpoint declined to take the request in the shape it was sent, which is what
        # a served engine did here for every request carrying tool schemas until two flags were added. Recording that as
        # an unaccepted answer makes a configuration problem look like a quality problem, permanently: the rate never
        # recovers because the question was never asked.
        unobserved = None
        if status != 200:
            unobserved = "unsupported" if 400 <= status < 500 else "execution_error"
        return Reply(text=text,
                     accepted=bool(status == 200 and text.strip()),
                     input_mtok=float(usage.get("prompt_tokens", 0)) / 1e6,
                     output_mtok=float(usage.get("completion_tokens", 0)) / 1e6,
                     unobserved_because=unobserved)
    return agent


#: The keys this driver reads out of a connection file written by `infra/tierbook-up connect`. Named as a constant
#: rather than read inline, because it is a contract between two programs and `tests/test_infra_connection.py` checks
#: the same list against a real connection file. A seam whose shape lives in two heads drifts; one whose shape is a
#: constant with a test on it cannot.
CONNECTION_KEYS = {
    "box": ("model", "in_cluster_url", "price_per_mtok", "price_basis", "price_is_upper_bound", "capacity"),
    "api": ("model", "chat_completions_url", "api_key_file", "price_per_mtok", "price_basis", "capacity"),
    "top": ("version", "required_per_hour"),
}

#: What a capacity block in the connection file has to carry. Every one of these is a field `throughput.Throughput`
#: refuses to be built without, so a connection file missing any of them cannot produce capacity evidence at all.
CONNECTION_CAPACITY_KEYS = ("per_hour", "goodput_per_hour", "deadline_seconds", "arrivals",
                            "offered_concurrency", "seats", "understated_because")


def from_connection(path: str) -> dict:
    """Turn a connection file into the arguments this driver takes, refusing rather than filling in gaps.

    The refusals are the point. A connection file with no derived box price is a file whose `measure` step never ran,
    and substituting a plausible price here would put an invented number where the whole discipline of this repository
    is that a fixed-cost candidate's price comes from a measured token rate.
    """
    conn = json.loads(pathlib.Path(path).read_text())
    if conn.get("version") != 1:
        raise SystemExit(f"connection file version {conn.get('version')!r} is not 1; this driver reads version 1")
    for side in ("box", "api"):
        missing = [k for k in CONNECTION_KEYS[side] if k not in conn.get(side, {})]
        if missing:
            raise SystemExit(f"connection file is missing {side}.{{{','.join(missing)}}}; it was not written by "
                             f"`infra/tierbook-up connect`, or that script and this driver have drifted apart")
    box, api = conn["box"], conn["api"]
    if box["price_per_mtok"] is None:
        raise SystemExit("the connection file has no derived box price. Run `infra/tierbook-up measure`: the box's "
                         "price is an instance's hourly rate over a MEASURED token rate, and there is no substitute")
    if not api["chat_completions_url"] or not api["api_key_file"]:
        raise SystemExit("the connection file has no gateway URL or no API key file; the metered arm cannot be called")
    cap = box.get("capacity")
    if cap is not None:
        missing = [k for k in CONNECTION_CAPACITY_KEYS if k not in cap]
        if missing:
            raise SystemExit(f"the box's capacity block is missing {missing}; a rate without its arrivals, deadline, "
                             f"offered load and seat count cannot be recorded as a measurement")
    return {
        "box_url": box["in_cluster_url"], "box_model": box["model"],
        "api_url": api["chat_completions_url"], "api_model": api["model"],
        "api_key_file": api["api_key_file"],
        "box_price_per_mtok": float(box["price_per_mtok"]),
        "api_price_per_mtok": float(api["price_per_mtok"]),
        "required_per_hour": float(conn["required_per_hour"]),
        "capacity": cap,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-connection", default=None,
                    help="a connection file written by infra/tierbook-up; supplies every value below")
    ap.add_argument("--box-url")
    ap.add_argument("--box-model")
    ap.add_argument("--api-url")
    ap.add_argument("--api-model")
    ap.add_argument("--api-key-file")
    ap.add_argument("--box-price-per-mtok", type=float,
                    help="derived: the instance's hourly rate over a MEASURED token rate")
    ap.add_argument("--api-price-per-mtok", type=float, help="the published list price")
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--required-per-hour", type=float, default=100.0)
    ap.add_argument("--box-goodput-per-hour", type=float, default=None,
                    help="a measured goodput for the box, from tools/open_loop_probe.py")
    ap.add_argument("--box-deadline-seconds", type=float, default=8.0)
    ap.add_argument("--box-offered-concurrency", type=int, default=None)
    ap.add_argument("--box-seats", type=int, default=None)
    ap.add_argument("--box-understated-because", default="")
    a = ap.parse_args(argv)

    if a.from_connection:
        got = from_connection(a.from_connection)
        # An explicit flag wins over the file. The box's URL in particular has to be overridable: the file records the
        # address inside the cluster, which is the right thing for it to record and not reachable from outside, so a
        # caller bridging the port has to be able to say so without editing the file.
        for flag, key in (("box_url", "box_url"), ("box_model", "box_model"), ("api_url", "api_url"),
                          ("api_model", "api_model"), ("api_key_file", "api_key_file"),
                          ("box_price_per_mtok", "box_price_per_mtok"),
                          ("api_price_per_mtok", "api_price_per_mtok")):
            if getattr(a, flag) is None:
                setattr(a, flag, got[key])
        if a.required_per_hour == 100.0:
            a.required_per_hour = got["required_per_hour"]
        cap = got["capacity"]
        if cap:
            a.box_goodput_per_hour = cap["goodput_per_hour"]
            a.box_deadline_seconds = cap["deadline_seconds"]
            a.box_offered_concurrency = cap["offered_concurrency"]
            a.box_seats = cap["seats"]
            a.box_understated_because = cap["understated_because"]
    else:
        needed = [n for n in ("box_url", "box_model", "api_url", "api_model", "api_key_file",
                              "box_price_per_mtok", "api_price_per_mtok") if getattr(a, n) is None]
        if needed:
            ap.error("without --from-connection these are required: " + ", ".join("--" + n.replace("_", "-")
                                                                                 for n in needed))

    capacity: dict[str, object] = {}
    if a.box_goodput_per_hour is not None:
        # Supplied from a real probe run rather than assumed, and its `understated_because` travels with it: a rate that
        # came back as a lower bound has to stay one, or the loop reports a ceiling nobody reached.
        capacity[P.CHEAP] = th.Throughput(
            per_hour=a.box_goodput_per_hour, goodput_per_hour=a.box_goodput_per_hour,
            deadline_seconds=a.box_deadline_seconds, arrivals="open_loop",
            understated_because=a.box_understated_because,
            offered=th.Offered(concurrency=a.box_offered_concurrency or 1, seats=a.box_seats,
                               generator="tools/open_loop_probe.py, in-cluster, poisson arrivals"))

    world = World(price_per_mtok={P.CHEAP: a.box_price_per_mtok, P.DEAR: a.api_price_per_mtok},
                  tenant_quota_left=5.0, hour_of_day=14, inflight={P.CHEAP: 0}, capacity=capacity)
    ops = Ops(world=world,
              agent=live_agent(box_url=a.box_url, box_model=a.box_model, api_url=a.api_url,
                               api_model=a.api_model, api_key=open(a.api_key_file).read().strip()),
              required_per_hour=a.required_per_hour)

    print(f"{'turn':>4} {'sent to':>4}  {'state':>9}  {'cost usd':>10}  {'capacity':>12}  why")
    for i in range(a.turns):
        t = ops.turn(f"Explain in one sentence what a queue is. Task {i}.", now=1000.0 + i)
        row = ops.history[-1]
        state = row["state"] + (f"/{row['unobserved_because']}" if row["unobserved_because"] else "")
        print(f"{i:>4} {t.candidate:>4}  {state:>9}  {t.cost.total:>10.8f}  "
              f"{t.capacity[t.candidate]:>12}  {row['why']}")

    print()
    for c in (P.CHEAP, P.DEAR):
        spa = ops.spend_per_accepted(c)
        acc = ops.acceptance(c)
        print(f"{c}: spend/accepted {'unmeasured' if spa is None else f'${spa:.8f}'}, "
              f"acceptance {'unmeasured' if acc is None else f'{acc:.2f}'}, "
              f"shown to carry the traffic: {ops.shown_to_carry_the_traffic(c)}"
              + (f", NEVER SERVED ({', '.join(ops.unserved_reasons(c))})" if ops.never_served(c) else ""))
    print("preferred:", ops.preferred())
    print("thresholds derived from the run:", {k: round(v, 8) for k, v in ops.thresholds().items()})

    legs = ops.history[0]
    print("\nfour legs recorded on every turn, cache legs present as zero rather than omitted:",
          all(r["spend"] is not None for r in ops.history), f"({len(ops.history)} turns)")
    print("harness identity, constant across turns with the same instruction:",
          len({r["harness"] for r in ops.history}) == 1, f"({legs['harness']})")
    return 0


if __name__ == "__main__":  # pragma: no cover - a command line
    sys.exit(main())
