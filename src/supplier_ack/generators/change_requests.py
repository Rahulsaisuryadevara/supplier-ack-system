"""Backward-compatible import path for the rule-driven change generator."""
from supplier_ack.generators.changes import generate_changes


def generate_change_requests_and_approvals(*args, **kwargs):
    """Compatibility wrapper; new orchestration should call ``generate_changes``."""
    return generate_changes(*args, **kwargs)
