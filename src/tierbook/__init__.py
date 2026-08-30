"""tierbook: a ledger of what each inference tier was measured to do, and a router that only reads it."""
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

__version__ = "0.1.0"
SCHEMA_VERSION = 1
