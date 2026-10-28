"""Deterministic, scoped identifiers for the supplier acknowledgement workflow.

IDs are issued monotonically from in-memory counters. The optional JSON snapshot
contains only counter state, not editable issued IDs; restoring it resumes the
same deterministic sequence. The year component is intentionally fixed at 2026 to
match the YottaFlex challenge's ID contract.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import re
from threading import RLock
from typing import Any, Mapping

ID_YEAR = 2026
STATE_VERSION = 1

# Public full-match patterns are useful to generators, validators, and tests.
ID_PATTERNS: dict[str, str] = {
    "Supplier": r"SUP-\d{6}",
    "PurchaseOrder": r"PO-2026-\d{6}",
    "POLine": r"PO-2026-\d{6}-L\d{2}",
    "Acknowledgement": r"ACK-PO-2026-\d{6}-\d{2}",
    "PromiseDate": r"PD-ACK-PO-2026-\d{6}-\d{2}-\d{2}",
    "ChangeRequest": r"CHG-PO-2026-\d{6}-\d{6}",
    "Approval": r"APR-CHG-PO-2026-\d{6}-\d{6}-\d{2}",
    "Notification": r"NOT-2026-\d{6}",
    "InventoryPlan": r"IP-PO-2026-\d{6}-L\d{2}-\d{2}",
    "ProductionOrder": r"PRO-2026-\d{6}",
}

_COMPILED_PATTERNS = {name: re.compile(pattern) for name, pattern in ID_PATTERNS.items()}
_PARENT_PATTERNS = {
    "po_id": re.compile(r"PO-2026-\d{6}"),
    "ack_id": re.compile(r"ACK-PO-2026-\d{6}-\d{2}"),
    "change_id": re.compile(r"CHG-PO-2026-\d{6}-\d{6}"),
    "po_line_id": re.compile(r"PO-2026-\d{6}-L\d{2}"),
}

_GLOBAL_COUNTERS = ("supplier", "purchase_order", "notification", "production_order")
_SCOPED_COUNTERS = {
    "line_by_po": ("po_id", 2),
    "ack_by_po": ("po_id", 2),
    "promise_date_by_ack": ("ack_id", 2),
    "change_by_po": ("po_id", 6),
    "approval_by_change": ("change_id", 2),
    "inventory_plan_by_po_line": ("po_line_id", 2),
}


def _new_state() -> dict[str, Any]:
    return {
        "supplier": 0,
        "purchase_order": 0,
        "notification": 0,
        "production_order": 0,
        "line_by_po": {},
        "ack_by_po": {},
        "promise_date_by_ack": {},
        "change_by_po": {},
        "approval_by_change": {},
        "inventory_plan_by_po_line": {},
    }


def _require_id(value: str, name: str) -> str:
    pattern = _PARENT_PATTERNS[name]
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{name} must match {pattern.pattern!r}; received {value!r}")
    return value


def _require_counter(value: Any, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
        raise ValueError(f"counter {label!r} must be an integer in [0, {maximum}]")
    return value


class IDFactory:
    """Issue deterministic IDs with independent global and parent-scoped counters.

    The factory exposes issuance methods only; there is deliberately no method to
    mutate, rename, or recycle an already-issued identifier. Methods are protected
    by a re-entrant lock so concurrent callers cannot receive the same ID.

    Two-digit scoped counters have a fixed range of 01–99. Six-digit counters have
    a fixed range of 000001–999999. Exhaustion raises :class:`OverflowError`
    rather than silently emitting IDs that violate the declared format.
    """

    year = ID_YEAR

    def __init__(self) -> None:
        self._state = _new_state()
        self._lock = RLock()

    @staticmethod
    def _increment_global(state: dict[str, Any], key: str, width: int) -> int:
        maximum = (10**width) - 1
        next_value = state[key] + 1
        if next_value > maximum:
            raise OverflowError(f"{key} ID counter exhausted its {width}-digit range")
        state[key] = next_value
        return next_value

    def _next_global(self, key: str, width: int, render: str) -> str:
        with self._lock:
            value = self._increment_global(self._state, key, width)
            return render.format(value=value)

    def _next_scoped(self, counter_name: str, parent_id: str, width: int, render: str) -> str:
        with self._lock:
            counters = self._state[counter_name]
            maximum = (10**width) - 1
            value = counters.get(parent_id, 0) + 1
            if value > maximum:
                raise OverflowError(
                    f"{counter_name} counter for {parent_id!r} exhausted its {width}-digit range"
                )
            counters[parent_id] = value
            return render.format(value=value, parent_id=parent_id)

    def next_supplier_id(self) -> str:
        """Return SUP-000001, incrementing a global six-digit counter."""
        return self._next_global("supplier", 6, "SUP-{value:06d}")

    def next_po_id(self) -> str:
        """Return PO-2026-000001, incrementing a global six-digit counter."""
        return self._next_global("purchase_order", 6, f"PO-{ID_YEAR}-{{value:06d}}")

    def next_line_id(self, po_id: str) -> str:
        """Return a per-PO line ID such as PO-2026-000001-L01."""
        parent = _require_id(po_id, "po_id")
        return self._next_scoped("line_by_po", parent, 2, "{parent_id}-L{value:02d}")

    def next_ack_id(self, po_id: str) -> str:
        """Return ACK-<PO-id>-NN with a revision counter scoped to the PO."""
        parent = _require_id(po_id, "po_id")
        return self._next_scoped("ack_by_po", parent, 2, "ACK-{parent_id}-{value:02d}")

    def next_promise_date_id(self, ack_id: str) -> str:
        """Return PD-<ACK-id>-NN with a counter scoped to the acknowledgement."""
        parent = _require_id(ack_id, "ack_id")
        return self._next_scoped("promise_date_by_ack", parent, 2, "PD-{parent_id}-{value:02d}")

    def next_change_id(self, po_id: str) -> str:
        """Return CHG-<PO-id>-NNNNNN, scoped to the PO."""
        parent = _require_id(po_id, "po_id")
        return self._next_scoped("change_by_po", parent, 6, "CHG-{parent_id}-{value:06d}")

    def next_approval_id(self, change_id: str) -> str:
        """Return APR-<full change-request ID>-NN, preserving the complete parent ID."""
        parent = _require_id(change_id, "change_id")
        return self._next_scoped("approval_by_change", parent, 2, "APR-{parent_id}-{value:02d}")

    def next_notification_id(self) -> str:
        """Return NOT-2026-000001, incrementing a global six-digit counter."""
        return self._next_global("notification", 6, f"NOT-{ID_YEAR}-{{value:06d}}")

    def next_inventory_plan_id(self, po_line_id: str) -> str:
        """Return IP-<full PO-line ID>-NN, scoped to the PO line."""
        parent = _require_id(po_line_id, "po_line_id")
        return self._next_scoped(
            "inventory_plan_by_po_line", parent, 2, "IP-{parent_id}-{value:02d}"
        )

    def next_production_order_id(self) -> str:
        """Return PRO-2026-000001, incrementing a global six-digit counter."""
        return self._next_global("production_order", 6, f"PRO-{ID_YEAR}-{{value:06d}}")

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-serializable snapshot of counter state."""
        with self._lock:
            return {
                "schema_version": STATE_VERSION,
                "year": ID_YEAR,
                "counters": deepcopy(self._state),
            }

    def to_json(self) -> str:
        """Serialize counter state in canonical, reproducible JSON form."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, snapshot: Mapping[str, Any]) -> "IDFactory":
        """Restore a factory from a state snapshot produced by :meth:`to_dict`."""
        if not isinstance(snapshot, Mapping):
            raise ValueError("IDFactory state must be a JSON object")
        if snapshot.get("schema_version") != STATE_VERSION:
            raise ValueError(f"unsupported IDFactory state version: {snapshot.get('schema_version')!r}")
        if snapshot.get("year") != ID_YEAR:
            raise ValueError(f"IDFactory state year must be {ID_YEAR}")
        counters = snapshot.get("counters")
        if not isinstance(counters, Mapping) or set(counters) != set(_new_state()):
            raise ValueError("IDFactory state counters have missing or unknown keys")

        state = _new_state()
        for key in _GLOBAL_COUNTERS:
            state[key] = _require_counter(counters[key], key, 999_999)
        for counter_name, (parent_type, width) in _SCOPED_COUNTERS.items():
            values = counters[counter_name]
            if not isinstance(values, Mapping):
                raise ValueError(f"counter group {counter_name!r} must be an object")
            maximum = (10**width) - 1
            for parent_id, count in values.items():
                if not isinstance(parent_id, str) or _PARENT_PATTERNS[parent_type].fullmatch(parent_id) is None:
                    raise ValueError(f"invalid parent ID {parent_id!r} in counter group {counter_name!r}")
                state[counter_name][parent_id] = _require_counter(count, f"{counter_name}:{parent_id}", maximum)

        factory = cls()
        factory._state = state
        return factory

    @classmethod
    def from_json(cls, serialized: str) -> "IDFactory":
        """Parse and restore canonical JSON state; malformed input raises ValueError."""
        if not isinstance(serialized, str):
            raise ValueError("serialized IDFactory state must be a string")
        try:
            value = json.loads(serialized)
        except json.JSONDecodeError as exc:
            raise ValueError("serialized IDFactory state is not valid JSON") from exc
        return cls.from_dict(value)


def matches_id_format(entity_name: str, value: str) -> bool:
    """Return whether *value* exactly matches the convention for an entity."""
    pattern = _COMPILED_PATTERNS.get(entity_name)
    return bool(pattern and isinstance(value, str) and pattern.fullmatch(value))


def make_id(prefix: str, sequence: int, width: int = 6) -> str:
    """Backward-compatible generic ID helper; prefer :class:`IDFactory` in generators."""
    if not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
        raise ValueError("prefix must contain uppercase letters/digits and start with a letter")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("sequence must be an integer >= 1")
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError("width must be an integer >= 1")
    return f"{prefix}-{sequence:0{width}d}"


def dated_id(prefix: str, sequence: int, on_date: date, width: int = 6) -> str:
    """Backward-compatible date-based ID helper for non-contract event records."""
    if not isinstance(on_date, date):
        raise TypeError("on_date must be a datetime.date")
    return f"{prefix}-{on_date:%Y%m%d}-{sequence:0{width}d}"
