"""SimAgent core: the eight atoms (see plan.md §5).

Dimension enters the system ONLY at the two boundaries — Space (input) and
View (output). Everything between is dimension-blind. This package must stay
pure: stdlib + numpy + sympy + the sandbox math leaves only (enforced by
tests/test_layering.py).
"""
from .claim import Claim, ClaimValidationError, require_valid_claim, validate_claim
from .derive import CONSTRUCTORS, recompute
from .entity import Entity, World
from .journal import Journal, read_trace, replay_vars
from .measure import measure_state, qualitative_lines
from .op import KERNEL_OPS, OpOutcome, apply_op
from .space import Box, IntBox, Space

__all__ = [
    "Space", "Box", "IntBox",
    "Entity", "World", "apply_op", "OpOutcome", "KERNEL_OPS",
    "CONSTRUCTORS", "recompute",
    "Claim", "ClaimValidationError", "validate_claim", "require_valid_claim",
    "Journal", "read_trace", "replay_vars",
    "measure_state", "qualitative_lines",
]
