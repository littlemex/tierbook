# v0.6: connecting trainers, inference systems and RL without becoming any of them

**Status.** Phase 1 implemented (this file's first section). Later phases are contracts, each closed by its own test and
measurement. The design was reached in two review rounds; the reviewed text and the decisions it changed are summarised
here, and what each phase needs is cited from the distillation record (`docs/verify/v0.5.0-distillation-loop.md`).

## The rule every contract follows

tierbook reads files in its own published formats and ships a validator for each (`check-observations` for
observations; each later format gets its own when it is added). A writer adapts to the reader's
format; tierbook core adapts only to public conventions. Neither tierbook nor any trainer imports the other. tierbook
never runs a trainer, a router or an optimiser, and holds no reward: it certifies what other systems produced, binds the
certificate to exactly what answered, and refuses evidence that cannot support a claim.

## Phase 1: what answered (implemented)

| what | why, from the record | test |
|---|---|---|
| Observation format 3 adds `arm_version` (opaque string) and `path` (component arms that ran) | Round 5's and round 12's checkpoints were discarded and retrained; round 13's retrain agreed with round 12 on 93.4% of labels. A certificate over one is not a certificate over the other | `tests/test_arm_versions.py` |
| `derive` refuses an arm whose fresh rows name two versions, or a version on some rows and none on others | A rate pooled over two things that answered certifies neither; an unversioned row cannot be shown to be the same thing | same |
| The policy records `arm_version` of the chosen arm, `component_versions` for a cascade; `drift` refuses fresh rows from another version, skips arms with no fresh rows, and lists unversioned certificates meeting versioned rows | Round 14's teacher was re-created and agreed with round 1 on 97 of 100 re-asked items | same |
| Candidate `interface` (opaque) and declared `interfaces` filter, applied before selection; with a filter, every candidate (a cascade too) must declare one | Round 12: the cheapest certified arms could not be served by the router, and the servable set was an amendment written after the result | manual replay on round 12's files: `interfaces: ["generates"]` picks the servable cascade (held-out 0.8510) in one run |
| `check-observations` and `ingest --arm-version` | The experiment scripts converted and checked files by hand | CLI tests |

tierbook does not say what a version is made of. A weights digest, an image digest, a perigraph identity, or a
composition of them is the sender's choice, and so is an interface name. The opaque string is compared, never parsed.

## Phase 2 to 7 (contracts)

| phase | repo | contract | test that closes it |
|---|---|---|---|
| 2 | any sender (Prismyra ships one) | Writers of format-3 rows: a not-yet-served candidate scored on a declared item set, and a server's logged requests exported under the assigned arm with the answering components in `path`. Prismyra's are in its own repo (`prismyra.learn.observations`) | `check-observations` reads their output |
| 3 | both | Set manifests `{item, content_sha256}`; trainers take `--exclude-set` and write `arm-provenance.json` (`trained_on`, `requires: [{arm, arm_version}]`, opaque trainer section). Candidates cite provenance and `consulted` sets; `derive` refuses a certificate whose held-out items appear in `trained_on` or `consulted`. Pushed claims may trigger a refusal and never lift one | Stub trainer with one held-out item in `trained_on` is refused |
| 4 | tierbook | Declared price inputs (`usd_per_hour`, `attempts_per_hour`, `measured_on`, `one_off_usd`, `horizon_attempts`), an `exact` binomial bound beside Wilson, `power` arithmetic, a looks ledger keyed by held-out set digest | Reproduces round 13's price and round 14's 0.0204 and 0.0119 |
| 5 | the router's side | A router admits what a policy certified by reading the policy's `arm`, `arm_version` and status; tierbook's export targets carry those fields and know nothing of the router's own admission rules. Prismyra's side is in its repo | A retrained artifact under the old policy is refused by the router |
| 6 | neither | End-to-end run on a second task, pre-registered, one look, no hand-written glue | Certificate, served artifact and drift rows carry one `arm_version` |
| 7 | any RL system (Prismyra's bandit is one) | Reads observations and the confirmed rungs; returns frozen snapshots as provenance | `drift` confirms each assigned arm |

**RL.** An RL system reads observations and the policy's confirmed rungs, honours the same exclude sets, and hands back
a frozen snapshot as `arm-provenance.json`. tierbook certifies the snapshot like any other arm. It keeps no reward
field: a scalar reward is turned into a verdict by an injected module on the sender's side, and the module's name is
recorded as the grader.

**Hidden-state students.** Round 15 measured a LightGBM student on the teacher's layer-16 hidden state at 0.853 on the
certification items, certified at floor 0.80 as the cheapest arm there. tierbook never reads a hidden state; such a
student declares `requires: [{arm: teacher, arm_version}]` in its provenance, and its price includes the trunk pass.

**perigraph** stays a separate spec. tierbook reads none of its fields; a sender may use a perigraph identity as part of
`arm_version`. Three of its rules are adopted: the content digest rule for item content, pushed claims only subtract,
and an absent record is never a clean one.

## Not building

A reward field, reward shaping or an optimiser in tierbook; an orchestrator or a trainer registry; an artifact store;
certificate signatures; an OpenTelemetry GenAI adapter (every attribute is still `development`); an OpenInference
adapter until a deployment has spans and no call log (T19).
