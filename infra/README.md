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

## Both sides are pinned to a commit

Neither of the other two repositories cuts versions, so **a commit id is the only thing that names a state of them**.
`GATEWAY_REF` and `CLUSTER_REF` carry the two commits this was verified against, and the checkout fetches exactly those:
`git fetch --depth 1 origin <sha>` and a detached checkout, never a branch.

"The tip of main" is not a state. Two runs a week apart would deploy different code while reporting the same thing, and a
failure could not be attributed to either side's change. An existing checkout is moved onto the pin rather than left
alone, because a stale working tree that happens to be sitting there is the quiet version of the same problem.

The pin must be the **full 40 characters** — fetching a single commit with an abbreviated id is refused by the server,
and the script says so rather than falling back to a branch. Override either with `TIERBOOK_GATEWAY_REF` /
`TIERBOOK_CLUSTER_REF`.

The connection file records both: `requested` (the pin) and `at` (what the checkout resolved to). They differ exactly
when something went wrong, so `connect` prints a warning when they do.

## The two changes the other repositories needed

**Both are fixed upstream, and the pinned commits are the ones that carry the fixes.** There are no patches in
`infra/patches/` any more.

| gap | where it was | now |
|---|---|---|
| the gateway's documented first-admin procedure could not work: the variable the backend reads at startup never reached its task definition, so a clean deployment ended with zero users | `iac/bin/iac.ts` | fixed upstream; `GATEWAY_REF` points at the merge that carries it |
| the serving chart rendered a closed list of engine arguments, so a request carrying tool schemas was rejected with 400 and no flag could be passed | `charts/experiments` | fixed upstream as `extraArgs`; `CLUSTER_REF` points at the merge that carries it |

The patch mechanism is still here for the next gap, and `infra/patches/README.md` says how to add one. It reports three
states — already upstream, applies, no longer matches — and refuses the third rather than applying half a fix:

```bash
./infra/tierbook-up patches            # what each patch would do; nothing to report while there are none
./infra/tierbook-up patches --apply    # apply them to the checkouts in the work directory
```

A pin and a patch answer different questions. A patch compensates for code that is wrong; a pin states which code was
verified. With the fixes upstream, the pin is the one doing the work.

**One case the patches cannot reach.** A gateway this script *adopted* was deployed by somebody else, and seeding its
first administrator means redeploying their ECS stack. This script will not do that. If an adopted gateway has no
administrator, `up` stops and names the two ways forward: have its owner create one, or point the prefix at a gateway of
your own, where the patch makes the documented procedure work.

## What this script does not do

- **It never authenticates.** Expired credentials are reported, not refreshed.
- **It never touches the storage layer.** The cluster is created with all three filesystems off, because they bill
  continuously and a verification should not outlive itself as a standing charge. Nothing here says they work.
- **It does not verify the teardown for you.** `down` says what it destroyed; whether anything is still billing is a
  question only the provider's instance API can answer, and the cluster module's own guard asks it. Read that output.
- **It holds no opinion about which candidate to use.** It supplies facts. `examples/opencode_ops` decides, and the
  mechanism in `src/tierbook` refuses claims the facts cannot support.
