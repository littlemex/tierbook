# infra: bringing the candidates up, in one command

**This directory is logic, not mechanism.** It stands in the same relation to `src/tierbook` as `examples/` does: it
makes decisions about a particular deployment, and the mechanism keeps having no opinion about any of them.

```bash
cp infra/config.example.env infra/config.env    # fill in the four required values
./infra/tierbook-up doctor                      # what is missing. Creates nothing, charges nothing
./infra/tierbook-up up                          # adopt what exists, create what does not, measure, connect
/usr/bin/python3 tools/verify_ops_live.py --from-connection ~/tmp/tierbook/infra/connection.json
./infra/tierbook-up down                        # destroy only what this script created
```

## The invariant, because it is the reason for most of the design

**This script never destroys anything it did not create.** Every resource it creates is recorded as owned; every
resource it finds is recorded as adopted. `down` acts on the first kind only, and its default when the record is missing
or unreadable is *adopted* — the safe direction. An operator whose account already holds a production gateway must be
able to run `down` without checking first.

Both directions are tested. `tests/test_infra_connection.py` asserts that a teardown with no state file destroys
nothing, and that a side marked as ours actually reaches its destroyer. The second test is not decoration: the first
version of the state reader returned Python's `True` while the shell compared against `true`, so a cluster this script
had created was reported as ours and then silently skipped — a teardown that reports success and leaves a bill.

## Which of the two prices is derived, and why they are not treated alike

| | the box | the metered arm |
|---|---|---|
| how it is obtained | **derived**: the instance's on-demand hourly price, from the price list API, divided by a **measured** token rate | **supplied**: a published list price |
| what happens if absent | `measure` runs and produces it | the script **refuses to continue** |
| direction of the error | the token rate is usually a lower bound, so the price is an **upper** bound | none; it is a quoted figure |

The refusal is deliberate and it is this repository's oldest correction. A fixed-cost candidate's cost per token cannot
be stated without a measured throughput, and the first time it was stated anyway — per-task latency multiplied by an
*assumed* parallelism — the answer moved by a factor of six and the conclusion about which candidate to use changed with
it. So the box's price is computed here from a real measurement, and the arm whose price is a published figure has to be
told to us rather than guessed at.

## What `up` actually does

```
doctor ──▶ gateway ──▶ API key ──▶ cluster ──▶ box ──▶ measure ──▶ connect
             │                       │          │        │
        adopt or create         adopt or    chart from   open-loop probe,
                                create     the cluster   inside the cluster
                                            repository
```

Two steps are worth calling out.

**The probe runs inside the cluster.** Across a port-forward or a laptop's uplink, the number produced belongs to the
tunnel. This project has twice published a load generator's own limit as a box's capacity, which is why the probe
measures its own dispatch lateness and marks the result as understated when it was the bottleneck.

**`measure` decides whether its own number is trustworthy, and records the answer either way.** A run that absorbed
everything offered is a lower bound even when the generator kept up and the offered load exceeded the engine's seat
count, because nothing queued and a ceiling nothing reached is a ceiling nobody measured.

## The connection file

`connect` writes one JSON file and `tools/verify_ops_live.py` reads it. The shape is a contract between two programs in
two languages, so it is pinned by a test that runs both halves — the script writes the file, the driver's own reader
consumes it, and a key one side adds without the other fails at merge time rather than on a paid cluster.

What it carries, and what it deliberately leaves null:

- the box's in-cluster URL, model, **derived** price and its basis, and whether that price is an upper bound;
- the box's capacity as the exact fields `throughput.Throughput` refuses to be built without — rate, goodput, deadline,
  arrivals, offered concurrency, seat count, and why it understates if it does;
- the gateway's URL, model, key file and **supplied** price;
- `api.capacity: null`, because nothing measured the metered endpoint. Null becomes `unknown` downstream, which is a
  different thing from a claim, and the mechanism keeps them apart.

## Workarounds for gaps in the other two repositories

Both are gathered in one block in the script, each stating the gap it compensates for and what would let it be deleted.
A test asserts both properties, and a second test asserts that no compensation sits outside that block — a workaround on
the happy path is one nobody retires.

| what it does | why it is needed | when to delete it |
|---|---|---|
| registers one task definition revision adding `STRATOCLAVE_BOOTSTRAP_ADMIN_EMAIL` | the gateway's documented first-admin procedure cannot work: the backend reads that variable at startup and nothing puts it into the task definition, so a clean deployment ends with zero users | when the gateway passes it through (two lines beside `ALLOW_ADMIN_CREATION`) |
| patches the box's engine arguments to accept tool schemas | the serving chart renders a closed list of five engine arguments, and every request a coding agent sends carries tool schemas, so without this the box returns 400 to all of them | when the chart grows an `extraArgs` list |

Each check is written so that it becomes a no-op automatically once upstream lands: it looks at the live resource, says
"no workaround needed" when the gap is closed, and only then does nothing. The two requests describing those fixes were
sent to the respective projects separately.

## What this script does not do

- **It never authenticates.** Expired credentials are reported, not refreshed.
- **It never touches the storage layer.** The cluster is created with all three filesystems off, because they bill
  continuously and a verification should not outlive itself as a standing charge. Nothing here says they work.
- **It does not verify the teardown for you.** `down` says what it destroyed; whether anything is still billing is a
  question only the provider's instance API can answer, and the cluster module's own guard asks it. Read that output.
- **It holds no opinion about which candidate to use.** It supplies facts. `examples/opencode_ops` decides, and the
  mechanism in `src/tierbook` refuses claims the facts cannot support.
