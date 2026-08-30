"""tierbook: a ledger of what each inference tier was measured to do, and a router that only reads it."""
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
