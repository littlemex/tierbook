"""tierbook: a ledger of what each inference tier was measured to do, and a router that only reads it.

**This package is a META mechanism. Logic is injected into it and is never built into it.**

Nothing here may encode which signals are worth using, carry a threshold taken from one corpus, or refuse on the
strength of a finding rather than on the record in front of it. A study that measured a signal not to help records
that measurement; the mechanism does not turn it into a list to refuse against, because the next corpus may measure
the opposite and must be able to express it.

The experiments in `docs/EXPERIMENT-FEEDBACK.md` exist to answer **what kinds of thing a general mechanism has to be
able to hold** -- which conditions must be recordable, which refusals are structural rather than empirical, which
fields a claim needs before it can be checked. They are the input to that question, not the answer.

The test for any addition here: **could a different study, on a different corpus, reaching the opposite conclusion,
express its own answer through this?** If the mechanism has already decided, it is wrong, however well the decision
is supported by the measurements in this repository.
"""
from pathlib import Path

from tierbook.policy import (  # noqa: F401
    Arrangement,
    Candidate,
    Decision,
    MECHANICAL_FAILURES,
    OBSERVABLE_FAILURES,
    CHECK_REJECTED,
    Tier,
    assign_family,
    compile_table,
    load_registry,
    paired_difference_lcb,
    registry_version,
    run,
    should_escalate,
)

#: The record schema, shipped inside the package rather than beside a ledger.
#:
#: It has to travel with the code because two things read it and one of them is a refusal: `config.py` derives
#: the set of keys a candidate file may NOT contain from this schema, so that a hand-written accuracy figure
#: cannot be smuggled into the file the compiler trusts. When the schema was a sibling of the ledger, that
#: rule quietly did nothing wherever the two were not sitting next to each other -- which is every deployment.
SCHEMA_PATH = Path(__file__).with_name("schema.json")

__version__ = "0.1.0"
SCHEMA_VERSION = 1
