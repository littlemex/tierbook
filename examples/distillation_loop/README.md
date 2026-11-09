# The distillation loop: a decision model teaches a student, and tierbook certifies the switch

For a routine, closed-label task type (sentiment, intent, a yes/no check), the cheapest arm that clears the floor can
be a small CPU model trained on the traffic itself. This example composes that with three pieces that already exist:

* **Prismyra** answers the traffic in the background, as a decision model, and logs what it answered under a
  registered tag (`prismyra.learn`).
* **Prismyra's learn pipeline** fits a LightGBM student on that growing log after each window of traffic, and its
  router can serve the student instead of the decision model (`ab`, `ramp`, `confidence` modes).
* **tierbook** certifies, per window, which arm is cheapest per accepted task at the declared floor -- the student,
  the decision model, a generation model, or a metered API -- on gold-labelled items the choice was not made on, and
  writes the decision back into Prismyra's learn spec (`export-policy --target prismyra-learn`).

Prismyra's own admission bar asks whether a student is close enough to its teacher; tierbook's certificate asks
whether an arm clears the operator's floor on gold labels at the lowest cost. A student can pass one and not the
other, and the switch is made only on tierbook's.

## The pieces in this directory

| file | what it is |
|---|---|
| `labels.py` | the caller's side for a closed-label task: the prompt a generation arm is sent, and an exact-label grader |
| `progress.py` | replays the windows in order and calls `certify.derive` at each, so each row is what `tierbook derive` would have said at that moment |

Arms that report no token usage (a decision model, a student) are priced from a declared `usd_per_attempt` -- an
hourly price over a measured items-per-hour, with its source -- and tierbook prices them on that rather than refusing
them for having no usage.

## Writing the switch back

`--arm-router` maps each arm Prismyra can serve to the `router` block it means, or to `null` for "Prismyra alone":

```json
{"prismyra": null,
 "student-w6": {"mode": "ab", "ratio": 10000, "student_path": "students/w6.json"},
 "prismyra-confidence-w6": {"mode": "confidence", "tau": 0.8, "student_path": "students/w6-conf.json"}}
```

```bash
tierbook export-policy --policy policy.json --target prismyra-learn --learn-spec learn.json --arm-router arms.json --signal finnews-sentiment=finnews-sentiment-v1 --out learn-next.json
```

A task type certified on an arm the map does not name (a metered API) is refused, because Prismyra cannot serve it; a
task type that is not certified gets no router, so Prismyra answers it.

The measured run is in `docs/verify/v0.5.0-distillation-loop.md`.
