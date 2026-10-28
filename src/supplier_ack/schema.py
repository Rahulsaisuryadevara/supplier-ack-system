"""Machine-readable data dictionary for the supplier acknowledgement workflow.

The metadata below is the source of truth for docs/data_dictionary.md. FieldSpec
contains all field-level contract attributes; validators are real callables.
Date/datetime inputs may be Python date/datetime values or ISO-8601 strings.
Foreign-key validation is activated when validate_record/validate_dataset receive
context records, allowing single-record validation without a database connection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

Validator = Callable[[Any, Mapping[str, Any], Mapping[str, Any], "FieldSpec"], str | None]

ACTOR_ROLES = (
    "supplier", "planner", "carrier_warehouse_operator",
    "logistics_analyst", "operations_manager",
)
ACK_LIFECYCLE_STATES = ("DRAFT", "SUBMITTED", "PROCESSED", "EXCEPTION")
ACK_LIFECYCLE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("SUBMITTED",),
    "SUBMITTED": ("PROCESSED", "EXCEPTION"),
    "PROCESSED": (),
    "EXCEPTION": (),
}
PROMISE_CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")
APPROVER_ROLES = ("planner", "operations_manager")
NOTIFICATION_TARGET_ROLES = (
    "supplier", "planner", "carrier_warehouse_operator",
    "logistics_analyst", "operations_manager",
)
CURRENCIES = ("INR", "USD", "EUR", "GBP", "SGD", "JPY", "AUD", "CAD")
REGIONS = ("NORTH", "SOUTH", "EAST", "WEST", "CENTRAL")
UNITS_OF_MEASURE = ("EA", "BOX", "KG", "G", "L", "ML", "M", "CM", "M2", "M3", "PALLET", "SET")
ANOMALY_TYPES = (
    "MISSING_ACK", "DATE_CONFLICT", "DATE_SLIP_REQUIRES_APPROVAL",
    "QUANTITY_MISMATCH", "OVER_ACKNOWLEDGEMENT", "PRICE_SPIKE",
    "PRICE_MISMATCH", "INVALID_TRANSITION", "DUPLICATE_REVISION",
    "MISSING_APPROVAL", "LATE_ACKNOWLEDGEMENT", "LEAD_TIME_BREACH",
    "FOREIGN_KEY_MISMATCH", "LINE_TOTAL_MISMATCH", "NOTIFICATION_FAILURE",
    "PROJECTED_SHORTAGE", "PROMISE_BEFORE_ORDER", "STATUS_DATE_MISMATCH",
    "UNAPPROVED_CHANGE_UPDATES_PLAN", "ACK_WRONG_PO_LINE",
    "PROMISE_DATE_BEFORE_ORDER_DATE", "STALE_REVISION_OVERWRITE",
)

# Every status value is explicit, and each map lists only legal outgoing edges.
STATUS_ENUMS: dict[str, tuple[str, ...]] = {
    "PurchaseOrder": ("DRAFT", "ISSUED", "PARTIALLY_ACKNOWLEDGED", "ACKNOWLEDGED", "CHANGE_PENDING", "IN_FULFILLMENT", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED", "CLOSED"),
    "POLine": ("DRAFT", "OPEN", "PARTIALLY_ACKNOWLEDGED", "ACKNOWLEDGED", "CHANGE_PENDING", "IN_FULFILLMENT", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED", "CLOSED"),
    "Acknowledgement": ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "SUPERSEDED", "WITHDRAWN"),
    "PromiseDate": ("PROPOSED", "CURRENT", "SUPERSEDED", "CANCELLED"),
    "ChangeRequest": ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "IMPLEMENTED", "CANCELLED", "WITHDRAWN", "CLOSED"),
    "Approval": ("PENDING", "APPROVED", "REJECTED", "ESCALATED", "WITHDRAWN"),
    "InventoryPlan": ("DRAFT", "PROPOSED", "APPROVED", "REJECTED", "ACTIVE", "AT_RISK", "PARTIALLY_FULFILLED", "FULFILLED", "SUPERSEDED", "CANCELLED", "CLOSED"),
    "ProductionOrder": ("PLANNED", "AT_RISK", "RESCHEDULED", "CONFIRMED", "DELAYED", "DRAFT", "RELEASED", "SCHEDULED", "IN_PROGRESS", "PARTIALLY_COMPLETED", "ON_HOLD", "COMPLETED", "CANCELLED", "CLOSED"),
    "Notification": ("QUEUED", "SENT", "DELIVERED", "BOUNCED", "RETRY_PENDING", "FAILED", "CANCELLED"),
}
STATUS_TRANSITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "PurchaseOrder": {
        "DRAFT": ("ISSUED", "CANCELLED"),
        "ISSUED": ("PARTIALLY_ACKNOWLEDGED", "ACKNOWLEDGED", "CHANGE_PENDING", "IN_FULFILLMENT", "CANCELLED", "CLOSED"),
        "PARTIALLY_ACKNOWLEDGED": ("ACKNOWLEDGED", "CHANGE_PENDING", "IN_FULFILLMENT", "CANCELLED"),
        "ACKNOWLEDGED": ("CHANGE_PENDING", "IN_FULFILLMENT", "CANCELLED"),
        "CHANGE_PENDING": ("ISSUED", "PARTIALLY_ACKNOWLEDGED", "ACKNOWLEDGED", "CANCELLED"),
        "IN_FULFILLMENT": ("PARTIALLY_RECEIVED", "RECEIVED", "CLOSED"),
        "PARTIALLY_RECEIVED": ("RECEIVED", "CLOSED"), "RECEIVED": ("CLOSED",), "CANCELLED": (), "CLOSED": (),
    },
    "POLine": {
        "DRAFT": ("OPEN", "CANCELLED"), "OPEN": ("PARTIALLY_ACKNOWLEDGED", "ACKNOWLEDGED", "CHANGE_PENDING", "CANCELLED"),
        "PARTIALLY_ACKNOWLEDGED": ("ACKNOWLEDGED", "CHANGE_PENDING", "CANCELLED"),
        "ACKNOWLEDGED": ("CHANGE_PENDING", "IN_FULFILLMENT", "CANCELLED"),
        "CHANGE_PENDING": ("OPEN", "PARTIALLY_ACKNOWLEDGED", "ACKNOWLEDGED", "CANCELLED"),
        "IN_FULFILLMENT": ("PARTIALLY_RECEIVED", "RECEIVED"), "PARTIALLY_RECEIVED": ("RECEIVED",),
        "RECEIVED": ("CLOSED",), "CANCELLED": ("CLOSED",), "CLOSED": (),
    },
    "Acknowledgement": {
        "DRAFT": ("SUBMITTED", "WITHDRAWN"), "SUBMITTED": ("UNDER_REVIEW", "ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "SUPERSEDED", "WITHDRAWN"),
        "UNDER_REVIEW": ("ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "SUPERSEDED", "WITHDRAWN"),
        "ACCEPTED": ("SUPERSEDED",), "PARTIALLY_ACCEPTED": ("SUPERSEDED",), "REJECTED": ("SUPERSEDED",), "SUPERSEDED": (), "WITHDRAWN": (),
    },
    "PromiseDate": {"PROPOSED": ("CURRENT", "CANCELLED"), "CURRENT": ("SUPERSEDED", "CANCELLED"), "SUPERSEDED": (), "CANCELLED": ()},
    "ChangeRequest": {
        "DRAFT": ("SUBMITTED", "WITHDRAWN"), "SUBMITTED": ("UNDER_REVIEW", "APPROVED", "REJECTED", "CANCELLED", "WITHDRAWN"),
        "UNDER_REVIEW": ("APPROVED", "REJECTED", "CANCELLED", "WITHDRAWN"), "APPROVED": ("IMPLEMENTED", "CANCELLED"),
        "IMPLEMENTED": ("CLOSED",), "REJECTED": ("CLOSED",), "CANCELLED": ("CLOSED",), "WITHDRAWN": ("CLOSED",), "CLOSED": (),
    },
    "Approval": {"PENDING": ("APPROVED", "REJECTED", "ESCALATED", "WITHDRAWN"), "ESCALATED": ("APPROVED", "REJECTED", "WITHDRAWN"), "APPROVED": (), "REJECTED": (), "WITHDRAWN": ()},
    "InventoryPlan": {
        "DRAFT": ("PROPOSED", "ACTIVE", "CANCELLED"), "PROPOSED": ("APPROVED", "REJECTED", "CANCELLED"),
        "APPROVED": ("ACTIVE", "SUPERSEDED", "CANCELLED"), "REJECTED": ("DRAFT", "CLOSED"),
        "ACTIVE": ("AT_RISK", "PARTIALLY_FULFILLED", "FULFILLED", "SUPERSEDED", "CANCELLED"),
        "AT_RISK": ("ACTIVE", "PARTIALLY_FULFILLED", "FULFILLED", "SUPERSEDED", "CANCELLED"),
        "PARTIALLY_FULFILLED": ("FULFILLED", "SUPERSEDED"), "FULFILLED": ("CLOSED",),
        "SUPERSEDED": (), "CANCELLED": (), "CLOSED": (),
    },
    "ProductionOrder": {
        "PLANNED": ("AT_RISK", "RESCHEDULED", "CONFIRMED", "DELAYED", "CANCELLED"),
        "AT_RISK": ("RESCHEDULED", "CONFIRMED", "DELAYED", "CANCELLED"),
        "RESCHEDULED": ("AT_RISK", "CONFIRMED", "DELAYED", "CANCELLED"),
        "CONFIRMED": ("AT_RISK", "RESCHEDULED", "DELAYED", "CLOSED"),
        "DELAYED": ("RESCHEDULED", "CONFIRMED", "CANCELLED", "CLOSED"),
        "DRAFT": ("RELEASED", "CANCELLED"), "RELEASED": ("SCHEDULED", "ON_HOLD", "CANCELLED"),
        "SCHEDULED": ("IN_PROGRESS", "ON_HOLD", "CANCELLED"),
        "IN_PROGRESS": ("PARTIALLY_COMPLETED", "COMPLETED", "ON_HOLD"),
        "PARTIALLY_COMPLETED": ("IN_PROGRESS", "COMPLETED", "ON_HOLD"),
        "ON_HOLD": ("SCHEDULED", "IN_PROGRESS", "CANCELLED"), "COMPLETED": ("CLOSED",), "CANCELLED": ("CLOSED",), "CLOSED": (),
    },
    "Notification": {
        "QUEUED": ("SENT", "RETRY_PENDING", "FAILED", "CANCELLED"), "SENT": ("DELIVERED", "BOUNCED", "RETRY_PENDING", "FAILED"),
        "DELIVERED": (), "BOUNCED": ("RETRY_PENDING", "FAILED"), "RETRY_PENDING": ("SENT", "FAILED", "CANCELLED"), "FAILED": ("RETRY_PENDING", "CANCELLED"), "CANCELLED": (),
    },
}

@dataclass(frozen=True)
class FieldSpec:
    name: str
    sql_type: str
    required: bool
    domain: str
    units: str
    uniqueness: str
    validation_rule: str
    validator_name: str
    validator: Validator
    enum_values: tuple[str, ...] = ()
    foreign_key: str | None = None
    primary_key: bool = False

@dataclass(frozen=True)
class EntitySpec:
    name: str
    table_name: str
    primary_key: str
    fields: tuple[FieldSpec, ...]
    lifecycle_field: str | None = None
    unique_constraints: tuple[tuple[str, ...], ...] = ()
    row_count_full: str = ""
    row_count_starter: str = ""
    generation_step: str = "Generation Step 1 — data dictionary / schema"
    description: str = ""


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _id_validator(pattern: str) -> Validator:
    compiled = re.compile(pattern)
    def _validate(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
        if not isinstance(value, str) or not compiled.fullmatch(value):
            return f"must match ID format {pattern!r}"
        return None
    _validate.__name__ = "validate_" + field_key_from_pattern(pattern)
    return _validate


def field_key_from_pattern(pattern: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", pattern.lower()).strip("_")[:40]


def _check_nonblank(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if not isinstance(value, str) or not value.strip(): return "must be a non-empty trimmed string"
    if value != value.strip(): return "must not contain leading/trailing whitespace"
    return None


def _check_email(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value): return "must be a syntactically valid email address"
    return None


def _check_phone(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9 ()-]{7,24}", value): return "must contain 7–24 phone-format characters"
    return None


def _check_positive_int(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1: return "must be an integer >= 1"
    return None


def _check_nonnegative_int(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0: return "must be an integer >= 0"
    return None


def _check_decimal_nonnegative(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    number = _decimal(value)
    if number is None or number < 0: return "must be a finite decimal >= 0"
    return None


def _check_decimal_positive(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    number = _decimal(value)
    if number is None or number <= 0: return "must be a finite decimal > 0"
    return None


def _check_decimal_finite(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if _decimal(value) is None: return "must be a finite decimal number"
    return None


def _check_percent(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    number = _decimal(value)
    if number is None or number < 0 or number > 100: return "must be a finite percentage in [0, 100]"
    return None


def _check_signed_percent(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    number = _decimal(value)
    if number is None or number < -100 or number > 100:
        return "must be a finite signed percentage in [-100, 100]"
    return None

def _check_unit_interval(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    number = _decimal(value)
    if number is None or number < 0 or number > 1: return "must be a finite decimal in [0, 1]"
    return None


def _check_iso_date(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if _date(value) is None: return "must be a valid ISO-8601 date (YYYY-MM-DD) or date object"
    if isinstance(value, str) and value != _date(value).isoformat(): return "date string must use canonical YYYY-MM-DD"
    return None


def _check_iso_datetime(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if _datetime(value) is None: return "must be an ISO-8601 datetime with an explicit UTC offset or a timezone-aware datetime"
    return None


def _check_json_object(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if isinstance(value, Mapping): return None
    if not isinstance(value, str): return "must be a JSON object or JSON object string"
    try: parsed = json.loads(value)
    except json.JSONDecodeError: return "must contain valid JSON"
    if not isinstance(parsed, dict): return "JSON value must be an object"
    return None


def _check_nonnegative_or_none(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    number = _decimal(value)
    if number is None or number < 0: return "must be a finite decimal >= 0"
    return None


def _check_line_total(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    qty, price, amount = (_decimal(record.get("requested_qty")), _decimal(record.get("unit_price")), _decimal(value))
    if qty is None or price is None or amount is None: return "cannot be checked until requested_qty, unit_price, and line_total are valid decimals"
    expected = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount != expected: return f"must equal requested_qty × unit_price rounded to 2 decimals ({expected})"
    return None


def _check_line_amount(field_name: str) -> Validator:
    mapping = {
        "acknowledged_value": ("ack_accepted_qty", "acknowledged_unit_price"),
        "promised_value": ("promised_qty", "promised_unit_price"),
        "projected_value": ("projected_qty", "projected_unit_price"),
    }
    qty_field, price_field = mapping[field_name]
    def check(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
        qty, price, amount = (_decimal(record.get(qty_field)), _decimal(record.get(price_field)), _decimal(value))
        if qty is None or price is None or amount is None:
            return f"{field_name} requires {qty_field}, {price_field}, and {field_name} all to be set"
        expected = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount != expected: return f"must equal ROUND_HALF_UP({qty_field} × {price_field}, 2) ({expected})"
        return None
    check.__name__ = "validate_" + field_name
    return check


def _check_ack_reconciliation(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if record.get("status") not in {"ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED"}: return None
    req, accepted, rejected = (_decimal(record.get("requested_qty")), _decimal(record.get("ack_accepted_qty")), _decimal(record.get("ack_rejected_qty")))
    if None in (req, accepted, rejected): return "final acknowledgement requires valid requested/accepted/rejected quantities"
    if req != accepted + rejected: return "requested_qty must equal ack_accepted_qty + ack_rejected_qty for a final acknowledgement"
    return None


def _check_enum(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if field.enum_values and value not in field.enum_values: return f"must be one of {', '.join(field.enum_values)}"
    return None


def _context_row(context: Mapping[str, Any], table: str, key: str, value: Any) -> Mapping[str, Any] | None:
    """Look up a parent row using a validation-time index when available."""
    indexes = context.get("_record_index_cache", {})
    index = indexes.get((table, key)) if isinstance(indexes, Mapping) else None
    if index is not None:
        row = index.get(value)
        return row if isinstance(row, Mapping) else None
    for row in context.get(table, ()):
        if isinstance(row, Mapping) and row.get(key) == value:
            return row
    return None


def _check_foreign_key(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if not field.foreign_key or not context: return None
    table, key = field.foreign_key.split(".", 1)
    rows = context.get(table)
    if rows is None: return None
    # validate_dataset installs precomputed FK indexes to avoid rebuilding a large
    # parent-ID set for every child row (important at the 10k-PO / 40k-line scale).
    cache = context.get("_fk_id_cache", {})
    ids = cache.get((table, key)) if isinstance(cache, Mapping) else None
    if ids is None:
        ids = {r.get(key) if isinstance(r, Mapping) else r for r in rows}
    if value not in ids: return f"must reference an existing {field.foreign_key} value"
    return None


def _check_string_length(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    match = re.fullmatch(r"(?:VAR)?CHAR\((\d+)\)|CHAR\((\d+)\)", field.sql_type)
    if match and isinstance(value, str):
        maximum = int(match.group(1) or match.group(2))
        if len(value) > maximum: return f"must be at most {maximum} characters"
    return None


def _bounded_int(minimum: int, maximum: int, label: str) -> Validator:
    def check(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            return f"must be an integer in [{minimum}, {maximum}]"
        return None
    check.__name__ = label
    return check


def _text_limit(maximum: int, label: str, require_nonblank: bool = False) -> Validator:
    def check(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
        if not isinstance(value, str): return "must be text"
        if require_nonblank and not value.strip(): return "must be non-empty text"
        if len(value) > maximum: return f"must be at most {maximum} characters"
        return None
    check.__name__ = label
    return check


def _check_supplier_code(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,39}", value):
        return "must match ^[A-Z0-9][A-Z0-9-]{1,39}$"
    return None


def _check_decimal_precision(value: Any, field: FieldSpec) -> str | None:
    match = re.fullmatch(r"DECIMAL\((\d+),(\d+)\)", field.sql_type.upper())
    if not match: return None
    precision, scale = int(match.group(1)), int(match.group(2))
    number = _decimal(value)
    if number is None: return "must be a finite decimal number"
    max_abs = (Decimal(10) ** (precision - scale)) - (Decimal(10) ** (-scale))
    if abs(number) > max_abs: return f"exceeds DECIMAL({precision},{scale}) range"
    quant = number.quantize(Decimal(1).scaleb(-scale))
    if number != quant: return f"supports at most {scale} decimal places"
    return None


def _check_basic_sql_type(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    t = field.sql_type.upper()
    if t in {"TEXT", "JSON"} or t.startswith(("VARCHAR", "CHAR")):
        if not isinstance(value, (str, Mapping)) if t == "JSON" else not isinstance(value, str): return f"must have type {t}"
        return _check_string_length(value, record, context, field)
    if t == "INTEGER":
        if isinstance(value, bool) or not isinstance(value, int): return "must be an integer"
        return None
    if t.startswith("DECIMAL"):
        return _check_decimal_precision(value, field)
    if t == "DATE": return _check_iso_date(value, record, context, field)
    if t == "DATETIME": return _check_iso_datetime(value, record, context, field)
    if t == "BOOLEAN":
        if not isinstance(value, bool): return "must be a boolean"
        return None
    if t == "ENUM": return _check_enum(value, record, context, field)
    return None


VALIDATORS: dict[str, Validator] = {
    "basic_type": _check_basic_sql_type,
    "nonblank": _check_nonblank,
    "email": _check_email,
    "phone": _check_phone,
    "positive_int": _check_positive_int,
    "nonnegative_int": _check_nonnegative_int,
    "positive_decimal": _check_decimal_positive,
    "nonnegative_decimal": _check_decimal_nonnegative,
    "finite_decimal": _check_decimal_finite,
    "percent": _check_percent,
    "signed_percent": _check_signed_percent,
    "unit_interval": _check_unit_interval,
    "iso_date": _check_iso_date,
    "iso_datetime": _check_iso_datetime,
    "json_object": _check_json_object,
    "line_total": _check_line_total,
    "acknowledged_value_calc": _check_line_amount("acknowledged_value"),
    "promised_value_calc": _check_line_amount("promised_value"),
    "projected_value_calc": _check_line_amount("projected_value"),
    "ack_reconciliation": _check_ack_reconciliation,
    "enum": _check_enum,
    "foreign_key": _check_foreign_key,
    "string_length": _check_string_length,
    "supplier_code_format": _check_supplier_code,
    "signed_int_365": _bounded_int(-365, 365, "signed_int_365"),
    "int_0_365": _bounded_int(0, 365, "int_0_365"),
    "int_7_90": _bounded_int(7, 90, "int_7_90"),
    "int_1_99": _bounded_int(1, 99, "int_1_99"),
    "int_1_99": _bounded_int(1, 9999, "int_1_99"),
    "int_0_10": _bounded_int(0, 10, "int_0_10"),
    "text_max_4000": _text_limit(4000, "text_max_4000"),
    "text_max_2000": _text_limit(2000, "text_max_2000"),
    "text_nonblank_max_2000": _text_limit(2000, "text_nonblank_max_2000", True),
    "text_nonblank_max_8000": _text_limit(8000, "text_nonblank_max_8000", True),
}

# Field constructor: every field has the seven requested attributes and a real callable.
def F(name: str, sql_type: str, required: bool, domain: str, units: str,
      uniqueness: str, validation_rule: str, validator_name: str = "basic_type",
      enum_values: Sequence[str] = (), foreign_key: str | None = None,
      primary_key: bool = False) -> FieldSpec:
    fn = VALIDATORS[validator_name]
    return FieldSpec(name, sql_type, required, domain, units, uniqueness,
                     validation_rule, validator_name, fn, tuple(enum_values),
                     foreign_key, primary_key)

# ID validators are independent callable functions exported by this module.
def _make_id_check(function_name: str, pattern: str) -> Validator:
    compiled = re.compile(pattern)
    def check(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
        return None if isinstance(value, str) and compiled.fullmatch(value) else f"must match {pattern}"
    check.__name__ = function_name
    VALIDATORS[function_name] = check
    return check

_make_id_check("supplier_id_format", r"SUP-\d{6}")
_make_id_check("purchase_order_id_format", r"PO-2026-\d{6}")
_make_id_check("po_line_id_format", r"PO-2026-\d{6}-L\d{2}")
_make_id_check("acknowledgement_id_format", r"ACK-PO-2026-\d{6}-\d{2}")
_make_id_check("acknowledgement_line_id_format", r"AL-ACK-PO-2026-\d{6}-\d{2}-PO-2026-\d{6}-L\d{2}")
_make_id_check("promise_date_id_format", r"PD-ACK-PO-2026-\d{6}-\d{2}-\d{2}")
_make_id_check("change_request_id_format", r"CHG-PO-2026-\d{6}-\d{6}")
_make_id_check("approval_id_format", r"APR-CHG-PO-2026-\d{6}-\d{6}-\d{2}")
_make_id_check("inventory_plan_id_format", r"IP-PO-2026-\d{6}-L\d{2}-\d{2}")
_make_id_check("production_order_id_format", r"PRO-2026-\d{6}")
_make_id_check("notification_id_format", r"NOT-2026-\d{6}")
_make_id_check("actor_id_format", r"(?:SUP|PLN|CWH|LOG|OPS)-\d{6}")
_make_id_check("item_id_format", r"ITEM-\d{6}")
_make_id_check("warehouse_id_format", r"WH-\d{4}")
_make_id_check("carrier_id_format", r"CAR-\d{6}")

STATUS_VALUES = {name: tuple(values) for name, values in STATUS_ENUMS.items()}

ENTITIES: dict[str, EntitySpec] = {}

def _entity(name: str, table: str, pk: str, fields: Sequence[FieldSpec], *, status: str | None = None,
            unique: Sequence[Sequence[str]] = (), full: str, starter: str, description: str) -> None:
    ENTITIES[name] = EntitySpec(name, table, pk, tuple(fields), status,
                                tuple(tuple(x) for x in unique), full, starter,
                                "Generation Step 1 defines contract; Step 2+ creates records", description)


# Supporting table: one full immutable line snapshot for every PO line on every
# acknowledgement revision. This is intentionally outside ENTITIES because the
# problem statement's ten core entities remain unchanged; PromiseDate and the
# PO-level acknowledgement header have separate lifecycles.
ACKNOWLEDGEMENT_LINE_FIELDS: tuple[FieldSpec, ...] = (
    F("acknowledgement_line_id", "VARCHAR(64)", True, "AL-<ACK-id>-<PO-line-id>", "none", "Primary key; globally unique", "must embed the byte-identical ack_id and po_line_id", "acknowledgement_line_id_format", primary_key=True),
    F("ack_id", "VARCHAR(30)", True, "Existing Acknowledgement.ack_id", "none", "Foreign key to acknowledgements.ack_id", "must reference an existing ACK revision", "foreign_key", foreign_key="acknowledgements.ack_id"),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id", "must equal acknowledgement.po_id and parent PO of po_line_id", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("po_line_id", "VARCHAR(25)", True, "Existing POLine.po_line_id", "none", "Foreign key to po_lines.po_line_id", "must refer to a line within po_id", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("revision_no", "INTEGER", True, "Integer >= 1 matching the acknowledgement revision", "revision number", "Unique per (ack_id, po_line_id)", "must equal parent Acknowledgement.revision_no", "positive_int"),
    F("status", "ENUM", True, "ACCEPTED, PARTIALLY_ACCEPTED, REJECTED, SUPERSEDED", "none", "Not unique", "must describe outcome or SUPERSEDED for a non-current ACK revision", "enum", ("ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "SUPERSEDED")),
    F("requested_qty", "DECIMAL(12,3)", True, "Exact copied POLine.requested_qty; > 0", "quantity in PO-line UOM", "Not unique", "must equal parent PO line requested_qty to 0.001", "positive_decimal"),
    F("accepted_qty", "DECIMAL(12,3)", True, "0–requested_qty", "quantity in PO-line UOM", "Not unique", "0 <= accepted_qty <= requested_qty; computed before rejected_qty", "nonnegative_decimal"),
    F("rejected_qty", "DECIMAL(12,3)", True, "0–requested_qty", "quantity in PO-line UOM", "Not unique", "rejected_qty = requested_qty − accepted_qty; three-decimal arithmetic", "nonnegative_decimal"),
    F("rejected_reason", "ENUM", False, "capacity, price, stock, logistics or NULL", "none", "Not unique", "required iff rejected_qty > 0; NULL when rejected_qty = 0", "enum", ("capacity", "price", "stock", "logistics")),
    F("requested_unit_price", "DECIMAL(12,2)", True, "0.00–9999999999.99 copied from POLine.unit_price", "currency per UOM", "Not unique", "must equal source POLine.unit_price", "nonnegative_decimal"),
    F("acknowledged_unit_price", "DECIMAL(12,2)", True, "0.00–9999999999.99", "currency per UOM", "Not unique", "supplier quote for this revision; price delta below is computed from it", "nonnegative_decimal"),
    F("qty_delta_pct", "DECIMAL(9,4)", True, "-100.0000–100.0000", "% of requested quantity", "Computed, not sampled", "ROUND_HALF_UP(100 × (accepted_qty − requested_qty) / requested_qty, 4)", "signed_percent"),
    F("price_delta_pct", "DECIMAL(9,4)", True, "-100.0000–100.0000", "% of requested unit price", "Computed, not sampled", "ROUND_HALF_UP(100 × (acknowledged_unit_price − requested_unit_price) / requested_unit_price, 4); zero if requested price is zero", "signed_percent"),
    F("date_slip_days", "INTEGER", False, "-365–365 or NULL if no promise exists", "calendar days vs POLine.required_date", "Computed, not sampled", "promise_date − source POLine.required_date; NULL when accepted_qty is zero", "signed_int_365"),
    F("response_timestamp", "DATETIME", True, "Timezone-aware ISO datetime copied from parent ACK response", "UTC recommended", "Not unique", "must equal parent Acknowledgement.acknowledged_at and be >= PO order_date", "iso_datetime"),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "must be a valid timezone-aware timestamp", "iso_datetime"),
    F("created_by_role", "ENUM", True, "supplier", "none", "Not unique", "all line snapshots originate from the supplier's acknowledgement", "enum", ("supplier",)),
    F("created_by_actor_id", "VARCHAR(10)", True, "Supplier actor ID equal to Supplier.supplier_id", "none", "Foreign key to actors.actor_id", "must equal parent acknowledgement supplier_id and actor role supplier", "actor_id_format", foreign_key="actors.actor_id"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise an ANOMALY_TYPES label", "none", "Not unique", "NULL or valid anomaly; must pair with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise an ANOMALY_TYPES label", "none", "Not unique", "NULL or valid anomaly; must pair with issue_type", "enum", ANOMALY_TYPES),
)

_enum = lambda values: tuple(values)

_entity("Supplier", "suppliers", "supplier_id", [
    F("supplier_id", "VARCHAR(10)", True, "SUP- followed by exactly 6 digits", "none", "Primary key; globally unique", "fullmatch ^SUP-\\d{6}$", "supplier_id_format", primary_key=True),
    F("supplier_name", "VARCHAR(160)", True, "1–160 printable characters; trimmed", "none", "Not unique", "non-empty after trim; max 160 chars", "nonblank"),
    F("supplier_code", "VARCHAR(40)", True, "Uppercase letters, digits, hyphens; 2–40 chars", "none", "Unique globally", "fullmatch ^[A-Z0-9][A-Z0-9-]{1,39}$", "supplier_code_format"),
    F("supplier_contact_name", "VARCHAR(120)", True, "1–120 trimmed characters", "none", "Not unique", "non-empty after trim; max 120 chars", "nonblank"),
    F("supplier_contact_email", "VARCHAR(254)", True, "RFC-like address local@domain.tld", "none", "Not unique; contact lookup index recommended", "must contain one @ and a domain suffix", "email"),
    F("supplier_contact_phone", "VARCHAR(24)", False, "Optional phone digits; spaces, +, parentheses, hyphen allowed", "E.164 preferred", "Not unique", "7–24 characters matching phone-format whitelist", "phone"),
    F("supplier_status", "ENUM", True, "ACTIVE, ON_HOLD, BLOCKED, INACTIVE", "none", "Not unique", "value in supplier_status enum", "enum", ("ACTIVE", "ON_HOLD", "BLOCKED", "INACTIVE")),
    F("risk_tier", "ENUM", True, "LOW, MEDIUM, HIGH, CRITICAL", "none", "Not unique", "value in risk_tier enum", "enum", ("LOW", "MEDIUM", "HIGH", "CRITICAL")),
    F("region", "ENUM", True, ", ".join(REGIONS), "supplier operating region", "Not unique", "must be one of the configured synthetic regions", "enum", REGIONS),
    F("lead_time_days", "INTEGER", True, "7–90 for generated supplier rows", "calendar days", "Not unique", "integer in [7,90] for generated masters", "int_7_90"),
    F("reliability_score", "DECIMAL(5,4)", True, "0.0000–1.0000 inclusive", "unit interval; 1 is most reliable", "Not unique", "finite decimal in [0,1]", "unit_interval"),
    F("on_time_rate", "DECIMAL(5,4)", True, "0.0000–1.0000 inclusive; positively correlated with reliability_score", "fraction of deliveries on time", "Not unique", "finite decimal in [0,1]; generated as a dependent function of reliability_score", "unit_interval"),
    F("ack_rate", "DECIMAL(5,4)", True, "0.0000–1.0000; ACKed distinct POs / supplier PO count", "fraction", "Derived from PurchaseOrder and Acknowledgement", "recomputed from actual supplier PO and ACK rows", "unit_interval"),
    F("on_time_promise_rate", "DECIMAL(5,4)", True, "0.0000–1.0000; on-time CURRENT promises / CURRENT promises", "fraction", "Derived from PromiseDate and POLine", "CURRENT promised dates on/before requested POLine date divided by current promises", "unit_interval"),
    F("avg_slip_days", "DECIMAL(8,3)", True, "Average positive lateness across CURRENT promises", "calendar days", "Derived from PromiseDate and POLine", "mean of max(0, promised_date - requested_date), or 0 without promises", "nonnegative_decimal"),
    F("preferred_carrier_id", "VARCHAR(10)", True, "Existing CAR-###### carrier ID", "none", "Foreign key to carriers.carrier_id", "must reference an existing carrier master row", "carrier_id_format", foreign_key="carriers.carrier_id"),
    F("default_currency", "CHAR(3)", True, ", ".join(CURRENCIES), "ISO-4217 alphabetic code", "Not unique", "must be in supported currency list", "enum", CURRENCIES),
    F("data_owner_role", "ENUM", True, ", ".join(ACTOR_ROLES), "none", "Not unique", "must identify an owning actor role", "enum", ACTOR_ROLES),
    F("created_at", "DATETIME", True, "ISO-8601 datetime with timezone", "UTC recommended", "Not unique", "parseable timezone-aware datetime", "iso_datetime"),
    F("updated_at", "DATETIME", True, "ISO-8601 datetime with timezone", "UTC recommended", "Not unique", "must be >= created_at", "iso_datetime"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise one of: " + ", ".join(ANOMALY_TYPES), "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], unique=(("supplier_code",),), full="200", starter="40", description="Supplier master, reliability/lead-time characteristics, carrier preference, contact, and ownership data." )

_entity("PurchaseOrder", "purchase_orders", "po_id", [
    F("po_id", "VARCHAR(16)", True, "PO-2026- followed by exactly 6 digits, e.g. PO-2026-000001", "none", "Primary key; globally unique", "fullmatch ^PO-2026-\\d{6}$", "purchase_order_id_format", primary_key=True),
    F("supplier_id", "VARCHAR(10)", True, "Existing Supplier.supplier_id", "none", "Foreign key to suppliers.supplier_id", "must reference an existing supplier", "foreign_key", foreign_key="suppliers.supplier_id"),
    F("planner_actor_id", "VARCHAR(10)", True, "Actor ID with PLN- prefix", "none", "Foreign key to actors.actor_id", "must identify an actor whose role is planner", "foreign_key", foreign_key="actors.actor_id"),
    F("warehouse_id", "VARCHAR(7)", True, "WH- followed by exactly 4 digits", "none", "Foreign key to warehouses.warehouse_id", "fullmatch ^WH-\\d{4}$ and existing warehouse", "warehouse_id_format", foreign_key="warehouses.warehouse_id"),
    F("carrier_id", "VARCHAR(10)", True, "CAR- followed by exactly 6 digits", "none", "Foreign key to carriers.carrier_id", "fullmatch ^CAR-\\d{6}$ and existing carrier", "carrier_id_format", foreign_key="carriers.carrier_id"),
    F("order_date", "DATE", True, "Valid calendar date YYYY-MM-DD", "calendar date", "Not unique", "valid ISO date", "iso_date"),
    F("required_delivery_date", "DATE", True, "Valid calendar date; >= order_date", "calendar date", "Not unique", "required_delivery_date >= order_date", "iso_date"),
    F("response_due_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "response_due_at >= created_at", "iso_datetime"),
    F("currency", "CHAR(3)", True, ", ".join(CURRENCIES), "ISO-4217 alphabetic code", "Not unique", "must be in supported currency list", "enum", CURRENCIES),
    F("total_order_value", "DECIMAL(14,2)", True, "0.00–999999999999.99", "currency per PO", "Not unique", "finite non-negative amount; equals sum POLine.line_total", "nonnegative_decimal"),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["PurchaseOrder"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.PurchaseOrder", "enum", STATUS_ENUMS["PurchaseOrder"]),
    F("created_by_role", "ENUM", True, "planner or operations_manager", "none", "Not unique", "value in approved creating roles", "enum", ("planner", "operations_manager")),
    F("created_by_actor_id", "VARCHAR(10)", True, "PLN-###### or OPS-###### actor ID", "none", "Foreign key to actors.actor_id", "must reference actor matching created_by_role", "foreign_key", foreign_key="actors.actor_id"),
    F("supplier_contact_email", "VARCHAR(254)", True, "Snapshot email in syntactically valid form", "none", "Not unique", "valid email; snapshot may differ from current Supplier master", "email"),
    F("version_no", "INTEGER", True, "Integer >= 1", "revision number", "Not unique", "integer >= 1; increment on material PO mutation", "positive_int"),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime; >= order_date at date precision", "iso_datetime"),
    F("updated_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "updated_at >= created_at", "iso_datetime"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise listed anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(), full="10,000", starter="200", description="Purchase order header, supplier relationship, key dates, owner and value." )

_entity("POLine", "po_lines", "po_line_id", [
    F("po_line_id", "VARCHAR(25)", True, "<PO-id>-L followed by 2-digit line number, e.g. PO-2026-000001-L01", "none", "Primary key; globally unique", "fullmatch ^PO-2026-\\d{6}-L\\d{2}$", "po_line_id_format", primary_key=True),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id; unique with line_no", "must reference an existing PO", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("line_no", "INTEGER", True, "Integer 1–99", "line ordinal per PO", "Unique per po_id", "integer [1,99]; PO line ID suffix equals line_no", "int_1_99"),
    F("item_id", "VARCHAR(11)", True, "ITEM- followed by 6 digits", "none", "Foreign key to items.item_id", "fullmatch ^ITEM-\\d{6}$ and existing item", "item_id_format", foreign_key="items.item_id"),
    F("item_description", "VARCHAR(240)", True, "1–240 trimmed characters", "none", "Not unique", "non-empty after trim; max 240 chars", "nonblank"),
    F("requested_qty", "DECIMAL(12,3)", True, "0.001–999999999.999", "quantity in uom", "Not unique", "finite decimal > 0", "positive_decimal"),
    F("ack_accepted_qty", "DECIMAL(12,3)", True, "0–999999999.999", "quantity in uom", "Not unique", "finite decimal >= 0; final line statuses reconcile", "nonnegative_decimal"),
    F("ack_rejected_qty", "DECIMAL(12,3)", True, "0–999999999.999", "quantity in uom", "Not unique", "finite decimal >= 0; final line statuses reconcile", "nonnegative_decimal"),
    F("promised_qty", "DECIMAL(12,3)", True, "0–999999999.999", "quantity in uom", "Not unique", "finite decimal >= 0; valid promise cannot exceed requested quantity", "nonnegative_decimal"),
    F("projected_qty", "DECIMAL(12,3)", True, "0–999999999.999", "quantity in uom", "Not unique", "finite decimal >= 0; derived from accepted/promise and plan policy", "nonnegative_decimal"),
    F("uom", "ENUM", True, ", ".join(UNITS_OF_MEASURE), "unit of measure", "Not unique", "value in UOM list", "enum", UNITS_OF_MEASURE),
    F("currency", "CHAR(3)", True, ", ".join(CURRENCIES), "ISO-4217 alphabetic code inherited/snapshotted from PO", "Not unique", "must match parent PurchaseOrder.currency", "enum", CURRENCIES),
    F("unit_price", "DECIMAL(12,2)", True, "0.00–9999999999.99", "currency per uom", "Not unique", "finite decimal >= 0", "nonnegative_decimal"),
    F("acknowledged_unit_price", "DECIMAL(12,2)", False, "0.00–9999999999.99 or NULL until acknowledged", "currency per uom", "Not unique", "NULL or finite decimal >= 0", "nonnegative_decimal"),
    F("promised_unit_price", "DECIMAL(12,2)", False, "0.00–9999999999.99 or NULL until promise confirmed", "currency per uom", "Not unique", "NULL or finite decimal >= 0", "nonnegative_decimal"),
    F("projected_unit_price", "DECIMAL(12,2)", False, "0.00–9999999999.99 or NULL until projection exists", "currency per uom", "Not unique", "NULL or finite decimal >= 0", "nonnegative_decimal"),
    F("line_total", "DECIMAL(14,2)", True, "0.00–999999999999.99", "currency", "Not unique", "line_total = ROUND_HALF_UP(requested_qty × unit_price, 2)", "line_total"),
    F("acknowledged_value", "DECIMAL(14,2)", False, "0.00–999999999999.99 or NULL", "currency", "Not unique", "NULL or ROUND_HALF_UP(ack_accepted_qty × acknowledged_unit_price, 2)", "acknowledged_value_calc"),
    F("promised_value", "DECIMAL(14,2)", False, "0.00–999999999999.99 or NULL", "currency", "Not unique", "NULL or ROUND_HALF_UP(promised_qty × promised_unit_price, 2)", "promised_value_calc"),
    F("projected_value", "DECIMAL(14,2)", False, "0.00–999999999999.99 or NULL", "currency", "Not unique", "NULL or ROUND_HALF_UP(projected_qty × projected_unit_price, 2)", "projected_value_calc"),
    F("required_date", "DATE", True, "Valid date >= parent PO order_date", "calendar date", "Not unique", "required_date >= purchase_orders.order_date", "iso_date"),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["POLine"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.POLine", "enum", STATUS_ENUMS["POLine"]),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid timezone-aware datetime", "iso_datetime"),
    F("updated_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "updated_at >= created_at", "iso_datetime"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise listed anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(("po_id", "line_no"),), full="~40,000 (2–6 lines per PO)", starter="~800 (2–6 lines per PO)", description="Purchase order line quantities and values at requested, acknowledged, promised and projected stages." )

_entity("Acknowledgement", "acknowledgements", "ack_id", [
    F("ack_id", "VARCHAR(30)", True, "ACK-<PO-id>-NN, e.g. ACK-PO-2026-000001-01", "none", "Primary key; unique per PO revision", "ID PO portion equals po_id and suffix equals revision_no", "acknowledgement_id_format", primary_key=True),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id", "must reference an existing PO", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("supplier_id", "VARCHAR(10)", True, "Existing Supplier.supplier_id and same supplier as parent PO", "none", "Foreign key to suppliers.supplier_id", "must equal parent PO supplier_id", "foreign_key", foreign_key="suppliers.supplier_id"),
    F("po_line_id", "VARCHAR(25)", False, "Existing PO line belonging to po_id; NULL for header-level acknowledgement", "none", "Optional foreign key to po_lines.po_line_id", "if supplied, line must belong to same po_id", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("revision_no", "INTEGER", True, "Integer >= 1; formatted as 2 digits in ack_id", "revision number per PO", "Unique per po_id", "integer >= 1; ack_id suffix equals revision_no", "positive_int"),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["Acknowledgement"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.Acknowledgement", "enum", STATUS_ENUMS["Acknowledgement"]),
    F("lifecycle_state", "ENUM", True, ", ".join(ACK_LIFECYCLE_STATES), "none", "Not unique", "DRAFT → SUBMITTED → PROCESSED or EXCEPTION; late response becomes EXCEPTION", "enum", ACK_LIFECYCLE_STATES),
    F("acknowledged_at", "DATETIME", False, "Timezone-aware ISO datetime; NULL before supplier response", "UTC recommended", "Not unique", "NULL or >= created_at", "iso_datetime"),
    F("response_due_at", "DATETIME", True, "PO response deadline copied byte-for-byte from PurchaseOrder.response_due_at", "UTC recommended", "Not unique", "must equal parent PO response_due_at; may precede acknowledged_at for late supplier responses", "iso_datetime"),
    F("requested_qty", "DECIMAL(14,3)", True, "0.001–99999999999.999; sum of PO line requested_qty", "quantity across PO lines or scoped line", "Not unique", "finite decimal > 0; reconciles when final", "positive_decimal"),
    F("ack_accepted_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity", "Not unique", "finite decimal >= 0; requested = accepted + rejected for final status", "nonnegative_decimal"),
    F("ack_rejected_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity", "Not unique", "finite decimal >= 0; requested = accepted + rejected for final status", "nonnegative_decimal"),
    F("rejection_reason", "ENUM", False, "capacity, price, stock, logistics; required on partial/full rejection; retained after supersession", "none", "Not unique", "NULL for full acceptance; one of capacity/price/stock/logistics for PARTIALLY_ACCEPTED or REJECTED", "enum", ("capacity", "price", "stock", "logistics")),
    F("promised_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity", "Not unique", "finite decimal >= 0; promised_qty <= ack_accepted_qty for final status", "nonnegative_decimal"),
    F("projected_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity", "Not unique", "finite decimal >= 0; same UOM basis as requested_qty", "nonnegative_decimal"),
    F("requested_value", "DECIMAL(16,2)", True, "0.00–99999999999999.99", "PO currency", "Not unique", "must equal sum of PO line_total for header acknowledgements", "nonnegative_decimal"),
    F("acknowledged_value", "DECIMAL(16,2)", True, "0.00–99999999999999.99", "PO currency", "Not unique", "finite non-negative amount; based on accepted quantities and acknowledged prices", "nonnegative_decimal"),
    F("promised_value", "DECIMAL(16,2)", True, "0.00–99999999999999.99", "PO currency", "Not unique", "finite non-negative amount; based on promised quantities/prices", "nonnegative_decimal"),
    F("projected_value", "DECIMAL(16,2)", True, "0.00–99999999999999.99", "PO currency", "Not unique", "finite non-negative amount; based on downstream projected quantities/prices", "nonnegative_decimal"),
    F("qty_delta_pct", "DECIMAL(9,4)", True, "-100.0000–100.0000 signed percent", "% against aggregate requested quantity", "Computed, not sampled", "ROUND_HALF_UP(100 × (ack_accepted_qty − requested_qty) / requested_qty, 4)", "signed_percent"),
    F("price_delta_pct", "DECIMAL(9,4)", True, "-100.0000–100.0000 signed percent", "% weighted by requested quantity", "Computed, not sampled", "100 × (Σ requested_qty × acknowledged_unit_price − requested_value) / requested_value, rounded to 4 decimals; evaluated against acknowledgement_lines", "signed_percent"),
    F("date_slip_days", "INTEGER", False, "-365–365 or NULL when the acknowledgement has no promised accepted line", "calendar days vs requested delivery date", "Computed, not sampled", "maximum promised_date − POLine.required_date for the acknowledgement's promised lines", "signed_int_365"),
    F("supplier_note", "TEXT", False, "Free text up to application limit of 4,000 characters", "none", "Not unique", "string or NULL; maximum 4,000 characters", "text_max_4000"),
    F("superseded_by", "VARCHAR(30)", False, "ACK id of a later revision for the same PO; NULL if current/non-superseded", "none", "Self foreign key to acknowledgements.ack_id", "SUPERSEDED requires a later same-PO acknowledgement; non-SUPERSEDED has NULL", "foreign_key", foreign_key="acknowledgements.ack_id"),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime; <= acknowledged_at when acknowledged_at is set", "iso_datetime"),
    F("created_by_role", "ENUM", True, ", ".join(ACTOR_ROLES), "none", "Not unique", "value in ACTOR_ROLES", "enum", ACTOR_ROLES),
    F("created_by_actor_id", "VARCHAR(10)", True, "Actor ID associated with created_by_role", "none", "Foreign key to actors.actor_id", "must reference actor and role must match", "foreign_key", foreign_key="actors.actor_id"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise listed anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(), full="10,803 rows at default seed 20261022; all acknowledgement revisions count toward the 15,000 ACK + ChangeRequest event budget", starter="214 rows at default seed 20261022; all acknowledgement revisions count toward the 300 ACK + ChangeRequest event budget", description="PO-level supplier acknowledgement revision header. Each revision's full per-line quantity and price snapshot is retained in the supporting acknowledgement_lines table." )

_entity("PromiseDate", "promise_dates", "promise_date_id", [
    F("promise_date_id", "VARCHAR(40)", True, "PD-<ACK-id>-NN, e.g. PD-ACK-PO-2026-000001-01-01", "none", "Primary key; sequence unique within acknowledgement", "ID embeds ack_id and an exactly 2-digit sequence; suffix is unique under ack_id", "promise_date_id_format", primary_key=True),
    F("ack_id", "VARCHAR(30)", True, "Existing Acknowledgement.ack_id", "none", "Foreign key to acknowledgements.ack_id", "must reference existing acknowledgement", "foreign_key", foreign_key="acknowledgements.ack_id"),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id; same as acknowledgement PO", "none", "Foreign key to purchase_orders.po_id", "must equal referenced acknowledgement.po_id", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("po_line_id", "VARCHAR(25)", True, "Existing PO line belonging to po_id", "none", "Foreign key to po_lines.po_line_id", "must reference a line belonging to same po_id", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("sequence_no", "INTEGER", True, "Integer 1–99 per ack_id; exactly 2 digits in ID", "sequence under ACK", "Unique per ack_id", "integer [1,99]; suffix embedded in promise_date_id", "int_1_99"),
    F("revision_no", "INTEGER", True, "Integer >= 1 per po_line_id", "promise revision", "Unique per (ack_id, po_line_id, revision_no)", "integer >= 1 and increments when line promise changes", "positive_int"),
    F("promised_date", "DATE", True, "Valid date >= PO order_date", "calendar date", "Not unique", "promised_date >= purchase_orders.order_date; no invalid pre-order promise", "iso_date"),
    F("slip_days", "INTEGER", True, "Signed calendar-day difference from POLine.required_date", "calendar days", "Derived", "promised_date minus source POLine.required_date", "signed_int_365"),
    F("is_late", "BOOLEAN", True, "True iff promised_date is after POLine.required_date", "boolean", "Derived", "equivalent to slip_days > 0", "basic_type"),
    F("promised_qty", "DECIMAL(12,3)", True, "0.000–99999999999.999", "quantity in PO-line UOM", "Not unique", "must equal accepted_qty in acknowledgement_lines for the same ack_id and po_line_id", "nonnegative_decimal"),
    F("promise_confidence", "ENUM", True, ", ".join(PROMISE_CONFIDENCE_LEVELS), "none", "Not unique", "HIGH/MEDIUM/LOW confidence derived from supplier reliability plus configured noise", "enum", PROMISE_CONFIDENCE_LEVELS),
    F("ship_from_location", "VARCHAR(160)", True, "Warehouse name in synthetic warehouse network", "location name", "Not unique", "must equal warehouses.warehouse_name for ship_from_warehouse_id", "nonblank"),
    F("ship_from_warehouse_id", "VARCHAR(10)", True, "Existing WH-#### identifier", "none", "Foreign key to warehouses.warehouse_id", "must reference an existing warehouse", "warehouse_id_format", foreign_key="warehouses.warehouse_id"),
    F("carrier_id", "VARCHAR(10)", True, "Existing CAR-###### identifier", "none", "Foreign key to carriers.carrier_id", "must reference an existing carrier", "carrier_id_format", foreign_key="carriers.carrier_id"),
    F("carrier_reference", "VARCHAR(30)", True, "Carrier code in carrier master", "none", "Not unique", "must equal carriers.carrier_code for carrier_id", "nonblank"),
    F("carrier_operator_actor_id", "VARCHAR(10)", True, "CWH-###### actor identifier", "none", "Foreign key to actors.actor_id", "must reference an actor whose role is carrier_warehouse_operator", "actor_id_format", foreign_key="actors.actor_id"),
    F("prior_promised_date", "DATE", False, "Prior valid promised date or NULL for first revision", "calendar date", "Not unique", "NULL for first revision; otherwise prior to or different from promised_date", "iso_date"),
    F("effective_date", "DATE", True, "Valid date >= record creation date for new forward-effective promises", "calendar date", "Not unique", "effective_date >= DATE(created_at) for newly created promises", "iso_date"),
    F("response_due_date", "DATE", True, "Valid date >= effective_date", "calendar date", "Not unique", "response_due_date >= effective_date", "iso_date"),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["PromiseDate"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.PromiseDate", "enum", STATUS_ENUMS["PromiseDate"]),
    F("superseded_by", "VARCHAR(40)", False, "PromiseDate ID of next revision or NULL", "none", "Self foreign key to promise_dates.promise_date_id", "SUPERSEDED rows require next revision; otherwise NULL", "foreign_key", foreign_key="promise_dates.promise_date_id"),
    F("source", "ENUM", True, "SUPPLIER_PORTAL, EMAIL, EDI, API, MANUAL", "none", "Not unique", "value in promise source enum", "enum", ("SUPPLIER_PORTAL", "EMAIL", "EDI", "API", "MANUAL")),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime; effective_date is not before its date", "iso_datetime"),
    F("created_by_role", "ENUM", True, ", ".join(ACTOR_ROLES), "none", "Not unique", "value in ACTOR_ROLES", "enum", ACTOR_ROLES),
    F("created_by_actor_id", "VARCHAR(10)", True, "Actor ID associated with created_by_role", "none", "Foreign key to actors.actor_id", "must reference actor and role must match", "foreign_key", foreign_key="actors.actor_id"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise listed anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(("ack_id", "sequence_no"),), full="34,097 line-promise rows at default seed 20261022; count varies with accepted lines and ACK revisions", starter="669 line-promise rows at default seed 20261022; count varies with accepted lines and ACK revisions", description="Line-specific promised dates, independently versioned and traceable to acknowledgement and PO line." )

_entity("ChangeRequest", "change_requests", "change_request_id", [
    F("change_request_id", "VARCHAR(40)", True, "CHG-<PO-id>- followed by 6 digits, e.g. CHG-PO-2026-000001-000001", "none", "Primary key; globally unique", "fullmatch ^CHG-PO-2026-NNNNNN-NNNNNN$", "change_request_id_format", primary_key=True),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id", "must reference an existing PO", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("supplier_id", "VARCHAR(10)", True, "Existing Supplier.supplier_id; same as parent PO", "none", "Foreign key to suppliers.supplier_id", "must equal parent PO supplier_id", "foreign_key", foreign_key="suppliers.supplier_id"),
    F("po_line_id", "VARCHAR(25)", False, "Existing PO line belonging to po_id; NULL for PO-wide change", "none", "Optional foreign key to po_lines.po_line_id", "if supplied, line must belong to same PO", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("request_type", "ENUM", True, "QUANTITY_CHANGE, DATE_CHANGE, PRICE_CHANGE, CANCEL_LINE, CANCEL_PO", "none", "Not unique", "value in request_type enum", "enum", ("QUANTITY_CHANGE", "DATE_CHANGE", "PRICE_CHANGE", "CANCEL_LINE", "CANCEL_PO")),
    F("change_type", "ENUM", True, "price, date, quantity", "none", "Not unique", "normalized change type; must match request_type", "enum", ("price", "date", "quantity")),
    F("old_value", "VARCHAR(64)", True, "Source value as text: numeric for price/quantity; ISO date for date", "type-dependent", "Not unique", "non-empty value derived from source records", "nonblank"),
    F("new_value", "VARCHAR(64)", True, "Observed/proposed value as text: numeric for price/quantity; ISO date for date", "type-dependent", "Not unique", "non-empty value derived from source records", "nonblank"),
    F("delta", "DECIMAL(14,4)", True, "Signed % for price/quantity; signed calendar days for date", "type-dependent", "Not unique", "Computed from old_value and new_value, not independently sampled", "finite_decimal"),
    F("delta_abs", "DECIMAL(14,4)", True, "Absolute value of delta", "type-dependent", "Derived", "abs(delta)", "nonnegative_decimal"),
    F("delta_pct", "DECIMAL(14,4)", False, "Signed percentage for price/quantity; NULL for date changes", "percent", "Derived", "equals delta for price/quantity, NULL for date changes", "signed_percent"),
    F("required_approval_level", "ENUM", True, "planner, operations_manager", "none", "Derived", "computed by configured threshold rules from source old/new values", "enum", ("planner", "operations_manager")),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["ChangeRequest"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.ChangeRequest", "enum", STATUS_ENUMS["ChangeRequest"]),
    F("requested_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime", "iso_datetime"),
    F("effective_date", "DATE", True, "Valid date >= request date", "calendar date", "Not unique", "effective_date >= DATE(requested_at)", "iso_date"),
    F("response_due_date", "DATE", True, "Valid date >= request date", "calendar date", "Not unique", "response_due_date >= DATE(requested_at)", "iso_date"),
    F("previous_qty", "DECIMAL(12,3)", False, "0–999999999.999 or NULL when not a quantity change", "quantity in line UOM", "Not unique", "NULL or finite decimal >= 0", "nonnegative_decimal"),
    F("requested_qty", "DECIMAL(12,3)", False, "0–999999999.999 or NULL when not a quantity change", "quantity in line UOM", "Not unique", "QUANTITY_CHANGE requires requested_qty > 0 and previous_qty set", "nonnegative_decimal"),
    F("previous_unit_price", "DECIMAL(12,2)", False, "0.00–9999999999.99 or NULL", "currency per UOM", "Not unique", "NULL or finite decimal >= 0", "nonnegative_decimal"),
    F("requested_unit_price", "DECIMAL(12,2)", False, "0.00–9999999999.99 or NULL", "currency per UOM", "Not unique", "PRICE_CHANGE requires requested_unit_price and previous_unit_price", "nonnegative_decimal"),
    F("previous_promised_date", "DATE", False, "Prior promised date or NULL", "calendar date", "Not unique", "NULL or valid ISO date", "iso_date"),
    F("requested_promised_date", "DATE", False, "Requested new promised date or NULL", "calendar date", "Not unique", "DATE_CHANGE requires requested_promised_date >= order_date", "iso_date"),
    F("reason_code", "ENUM", True, "SUPPLIER_CAPACITY, MATERIAL_SHORTAGE, TRANSPORT_DELAY, QUALITY_HOLD, PRICE_CHANGE, CUSTOMER_PRIORITY, DATA_CORRECTION, OTHER", "none", "Not unique", "value in reason_code enum", "enum", ("SUPPLIER_CAPACITY", "MATERIAL_SHORTAGE", "TRANSPORT_DELAY", "QUALITY_HOLD", "PRICE_CHANGE", "CUSTOMER_PRIORITY", "DATA_CORRECTION", "OTHER")),
    F("reason_text", "TEXT", True, "1–2,000 trimmed characters", "none", "Not unique", "non-empty text <= 2,000 chars", "text_nonblank_max_2000"),
    F("requested_by_role", "ENUM", True, ", ".join(ACTOR_ROLES), "none", "Not unique", "value in ACTOR_ROLES", "enum", ACTOR_ROLES),
    F("requested_by_actor_id", "VARCHAR(10)", True, "Actor ID associated with requester role", "none", "Foreign key to actors.actor_id", "must reference actor and role must match", "foreign_key", foreign_key="actors.actor_id"),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "created_at <= requested_at; timestamps are timezone-aware", "iso_datetime"),
    F("updated_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "updated_at >= created_at", "iso_datetime"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise listed anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(), full="4,197 residual rows at default seed 20261022; ACK rows + ChangeRequest rows = 15,000 events", starter="86 residual rows at default seed 20261022; ACK rows + ChangeRequest rows = 300 events", description="Source-derived supplier/planner change requests with signed price/quantity percentage deltas or date-slip days; configured thresholds determine planner approval versus operations-manager escalation. Lifecycle state history is captured in entity_event." )

_entity("Approval", "approvals", "approval_id", [
    F("approval_id", "VARCHAR(50)", True, "APR-<change_request_id>-NN, e.g. APR-CHG-PO-2026-000001-000001-01", "none", "Primary key; unique per change approval round", "ID embeds change_request_id and 2-digit approval round", "approval_id_format", primary_key=True),
    F("change_request_id", "VARCHAR(40)", True, "Existing ChangeRequest.change_request_id", "none", "Foreign key to change_requests.change_request_id", "must reference existing change request", "foreign_key", foreign_key="change_requests.change_request_id"),
    F("approval_round", "INTEGER", True, "Integer 1–99", "approval round", "Unique per change_request_id", "integer [1,99]; approval_id suffix equals approval_round", "int_1_99"),
    F("approver_role", "ENUM", True, "planner or operations_manager only", "none", "Not unique", "value in APPROVER_ROLES", "enum", APPROVER_ROLES),
    F("approval_level", "ENUM", True, "planner or operations_manager", "none", "Not unique", "approval_level must equal approver_role; used by can_apply routing rule", "enum", APPROVER_ROLES),
    F("approver_actor_id", "VARCHAR(10)", True, "PLN-###### or OPS-######", "none", "Foreign key to actors.actor_id", "must reference actor matching approver_role", "foreign_key", foreign_key="actors.actor_id"),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["Approval"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.Approval", "enum", STATUS_ENUMS["Approval"]),
    F("requested_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime", "iso_datetime"),
    F("due_at", "DATETIME", True, "Timezone-aware ISO datetime >= requested_at", "UTC recommended", "Not unique", "due_at >= requested_at", "iso_datetime"),
    F("decided_at", "DATETIME", False, "Timezone-aware ISO datetime; NULL while PENDING", "UTC recommended", "Not unique", "PENDING requires NULL; terminal decision requires timestamp >= requested_at", "iso_datetime"),
    F("decision_reason", "TEXT", False, "0–2,000 characters; required when rejected/escalated", "none", "Not unique", "REJECTED or ESCALATED requires non-empty decision_reason; max 2,000 chars", "text_max_2000"),
    F("comments", "TEXT", True, "1–2,000 trimmed characters", "none", "Not unique", "Human-readable comments for the approval step; never mutated after insert", "text_nonblank_max_2000"),
    F("threshold_name", "ENUM", False, "PRICE_CHANGE_PCT, DATE_SLIP_DAYS, QUANTITY_CHANGE_PCT, CANCELLATION, MANUAL_EXCEPTION", "none", "Not unique", "NULL or recognized approval trigger", "enum", ("PRICE_CHANGE_PCT", "DATE_SLIP_DAYS", "QUANTITY_CHANGE_PCT", "CANCELLATION", "MANUAL_EXCEPTION")),
    F("threshold_value", "DECIMAL(12,3)", False, "Finite non-negative numeric threshold or NULL", "percent, days or quantity depending on threshold_name", "Not unique", "NULL or finite decimal >= 0", "nonnegative_decimal"),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime; created_at <= requested_at", "iso_datetime"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise listed anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(("change_request_id", "approval_round"),), full="6,188 append-only approval rows at default seed 20261022, including escalations and pending silence chases", starter="128 append-only approval rows at default seed 20261022, including escalations and pending silence chases", description="Append-only planner/operations-manager decisions, comments, escalations, and pending approval steps; a later decision or appeal is inserted as a new row." )

_entity("InventoryPlan", "inventory_plans", "inventory_plan_id", [
    F("inventory_plan_id", "VARCHAR(32)", True, "IP-<po_line_id>-NN, e.g. IP-PO-2026-000001-L01-01", "none", "Primary key; globally unique", "ID embeds po_line_id plus 2-digit plan revision", "inventory_plan_id_format", primary_key=True),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id", "must equal PO of po_line_id", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("po_line_id", "VARCHAR(25)", True, "Existing POLine.po_line_id", "none", "Foreign key to po_lines.po_line_id", "must reference existing PO line", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("plan_revision_no", "INTEGER", True, "Integer 1–99; 2-digit suffix in ID", "plan revision", "Unique per po_line_id", "integer [1,99]; suffix equals plan_revision_no", "int_1_99"),
    F("plan_version", "INTEGER", True, "Append-only projection version, beginning at 1 per PO line", "version", "Unique per po_line_id and equal to plan_revision_no", "integer >= 1; monotonically increments per PO line", "positive_int"),
    F("previous_version_id", "VARCHAR(32)", False, "Previous InventoryPlan version for the same PO line", "none", "Self foreign key to inventory_plans.inventory_plan_id", "NULL only for version 1; otherwise links to prior plan version", "foreign_key", foreign_key="inventory_plans.inventory_plan_id"),
    F("source", "ENUM", True, "po_baseline, approved_ack, approved_change", "none", "Not unique", "Projection provenance; non-baseline rows require processed ACK/passed approval gate", "enum", ("po_baseline", "approved_ack", "approved_change")),
    F("is_effective", "INTEGER", True, "0 or 1; exactly one effective version per PO line", "boolean flag", "One effective row per po_line_id", "1 only on latest version; history rows remain append-only", "basic_type"),
    F("projected_delivery_date", "DATE", True, "Projected supply delivery date", "calendar date", "Not unique", "Derived from baseline required date or an approved current PromiseDate", "iso_date"),
    F("change_request_id", "VARCHAR(40)", False, "Approved source change that caused this projection version", "none", "Foreign key to change_requests.change_request_id", "NULL for baseline and ACK-only projections; otherwise implemented change", "foreign_key", foreign_key="change_requests.change_request_id"),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["InventoryPlan"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.InventoryPlan", "enum", STATUS_ENUMS["InventoryPlan"]),
    F("demand_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity in PO line UOM", "Not unique", "finite decimal >= 0", "nonnegative_decimal"),
    F("requested_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity in PO line UOM", "Not unique", "copied from POLine.requested_qty unless anomaly-labelled", "nonnegative_decimal"),
    F("acknowledged_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity in PO line UOM", "Not unique", "finite decimal >= 0", "nonnegative_decimal"),
    F("promised_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity in PO line UOM", "Not unique", "finite decimal >= 0", "nonnegative_decimal"),
    F("projected_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity in PO line UOM", "Not unique", "projected receipt cannot be negative; compare with demand_qty", "nonnegative_decimal"),
    F("on_hand_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity in UOM", "Not unique", "finite decimal >= 0", "nonnegative_decimal"),
    F("reserved_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity in UOM", "Not unique", "finite decimal >= 0; reserved_qty <= on_hand_qty for valid rows", "nonnegative_decimal"),
    F("planned_receipt_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity in UOM", "Not unique", "finite decimal >= 0", "nonnegative_decimal"),
    F("projected_available_qty", "DECIMAL(14,3)", True, "May be negative for diagnosed shortages; within DECIMAL(14,3)", "quantity in UOM", "Not unique", "projected_available_qty = on_hand_qty - reserved_qty + planned_receipt_qty", "finite_decimal"),
    F("projected_shortage_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity in UOM", "Not unique", "max(0, demand_qty - projected_available_qty)", "nonnegative_decimal"),
    F("required_date", "DATE", True, "Valid date >= parent PO order_date", "calendar date", "Not unique", "required_date >= parent PO order_date", "iso_date"),
    F("promised_date", "DATE", False, "Current promised date or NULL until supplier commitment", "calendar date", "Not unique", "NULL or valid ISO date >= parent PO order_date", "iso_date"),
    F("plan_start_date", "DATE", True, "Valid date; <= plan_end_date", "calendar date", "Not unique", "plan_start_date <= plan_end_date", "iso_date"),
    F("plan_end_date", "DATE", True, "Valid date; >= plan_start_date", "calendar date", "Not unique", "plan_end_date >= plan_start_date", "iso_date"),
    F("planner_actor_id", "VARCHAR(10)", True, "PLN-######", "none", "Foreign key to actors.actor_id", "must reference actor with role planner", "foreign_key", foreign_key="actors.actor_id"),
    F("approved_by_actor_id", "VARCHAR(10)", False, "PLN-###### or OPS-######; NULL before approval", "none", "Foreign key to actors.actor_id", "if status APPROVED or ACTIVE requires approver; approver role planner or operations_manager", "foreign_key", foreign_key="actors.actor_id"),
    F("effective_date", "DATE", True, "Valid date", "calendar date", "Not unique", "effective_date >= DATE(created_at)", "iso_date"),
    F("superseded_by", "VARCHAR(32)", False, "InventoryPlan ID of replacement or NULL", "none", "Self foreign key to inventory_plans.inventory_plan_id", "SUPERSEDED requires replacement; otherwise NULL", "foreign_key", foreign_key="inventory_plans.inventory_plan_id"),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime", "iso_datetime"),
    F("updated_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "updated_at >= created_at", "iso_datetime"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise listed anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(("po_line_id", "plan_revision_no"),), full="39,876 baseline rows plus at most one approval-gated projection per PO line", starter="791 baseline rows plus at most one approval-gated projection per PO line at default seed", description="Append-only projected supply snapshots: one original PO-line baseline and at most one current approved promise/change projection per line." )

_entity("ProductionOrder", "production_orders", "production_order_id", [
    F("production_order_id", "VARCHAR(16)", True, "PRO-2026- followed by exactly 6 digits", "none", "Primary key; globally unique", "fullmatch ^PRO-2026-\\d{6}$", "production_order_id_format", primary_key=True),
    F("inventory_plan_id", "VARCHAR(32)", True, "Existing InventoryPlan.inventory_plan_id", "none", "Foreign key to inventory_plans.inventory_plan_id", "must reference existing inventory plan", "foreign_key", foreign_key="inventory_plans.inventory_plan_id"),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id", "must equal plan PO", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("po_line_id", "VARCHAR(25)", True, "Existing POLine.po_line_id", "none", "Foreign key to po_lines.po_line_id", "must equal plan PO line", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("required_by_date", "DATE", True, "Date component must be available to production", "calendar date", "Not unique", "valid ISO date; used to identify promise conflicts", "iso_date"),
    F("planned_start_date", "DATE", True, "Current planned production start date", "calendar date", "Not unique", "valid ISO date and derived from the current projected delivery after rescheduling", "iso_date"),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["ProductionOrder"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.ProductionOrder", "enum", STATUS_ENUMS["ProductionOrder"]),
    F("at_risk", "BOOLEAN", True, "True for AT_RISK or DELAYED lifecycle state", "boolean", "Derived", "computed from current ProductionOrder.status", "basic_type"),
    F("shortfall_qty", "DECIMAL(14,3)", True, "max(0, allocated_quantity - current projected supply)", "quantity in PO-line UOM", "Derived", "computed from production_order_line allocation and effective InventoryPlan projection", "nonnegative_decimal"),
    F("delay_days", "INTEGER", True, "Positive days current projected delivery exceeds required_by_date; else 0", "calendar days", "Derived", "max(0, projected_delivery_date - required_by_date)", "nonnegative_int"),
    F("planned_qty", "DECIMAL(14,3)", True, "0.001–99999999999.999", "finished-good quantity", "Not unique", "finite decimal > 0", "positive_decimal"),
    F("released_qty", "DECIMAL(14,3)", True, "0–planned_qty", "finished-good quantity", "Not unique", "0 <= released_qty <= planned_qty", "nonnegative_decimal"),
    F("completed_qty", "DECIMAL(14,3)", True, "0–released_qty", "finished-good quantity", "Not unique", "0 <= completed_qty <= released_qty <= planned_qty", "nonnegative_decimal"),
    F("affected_material_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "input material quantity", "Not unique", "finite decimal >= 0", "nonnegative_decimal"),
    F("priority", "ENUM", True, "LOW, NORMAL, HIGH, URGENT", "none", "Not unique", "value in production priority enum", "enum", ("LOW", "NORMAL", "HIGH", "URGENT")),
    F("original_start_date", "DATE", True, "Valid planned date", "calendar date", "Not unique", "valid ISO date", "iso_date"),
    F("current_start_date", "DATE", True, "Valid current schedule date", "calendar date", "Not unique", "valid ISO date; may differ from original_start_date", "iso_date"),
    F("scheduled_end_date", "DATE", True, "Valid date >= current_start_date", "calendar date", "Not unique", "scheduled_end_date >= current_start_date", "iso_date"),
    F("actual_start_date", "DATE", False, "Actual start date or NULL before execution", "calendar date", "Not unique", "NULL or actual_start_date >= current_start_date unless approved expedite", "iso_date"),
    F("actual_end_date", "DATE", False, "Actual completion date or NULL until completed", "calendar date", "Not unique", "NULL or actual_end_date >= actual_start_date", "iso_date"),
    F("schedule_shift_days", "INTEGER", True, "-365–365; signed difference from original start", "calendar days", "Not unique", "integer in [-365,365] and equals current_start_date - original_start_date in days", "signed_int_365"),
    F("owner_role", "ENUM", True, "planner or operations_manager", "none", "Not unique", "value in allowed production-owner roles", "enum", ("planner", "operations_manager")),
    F("owner_actor_id", "VARCHAR(10)", True, "PLN-###### or OPS-######", "none", "Foreign key to actors.actor_id", "must reference actor matching owner_role", "foreign_key", foreign_key="actors.actor_id"),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime", "iso_datetime"),
    F("updated_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "updated_at >= created_at", "iso_datetime"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise listed anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(), full="5,000 initial production orders (configurable planning slice)", starter="100 initial production orders", description="Downstream production schedules affected by component availability or changed supplier promises." )

_entity("Notification", "notifications", "notification_id", [
    F("notification_id", "VARCHAR(16)", True, "NOT-2026- followed by exactly 6 digits", "none", "Primary key; globally unique", "fullmatch ^NOT-2026-\\d{6}$", "notification_id_format", primary_key=True),
    F("not_id", "VARCHAR(16)", True, "Same traceable identifier as notification_id", "none", "Unique alias for notification_id", "must equal notification_id", "nonblank"),
    F("not_type", "VARCHAR(40)", True, "Template key describing the notification event", "none", "Not unique", "nonblank; e.g. CHANGE_RAISED, PLAN_UPDATED, DOWNSTREAM_IMPACT", "nonblank"),
    F("severity", "ENUM", True, "INFO, LOW, MEDIUM, HIGH, CRITICAL", "none", "Not unique", "severity derived from event type/impact severity", "enum", ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")),
    F("subject", "VARCHAR(200)", True, "Rendered notification subject", "none", "Not unique", "non-empty; must match title", "nonblank"),
    F("related_entity_type", "VARCHAR(40)", True, "Trace root entity type", "none", "Not unique", "entity ID in related_entity_id can be traced to its source PO/supplier", "nonblank"),
    F("related_entity_id", "VARCHAR(40)", True, "Trace root entity ID", "none", "Not unique", "must be present and resolve to a source entity", "nonblank"),
    F("read_status", "ENUM", True, "UNREAD, READ", "none", "Not unique", "read state is separate from send/delivery status", "enum", ("UNREAD", "READ")),
    F("po_id", "VARCHAR(16)", False, "Existing PurchaseOrder.po_id or NULL for a system-wide notice", "none", "Optional foreign key to purchase_orders.po_id", "NULL only for system-wide notices without an acknowledgement or change link", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("open_impact_count", "INTEGER", True, "Count of open downstream impacts for related PO", "impact records", "Derived", "counts impacts for PO whose production order remains AT_RISK or DELAYED", "nonnegative_int"),
    F("ack_id", "VARCHAR(30)", False, "Acknowledgement id or NULL when notification is not ack-specific", "none", "Optional foreign key to acknowledgements.ack_id", "if supplied, po_id must be supplied and acknowledgement must belong to it", "foreign_key", foreign_key="acknowledgements.ack_id"),
    F("change_request_id", "VARCHAR(40)", False, "ChangeRequest id or NULL when notification is unrelated to a change", "none", "Optional foreign key to change_requests.change_request_id", "if supplied, po_id must be supplied and change request must belong to it", "foreign_key", foreign_key="change_requests.change_request_id"),
    F("source_event_id", "VARCHAR(40)", False, "entity_event identifier or NULL for direct notifications", "none", "Optional foreign key to entity_event.event_id", "if supplied, event must exist in append-only entity event ledger", "foreign_key", foreign_key="entity_event.event_id"),
    F("channel", "ENUM", True, "IN_APP, EMAIL, SMS, WEBHOOK", "none", "Not unique", "value in notification channel enum", "enum", ("IN_APP", "EMAIL", "SMS", "WEBHOOK")),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["Notification"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.Notification", "enum", STATUS_ENUMS["Notification"]),
    F("title", "VARCHAR(200)", True, "1–200 trimmed characters", "none", "Not unique", "non-empty after trim; max 200 chars", "nonblank"),
    F("body", "TEXT", True, "1–8,000 characters", "none", "Not unique", "non-empty text <= 8,000 chars", "text_nonblank_max_8000"),
    F("scheduled_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "scheduled_at >= created_at", "iso_datetime"),
    F("sent_at", "DATETIME", False, "Timezone-aware ISO datetime; NULL until attempted", "UTC recommended", "Not unique", "NULL or sent_at >= scheduled_at", "iso_datetime"),
    F("delivered_at", "DATETIME", False, "Timezone-aware ISO datetime; NULL until delivery confirmed", "UTC recommended", "Not unique", "DELIVERED requires value >= sent_at; otherwise may be NULL", "iso_datetime"),
    F("retry_count", "INTEGER", True, "Integer 0–10 inclusive", "attempt count", "Not unique", "integer in [0,10]", "int_0_10"),
    F("last_error", "TEXT", False, "Error details up to 2,000 characters or NULL", "none", "Not unique", "NULL or string <= 2,000 chars; set for FAILED/BOUNCED", "text_max_2000"),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime", "iso_datetime"),
    F("issue_type", "ENUM", False, "NULL for normal rows; NOTIFICATION_FAILURE or other listed anomaly", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(), full="Event-driven: change, approval, plan, impact, silence, and weekly-summary notices; recipient links stored separately", starter="Event-driven notices including change, approval, plan, impact, silence, and weekly-summary events", description="Traceable notification fan-out to supplier and operational role recipients, with separate read status and delivery/retry outcome." )

# The data dictionary itself is Generation Step 1; these later steps create the entity rows.
_GENERATION_STEPS = {
    "Supplier": "Step 2 — supplier/master-data generation",
    "PurchaseOrder": "Step 3 — purchase-order header generation",
    "POLine": "Step 3 — purchase-order line generation",
    "Acknowledgement": "Step 4 — acknowledgement/revision generation",
    "PromiseDate": "Step 4 — line-level promise-date generation",
    "ChangeRequest": "Step 5 — change-request generation",
    "Approval": "Step 5 — approval/decision generation",
    "InventoryPlan": "Step 6 — inventory-plan generation",
    "ProductionOrder": "Step 6 — downstream production-order generation",
    "Notification": "Step 7 — event-driven notification generation",
}
for _entity_name, _step in _GENERATION_STEPS.items():
    _old = ENTITIES[_entity_name]
    ENTITIES[_entity_name] = EntitySpec(_old.name, _old.table_name, _old.primary_key, _old.fields,
                                        _old.lifecycle_field, _old.unique_constraints,
                                        _old.row_count_full, _old.row_count_starter, _step, _old.description)

# Keyed aliases make schema lookup by public entity name stable.
ENTITY_SPECS = ENTITIES


def validate_schema_contract() -> list[str]:
    """Check internal dictionary integrity, including enum/status consistency."""
    errors=[]
    for name, entity in ENTITIES.items():
        fields=[field for field in entity.fields if field.name == entity.primary_key]
        if len(fields) != 1 or not fields[0].primary_key:
            errors.append(f"{name}: primary key declaration is inconsistent")
        field_names=[field.name for field in entity.fields]
        if len(field_names) != len(set(field_names)):
            errors.append(f"{name}: duplicate field names")
        for field in entity.fields:
            if not callable(field.validator): errors.append(f"{name}.{field.name}: validator is not callable")
            if field.sql_type == "ENUM" and not field.enum_values: errors.append(f"{name}.{field.name}: ENUM field has no enum_values")
        if entity.lifecycle_field:
            status_field=next((f for f in entity.fields if f.name == entity.lifecycle_field), None)
            if not status_field or set(status_field.enum_values) != set(STATUS_ENUMS[name]):
                errors.append(f"{name}: lifecycle field enum differs from STATUS_ENUMS")
            if set(STATUS_ENUMS[name]) != set(STATUS_TRANSITIONS[name]):
                errors.append(f"{name}: missing lifecycle transition entries")
    return errors


def _as_date(value: Any) -> date | None:
    return _date(value)


def _entity_rule_anomaly_pair(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    issue, truth = record.get("issue_type"), record.get("ground_truth")
    # This synthetic baseline labels anomaly rows as paired truth/issue classes.
    # Both are NULL for normal rows; partial labelling is treated as malformed.
    if (issue is None) != (truth is None): errors.append("issue_type and ground_truth must both be NULL for normal rows or both be populated for labelled anomaly rows")
    return errors


def _entity_rule_dates(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    for left, right, message in (
        ("created_at", "updated_at", "updated_at must be >= created_at"),
        ("created_at", "response_due_at", "response_due_at must be >= created_at"),
    ):
        a,b=record.get(left),record.get(right)
        if a is not None and b is not None:
            da,db=(_datetime(a),_datetime(b))
            if da and db and db < da: errors.append(message)
    od, rd = _as_date(record.get("order_date")), _as_date(record.get("required_delivery_date"))
    if od and rd and rd < od: errors.append("required_delivery_date must be >= order_date")
    created, order = _datetime(record.get("created_at")), od
    if created and order and created.date() < order: errors.append("created_at date must be >= order_date")
    return errors


def _entity_rule_po_line(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    line_total = _decimal(record.get("line_total"))
    qty, price = _decimal(record.get("requested_qty")), _decimal(record.get("unit_price"))
    if qty is not None and price is not None and line_total is not None:
        expected=(qty*price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if line_total != expected: errors.append(f"line_total must equal ROUND_HALF_UP(requested_qty * unit_price, 2) = {expected}")
    line_id, po_id, line_no = record.get("po_line_id"), record.get("po_id"), _integer(record.get("line_no"))
    if isinstance(line_id, str) and isinstance(po_id, str) and line_no is not None and line_id != f"{po_id}-L{line_no:02d}": errors.append("po_line_id must equal f'{po_id}-L{line_no:02d}'")
    status=record.get("status")
    if status in {"PARTIALLY_ACKNOWLEDGED", "ACKNOWLEDGED", "IN_FULFILLMENT", "PARTIALLY_RECEIVED", "RECEIVED", "CLOSED"}:
        accepted, rejected = _decimal(record.get("ack_accepted_qty")), _decimal(record.get("ack_rejected_qty"))
        if None not in (qty, accepted, rejected) and qty != accepted + rejected:
            errors.append("requested_qty must equal ack_accepted_qty + ack_rejected_qty once line acknowledgement is resolved")
    promised, projected = _decimal(record.get("promised_qty")), _decimal(record.get("projected_qty"))
    if qty is not None and promised is not None and promised > qty and not record.get("issue_type"):
        errors.append("promised_qty must not exceed requested_qty unless row is anomaly-labelled")
    if qty is not None and projected is not None and projected > qty and not record.get("issue_type"):
        errors.append("projected_qty must not exceed requested_qty unless row is anomaly-labelled")
    return errors


def _entity_rule_ack(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    # The callable returns a single error string, normalized here.
    e = _check_ack_reconciliation(None, record, context, next(f for f in ENTITIES["Acknowledgement"].fields if f.name == "ack_accepted_qty"))
    if e: errors.append(e)
    created, acknowledged = _datetime(record.get("created_at")), _datetime(record.get("acknowledged_at"))
    if created and acknowledged and acknowledged < created: errors.append("acknowledged_at must be >= created_at")
    # response_due_at is the original PO deadline. It is valid for a late supplier
    # response to have acknowledged_at > response_due_at; this is an exception to
    # surface, not a malformed date range.
    lifecycle = record.get("lifecycle_state")
    if lifecycle not in ACK_LIFECYCLE_STATES:
        errors.append(f"lifecycle_state must be one of {ACK_LIFECYCLE_STATES}")
    if lifecycle in {"PROCESSED", "EXCEPTION"} and acknowledged is None:
        errors.append("PROCESSED/EXCEPTION lifecycle state requires acknowledged_at")
    due = _datetime(record.get("response_due_at"))
    if acknowledged and due:
        if acknowledged > due and lifecycle == "PROCESSED":
            errors.append("late supplier response must have lifecycle_state=EXCEPTION")
        if acknowledged <= due and lifecycle == "EXCEPTION":
            errors.append("on-time supplier response must not have lifecycle_state=EXCEPTION")
    req_total, accepted_total = _decimal(record.get("requested_qty")), _decimal(record.get("ack_accepted_qty"))
    qty_delta = _decimal(record.get("qty_delta_pct"))
    if req_total is not None and req_total > 0 and accepted_total is not None and qty_delta is not None:
        expected_delta = (Decimal("100") * (accepted_total - req_total) / req_total).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if qty_delta != expected_delta:
            errors.append(f"qty_delta_pct must equal computed aggregate accepted-quantity delta ({expected_delta})")
    if record.get("status") in {"PARTIALLY_ACCEPTED", "REJECTED"} and record.get("rejection_reason") not in {"capacity", "price", "stock", "logistics"}:
        errors.append("PARTIALLY_ACCEPTED or REJECTED acknowledgement requires rejection_reason in capacity/price/stock/logistics")
    if record.get("status") == "ACCEPTED" and record.get("rejection_reason") is not None:
        errors.append("fully accepted acknowledgement must have rejection_reason=NULL")
    if record.get("status") in {"ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED"}:
        accepted, promised = _decimal(record.get("ack_accepted_qty")), _decimal(record.get("promised_qty"))
        if accepted is not None and promised is not None and promised > accepted and not record.get("issue_type"):
            errors.append("promised_qty must not exceed ack_accepted_qty unless anomaly-labelled")
    if record.get("status") == "SUPERSEDED" and not record.get("superseded_by"): errors.append("SUPERSEDED acknowledgement must set superseded_by")
    if record.get("status") != "SUPERSEDED" and record.get("superseded_by") is not None: errors.append("only SUPERSEDED acknowledgement may set superseded_by")
    ack_id, po_id, rev = record.get("ack_id"), record.get("po_id"), _integer(record.get("revision_no"))
    if isinstance(ack_id, str) and isinstance(po_id, str) and rev is not None and ack_id != f"ACK-{po_id}-{rev:02d}": errors.append("ack_id must equal f'ACK-{po_id}-{revision_no:02d}'")
    return errors


def _entity_rule_promise(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    promised, effective = _as_date(record.get("promised_date")), _as_date(record.get("effective_date"))
    created = _datetime(record.get("created_at"))
    if promised and effective and promised < effective: errors.append("promised_date must be >= effective_date")
    if effective and created and effective < created.date(): errors.append("effective_date must be >= DATE(created_at)")
    due = _as_date(record.get("response_due_date"))
    if effective and due and due < effective: errors.append("response_due_date must be >= effective_date")
    if record.get("status") == "SUPERSEDED" and not record.get("superseded_by"): errors.append("SUPERSEDED promise date must set superseded_by")
    if record.get("status") != "SUPERSEDED" and record.get("superseded_by") is not None: errors.append("only SUPERSEDED promise date may set superseded_by")
    pid, aid, seq = record.get("promise_date_id"), record.get("ack_id"), _integer(record.get("sequence_no"))
    if isinstance(pid, str) and isinstance(aid, str) and seq is not None and pid != f"PD-{aid}-{seq:02d}": errors.append("promise_date_id must equal f'PD-{ack_id}-{sequence_no:02d}' (suffix is exactly 2 digits)")
    if record.get("carrier_id") and record.get("carrier_reference"):
        carrier = _context_row(context, "carriers", "carrier_id", record.get("carrier_id"))
        if carrier and carrier.get("carrier_code") != record.get("carrier_reference"):
            errors.append("carrier_reference must equal carrier master carrier_code")
    if record.get("ship_from_warehouse_id") and record.get("ship_from_location"):
        warehouse = _context_row(context, "warehouses", "warehouse_id", record.get("ship_from_warehouse_id"))
        if warehouse and warehouse.get("warehouse_name") != record.get("ship_from_location"):
            errors.append("ship_from_location must equal warehouse master warehouse_name")
    if record.get("carrier_operator_actor_id"):
        operator = _context_row(context, "actors", "actor_id", record.get("carrier_operator_actor_id"))
        if operator and operator.get("actor_role", operator.get("role")) != "carrier_warehouse_operator":
            errors.append("carrier_operator_actor_id must reference a carrier_warehouse_operator")
    return errors


def validate_acknowledgement_line_rows(
    rows: Sequence[Mapping[str, Any]], context: Mapping[str, Any]
) -> list[str]:
    """Validate immutable per-PO-line acknowledgement snapshots and their joins.

    This supporting table is separate from the PO-level Acknowledgement revision
    header because one ACK ID identifies one revision, not multiple line rows.
    """
    errors: list[str] = []
    # This helper is also public and may be called outside validate_dataset. Build
    # only its missing FK index entries once rather than rebuilding sets per row.
    local_context: Mapping[str, Any] = context
    current_fk_cache = context.get("_fk_id_cache", {})
    missing_fk_pairs = {
        tuple(field.foreign_key.split(".", 1))
        for field in ACKNOWLEDGEMENT_LINE_FIELDS
        if field.foreign_key and (
            not isinstance(current_fk_cache, Mapping)
            or tuple(field.foreign_key.split(".", 1)) not in current_fk_cache
        )
    }
    if missing_fk_pairs:
        new_context = dict(context)
        new_fk_cache = dict(current_fk_cache) if isinstance(current_fk_cache, Mapping) else {}
        for table, key in missing_fk_pairs:
            source = context.get(table, ())
            new_fk_cache[(table, key)] = {
                row.get(key) if isinstance(row, Mapping) else row for row in source
            }
        new_context["_fk_id_cache"] = new_fk_cache
        local_context = new_context
    context = local_context
    acknowledgements = context.get("Acknowledgement", context.get("acknowledgements", ()))
    purchase_orders = context.get("PurchaseOrder", context.get("purchase_orders", ()))
    po_lines = context.get("POLine", context.get("po_lines", ()))
    promises = context.get("PromiseDate", context.get("promise_dates", ()))
    actors = context.get("actors", ())
    ack_by_id = {row.get("ack_id"): row for row in acknowledgements if isinstance(row, Mapping)}
    po_by_id = {row.get("po_id"): row for row in purchase_orders if isinstance(row, Mapping)}
    line_by_id = {row.get("po_line_id"): row for row in po_lines if isinstance(row, Mapping)}
    actor_by_id = {row.get("actor_id"): row for row in actors if isinstance(row, Mapping)}
    promise_by_key = {
        (row.get("ack_id"), row.get("po_line_id")): row
        for row in promises if isinstance(row, Mapping)
    }
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        prefix = f"AcknowledgementLine[{index}]"
        for field in ACKNOWLEDGEMENT_LINE_FIELDS:
            value = row.get(field.name)
            if value is None:
                if field.required:
                    errors.append(f"{prefix}: {field.name} is required")
                continue
            problem = field.validator(value, row, context, field)
            if problem:
                errors.append(f"{prefix}: {field.name} {problem}")
        child_id = row.get("acknowledgement_line_id")
        if child_id in seen:
            errors.append(f"{prefix}: duplicate acknowledgement_line_id {child_id!r}")
        seen.add(child_id)

        ack = ack_by_id.get(row.get("ack_id"))
        po = po_by_id.get(row.get("po_id"))
        line = line_by_id.get(row.get("po_line_id"))
        if ack is not None:
            if row.get("po_id") != ack.get("po_id"):
                errors.append(f"{prefix}: po_id must exactly match parent acknowledgement po_id")
            if row.get("revision_no") != ack.get("revision_no"):
                errors.append(f"{prefix}: revision_no must match parent acknowledgement revision_no")
            if row.get("created_by_actor_id") != ack.get("supplier_id"):
                errors.append(f"{prefix}: created_by_actor_id must match parent acknowledgement supplier_id")
            if row.get("response_timestamp") != ack.get("acknowledged_at"):
                errors.append(f"{prefix}: response_timestamp must equal parent acknowledgement acknowledged_at")
            if child_id != f"AL-{row.get('ack_id')}-{row.get('po_line_id')}":
                errors.append(f"{prefix}: acknowledgement_line_id must embed exact ack_id and po_line_id")
        if line is not None:
            if row.get("po_id") != line.get("po_id"):
                errors.append(f"{prefix}: po_line_id belongs to another PO")
            requested = _decimal(row.get("requested_qty"))
            source_requested = _decimal(line.get("requested_qty"))
            if requested is not None and source_requested is not None and requested != source_requested:
                errors.append(f"{prefix}: requested_qty must equal source POLine.requested_qty")
            requested_price = _decimal(row.get("requested_unit_price"))
            source_price = _decimal(line.get("unit_price"))
            if requested_price is not None and source_price is not None and requested_price != source_price:
                errors.append(f"{prefix}: requested_unit_price must equal source POLine.unit_price")
        requested_qty = _decimal(row.get("requested_qty"))
        accepted_qty = _decimal(row.get("accepted_qty"))
        rejected_qty = _decimal(row.get("rejected_qty"))
        if None not in (requested_qty, accepted_qty, rejected_qty):
            if requested_qty != accepted_qty + rejected_qty:
                errors.append(f"{prefix}: requested_qty must equal accepted_qty + rejected_qty")
            if accepted_qty < 0 or accepted_qty > requested_qty or rejected_qty < 0:
                errors.append(f"{prefix}: accepted/rejected quantities must be within [0, requested_qty]")
            expected_qty_pct = (Decimal("100") * (accepted_qty - requested_qty) / requested_qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if requested_qty else None
            actual_qty_pct = _decimal(row.get("qty_delta_pct"))
            if expected_qty_pct is not None and actual_qty_pct != expected_qty_pct:
                errors.append(f"{prefix}: qty_delta_pct must equal computed value {expected_qty_pct}")
        req_price = _decimal(row.get("requested_unit_price"))
        ack_price = _decimal(row.get("acknowledged_unit_price"))
        actual_price_pct = _decimal(row.get("price_delta_pct"))
        if req_price is not None and ack_price is not None and actual_price_pct is not None:
            expected_price_pct = Decimal("0.0000") if req_price == 0 else (Decimal("100") * (ack_price - req_price) / req_price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if actual_price_pct != expected_price_pct:
                errors.append(f"{prefix}: price_delta_pct must equal computed value {expected_price_pct}")
        if rejected_qty is not None:
            reason = row.get("rejected_reason")
            if rejected_qty > 0 and reason not in {"capacity", "price", "stock", "logistics"}:
                errors.append(f"{prefix}: rejected_reason is required when rejected_qty > 0")
            if rejected_qty == 0 and reason is not None:
                errors.append(f"{prefix}: rejected_reason must be NULL when rejected_qty = 0")
            if requested_qty is not None and accepted_qty is not None:
                wanted = "REJECTED" if accepted_qty == 0 else "PARTIALLY_ACCEPTED" if rejected_qty > 0 else "ACCEPTED"
                if row.get("status") not in {wanted, "SUPERSEDED"}:
                    errors.append(f"{prefix}: status must be {wanted} or SUPERSEDED")
        actor = actor_by_id.get(row.get("created_by_actor_id"))
        if actor is not None and actor.get("actor_role", actor.get("role")) != "supplier":
            errors.append(f"{prefix}: created_by_actor_id must reference supplier role")
        promise = promise_by_key.get((row.get("ack_id"), row.get("po_line_id")))
        slip = _integer(row.get("date_slip_days"))
        if promise is not None and line is not None:
            promised_date = _as_date(promise.get("promised_date"))
            required_date = _as_date(line.get("required_date"))
            if promised_date and required_date:
                expected_slip = (promised_date - required_date).days
                if slip != expected_slip:
                    errors.append(f"{prefix}: date_slip_days must equal matching PromiseDate promised_date minus POLine.required_date ({expected_slip})")
        elif accepted_qty is not None and accepted_qty == 0 and slip is not None:
            errors.append(f"{prefix}: date_slip_days must be NULL when accepted_qty is zero and no promise exists")
        if (row.get("issue_type") is None) != (row.get("ground_truth") is None):
            errors.append(f"{prefix}: issue_type and ground_truth must be populated together")
    return errors


def _entity_rule_change(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    req_at = _datetime(record.get("requested_at")); created = _datetime(record.get("created_at"))
    effective = _as_date(record.get("effective_date")); due = _as_date(record.get("response_due_date"))
    if req_at and created and created > req_at: errors.append("created_at must be <= requested_at")
    if req_at and effective and effective < req_at.date(): errors.append("effective_date must be >= DATE(requested_at)")
    if req_at and due and due < req_at.date(): errors.append("response_due_date must be >= DATE(requested_at)")
    updated = _datetime(record.get("updated_at"))
    if created and updated and updated < created: errors.append("updated_at must be >= created_at")
    cid, po_id = record.get("change_request_id"), record.get("po_id")
    if isinstance(cid, str) and isinstance(po_id, str) and not cid.startswith(f"CHG-{po_id}-"): errors.append("change_request_id must start with f'CHG-{po_id}-'")
    kind=record.get("request_type")
    normalized_type = {"PRICE_CHANGE": "price", "DATE_CHANGE": "date", "QUANTITY_CHANGE": "quantity"}.get(kind)
    if normalized_type is not None and record.get("change_type") != normalized_type:
        errors.append(f"change_type must be {normalized_type!r} for request_type {kind}")
    if normalized_type is not None:
        old_value, new_value = record.get("old_value"), record.get("new_value")
        try:
            if normalized_type == "date":
                old_day, new_day = _as_date(old_value), _as_date(new_value)
                expected_delta = float((new_day - old_day).days) if old_day and new_day else None
            else:
                old_decimal, new_decimal = _decimal(old_value), _decimal(new_value)
                if old_decimal is not None and new_decimal is not None and old_decimal != 0:
                    expected_delta = float((Decimal("100") * (new_decimal - old_decimal) / old_decimal).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
                elif old_decimal is not None and new_decimal is not None and old_decimal == new_decimal:
                    expected_delta = 0.0
                else:
                    expected_delta = None
            actual_delta = _decimal(record.get("delta"))
            if expected_delta is not None and actual_delta is not None and abs(float(actual_delta) - expected_delta) > 0.00011:
                errors.append(f"delta must be computed from old_value/new_value (expected {expected_delta})")
        except (TypeError, ValueError, ArithmeticError):
            errors.append("delta must be computable from old_value and new_value")
    if kind == "QUANTITY_CHANGE":
        previous_qty, requested_qty = _decimal(record.get("previous_qty")), _decimal(record.get("requested_qty"))
        if previous_qty is None or requested_qty is None: errors.append("QUANTITY_CHANGE requires both previous_qty and requested_qty")
        elif previous_qty < 0 or requested_qty <= 0: errors.append("QUANTITY_CHANGE requires previous_qty >= 0 and requested_qty > 0")
    if kind == "PRICE_CHANGE":
        if _decimal(record.get("previous_unit_price")) is None or _decimal(record.get("requested_unit_price")) is None: errors.append("PRICE_CHANGE requires previous_unit_price and requested_unit_price")
    if kind == "DATE_CHANGE" and _as_date(record.get("requested_promised_date")) is None: errors.append("DATE_CHANGE requires requested_promised_date")
    if kind == "DATE_CHANGE":
        requested_promise = _as_date(record.get("requested_promised_date"))
        parent = _context_row(context, "purchase_orders", "po_id", record.get("po_id"))
        po_order_date = _as_date(parent.get("order_date")) if parent else None
        if requested_promise and po_order_date and requested_promise < po_order_date:
            errors.append("requested_promised_date must be >= parent purchase_orders.order_date")
    return errors


def _entity_rule_approval(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    status=record.get("status"); decided=_datetime(record.get("decided_at")); requested=_datetime(record.get("requested_at"))
    if status == "PENDING" and record.get("decided_at") is not None: errors.append("PENDING approval must have decided_at=NULL")
    if status in {"APPROVED", "REJECTED", "ESCALATED", "WITHDRAWN"} and not decided: errors.append("non-PENDING approval requires timezone-aware decided_at")
    due = _datetime(record.get("due_at"))
    if requested and due and due < requested: errors.append("due_at must be >= requested_at")
    if requested and decided and decided < requested: errors.append("decided_at must be >= requested_at")
    if status in {"REJECTED", "ESCALATED"} and not str(record.get("decision_reason") or "").strip(): errors.append("REJECTED or ESCALATED approval requires decision_reason")
    if record.get("approval_level") != record.get("approver_role"):
        errors.append("approval_level must equal approver_role")
    created=_datetime(record.get("created_at"))
    if created and requested and created > requested: errors.append("created_at must be <= requested_at")
    aid, cid, rnd=record.get("approval_id"),record.get("change_request_id"),_integer(record.get("approval_round"))
    if isinstance(aid, str) and isinstance(cid, str) and rnd is not None and aid != f"APR-{cid}-{rnd:02d}": errors.append("approval_id must equal f'APR-{change_request_id}-{approval_round:02d}'")
    return errors


def _entity_rule_inventory(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    get=lambda k:_decimal(record.get(k))
    on, reserved, receipts, avail, demand, shortage = (get("on_hand_qty"),get("reserved_qty"),get("planned_receipt_qty"),get("projected_available_qty"),get("demand_qty"),get("projected_shortage_qty"))
    if None not in (on,reserved,receipts,avail):
        expected=on-reserved+receipts
        if avail != expected: errors.append(f"projected_available_qty must equal on_hand_qty - reserved_qty + planned_receipt_qty ({expected})")
    created = _datetime(record.get("created_at")); effective = _as_date(record.get("effective_date"))
    if created and effective and effective < created.date(): errors.append("effective_date must be >= DATE(created_at)")
    if None not in (demand,avail,shortage):
        expected=max(Decimal("0"), demand-avail)
        if shortage != expected: errors.append(f"projected_shortage_qty must equal max(0, demand_qty - projected_available_qty) ({expected})")
    if None not in (on,reserved) and reserved > on and not record.get("issue_type"): errors.append("reserved_qty must not exceed on_hand_qty unless row is anomaly-labelled")
    line_id, rev, ipid=record.get("po_line_id"),_integer(record.get("plan_revision_no")),record.get("inventory_plan_id")
    version = _integer(record.get("plan_version"))
    if isinstance(line_id, str) and rev is not None and isinstance(ipid, str) and ipid != f"IP-{line_id}-{rev:02d}": errors.append("inventory_plan_id must equal f'IP-{po_line_id}-{plan_revision_no:02d}'")
    if version is not None and rev is not None and version != rev: errors.append("plan_version must equal plan_revision_no")
    if version == 1 and record.get("previous_version_id") is not None: errors.append("version 1 must have previous_version_id=NULL")
    if version is not None and version > 1 and not record.get("previous_version_id"): errors.append("versions after 1 require previous_version_id")
    if record.get("source") == "po_baseline" and version != 1: errors.append("po_baseline source is only valid for version 1")
    if record.get("source") == "approved_change" and not record.get("change_request_id"): errors.append("approved_change source requires change_request_id")
    if record.get("is_effective") not in (0, 1): errors.append("is_effective must be 0 or 1")
    start, end = _as_date(record.get("plan_start_date")), _as_date(record.get("plan_end_date"))
    if start and end and start > end: errors.append("plan_start_date must be <= plan_end_date")
    if record.get("status") in {"APPROVED", "ACTIVE", "AT_RISK", "PARTIALLY_FULFILLED", "FULFILLED"} and not record.get("approved_by_actor_id"):
        errors.append("approved_by_actor_id is required for approved/active/fulfilled inventory plans")
    if record.get("status") == "SUPERSEDED" and not record.get("superseded_by"): errors.append("SUPERSEDED inventory plan must set superseded_by")
    if record.get("status") != "SUPERSEDED" and record.get("superseded_by") is not None: errors.append("only SUPERSEDED inventory plan may set superseded_by")
    return errors


def _entity_rule_production(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    planned,released,completed=(_decimal(record.get("planned_qty")),_decimal(record.get("released_qty")),_decimal(record.get("completed_qty")))
    if None not in (planned,released,completed) and not (Decimal(0) <= completed <= released <= planned): errors.append("0 <= completed_qty <= released_qty <= planned_qty")
    original,current=_as_date(record.get("original_start_date")),_as_date(record.get("current_start_date"))
    if original and current and record.get("schedule_shift_days") is not None and (current-original).days != record.get("schedule_shift_days"):
        errors.append("schedule_shift_days must equal (current_start_date - original_start_date).days")
    end=_as_date(record.get("scheduled_end_date"))
    if current and end and end < current: errors.append("scheduled_end_date must be >= current_start_date")
    actual_start,actual_end=_as_date(record.get("actual_start_date")),_as_date(record.get("actual_end_date"))
    if actual_start and current and actual_start < current and not record.get("issue_type"): errors.append("actual_start_date must be >= current_start_date unless anomaly-labelled/approved expedite")
    if actual_start and actual_end and actual_end < actual_start: errors.append("actual_end_date must be >= actual_start_date")
    if record.get("status") == "COMPLETED" and (planned is not None and completed is not None and completed < planned): errors.append("COMPLETED production order requires completed_qty >= planned_qty")
    return errors


def _entity_rule_notification(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    created, scheduled, sent, delivered=(_datetime(record.get("created_at")),_datetime(record.get("scheduled_at")),_datetime(record.get("sent_at")),_datetime(record.get("delivered_at")))
    if created and scheduled and scheduled < created: errors.append("scheduled_at must be >= created_at")
    if scheduled and sent and sent < scheduled: errors.append("sent_at must be >= scheduled_at")
    if sent and delivered and delivered < sent: errors.append("delivered_at must be >= sent_at")
    if record.get("status") == "DELIVERED" and not delivered: errors.append("DELIVERED notification requires delivered_at")
    if record.get("status") in {"FAILED", "BOUNCED"} and not str(record.get("last_error") or "").strip(): errors.append("FAILED or BOUNCED notification requires last_error")
    if record.get("status") in {"SENT", "DELIVERED", "BOUNCED"} and not sent: errors.append("SENT/DELIVERED/BOUNCED notification requires sent_at")
    if record.get("notification_id") != record.get("not_id"): errors.append("not_id must equal notification_id")
    if record.get("title") != record.get("subject"): errors.append("subject must equal title")
    return errors


def _entity_rule_supplier(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors=[]
    created, updated = _datetime(record.get("created_at")), _datetime(record.get("updated_at"))
    if created and updated and updated < created: errors.append("updated_at must be >= created_at")
    return errors


def _entity_rule_generic(record: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    return []

ENTITY_VALIDATORS: dict[str, tuple[Callable[[Mapping[str, Any], Mapping[str, Any]], list[str]], ...]] = {
    "Supplier": (_entity_rule_anomaly_pair, _entity_rule_supplier),
    "PurchaseOrder": (_entity_rule_anomaly_pair, _entity_rule_dates),
    "POLine": (_entity_rule_anomaly_pair, _entity_rule_po_line),
    "Acknowledgement": (_entity_rule_anomaly_pair, _entity_rule_ack),
    "PromiseDate": (_entity_rule_anomaly_pair, _entity_rule_promise),
    "ChangeRequest": (_entity_rule_anomaly_pair, _entity_rule_change),
    "Approval": (_entity_rule_anomaly_pair, _entity_rule_approval),
    "InventoryPlan": (_entity_rule_anomaly_pair, _entity_rule_inventory),
    "ProductionOrder": (_entity_rule_anomaly_pair, _entity_rule_production),
    "Notification": (_entity_rule_anomaly_pair, _entity_rule_notification),
}


def validate_record(entity_name: str, record: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> list[str]:
    """Return machine-readable validation errors for one record (empty means valid)."""
    if entity_name not in ENTITIES: raise KeyError(f"Unknown entity: {entity_name}")
    context = context or {}
    spec=ENTITIES[entity_name]; errors=[]
    for field in spec.fields:
        value=record.get(field.name)
        if value is None:
            if field.required: errors.append(f"{field.name}: required field is NULL or missing")
            continue
        base_error=_check_basic_sql_type(value, record, context, field)
        if base_error: errors.append(f"{field.name}: {base_error}"); continue
        custom_error=field.validator(value, record, context, field)
        if custom_error and f"{field.name}: {custom_error}" not in errors: errors.append(f"{field.name}: {custom_error}")
        if field.foreign_key:
            fk_error = _check_foreign_key(value, record, context, field)
            if fk_error and f"{field.name}: {fk_error}" not in errors: errors.append(f"{field.name}: {fk_error}")
        if field.enum_values and value not in field.enum_values:
            enum_error = f"{field.name}: must be one of {', '.join(field.enum_values)}"
            if enum_error not in errors: errors.append(enum_error)
    if spec.primary_key in record and record.get(spec.primary_key) is not None:
        pk_field=next(f for f in spec.fields if f.name == spec.primary_key)
        error=pk_field.validator(record[spec.primary_key], record, context, pk_field)
        # `basic_type` is not used for IDs; call the named format validator above.
        if error and error not in errors: errors.append(f"{spec.primary_key}: {error}")
    for rule in ENTITY_VALIDATORS[entity_name]: errors.extend(rule(record, context))
    return errors


def validate_dataset(records_by_entity: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[str]:
    """Validate uniqueness, all row rules, and foreign-key existence for a dataset.

    Context table names must match EntitySpec.table_name. External master tables
    (actors/items/warehouses/carriers/entity_event) may be provided the same way.
    """
    errors=[]
    context=dict(records_by_entity)
    for entity_name, rows in records_by_entity.items():
        if entity_name not in ENTITIES:
            continue
        spec=ENTITIES[entity_name]
        # Accept either entity-keyed or table-name-keyed contexts.
        context.setdefault(spec.table_name, rows)
    fk_pairs = {
        tuple(field.foreign_key.split(".", 1))
        for spec in ENTITIES.values() for field in spec.fields if field.foreign_key
    }
    fk_cache: dict[tuple[str, str], set[Any]] = {}
    for table, key in fk_pairs:
        rows = context.get(table)
        if rows is not None:
            fk_cache[(table, key)] = {
                row.get(key) if isinstance(row, Mapping) else row for row in rows
            }
    # The supporting acknowledgement-line snapshot table has field-level FKs too;
    # include its definitions here or each snapshot validation would rebuild parent
    # key sets for every child row at full scale.
    fk_pairs.update(
        tuple(field.foreign_key.split(".", 1))
        for field in ACKNOWLEDGEMENT_LINE_FIELDS if field.foreign_key
    )
    for table, key in fk_pairs:
        if (table, key) in fk_cache:
            continue
        rows = context.get(table)
        if rows is not None:
            fk_cache[(table, key)] = {
                row.get(key) if isinstance(row, Mapping) else row for row in rows
            }
    context["_fk_id_cache"] = fk_cache
    # Several record rules compare against a small parent master but run once per
    # child row. Pre-index parent rows to keep full-scale validation O(n), not O(n*m).
    indexed_tables = {
        ("purchase_orders", "po_id"),
        ("actors", "actor_id"),
        ("carriers", "carrier_id"),
        ("warehouses", "warehouse_id"),
    }
    record_indexes = {}
    for table, key in indexed_tables:
        rows = context.get(table, ())
        record_indexes[(table, key)] = {
            row.get(key): row for row in rows if isinstance(row, Mapping)
        }
    context["_record_index_cache"] = record_indexes
    for entity_name, spec in ENTITIES.items():
        rows=records_by_entity.get(entity_name, records_by_entity.get(spec.table_name, ()))
        seen_pk=set()
        unique_seen={constraint: set() for constraint in spec.unique_constraints}
        for row_num, row in enumerate(rows, 1):
            for error in validate_record(entity_name, row, context): errors.append(f"{entity_name}[{row_num}]: {error}")
            pk=row.get(spec.primary_key)
            pk_marker=(type(pk).__name__, repr(pk))
            if pk_marker in seen_pk: errors.append(f"{entity_name}[{row_num}]: duplicate primary key {spec.primary_key}={pk!r}")
            seen_pk.add(pk_marker)
            for constraint, values_seen in unique_seen.items():
                values=tuple(row.get(col) for col in constraint)
                if any(v is None for v in values): continue
                if values in values_seen: errors.append(f"{entity_name}[{row_num}]: duplicate unique constraint {constraint}={values!r}")
                values_seen.add(values)
    # Cross-entity ownership coherence, checked when both tables are supplied.
    po_rows={r.get("po_id"):r for r in records_by_entity.get("PurchaseOrder", records_by_entity.get("purchase_orders", ())) }
    line_rows={r.get("po_line_id"):r for r in records_by_entity.get("POLine", records_by_entity.get("po_lines", ())) }
    ack_rows={r.get("ack_id"):r for r in records_by_entity.get("Acknowledgement", records_by_entity.get("acknowledgements", ())) }
    change_rows={r.get("change_request_id"):r for r in records_by_entity.get("ChangeRequest", records_by_entity.get("change_requests", ())) }
    plan_rows={r.get("inventory_plan_id"):r for r in records_by_entity.get("InventoryPlan", records_by_entity.get("inventory_plans", ())) }
    acknowledgement_line_snapshot_by_key = {
        (r.get("ack_id"), r.get("po_line_id")): r
        for r in records_by_entity.get("acknowledgement_lines", ())
        if isinstance(r, Mapping)
    }
    event_rows_for_validation = context.get("entity_event", context.get("events", ()))
    event_ids_for_validation = {
        r.get("event_id") for r in event_rows_for_validation if isinstance(r, Mapping)
    }
    for name, rows in (("POLine", records_by_entity.get("POLine", records_by_entity.get("po_lines", ()))),
                       ("Acknowledgement", records_by_entity.get("Acknowledgement", records_by_entity.get("acknowledgements", ()))),
                       ("PromiseDate", records_by_entity.get("PromiseDate", records_by_entity.get("promise_dates", ()))),
                       ("ChangeRequest", records_by_entity.get("ChangeRequest", records_by_entity.get("change_requests", ()))),
                       ("InventoryPlan", records_by_entity.get("InventoryPlan", records_by_entity.get("inventory_plans", ()))),
                       ("ProductionOrder", records_by_entity.get("ProductionOrder", records_by_entity.get("production_orders", ()))),
                       ("Notification", records_by_entity.get("Notification", records_by_entity.get("notifications", ())))):
        for index, row in enumerate(rows,1):
            po_id=row.get("po_id"); line_id=row.get("po_line_id")
            if line_id and line_id in line_rows and po_id and line_rows[line_id].get("po_id") != po_id:
                errors.append(f"{name}[{index}]: po_line_id belongs to a different po_id")
            if name == "POLine" and po_id in po_rows and row.get("currency") != po_rows[po_id].get("currency"):
                errors.append(f"POLine[{index}]: currency must match parent PurchaseOrder.currency")
            if name == "POLine" and po_id in po_rows:
                order_date = _as_date(po_rows[po_id].get("order_date")); required_date = _as_date(row.get("required_date"))
                if order_date and required_date and required_date < order_date: errors.append(f"POLine[{index}]: required_date must be >= parent PO order_date")
            if po_id and po_id in po_rows and name == "Acknowledgement" and row.get("supplier_id") != po_rows[po_id].get("supplier_id"):
                errors.append(f"{name}[{index}]: supplier_id must match its purchase order")
            if name == "Acknowledgement":
                parent_po = po_rows.get(po_id)
                if parent_po is not None:
                    if row.get("response_due_at") != parent_po.get("response_due_at"):
                        errors.append(f"Acknowledgement[{index}]: response_due_at must be byte-identical to parent PO response_due_at")
                    acknowledged_at = _datetime(row.get("acknowledged_at"))
                    order_date = _as_date(parent_po.get("order_date"))
                    if acknowledged_at and order_date and acknowledged_at.date() < order_date:
                        errors.append(f"Acknowledgement[{index}]: acknowledged_at must be on or after parent PO order_date")
            if name == "PromiseDate":
                ack=ack_rows.get(row.get("ack_id"))
                if ack and (ack.get("po_id") != po_id or (ack.get("po_line_id") is not None and ack.get("po_line_id") != row.get("po_line_id"))): errors.append(f"PromiseDate[{index}]: PO and optional acknowledgement line must match")
                parent_po=po_rows.get(po_id)
                promised=_as_date(row.get("promised_date")); order_date=_as_date(parent_po.get("order_date")) if parent_po else None
                if promised and order_date and promised < order_date: errors.append(f"PromiseDate[{index}]: promised_date must be >= parent PO order_date")
                if ack is not None and row.get("promised_qty") is not None:
                    line_snapshot = acknowledgement_line_snapshot_by_key.get((row.get("ack_id"), row.get("po_line_id")))
                    if line_snapshot is not None and _decimal(row.get("promised_qty")) != _decimal(line_snapshot.get("accepted_qty")):
                        errors.append(f"PromiseDate[{index}]: promised_qty must equal the corresponding acknowledgement line accepted_qty")
            if name == "ChangeRequest" and po_id in po_rows and row.get("supplier_id") != po_rows[po_id].get("supplier_id"):
                errors.append(f"ChangeRequest[{index}]: supplier_id must match its purchase order")
            if name == "InventoryPlan":
                if line_id in line_rows and line_rows[line_id].get("po_id") != po_id:
                    errors.append(f"InventoryPlan[{index}]: po_id must match po_lines.po_id")
                if row.get("source") == "approved_change":
                    linked_change = change_rows.get(row.get("change_request_id"))
                    if linked_change is None or linked_change.get("status") != "IMPLEMENTED":
                        errors.append(f"InventoryPlan[{index}]: approved_change version requires an IMPLEMENTED ChangeRequest")
                    elif linked_change.get("po_line_id") != line_id or linked_change.get("po_id") != po_id:
                        errors.append(f"InventoryPlan[{index}]: source ChangeRequest must belong to the same PO line")
            if name == "ProductionOrder":
                plan=plan_rows.get(row.get("inventory_plan_id"))
                if plan and (plan.get("po_id") != po_id or plan.get("po_line_id") != line_id): errors.append(f"ProductionOrder[{index}]: po_id and po_line_id must match referenced inventory plan")
            if name == "Notification":
                if row.get("ack_id") in ack_rows and ack_rows[row.get("ack_id")].get("po_id") != po_id: errors.append(f"Notification[{index}]: ack_id must belong to po_id")
                if row.get("change_request_id") in change_rows and change_rows[row.get("change_request_id")].get("po_id") != po_id: errors.append(f"Notification[{index}]: change_request_id must belong to po_id")
                if row.get("source_event_id") and ("entity_event" in context or "events" in context) and row.get("source_event_id") not in event_ids_for_validation:
                    errors.append(f"Notification[{index}]: source_event_id must exist in entity_event ledger")
    # Header totals must agree with their PO lines whenever both are present.
    lines_by_po: dict[str, list[Mapping[str, Any]]] = {}
    for line in records_by_entity.get("POLine", records_by_entity.get("po_lines", ())):
        lines_by_po.setdefault(line.get("po_id"), []).append(line)
    for po in records_by_entity.get("PurchaseOrder", records_by_entity.get("purchase_orders", ())):
        lines=lines_by_po.get(po.get("po_id"), [])
        if lines and all(_decimal(x.get("line_total")) is not None for x in lines):
            expected=sum((_decimal(x.get("line_total")) for x in lines), Decimal("0.00"))
            actual=_decimal(po.get("total_order_value"))
            if actual is not None and actual != expected: errors.append(f"PurchaseOrder {po.get('po_id')}: total_order_value must equal sum(POLine.line_total) ({expected})")
    for ack in records_by_entity.get("Acknowledgement", records_by_entity.get("acknowledgements", ())):
        if ack.get("po_line_id") is None:
            lines=lines_by_po.get(ack.get("po_id"), [])
            if lines:
                quantities=[_decimal(x.get("requested_qty")) for x in lines]
                if all(value is not None for value in quantities):
                    expected_qty=sum(quantities, Decimal("0.000"))
                    actual_qty=_decimal(ack.get("requested_qty"))
                    if actual_qty is not None and actual_qty != expected_qty: errors.append(f"Acknowledgement {ack.get('ack_id')}: requested_qty must equal sum of PO line requested_qty ({expected_qty})")
            if lines and all(_decimal(x.get("line_total")) is not None for x in lines):
                expected=sum((_decimal(x.get("line_total")) for x in lines), Decimal("0.00"))
                actual=_decimal(ack.get("requested_value"))
                if actual is not None and actual != expected: errors.append(f"Acknowledgement {ack.get('ack_id')}: requested_value must equal sum of PO line totals ({expected})")
    # Validate supporting line snapshots against the canonical entity/master frames.
    acknowledgements = records_by_entity.get("Acknowledgement", records_by_entity.get("acknowledgements", ()))
    promises = records_by_entity.get("PromiseDate", records_by_entity.get("promise_dates", ()))
    ack_line_rows = records_by_entity.get("acknowledgement_lines", ())
    if ack_line_rows:
        errors.extend(validate_acknowledgement_line_rows(ack_line_rows, context))
        acknowledgement_line_keys = {(r.get("ack_id"), r.get("po_line_id")) for r in ack_line_rows}
        for ack in acknowledgements:
            po_id = ack.get("po_id")
            source_lines = lines_by_po.get(po_id, [])
            for source_line in source_lines:
                key = (ack.get("ack_id"), source_line.get("po_line_id"))
                if key not in acknowledgement_line_keys:
                    errors.append(f"Acknowledgement {ack.get('ack_id')}: missing acknowledgement_lines snapshot for PO line {source_line.get('po_line_id')}")
        snapshots_by_ack: dict[str, list[Mapping[str, Any]]] = {}
        for child in ack_line_rows:
            snapshots_by_ack.setdefault(str(child.get("ack_id")), []).append(child)
        promise_rows_by_ack: dict[str, list[Mapping[str, Any]]] = {}
        for promise in promises:
            promise_rows_by_ack.setdefault(str(promise.get("ack_id")), []).append(promise)
        for ack in acknowledgements:
            children = snapshots_by_ack.get(str(ack.get("ack_id")), [])
            requested_value = _decimal(ack.get("requested_value"))
            if children and requested_value is not None and requested_value > 0:
                quoted_value = sum((
                    (_decimal(child.get("requested_qty")) or Decimal("0")) * (_decimal(child.get("acknowledged_unit_price")) or Decimal("0"))
                    for child in children
                ), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                expected_price_pct = (Decimal("100") * (quoted_value - requested_value) / requested_value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                actual_price_pct = _decimal(ack.get("price_delta_pct"))
                if actual_price_pct is not None and actual_price_pct != expected_price_pct:
                    errors.append(f"Acknowledgement {ack.get('ack_id')}: price_delta_pct must match the line-snapshot weighted quote ({expected_price_pct})")
            current_slips: list[int] = []
            for promise in promise_rows_by_ack.get(str(ack.get("ack_id")), []):
                source_line = line_rows.get(promise.get("po_line_id"))
                promised_day = _as_date(promise.get("promised_date"))
                required_day = _as_date(source_line.get("required_date")) if source_line else None
                if promised_day and required_day:
                    current_slips.append((promised_day - required_day).days)
            expected_slip = max(current_slips) if current_slips else None
            actual_slip = _integer(ack.get("date_slip_days"))
            if actual_slip != expected_slip:
                errors.append(f"Acknowledgement {ack.get('ack_id')}: date_slip_days must equal maximum line promise slip ({expected_slip}) or NULL when no promise exists")

    # Revision supersession pointers must move forward within the same parent scope.
    acknowledgements = records_by_entity.get("Acknowledgement", records_by_entity.get("acknowledgements", ()))
    for index, ack in enumerate(acknowledgements, 1):
        target=ack_rows.get(ack.get("superseded_by"))
        if target and (target.get("po_id") != ack.get("po_id") or (_integer(target.get("revision_no")) or 0) <= (_integer(ack.get("revision_no")) or 0)):
            errors.append(f"Acknowledgement[{index}]: superseded_by must reference a higher revision of the same PO")
    promises = records_by_entity.get("PromiseDate", records_by_entity.get("promise_dates", ()))
    promise_rows = {r.get("promise_date_id"): r for r in promises}
    for index, promise in enumerate(promises, 1):
        target=promise_rows.get(promise.get("superseded_by"))
        if target and (target.get("po_line_id") != promise.get("po_line_id") or (_integer(target.get("revision_no")) or 0) <= (_integer(promise.get("revision_no")) or 0)):
            errors.append(f"PromiseDate[{index}]: superseded_by must reference a higher revision of the same PO line")
    plans = records_by_entity.get("InventoryPlan", records_by_entity.get("inventory_plans", ()))
    for index, plan in enumerate(plans, 1):
        target=plan_rows.get(plan.get("superseded_by"))
        if target and (target.get("po_line_id") != plan.get("po_line_id") or (_integer(target.get("plan_revision_no")) or 0) <= (_integer(plan.get("plan_revision_no")) or 0)):
            errors.append(f"InventoryPlan[{index}]: superseded_by must reference a higher revision of the same PO line")
    # Actor role references are checked against the optional support actors table.
    actors = context.get("actors", ())
    actor_roles = {r.get("actor_id"): r.get("role", r.get("actor_role")) for r in actors if isinstance(r, Mapping)}
    role_pairs = {
        "PurchaseOrder": (("planner_actor_id", "planner"), ("created_by_actor_id", "created_by_role")),
        "Acknowledgement": (("created_by_actor_id", "created_by_role"),),
        "PromiseDate": (("created_by_actor_id", "created_by_role"),),
        "ChangeRequest": (("requested_by_actor_id", "requested_by_role"),),
        "Approval": (("approver_actor_id", "approver_role"),),
        "InventoryPlan": (("planner_actor_id", "planner"), ("approved_by_actor_id", None)),
        "ProductionOrder": (("owner_actor_id", "owner_role"),),
    }
    if actor_roles:
        for en, pairs in role_pairs.items():
            spec=ENTITIES[en]; rows=records_by_entity.get(en, records_by_entity.get(spec.table_name, ()))
            for i,row in enumerate(rows,1):
                for actor_field, role_field in pairs:
                    actor_id=row.get(actor_field)
                    if actor_id is None: continue
                    expected_role = role_field if role_field in {"planner", "operations_manager"} else row.get(role_field) if role_field else None
                    actual_role=actor_roles.get(actor_id)
                    if actor_field == "approved_by_actor_id" and actual_role and actual_role not in APPROVER_ROLES:
                        errors.append(f"{en}[{i}]: approved_by_actor_id role must be one of {APPROVER_ROLES}, actor has {actual_role}")
                    if expected_role and actual_role and actual_role != expected_role:
                        errors.append(f"{en}[{i}]: {actor_field} role must be {expected_role}, actor has {actual_role}")
    return errors


def is_legal_transition(entity_name: str, previous_status: str, next_status: str) -> bool:
    """Return whether a status transition is defined in the lifecycle state machine."""
    if entity_name not in STATUS_TRANSITIONS: raise KeyError(f"{entity_name} has no lifecycle transition map")
    return next_status in STATUS_TRANSITIONS[entity_name].get(previous_status, ())


def render_markdown_dictionary() -> str:
    """Render the complete field dictionary from the same metadata exported here."""
    lines=["# Complete data dictionary — Generation Step 1", "",
           "This is the schema contract for synthetic data generation, persistence, workflow rules, validation, and metrics. The machine-readable source is `src/supplier_ack/schema.py`; this Markdown is generated from the same `ENTITIES` specs.", "",
           "## Conventions and validation semantics", "",
           "- `Required` means a stored value must be non-NULL; optional values may be NULL. ISO datetimes must include an explicit UTC offset; UTC is recommended.",
           "- Primary keys follow the ID formats in their field rows. Number suffixes are zero-padded; references embedded in IDs must match their FK fields.",
           "- Foreign keys naming support tables (`actors`, `items`, `warehouses`, `carriers`, `entity_event`) refer to supporting operational/master tables outside the ten core entities. Actor role values are `supplier`, `planner`, `carrier_warehouse_operator`, `logistics_analyst`, and `operations_manager`.",
           "- On `Acknowledgement`, a header-level row has `po_line_id = NULL`; when a line is the focus of an exception, it may be populated and must belong to `po_id`. The supporting `acknowledgement_lines` table stores an immutable full per-line snapshot for every ACK revision; `PromiseDate` stores the per-line promised quantity/date commitment.",
           "- Anomaly injection occurs only after baseline schema validation and zero-mismatch reconciliation. `issue_type`, `ground_truth`, and boundary labels are internal/target metadata and are removed from all input/export tables; target labels are written separately to `ground_truth.csv` and `ground_truth.json`.",
           "- `line_total` is `ROUND_HALF_UP(requested_qty * unit_price, 2)`. On final acknowledgement states, `requested_qty = ack_accepted_qty + ack_rejected_qty`; pending/submitted acknowledgements can have no resolved quantity split yet.",
           "- Cross-table FK checks and ownership consistency checks run with `validate_dataset(...)`; row-level rules run with `validate_record(...)`. `is_legal_transition(...)` validates lifecycle transitions.", "",
           "## Entity volume summary", "",
           "Counts are baseline generation targets, before revision/event-driven uplift and before optional multi-recipient notification fan-out. The starter and full scales use the same generator rules; only configured scale counts differ.", "",
           "| Entity | Primary key | Foreign keys | Baseline rows (starter / full) | Generation step |", "|---|---|---|---:|---|"]
    for name,s in ENTITIES.items():
        fks=[]
        for f in s.fields:
            if f.foreign_key:
                rel=f"`{f.name}` → `{f.foreign_key}`"
                if rel not in fks: fks.append(rel)
        lines.append(f"| {name} | `{s.primary_key}` | {'; '.join(fks) if fks else '—'} | {s.row_count_starter} / {s.row_count_full} | {s.generation_step} |")
    lines += ["", "## Entity lifecycle transitions", ""]
    for name, transitions in STATUS_TRANSITIONS.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| Current state | Legal next states |")
        lines.append("|---|---|")
        for current in STATUS_ENUMS[name]:
            nexts=transitions.get(current, ())
            lines.append(f"| `{current}` | {', '.join(f'`{v}`' for v in nexts) if nexts else 'Terminal; no outgoing transition'} |")
        lines.append("")
    for name,s in ENTITIES.items():
        lines += [f"## {name}", "", s.description, "",
                  "| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |", "|---|---|---|---|---|---|---|"]
        for f in s.fields:
            domain=f.domain.replace("|", "\\|").replace("\n", " ")
            rule=f.validation_rule.replace("|", "\\|").replace("\n", " ")
            units=f.units.replace("|", "\\|")
            lines.append(f"| `{f.name}` | `{f.sql_type}` | {'Required' if f.required else 'Optional'} | {domain} | {units} | {f.uniqueness}" + ("; **FK** `"+f.foreign_key+"`" if f.foreign_key else "") + ("; **PK**" if f.primary_key else "") + f" | {rule} |")
        if s.lifecycle_field:
            lines += ["", f"Lifecycle field: `{s.lifecycle_field}`. Full enum and legal transitions are listed in the lifecycle section above; the Python module exposes these as `STATUS_ENUMS` and `STATUS_TRANSITIONS`."]
        lines.append("")
    lines += ["## Supporting table: acknowledgement_lines", "",
              "This table is outside the ten named business entities because an Acknowledgement ID identifies a PO-level revision, while a revision contains one snapshot per PO line. Every ACK revision must have exactly one child row per PO line; all snapshots are immutable.", "",
              "| Field name | Data type | Required? | Allowed values / domain | Units | Uniqueness / key | Validation rule |", "|---|---|---|---|---|---|---|"]
    for f in ACKNOWLEDGEMENT_LINE_FIELDS:
        domain = f.domain.replace("|", "\\|").replace("\n", " ")
        rule = f.validation_rule.replace("|", "\\|").replace("\n", " ")
        units = f.units.replace("|", "\\|")
        lines.append(f"| `{f.name}` | `{f.sql_type}` | {'Required' if f.required else 'Optional'} | {domain} | {units} | {f.uniqueness}" + ("; **FK** `"+f.foreign_key+"`" if f.foreign_key else "") + ("; **PK**" if f.primary_key else "") + f" | {rule} |")
    lines += ["", "## Supporting event table: entity_event", "",
              "`entity_event` is the append-only, polymorphic event ledger. It records `event_id`, `entity_type`, `entity_id`, `event_type`, `event_timestamp`, `actor_role`, `actor_id`, `payload_json`, `previous_state`, `new_state`, `issue_type`, `ground_truth`, and typed nullable target-FK columns (one target populated for a core-entity event). Acknowledgement submissions and revisions emit `ack_submitted` / `ack_revised` events with `actor_role = supplier`.", ""]
    lines += ["## Machine-checkable validation API", "",
              "```python", "from supplier_ack.schema import ENTITIES, validate_record, validate_dataset, is_legal_transition", "", "spec = ENTITIES['POLine']", "print(spec.fields[0].validator)  # real callable", "errors = validate_record('POLine', row, context={'purchase_orders': [po_row]})", "dataset_errors = validate_dataset({'PurchaseOrder': [po_row], 'POLine': [row]})", "assert is_legal_transition('PurchaseOrder', 'ISSUED', 'ACKNOWLEDGED')", "```", ""]
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Relational SQLite schema and event-history model.
# The field metadata above remains the source of truth for the ten core tables.
# Supporting master tables and bridge tables are declared below.
# ---------------------------------------------------------------------------

import os as _os
import sqlite3 as _sqlite3
from pathlib import Path as _Path

SCHEMA_VERSION = 4

_SQLITE_ID_GLOBS: dict[tuple[str, str], tuple[str, ...]] = {
    ("suppliers", "supplier_id"): ("SUP-[0-9][0-9][0-9][0-9][0-9][0-9]",),
    ("purchase_orders", "po_id"): ("PO-2026-[0-9][0-9][0-9][0-9][0-9][0-9]",),
    ("po_lines", "po_line_id"): ("PO-2026-[0-9][0-9][0-9][0-9][0-9][0-9]-L[0-9][0-9]",),
    ("acknowledgements", "ack_id"): ("ACK-PO-2026-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9]",),
    ("promise_dates", "promise_date_id"): (
        "PD-ACK-PO-2026-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]",
    ),
    ("change_requests", "change_request_id"): ("CHG-PO-2026-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]",),
    ("approvals", "approval_id"): ("APR-CHG-PO-2026-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9]",),
    ("inventory_plans", "inventory_plan_id"): ("IP-PO-2026-[0-9][0-9][0-9][0-9][0-9][0-9]-L[0-9][0-9]-[0-9][0-9]",),
    ("production_orders", "production_order_id"): ("PRO-2026-[0-9][0-9][0-9][0-9][0-9][0-9]",),
    ("notifications", "notification_id"): ("NOT-2026-[0-9][0-9][0-9][0-9][0-9][0-9]",),
}


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_type(field: FieldSpec) -> str:
    # SQLite has no native ENUM; TEXT plus CHECK expresses the same domain.
    return "TEXT" if field.sql_type == "ENUM" else field.sql_type


def _render_core_table(entity: EntitySpec) -> str:
    columns: list[str] = []
    for field in entity.fields:
        name = field.name
        parts = [f'"{name}"', _sql_type(field)]
        if field.required or field.primary_key:
            parts.append("NOT NULL")
        if field.primary_key:
            parts.append("PRIMARY KEY")
        if field.enum_values:
            allowed = ", ".join(_sql_quote(x) for x in field.enum_values)
            parts.append(f'CHECK ("{name}" IS NULL OR "{name}" IN ({allowed}))')
        if field.foreign_key:
            parent_table, parent_column = field.foreign_key.split(".", 1)
            parts.append(f'REFERENCES "{parent_table}"("{parent_column}") ON UPDATE CASCADE ON DELETE RESTRICT')
        for glob in _SQLITE_ID_GLOBS.get((entity.table_name, name), ()):
            parts.append(f'CHECK ("{name}" GLOB {_sql_quote(glob)})')
        columns.append("    " + " ".join(parts))

    # Composite/alternate keys are first-class referenced keys for ownership-preserving joins.
    extra: list[str] = []
    for constraint in entity.unique_constraints:
        if entity.name == "Acknowledgement":
            # Header and line ACK revisions use different unique scopes and are implemented by partial indexes.
            continue
        joined = ", ".join(f'"{x}"' for x in constraint)
        extra.append(f"    UNIQUE ({joined})")

    if entity.name == "PurchaseOrder":
        extra.append('    UNIQUE ("po_id", "supplier_id")')
    elif entity.name == "POLine":
        extra.append('    UNIQUE ("po_id", "po_line_id")')
    elif entity.name == "Acknowledgement":
        extra.extend([
            '    UNIQUE ("ack_id", "po_id")',
            '    UNIQUE ("ack_id", "po_id", "po_line_id")',
        ])
        extra.append('    FOREIGN KEY ("po_id", "supplier_id") REFERENCES "purchase_orders"("po_id", "supplier_id") ON UPDATE CASCADE ON DELETE RESTRICT')
        extra.append('    FOREIGN KEY ("po_id", "po_line_id") REFERENCES "po_lines"("po_id", "po_line_id") ON UPDATE CASCADE ON DELETE RESTRICT')
    elif entity.name == "PromiseDate":
        extra.append('    FOREIGN KEY ("ack_id", "po_id") REFERENCES "acknowledgements"("ack_id", "po_id") ON UPDATE CASCADE ON DELETE RESTRICT')
        extra.append('    FOREIGN KEY ("po_id", "po_line_id") REFERENCES "po_lines"("po_id", "po_line_id") ON UPDATE CASCADE ON DELETE RESTRICT')
    elif entity.name == "ChangeRequest":
        extra.append('    FOREIGN KEY ("po_id", "supplier_id") REFERENCES "purchase_orders"("po_id", "supplier_id") ON UPDATE CASCADE ON DELETE RESTRICT')
        extra.append('    FOREIGN KEY ("po_id", "po_line_id") REFERENCES "po_lines"("po_id", "po_line_id") ON UPDATE CASCADE ON DELETE RESTRICT')
        extra.append('    UNIQUE ("change_request_id", "po_id")')
    elif entity.name == "InventoryPlan":
        extra.append('    FOREIGN KEY ("po_id", "po_line_id") REFERENCES "po_lines"("po_id", "po_line_id") ON UPDATE CASCADE ON DELETE RESTRICT')
        extra.append('    UNIQUE ("inventory_plan_id", "po_id", "po_line_id")')
    elif entity.name == "ProductionOrder":
        extra.append('    FOREIGN KEY ("po_id", "po_line_id") REFERENCES "po_lines"("po_id", "po_line_id") ON UPDATE CASCADE ON DELETE RESTRICT')
        extra.append('    FOREIGN KEY ("inventory_plan_id", "po_id", "po_line_id") REFERENCES "inventory_plans"("inventory_plan_id", "po_id", "po_line_id") ON UPDATE CASCADE ON DELETE RESTRICT')
    elif entity.name == "Notification":
        extra.append('    FOREIGN KEY ("ack_id", "po_id") REFERENCES "acknowledgements"("ack_id", "po_id") ON UPDATE CASCADE ON DELETE RESTRICT')
        extra.append('    FOREIGN KEY ("change_request_id", "po_id") REFERENCES "change_requests"("change_request_id", "po_id") ON UPDATE CASCADE ON DELETE RESTRICT')
        extra.append('    CHECK (("po_id" IS NOT NULL) OR ("ack_id" IS NULL AND "change_request_id" IS NULL))')

    # Every core entity carries paired nullable labels; a normal row has both NULL.
    names = {f.name for f in entity.fields}
    if {"issue_type", "ground_truth"}.issubset(names):
        extra.append('    CHECK (("issue_type" IS NULL AND "ground_truth" IS NULL) OR ("issue_type" IS NOT NULL AND "ground_truth" IS NOT NULL))')

    if entity.name == "Supplier":
        extra.append('    CHECK ("updated_at" >= "created_at")')
    elif entity.name == "PurchaseOrder":
        extra.extend([
            '    CHECK ("required_delivery_date" >= "order_date" OR ("issue_type" = \'DATE_CONFLICT\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("updated_at" >= "created_at")',
            '    CHECK (CAST("total_order_value" AS NUMERIC) >= 0)',
        ])
    elif entity.name == "POLine":
        for qty in ("requested_qty", "ack_accepted_qty", "ack_rejected_qty", "promised_qty", "projected_qty"):
            extra.append(f'    CHECK (CAST("{qty}" AS NUMERIC) >= 0)')
        extra.extend([
            '    CHECK (CAST("unit_price" AS NUMERIC) >= 0)',
            '    CHECK (CAST("line_total" AS NUMERIC) >= 0)',
            '    CHECK (ABS(CAST("line_total" AS REAL) - ROUND(CAST("requested_qty" AS REAL) * CAST("unit_price" AS REAL), 2)) < 0.005 OR ("issue_type" = \'LINE_TOTAL_MISMATCH\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("updated_at" >= "created_at")',
        ])
    elif entity.name == "Acknowledgement":
        for qty in ("requested_qty", "ack_accepted_qty", "ack_rejected_qty", "promised_qty", "projected_qty"):
            extra.append(f'    CHECK (CAST("{qty}" AS NUMERIC) >= 0)')
        extra.append('    CHECK ("revision_no" >= 1)')
        extra.append('    CHECK ("acknowledged_at" IS NULL OR "acknowledged_at" >= "created_at" OR ("issue_type" = \'STATUS_DATE_MISMATCH\' AND "ground_truth" IS NOT NULL))')
        extra.append('    CHECK ("status" NOT IN (\'ACCEPTED\', \'PARTIALLY_ACCEPTED\', \'REJECTED\') OR ABS(CAST("requested_qty" AS REAL) - CAST("ack_accepted_qty" AS REAL) - CAST("ack_rejected_qty" AS REAL)) < 0.0005 OR ("issue_type" IN (\'QUANTITY_MISMATCH\', \'OVER_ACKNOWLEDGEMENT\') AND "ground_truth" IS NOT NULL))')
        extra.append('    CHECK ("status" NOT IN (\'PARTIALLY_ACCEPTED\', \'REJECTED\') OR "rejection_reason" IS NOT NULL)')
    elif entity.name == "PromiseDate":
        extra.extend([
            '    CHECK ("sequence_no" BETWEEN 1 AND 99 AND "revision_no" >= 1)',
            '    CHECK ("response_due_date" >= "effective_date" OR ("issue_type" = \'DATE_CONFLICT\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("effective_date" >= substr("created_at", 1, 10) OR ("issue_type" = \'DATE_CONFLICT\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("promised_date" >= "effective_date" OR ("issue_type" IN (\'DATE_CONFLICT\', \'PROMISE_BEFORE_ORDER\') AND "ground_truth" IS NOT NULL))',
        ])
    elif entity.name == "ChangeRequest":
        extra.extend([
            '    CHECK ("updated_at" >= "created_at")',
            '    CHECK ("effective_date" >= substr("requested_at", 1, 10) OR ("issue_type" = \'DATE_CONFLICT\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("response_due_date" >= substr("requested_at", 1, 10) OR ("issue_type" = \'STATUS_DATE_MISMATCH\' AND "ground_truth" IS NOT NULL))',
        ])
    elif entity.name == "Approval":
        extra.extend([
            '    CHECK ("approval_round" >= 1)',
            '    CHECK ("due_at" >= "requested_at" OR ("issue_type" = \'STATUS_DATE_MISMATCH\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("status" IN (\'PENDING\', \'ESCALATED\') OR "decided_at" IS NOT NULL OR ("issue_type" = \'STATUS_DATE_MISMATCH\' AND "ground_truth" IS NOT NULL))',
        ])
    elif entity.name == "InventoryPlan":
        for qty in ("demand_qty", "requested_qty", "acknowledged_qty", "promised_qty", "projected_qty", "on_hand_qty", "reserved_qty", "planned_receipt_qty", "projected_available_qty", "projected_shortage_qty"):
            extra.append(f'    CHECK (CAST("{qty}" AS NUMERIC) >= 0)')
        extra.extend([
            '    CHECK (CAST("reserved_qty" AS NUMERIC) <= CAST("on_hand_qty" AS NUMERIC) OR ("issue_type" = \'QUANTITY_MISMATCH\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("status" NOT IN (\'APPROVED\', \'ACTIVE\') OR "approved_by_actor_id" IS NOT NULL OR ("issue_type" = \'MISSING_APPROVAL\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("plan_end_date" >= "plan_start_date" OR ("issue_type" = \'DATE_CONFLICT\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("updated_at" >= "created_at")',
            '    CHECK (ABS(CAST("projected_available_qty" AS REAL) - (CAST("on_hand_qty" AS REAL) - CAST("reserved_qty" AS REAL) + CAST("planned_receipt_qty" AS REAL))) < 0.0005 OR ("issue_type" = \'QUANTITY_MISMATCH\' AND "ground_truth" IS NOT NULL))',
            '    CHECK (ABS(CAST("projected_shortage_qty" AS REAL) - MAX(0, CAST("demand_qty" AS REAL) - CAST("projected_available_qty" AS REAL))) < 0.0005 OR ("issue_type" = \'QUANTITY_MISMATCH\' AND "ground_truth" IS NOT NULL))',
        ])
    elif entity.name == "ProductionOrder":
        for qty in ("planned_qty", "released_qty", "completed_qty", "affected_material_qty"):
            extra.append(f'    CHECK (CAST("{qty}" AS NUMERIC) >= 0)')
        extra.extend([
            '    CHECK ("scheduled_end_date" >= "current_start_date" OR ("issue_type" = \'DATE_CONFLICT\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("actual_end_date" IS NULL OR "actual_start_date" IS NULL OR "actual_end_date" >= "actual_start_date" OR ("issue_type" = \'DATE_CONFLICT\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("updated_at" >= "created_at")',
        ])
    elif entity.name == "Notification":
        extra.extend([
            '    CHECK ("retry_count" BETWEEN 0 AND 10)',
            '    CHECK ("scheduled_at" >= "created_at" OR ("issue_type" = \'STATUS_DATE_MISMATCH\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("sent_at" IS NULL OR "sent_at" >= "scheduled_at" OR ("issue_type" = \'STATUS_DATE_MISMATCH\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("delivered_at" IS NULL OR "sent_at" IS NOT NULL AND "delivered_at" >= "sent_at" OR ("issue_type" = \'STATUS_DATE_MISMATCH\' AND "ground_truth" IS NOT NULL))',
            '    CHECK ("status" != \'DELIVERED\' OR "delivered_at" IS NOT NULL OR ("issue_type" = \'NOTIFICATION_FAILURE\' AND "ground_truth" IS NOT NULL))',
        ])

    all_items = columns + extra
    return f'CREATE TABLE IF NOT EXISTS "{entity.table_name}" (\n' + ",\n".join(all_items) + "\n);"


def _supporting_tables_sql() -> str:
    uom = ", ".join(_sql_quote(x) for x in UNITS_OF_MEASURE)
    roles = ", ".join(_sql_quote(x) for x in ACTOR_ROLES)
    return f"""
CREATE TABLE IF NOT EXISTS actors (
    actor_id TEXT PRIMARY KEY NOT NULL,
    actor_role TEXT NOT NULL CHECK (actor_role IN ({roles})),
    actor_name TEXT NOT NULL CHECK (length(trim(actor_name)) BETWEEN 1 AND 120),
    email TEXT,
    supplier_id TEXT REFERENCES suppliers(supplier_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (actor_id, actor_role),
    CHECK (
      (actor_role = 'supplier' AND actor_id GLOB 'SUP-[0-9][0-9][0-9][0-9][0-9][0-9]' AND supplier_id = actor_id)
      OR (actor_role = 'planner' AND actor_id GLOB 'PLN-[0-9][0-9][0-9][0-9][0-9][0-9]' AND supplier_id IS NULL)
      OR (actor_role = 'carrier_warehouse_operator' AND actor_id GLOB 'CWH-[0-9][0-9][0-9][0-9][0-9][0-9]' AND supplier_id IS NULL)
      OR (actor_role = 'logistics_analyst' AND actor_id GLOB 'LOG-[0-9][0-9][0-9][0-9][0-9][0-9]' AND supplier_id IS NULL)
      OR (actor_role = 'operations_manager' AND actor_id GLOB 'OPS-[0-9][0-9][0-9][0-9][0-9][0-9]' AND supplier_id IS NULL)
    )
);
CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id TEXT PRIMARY KEY NOT NULL CHECK (warehouse_id GLOB 'WH-[0-9][0-9][0-9][0-9]'),
    warehouse_name TEXT NOT NULL CHECK (length(trim(warehouse_name)) BETWEEN 1 AND 160),
    site_code TEXT NOT NULL UNIQUE CHECK (length(trim(site_code)) BETWEEN 1 AND 30),
    timezone TEXT NOT NULL DEFAULT 'UTC',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS carriers (
    carrier_id TEXT PRIMARY KEY NOT NULL CHECK (carrier_id GLOB 'CAR-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    carrier_name TEXT NOT NULL CHECK (length(trim(carrier_name)) BETWEEN 1 AND 160),
    carrier_code TEXT NOT NULL UNIQUE CHECK (length(trim(carrier_code)) BETWEEN 1 AND 30),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY NOT NULL CHECK (item_id GLOB 'ITEM-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    item_name TEXT NOT NULL CHECK (length(trim(item_name)) BETWEEN 1 AND 240),
    default_uom TEXT NOT NULL CHECK (default_uom IN ({uom})),
    item_status TEXT NOT NULL CHECK (item_status IN ('ACTIVE', 'DISCONTINUED')),
    unit_price_min DECIMAL(12,2) NOT NULL CHECK (unit_price_min >= 0),
    unit_price_max DECIMAL(12,2) NOT NULL CHECK (unit_price_max >= unit_price_min),
    price_currency TEXT NOT NULL CHECK (price_currency IN ({", ".join(_sql_quote(x) for x in CURRENCIES)})),
    created_at TEXT NOT NULL
);
"""


def _acknowledgement_lines_table_sql() -> str:
    """Create the supporting per-line immutable snapshot for each ACK revision."""
    columns: list[str] = []
    for field in ACKNOWLEDGEMENT_LINE_FIELDS:
        parts = [f'"{field.name}"', _sql_type(field)]
        if field.required or field.primary_key:
            parts.append("NOT NULL")
        if field.primary_key:
            parts.append("PRIMARY KEY")
        if field.enum_values:
            allowed = ", ".join(_sql_quote(value) for value in field.enum_values)
            parts.append(f'CHECK ("{field.name}" IS NULL OR "{field.name}" IN ({allowed}))')
        if field.foreign_key:
            parent_table, parent_column = field.foreign_key.split(".", 1)
            parts.append(f'REFERENCES "{parent_table}"("{parent_column}") ON UPDATE CASCADE ON DELETE RESTRICT')
        columns.append("    " + " ".join(parts))
    columns.extend([
        '    UNIQUE ("ack_id", "po_line_id")',
        '    FOREIGN KEY ("ack_id", "po_id") REFERENCES "acknowledgements"("ack_id", "po_id") ON UPDATE CASCADE ON DELETE RESTRICT',
        '    FOREIGN KEY ("po_id", "po_line_id") REFERENCES "po_lines"("po_id", "po_line_id") ON UPDATE CASCADE ON DELETE RESTRICT',
        '    FOREIGN KEY ("created_by_actor_id", "created_by_role") REFERENCES "actors"("actor_id", "actor_role") ON UPDATE CASCADE ON DELETE RESTRICT',
        '    CHECK ("acknowledgement_line_id" GLOB \'AL-ACK-PO-2026-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9]-PO-2026-[0-9][0-9][0-9][0-9][0-9][0-9]-L[0-9][0-9]\')',
        '    CHECK (CAST("requested_qty" AS NUMERIC) > 0)',
        '    CHECK (CAST("accepted_qty" AS NUMERIC) >= 0 AND CAST("accepted_qty" AS NUMERIC) <= CAST("requested_qty" AS NUMERIC))',
        '    CHECK (CAST("rejected_qty" AS NUMERIC) >= 0)',
        '    CHECK (ABS(CAST("requested_qty" AS REAL) - CAST("accepted_qty" AS REAL) - CAST("rejected_qty" AS REAL)) < 0.0005 OR ("issue_type" = \'QUANTITY_MISMATCH\' AND "ground_truth" IS NOT NULL))',
        '    CHECK (("rejected_qty" = 0 AND "rejected_reason" IS NULL) OR ("rejected_qty" > 0 AND "rejected_reason" IN (\'capacity\', \'price\', \'stock\', \'logistics\')))',
        '    CHECK (ABS(CAST("qty_delta_pct" AS REAL) - ROUND(100.0 * (CAST("accepted_qty" AS REAL) - CAST("requested_qty" AS REAL)) / CAST("requested_qty" AS REAL), 4)) < 0.00005 OR ("issue_type" = \'QUANTITY_MISMATCH\' AND "ground_truth" IS NOT NULL))',
        '    CHECK (ABS(CAST("price_delta_pct" AS REAL) - CASE WHEN CAST("requested_unit_price" AS REAL) = 0 THEN 0 ELSE ROUND(100.0 * (CAST("acknowledged_unit_price" AS REAL) - CAST("requested_unit_price" AS REAL)) / CAST("requested_unit_price" AS REAL), 4) END) < 0.00005 OR ("issue_type" = \'PRICE_MISMATCH\' AND "ground_truth" IS NOT NULL))',
        '    CHECK (("issue_type" IS NULL AND "ground_truth" IS NULL) OR ("issue_type" IS NOT NULL AND "ground_truth" IS NOT NULL))',
    ])
    return "CREATE TABLE IF NOT EXISTS acknowledgement_lines (\n" + ",\n".join(columns) + "\n);"


def _entity_event_table_sql() -> str:
    types = ", ".join(_sql_quote(name) for name in ENTITIES)
    event_roles = ", ".join(_sql_quote(x) for x in (*ACTOR_ROLES, "system"))
    # Typed target FKs provide actual referential constraints for a polymorphic event target.
    targets = [
        ("Supplier", "target_supplier_id", "suppliers", "supplier_id"),
        ("PurchaseOrder", "target_po_id", "purchase_orders", "po_id"),
        ("POLine", "target_po_line_id", "po_lines", "po_line_id"),
        ("Acknowledgement", "target_ack_id", "acknowledgements", "ack_id"),
        ("PromiseDate", "target_promise_date_id", "promise_dates", "promise_date_id"),
        ("ChangeRequest", "target_change_request_id", "change_requests", "change_request_id"),
        ("Approval", "target_approval_id", "approvals", "approval_id"),
        ("InventoryPlan", "target_inventory_plan_id", "inventory_plans", "inventory_plan_id"),
        ("ProductionOrder", "target_production_order_id", "production_orders", "production_order_id"),
        ("Notification", "target_notification_id", "notifications", "notification_id"),
    ]
    target_cols = ",\n".join(
        f'    "{col}" TEXT REFERENCES "{table}"("{pk}") ON UPDATE CASCADE ON DELETE RESTRICT'
        for _, col, table, pk in targets
    )
    target_checks = []
    for entity_type, col, _, _ in targets:
        target_checks.append(
            f'("entity_type" = {_sql_quote(entity_type)} AND "entity_id" = "{col}" AND '
            + " AND ".join(f'"{other_col}" IS NULL' for _, other_col, _, _ in targets if other_col != col)
            + ")"
        )
    label_pair = 'CHECK (("issue_type" IS NULL AND "ground_truth" IS NULL) OR ("issue_type" IS NOT NULL AND "ground_truth" IS NOT NULL))'
    return f"""
CREATE TABLE IF NOT EXISTS entity_event (
    event_id TEXT PRIMARY KEY NOT NULL DEFAULT ('EVT-' || upper(hex(randomblob(12)))),
    entity_type TEXT NOT NULL CHECK (entity_type IN ({types})),
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (length(trim(event_type)) BETWEEN 1 AND 80),
    event_timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    actor_role TEXT NOT NULL CHECK (actor_role IN ({event_roles})),
    actor_id TEXT,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object'),
    previous_state TEXT CHECK (previous_state IS NULL OR (json_valid(previous_state) AND json_type(previous_state) = 'object')),
    new_state TEXT CHECK (new_state IS NULL OR (json_valid(new_state) AND json_type(new_state) = 'object')),
    issue_type TEXT CHECK (issue_type IS NULL OR issue_type IN ({", ".join(_sql_quote(x) for x in ANOMALY_TYPES)})),
    ground_truth TEXT CHECK (ground_truth IS NULL OR ground_truth IN ({", ".join(_sql_quote(x) for x in ANOMALY_TYPES)})),
{target_cols},
    FOREIGN KEY (actor_id, actor_role) REFERENCES actors(actor_id, actor_role) ON UPDATE CASCADE ON DELETE RESTRICT,
    {label_pair},
    CHECK ({' OR '.join(target_checks)})
);
CREATE INDEX IF NOT EXISTS ix_entity_event_entity ON entity_event(entity_type, entity_id, event_timestamp);
CREATE INDEX IF NOT EXISTS ix_entity_event_type_time ON entity_event(event_type, event_timestamp);
CREATE TRIGGER IF NOT EXISTS trg_entity_event_no_update
BEFORE UPDATE ON entity_event
BEGIN SELECT RAISE(ABORT, 'entity_event is append-only; UPDATE is forbidden'); END;
CREATE TRIGGER IF NOT EXISTS trg_entity_event_no_delete
BEFORE DELETE ON entity_event
BEGIN SELECT RAISE(ABORT, 'entity_event is append-only; DELETE is forbidden'); END;
"""


def _bridge_tables_sql() -> str:
    roles = ", ".join(_sql_quote(x) for x in NOTIFICATION_TARGET_ROLES)
    return f"""
CREATE TABLE IF NOT EXISTS notification_recipient (
    notification_id TEXT NOT NULL REFERENCES notifications(notification_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    actor_role TEXT NOT NULL CHECK (actor_role IN ({roles})),
    recipient_actor_id TEXT,
    PRIMARY KEY (notification_id, actor_role),
    FOREIGN KEY (recipient_actor_id, actor_role) REFERENCES actors(actor_id, actor_role) ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS ix_notification_recipient_role ON notification_recipient(actor_role, notification_id);

CREATE TABLE IF NOT EXISTS production_order_line (
    production_order_id TEXT NOT NULL REFERENCES production_orders(production_order_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    po_line_id TEXT NOT NULL REFERENCES po_lines(po_line_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    allocated_quantity DECIMAL(14,3) NOT NULL CHECK (CAST(allocated_quantity AS NUMERIC) > 0),
    allocated_uom TEXT NOT NULL CHECK (allocated_uom IN ({', '.join(_sql_quote(x) for x in UNITS_OF_MEASURE)})),
    created_at TEXT NOT NULL,
    PRIMARY KEY (production_order_id, po_line_id)
);
CREATE INDEX IF NOT EXISTS ix_production_order_line_po_line ON production_order_line(po_line_id, production_order_id);

CREATE TABLE IF NOT EXISTS production_order_impact (
    impact_id TEXT PRIMARY KEY NOT NULL CHECK (impact_id GLOB 'IMP-2026-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    production_order_id TEXT NOT NULL REFERENCES production_orders(production_order_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    change_request_id TEXT NOT NULL REFERENCES change_requests(change_request_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    po_line_id TEXT NOT NULL REFERENCES po_lines(po_line_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    impact_type TEXT NOT NULL CHECK (impact_type IN ('date_conflict', 'quantity_shortfall')),
    severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    slip_days INTEGER NOT NULL,
    shortfall_pct DECIMAL(9,4) NOT NULL,
    old_projected_delivery_date TEXT NOT NULL,
    new_projected_delivery_date TEXT NOT NULL,
    old_projected_qty DECIMAL(14,3) NOT NULL,
    new_projected_qty DECIMAL(14,3) NOT NULL,
    rescheduled_planned_start_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (slip_days >= 0),
    CHECK (shortfall_pct >= 0),
    CHECK (CAST(old_projected_qty AS NUMERIC) >= 0 AND CAST(new_projected_qty AS NUMERIC) >= 0)
);
CREATE INDEX IF NOT EXISTS ix_production_order_impact_change ON production_order_impact(change_request_id, production_order_id);
CREATE TRIGGER IF NOT EXISTS trg_production_order_impact_no_update
BEFORE UPDATE ON production_order_impact
BEGIN SELECT RAISE(ABORT, 'production_order_impact is append-only; UPDATE is forbidden'); END;
CREATE TRIGGER IF NOT EXISTS trg_production_order_impact_no_delete
BEFORE DELETE ON production_order_impact
BEGIN SELECT RAISE(ABORT, 'production_order_impact is append-only; DELETE is forbidden'); END;
"""


def _json_object(alias: str, entity: EntitySpec) -> str:
    parts: list[str] = []
    for field in entity.fields:
        parts.extend((_sql_quote(field.name), f'{alias}."{field.name}"'))
    return "json_object(" + ", ".join(parts) + ")"


def _event_target_column(entity_name: str) -> str:
    return {
        "Supplier": "target_supplier_id", "PurchaseOrder": "target_po_id",
        "POLine": "target_po_line_id", "Acknowledgement": "target_ack_id",
        "PromiseDate": "target_promise_date_id", "ChangeRequest": "target_change_request_id",
        "Approval": "target_approval_id", "InventoryPlan": "target_inventory_plan_id",
        "ProductionOrder": "target_production_order_id", "Notification": "target_notification_id",
    }[entity_name]


def _event_actor_sql(entity: EntitySpec, update: bool = False) -> tuple[str, str]:
    fields = {f.name for f in entity.fields}
    if entity.name == "PurchaseOrder":
        role = 'COALESCE(NEW."created_by_role", \'system\')'
        actor = 'NEW."created_by_actor_id"'
    elif entity.name in {"Acknowledgement", "PromiseDate"}:
        role = 'COALESCE(NEW."created_by_role", \'system\')'
        actor = 'NEW."created_by_actor_id"'
    elif entity.name == "ChangeRequest":
        role = 'COALESCE(NEW."requested_by_role", \'system\')'
        actor = 'NEW."requested_by_actor_id"'
    elif entity.name == "Approval":
        role = 'COALESCE(NEW."approver_role", \'system\')'
        actor = 'NEW."approver_actor_id"'
    elif entity.name == "InventoryPlan":
        role = "'planner'"
        actor = 'NEW."planner_actor_id"'
    elif entity.name == "ProductionOrder":
        role = 'COALESCE(NEW."owner_role", \'system\')'
        actor = 'NEW."owner_actor_id"'
    elif entity.name == "Supplier":
        role = 'COALESCE(NEW."data_owner_role", \'system\')'
        actor = "NULL"
    else:
        role = "'system'"
        actor = "NULL"
    return role, actor


def _insert_event_type_sql(entity: EntitySpec) -> str:
    n = entity.name
    if n == "PurchaseOrder": return "'PO_CREATED'"
    if n == "POLine": return "'PO_LINE_CREATED'"
    if n == "Acknowledgement":
        return "CASE NEW.status WHEN 'ACCEPTED' THEN 'ACK_ACCEPTED' WHEN 'PARTIALLY_ACCEPTED' THEN 'ACK_PARTIALLY_ACCEPTED' WHEN 'REJECTED' THEN 'ACK_REJECTED' WHEN 'SUBMITTED' THEN 'ACKNOWLEDGEMENT_RECEIVED' ELSE 'ACKNOWLEDGEMENT_CREATED' END"
    if n == "PromiseDate": return "'PROMISE_DATE_RECORDED'"
    if n == "ChangeRequest": return "CASE WHEN NEW.status = 'SUBMITTED' THEN 'CHANGE_REQUESTED' ELSE 'CHANGE_REQUEST_CREATED' END"
    if n == "Approval": return "CASE NEW.status WHEN 'APPROVED' THEN 'CHANGE_APPROVED' WHEN 'REJECTED' THEN 'CHANGE_REJECTED' ELSE 'APPROVAL_CREATED' END"
    if n == "InventoryPlan": return "'PLAN_CREATED'"
    if n == "ProductionOrder": return "'PRODUCTION_ORDER_CREATED'"
    if n == "Notification": return "CASE WHEN NEW.status = 'SENT' THEN 'NOTIFICATION_SENT' ELSE 'NOTIFICATION_CREATED' END"
    return "'SUPPLIER_CREATED'"


def _update_event_type_sql(entity: EntitySpec) -> str:
    n = entity.name
    if n == "PurchaseOrder": return "CASE WHEN OLD.status IS NOT NEW.status THEN 'PO_STATUS_CHANGED' ELSE 'PO_UPDATED' END"
    if n == "POLine": return "CASE WHEN OLD.status IS NOT NEW.status THEN 'PO_LINE_STATUS_CHANGED' ELSE 'PO_LINE_UPDATED' END"
    if n == "Acknowledgement": return "CASE WHEN OLD.status IS NOT NEW.status AND NEW.status = 'ACCEPTED' THEN 'ACK_ACCEPTED' WHEN OLD.status IS NOT NEW.status AND NEW.status = 'PARTIALLY_ACCEPTED' THEN 'ACK_PARTIALLY_ACCEPTED' WHEN OLD.status IS NOT NEW.status AND NEW.status = 'REJECTED' THEN 'ACK_REJECTED' WHEN OLD.status IS NOT NEW.status AND NEW.status = 'SUBMITTED' THEN 'ACKNOWLEDGEMENT_RECEIVED' ELSE 'ACKNOWLEDGEMENT_UPDATED' END"
    if n == "PromiseDate": return "CASE WHEN OLD.status IS NOT NEW.status THEN 'PROMISE_DATE_STATUS_CHANGED' ELSE 'PROMISE_DATE_UPDATED' END"
    if n == "ChangeRequest": return "CASE WHEN NEW.status = 'APPROVED' AND OLD.status IS NOT NEW.status THEN 'CHANGE_APPROVED' WHEN NEW.status = 'REJECTED' AND OLD.status IS NOT NEW.status THEN 'CHANGE_REJECTED' WHEN NEW.status = 'SUBMITTED' AND OLD.status IS NOT NEW.status THEN 'CHANGE_REQUESTED' ELSE 'CHANGE_REQUEST_UPDATED' END"
    if n == "Approval": return "CASE WHEN NEW.status = 'APPROVED' AND OLD.status IS NOT NEW.status THEN 'CHANGE_APPROVED' WHEN NEW.status = 'REJECTED' AND OLD.status IS NOT NEW.status THEN 'CHANGE_REJECTED' ELSE 'APPROVAL_DECISION_UPDATED' END"
    if n == "InventoryPlan": return "CASE WHEN OLD.status IS NOT NEW.status THEN 'PLAN_STATUS_CHANGED' ELSE 'PLAN_UPDATED' END"
    if n == "ProductionOrder": return "CASE WHEN OLD.status IS NOT NEW.status THEN 'PRODUCTION_ORDER_STATUS_CHANGED' ELSE 'PRODUCTION_ORDER_UPDATED' END"
    if n == "Notification": return "CASE WHEN NEW.status = 'SENT' AND OLD.status IS NOT NEW.status THEN 'NOTIFICATION_SENT' WHEN NEW.status = 'DELIVERED' AND OLD.status IS NOT NEW.status THEN 'NOTIFICATION_DELIVERED' ELSE 'NOTIFICATION_STATUS_OR_CONTENT_CHANGED' END"
    return "'SUPPLIER_UPDATED'"


def _event_triggers_sql() -> str:
    chunks: list[str] = []
    for entity_name, entity in ENTITIES.items():
        table, pk = entity.table_name, entity.primary_key
        target_col = _event_target_column(entity_name)
        actor_role, actor_id = _event_actor_sql(entity)
        snapshot_new = _json_object("NEW", entity)
        insert_type = _insert_event_type_sql(entity)
        chunks.append(f"""
CREATE TRIGGER IF NOT EXISTS trg_{table}_event_insert
AFTER INSERT ON "{table}"
BEGIN
  INSERT INTO entity_event (
    entity_type, entity_id, event_type, actor_role, actor_id, payload_json,
    previous_state, new_state, issue_type, ground_truth, "{target_col}"
  ) VALUES (
    {_sql_quote(entity_name)}, NEW."{pk}", {insert_type}, {actor_role}, {actor_id},
    json_object('operation', 'INSERT', 'table', {_sql_quote(table)}), NULL,
    {snapshot_new}, NEW.issue_type, NEW.ground_truth, NEW."{pk}"
  );
END;
""")
        comparisons = " OR ".join(f'OLD."{f.name}" IS NOT NEW."{f.name}"' for f in entity.fields)
        role_update, actor_update = _event_actor_sql(entity, update=True)
        chunks.append(f"""
CREATE TRIGGER IF NOT EXISTS trg_{table}_event_update
AFTER UPDATE ON "{table}"
WHEN {comparisons}
BEGIN
  INSERT INTO entity_event (
    entity_type, entity_id, event_type, actor_role, actor_id, payload_json,
    previous_state, new_state, issue_type, ground_truth, "{target_col}"
  ) VALUES (
    {_sql_quote(entity_name)}, NEW."{pk}", {_update_event_type_sql(entity)}, {role_update}, {actor_update},
    json_object('operation', 'UPDATE', 'table', {_sql_quote(table)}),
    {_json_object('OLD', entity)}, {_json_object('NEW', entity)}, NEW.issue_type, NEW.ground_truth, NEW."{pk}"
  );
END;
""")
    # Cross-row ownership joins are enforced by triggers in addition to their column/composite FKs.
    chunks.append("""
CREATE TRIGGER IF NOT EXISTS trg_po_line_parent_consistency_insert
BEFORE INSERT ON po_lines
WHEN EXISTS (
  SELECT 1 FROM purchase_orders p WHERE p.po_id = NEW.po_id
    AND (p.currency <> NEW.currency OR (NEW.required_date < p.order_date AND NOT (NEW.issue_type = 'DATE_CONFLICT' AND NEW.ground_truth IS NOT NULL)))
)
BEGIN SELECT RAISE(ABORT, 'PO line currency must match PO and required_date must not predate order_date'); END;
CREATE TRIGGER IF NOT EXISTS trg_po_line_parent_consistency_update
BEFORE UPDATE OF po_id, currency, required_date ON po_lines
WHEN EXISTS (
  SELECT 1 FROM purchase_orders p WHERE p.po_id = NEW.po_id
    AND (p.currency <> NEW.currency OR (NEW.required_date < p.order_date AND NOT (NEW.issue_type = 'DATE_CONFLICT' AND NEW.ground_truth IS NOT NULL)))
)
BEGIN SELECT RAISE(ABORT, 'PO line currency must match PO and required_date must not predate order_date'); END;
CREATE TRIGGER IF NOT EXISTS trg_actor_role_purchase_order_insert
BEFORE INSERT ON purchase_orders
WHEN NOT EXISTS (SELECT 1 FROM actors a WHERE a.actor_id = NEW.planner_actor_id AND a.actor_role = 'planner')
  OR NOT EXISTS (SELECT 1 FROM actors a WHERE a.actor_id = NEW.created_by_actor_id AND a.actor_role = NEW.created_by_role)
BEGIN SELECT RAISE(ABORT, 'purchase order actor IDs must resolve to actors with matching roles'); END;
CREATE TRIGGER IF NOT EXISTS trg_actor_role_purchase_order_update
BEFORE UPDATE OF planner_actor_id, created_by_actor_id, created_by_role ON purchase_orders
WHEN NOT EXISTS (SELECT 1 FROM actors a WHERE a.actor_id = NEW.planner_actor_id AND a.actor_role = 'planner')
  OR NOT EXISTS (SELECT 1 FROM actors a WHERE a.actor_id = NEW.created_by_actor_id AND a.actor_role = NEW.created_by_role)
BEGIN SELECT RAISE(ABORT, 'purchase order actor IDs must resolve to actors with matching roles'); END;
CREATE TRIGGER IF NOT EXISTS trg_promise_parent_consistency_insert
BEFORE INSERT ON promise_dates
WHEN NOT EXISTS (
  SELECT 1 FROM acknowledgements a
  WHERE a.ack_id = NEW.ack_id AND a.po_id = NEW.po_id
    AND (a.po_line_id IS NULL OR a.po_line_id = NEW.po_line_id)
)
BEGIN SELECT RAISE(ABORT, 'PromiseDate must reference an acknowledgement for the same PO line'); END;
CREATE TRIGGER IF NOT EXISTS trg_promise_date_order_date_insert
BEFORE INSERT ON promise_dates
WHEN NEW.promised_date < (SELECT p.order_date FROM purchase_orders p WHERE p.po_id = NEW.po_id)
 AND NOT (NEW.issue_type = 'PROMISE_BEFORE_ORDER' AND NEW.ground_truth IS NOT NULL)
BEGIN SELECT RAISE(ABORT, 'promised_date must be >= parent PO order_date unless explicitly labelled PROMISE_BEFORE_ORDER'); END;
CREATE TRIGGER IF NOT EXISTS trg_promise_date_order_date_update
BEFORE UPDATE OF promised_date, po_id, issue_type, ground_truth ON promise_dates
WHEN NEW.promised_date < (SELECT p.order_date FROM purchase_orders p WHERE p.po_id = NEW.po_id)
 AND NOT (NEW.issue_type = 'PROMISE_BEFORE_ORDER' AND NEW.ground_truth IS NOT NULL)
BEGIN SELECT RAISE(ABORT, 'promised_date must be >= parent PO order_date unless explicitly labelled PROMISE_BEFORE_ORDER'); END;
CREATE TRIGGER IF NOT EXISTS trg_change_request_actor_role_insert
BEFORE INSERT ON change_requests
WHEN NOT EXISTS (SELECT 1 FROM actors a WHERE a.actor_id = NEW.requested_by_actor_id AND a.actor_role = NEW.requested_by_role)
BEGIN SELECT RAISE(ABORT, 'change request requester ID and role must match'); END;
CREATE TRIGGER IF NOT EXISTS trg_approval_actor_role_insert
BEFORE INSERT ON approvals
WHEN NOT EXISTS (SELECT 1 FROM actors a WHERE a.actor_id = NEW.approver_actor_id AND a.actor_role = NEW.approver_role)
BEGIN SELECT RAISE(ABORT, 'approval actor ID and role must match'); END;
CREATE TRIGGER IF NOT EXISTS trg_inventory_plan_actor_role_insert
BEFORE INSERT ON inventory_plans
WHEN NOT EXISTS (SELECT 1 FROM actors a WHERE a.actor_id = NEW.planner_actor_id AND a.actor_role = 'planner')
  OR (NEW.approved_by_actor_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM actors a WHERE a.actor_id = NEW.approved_by_actor_id AND a.actor_role IN ('planner', 'operations_manager')))
BEGIN SELECT RAISE(ABORT, 'inventory plan actors must resolve to allowed roles'); END;
CREATE TRIGGER IF NOT EXISTS trg_notification_relation_consistency_insert
BEFORE INSERT ON notifications
WHEN (NEW.ack_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM acknowledgements a WHERE a.ack_id = NEW.ack_id AND a.po_id = NEW.po_id))
  OR (NEW.change_request_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM change_requests c WHERE c.change_request_id = NEW.change_request_id AND c.po_id = NEW.po_id))
BEGIN SELECT RAISE(ABORT, 'notification links must belong to its PO'); END;

CREATE TRIGGER IF NOT EXISTS trg_acknowledgement_revision_payload_immutable
BEFORE UPDATE ON acknowledgements
WHEN OLD.po_id IS NOT NEW.po_id OR OLD.supplier_id IS NOT NEW.supplier_id OR OLD.po_line_id IS NOT NEW.po_line_id
 OR OLD.revision_no IS NOT NEW.revision_no OR OLD.acknowledged_at IS NOT NEW.acknowledged_at
 OR OLD.response_due_at IS NOT NEW.response_due_at OR OLD.requested_qty IS NOT NEW.requested_qty
 OR OLD.ack_accepted_qty IS NOT NEW.ack_accepted_qty OR OLD.ack_rejected_qty IS NOT NEW.ack_rejected_qty
 OR OLD.promised_qty IS NOT NEW.promised_qty OR OLD.projected_qty IS NOT NEW.projected_qty
 OR OLD.requested_value IS NOT NEW.requested_value OR OLD.acknowledged_value IS NOT NEW.acknowledged_value
 OR OLD.promised_value IS NOT NEW.promised_value OR OLD.projected_value IS NOT NEW.projected_value
 OR OLD.supplier_note IS NOT NEW.supplier_note OR OLD.rejection_reason IS NOT NEW.rejection_reason OR OLD.created_at IS NOT NEW.created_at
 OR OLD.created_by_role IS NOT NEW.created_by_role OR OLD.created_by_actor_id IS NOT NEW.created_by_actor_id
BEGIN SELECT RAISE(ABORT, 'acknowledgement revision payload is immutable; insert a new revision'); END;
CREATE TRIGGER IF NOT EXISTS trg_inventory_plan_projection_immutable
BEFORE UPDATE ON inventory_plans
WHEN OLD.po_id IS NOT NEW.po_id OR OLD.po_line_id IS NOT NEW.po_line_id OR OLD.plan_revision_no IS NOT NEW.plan_revision_no
 OR OLD.demand_qty IS NOT NEW.demand_qty OR OLD.requested_qty IS NOT NEW.requested_qty
 OR OLD.acknowledged_qty IS NOT NEW.acknowledged_qty OR OLD.promised_qty IS NOT NEW.promised_qty
 OR OLD.projected_qty IS NOT NEW.projected_qty OR OLD.on_hand_qty IS NOT NEW.on_hand_qty
 OR OLD.reserved_qty IS NOT NEW.reserved_qty OR OLD.planned_receipt_qty IS NOT NEW.planned_receipt_qty
 OR OLD.projected_available_qty IS NOT NEW.projected_available_qty OR OLD.projected_shortage_qty IS NOT NEW.projected_shortage_qty
 OR OLD.required_date IS NOT NEW.required_date OR OLD.promised_date IS NOT NEW.promised_date
 OR OLD.plan_start_date IS NOT NEW.plan_start_date OR OLD.plan_end_date IS NOT NEW.plan_end_date
 OR OLD.planner_actor_id IS NOT NEW.planner_actor_id OR OLD.approved_by_actor_id IS NOT NEW.approved_by_actor_id
 OR OLD.effective_date IS NOT NEW.effective_date OR OLD.created_at IS NOT NEW.created_at
BEGIN SELECT RAISE(ABORT, 'inventory plan projection is immutable; insert a new plan revision'); END;
CREATE TRIGGER IF NOT EXISTS trg_inventory_plan_append_only_update
BEFORE UPDATE ON inventory_plans
BEGIN SELECT RAISE(ABORT, 'InventoryPlan versions are append-only; insert a new version'); END;
CREATE TRIGGER IF NOT EXISTS trg_inventory_plan_append_only_delete
BEFORE DELETE ON inventory_plans
BEGIN SELECT RAISE(ABORT, 'InventoryPlan versions are append-only; deletion is forbidden'); END;
CREATE TRIGGER IF NOT EXISTS trg_terminal_approval_immutable
BEFORE UPDATE ON approvals
WHEN OLD.status IN ('APPROVED', 'REJECTED', 'WITHDRAWN')
 AND (OLD.approval_id IS NOT NEW.approval_id OR OLD.change_request_id IS NOT NEW.change_request_id
      OR OLD.approval_round IS NOT NEW.approval_round OR OLD.approver_role IS NOT NEW.approver_role
      OR OLD.approval_level IS NOT NEW.approval_level OR OLD.approver_actor_id IS NOT NEW.approver_actor_id OR OLD.status IS NOT NEW.status
      OR OLD.requested_at IS NOT NEW.requested_at OR OLD.due_at IS NOT NEW.due_at
      OR OLD.decided_at IS NOT NEW.decided_at OR OLD.decision_reason IS NOT NEW.decision_reason OR OLD.comments IS NOT NEW.comments
      OR OLD.threshold_name IS NOT NEW.threshold_name OR OLD.threshold_value IS NOT NEW.threshold_value
      OR OLD.created_at IS NOT NEW.created_at OR OLD.issue_type IS NOT NEW.issue_type
      OR OLD.ground_truth IS NOT NEW.ground_truth)
BEGIN SELECT RAISE(ABORT, 'terminal approval decisions are immutable; create a new approval round'); END;

CREATE TRIGGER IF NOT EXISTS trg_approval_rows_append_only_update
BEFORE UPDATE ON approvals
BEGIN SELECT RAISE(ABORT, 'Approval records are append-only; insert a new approval round'); END;
CREATE TRIGGER IF NOT EXISTS trg_approval_rows_append_only_delete
BEFORE DELETE ON approvals
BEGIN SELECT RAISE(ABORT, 'Approval records are append-only; deletion is forbidden'); END;

CREATE TRIGGER IF NOT EXISTS trg_notification_recipient_audit_insert
AFTER INSERT ON notification_recipient
BEGIN
  INSERT INTO entity_event(entity_type, entity_id, event_type, actor_role, payload_json, previous_state, new_state, target_notification_id)
  VALUES ('Notification', NEW.notification_id, 'NOTIFICATION_RECIPIENT_ADDED', 'system',
    json_object('operation','INSERT','actor_role',NEW.actor_role,'recipient_actor_id',NEW.recipient_actor_id), NULL,
    json_object('notification_id',NEW.notification_id,'actor_role',NEW.actor_role,'recipient_actor_id',NEW.recipient_actor_id), NEW.notification_id);
END;
CREATE TRIGGER IF NOT EXISTS trg_notification_recipient_audit_delete
AFTER DELETE ON notification_recipient
BEGIN
  INSERT INTO entity_event(entity_type, entity_id, event_type, actor_role, payload_json, previous_state, new_state, target_notification_id)
  VALUES ('Notification', OLD.notification_id, 'NOTIFICATION_RECIPIENT_REMOVED', 'system',
    json_object('operation','DELETE','actor_role',OLD.actor_role,'recipient_actor_id',OLD.recipient_actor_id),
    json_object('notification_id',OLD.notification_id,'actor_role',OLD.actor_role,'recipient_actor_id',OLD.recipient_actor_id), NULL, OLD.notification_id);
END;
CREATE TRIGGER IF NOT EXISTS trg_production_order_line_audit_insert
AFTER INSERT ON production_order_line
BEGIN
  INSERT INTO entity_event(entity_type, entity_id, event_type, actor_role, payload_json, previous_state, new_state, target_production_order_id)
  VALUES ('ProductionOrder', NEW.production_order_id, 'PRODUCTION_MATERIAL_ALLOCATED', 'system',
    json_object('operation','INSERT','po_line_id',NEW.po_line_id,'allocated_quantity',NEW.allocated_quantity,'allocated_uom',NEW.allocated_uom), NULL,
    json_object('production_order_id',NEW.production_order_id,'po_line_id',NEW.po_line_id,'allocated_quantity',NEW.allocated_quantity,'allocated_uom',NEW.allocated_uom), NEW.production_order_id);
END;
CREATE TRIGGER IF NOT EXISTS trg_production_order_line_audit_update
AFTER UPDATE ON production_order_line
BEGIN
  INSERT INTO entity_event(entity_type, entity_id, event_type, actor_role, payload_json, previous_state, new_state, target_production_order_id)
  VALUES ('ProductionOrder', NEW.production_order_id, 'PRODUCTION_MATERIAL_ALLOCATION_CHANGED', 'system',
    json_object('operation','UPDATE','po_line_id',NEW.po_line_id),
    json_object('production_order_id',OLD.production_order_id,'po_line_id',OLD.po_line_id,'allocated_quantity',OLD.allocated_quantity,'allocated_uom',OLD.allocated_uom),
    json_object('production_order_id',NEW.production_order_id,'po_line_id',NEW.po_line_id,'allocated_quantity',NEW.allocated_quantity,'allocated_uom',NEW.allocated_uom), NEW.production_order_id);
END;
CREATE TRIGGER IF NOT EXISTS trg_production_order_line_audit_delete
AFTER DELETE ON production_order_line
BEGIN
  INSERT INTO entity_event(entity_type, entity_id, event_type, actor_role, payload_json, previous_state, new_state, target_production_order_id)
  VALUES ('ProductionOrder', OLD.production_order_id, 'PRODUCTION_MATERIAL_ALLOCATION_REMOVED', 'system',
    json_object('operation','DELETE','po_line_id',OLD.po_line_id),
    json_object('production_order_id',OLD.production_order_id,'po_line_id',OLD.po_line_id,'allocated_quantity',OLD.allocated_quantity,'allocated_uom',OLD.allocated_uom), NULL, OLD.production_order_id);
END;
""")
    return "\n".join(chunks)


def _build_create_schema_sql() -> str:
    sections = [
        "PRAGMA foreign_keys = ON;",
        "BEGIN IMMEDIATE;",
        "CREATE TABLE IF NOT EXISTS suppliers (\n"
        + ",\n".join([
            '    supplier_id VARCHAR(10) NOT NULL PRIMARY KEY CHECK (supplier_id GLOB \'SUP-[0-9][0-9][0-9][0-9][0-9][0-9]\')',
            '    supplier_name VARCHAR(160) NOT NULL CHECK (length(trim(supplier_name)) BETWEEN 1 AND 160)',
            '    supplier_code VARCHAR(40) NOT NULL UNIQUE CHECK (length(trim(supplier_code)) BETWEEN 2 AND 40)',
            '    supplier_contact_name VARCHAR(120) NOT NULL CHECK (length(trim(supplier_contact_name)) BETWEEN 1 AND 120)',
            '    supplier_contact_email VARCHAR(254) NOT NULL',
            '    supplier_contact_phone VARCHAR(24)',
            '    supplier_status TEXT NOT NULL CHECK (supplier_status IN (\'ACTIVE\', \'ON_HOLD\', \'BLOCKED\', \'INACTIVE\'))',
            '    risk_tier TEXT NOT NULL CHECK (risk_tier IN (\'LOW\', \'MEDIUM\', \'HIGH\', \'CRITICAL\'))',
            f'    region TEXT NOT NULL CHECK (region IN ({", ".join(_sql_quote(x) for x in REGIONS)}))',
            '    lead_time_days INTEGER NOT NULL CHECK (lead_time_days BETWEEN 7 AND 90)',
            '    reliability_score DECIMAL(5,4) NOT NULL CHECK (reliability_score BETWEEN 0 AND 1)',
            '    on_time_rate DECIMAL(5,4) NOT NULL CHECK (on_time_rate BETWEEN 0 AND 1)',
            '    ack_rate DECIMAL(5,4) NOT NULL CHECK (ack_rate BETWEEN 0 AND 1)',
            '    on_time_promise_rate DECIMAL(5,4) NOT NULL CHECK (on_time_promise_rate BETWEEN 0 AND 1)',
            '    avg_slip_days DECIMAL(8,3) NOT NULL CHECK (avg_slip_days >= 0)',
            '    preferred_carrier_id VARCHAR(10) NOT NULL REFERENCES carriers(carrier_id) ON UPDATE CASCADE ON DELETE RESTRICT',
            f'    default_currency CHAR(3) NOT NULL CHECK (default_currency IN ({", ".join(_sql_quote(x) for x in CURRENCIES)}))',
            f'    data_owner_role TEXT NOT NULL CHECK (data_owner_role IN ({", ".join(_sql_quote(x) for x in ACTOR_ROLES)}))',
            '    created_at DATETIME NOT NULL',
            '    updated_at DATETIME NOT NULL CHECK (updated_at >= created_at)',
            f'    issue_type TEXT CHECK (issue_type IS NULL OR issue_type IN ({", ".join(_sql_quote(x) for x in ANOMALY_TYPES)}))',
            f'    ground_truth TEXT CHECK (ground_truth IS NULL OR ground_truth IN ({", ".join(_sql_quote(x) for x in ANOMALY_TYPES)}))',
            '    CHECK ((issue_type IS NULL AND ground_truth IS NULL) OR (issue_type IS NOT NULL AND ground_truth IS NOT NULL))',
        ]) + "\n);",
        _supporting_tables_sql(),
    ]
    # Supplier is rendered manually above for strong SQL-native string/email checks; the remaining core tables use FieldSpec metadata.
    order = ["PurchaseOrder", "POLine", "Acknowledgement", "PromiseDate", "ChangeRequest", "Approval", "InventoryPlan", "ProductionOrder"]
    for name in order:
        sections.append(_render_core_table(ENTITIES[name]))
    sections.append(_entity_event_table_sql())
    sections.append(_acknowledgement_lines_table_sql())
    sections.append(_render_core_table(ENTITIES["Notification"]))
    sections.append(_bridge_tables_sql())
    sections.append("""
CREATE UNIQUE INDEX IF NOT EXISTS uq_ack_header_revision
ON acknowledgements(po_id, revision_no) WHERE po_line_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ack_line_revision
ON acknowledgements(po_line_id, revision_no) WHERE po_line_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_po_supplier_status ON purchase_orders(supplier_id, status);
CREATE INDEX IF NOT EXISTS ix_po_required_delivery_date ON purchase_orders(required_delivery_date);
CREATE INDEX IF NOT EXISTS ix_po_lines_po_status ON po_lines(po_id, status);
CREATE INDEX IF NOT EXISTS ix_ack_po_created ON acknowledgements(po_id, created_at);
CREATE INDEX IF NOT EXISTS ix_ack_lines_po_line ON acknowledgement_lines(po_line_id, ack_id);
CREATE INDEX IF NOT EXISTS ix_promises_line_date ON promise_dates(po_line_id, promised_date);
CREATE INDEX IF NOT EXISTS ix_change_status_due ON change_requests(status, response_due_date);
CREATE INDEX IF NOT EXISTS ix_approvals_change_status ON approvals(change_request_id, status);
CREATE INDEX IF NOT EXISTS ix_inventory_plan_line_status ON inventory_plans(po_line_id, status);
CREATE INDEX IF NOT EXISTS ix_production_order_schedule ON production_orders(current_start_date, status);
CREATE INDEX IF NOT EXISTS ix_notification_status_schedule ON notifications(status, scheduled_at);
""")
    sections.append(_event_triggers_sql())
    sections.append("""
CREATE TRIGGER IF NOT EXISTS trg_acknowledgement_lines_immutable_update
BEFORE UPDATE ON acknowledgement_lines
BEGIN SELECT RAISE(ABORT, 'acknowledgement line snapshots are immutable; insert a new ACK revision'); END;
CREATE TRIGGER IF NOT EXISTS trg_acknowledgement_lines_immutable_delete
BEFORE DELETE ON acknowledgement_lines
BEGIN SELECT RAISE(ABORT, 'acknowledgement line snapshots are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_promise_logistics_consistency_insert
BEFORE INSERT ON promise_dates
WHEN NOT EXISTS (SELECT 1 FROM carriers c WHERE c.carrier_id = NEW.carrier_id AND c.carrier_code = NEW.carrier_reference)
  OR NOT EXISTS (SELECT 1 FROM warehouses w WHERE w.warehouse_id = NEW.ship_from_warehouse_id AND w.warehouse_name = NEW.ship_from_location)
  OR NOT EXISTS (SELECT 1 FROM actors a WHERE a.actor_id = NEW.carrier_operator_actor_id AND a.actor_role = 'carrier_warehouse_operator')
BEGIN SELECT RAISE(ABORT, 'promise logistics carrier, warehouse, and operator must match their masters'); END;
CREATE TRIGGER IF NOT EXISTS trg_promise_logistics_consistency_update
BEFORE UPDATE OF carrier_id, carrier_reference, ship_from_warehouse_id, ship_from_location, carrier_operator_actor_id ON promise_dates
WHEN NOT EXISTS (SELECT 1 FROM carriers c WHERE c.carrier_id = NEW.carrier_id AND c.carrier_code = NEW.carrier_reference)
  OR NOT EXISTS (SELECT 1 FROM warehouses w WHERE w.warehouse_id = NEW.ship_from_warehouse_id AND w.warehouse_name = NEW.ship_from_location)
  OR NOT EXISTS (SELECT 1 FROM actors a WHERE a.actor_id = NEW.carrier_operator_actor_id AND a.actor_role = 'carrier_warehouse_operator')
BEGIN SELECT RAISE(ABORT, 'promise logistics carrier, warehouse, and operator must match their masters'); END;
CREATE TRIGGER IF NOT EXISTS trg_inventory_plans_no_update
BEFORE UPDATE ON inventory_plans
BEGIN SELECT RAISE(ABORT, 'inventory plan versions are append-only; UPDATE is forbidden'); END;
CREATE TRIGGER IF NOT EXISTS trg_inventory_plans_no_delete
BEFORE DELETE ON inventory_plans
BEGIN SELECT RAISE(ABORT, 'inventory plan versions are append-only; DELETE is forbidden'); END;
""")
    sections.append("COMMIT;")
    return "\n\n".join(sections)


create_schema_sql = _build_create_schema_sql()


def create_all(connection_or_path: _sqlite3.Connection | str | _os.PathLike[str] = ":memory:") -> _sqlite3.Connection:
    """Create the complete schema and return a connection with FK enforcement ON.

    Args:
        connection_or_path: An existing sqlite3.Connection or database path. For
            a path, the new connection remains open and is returned to the caller.

    Raises:
        RuntimeError: If foreign-key enforcement cannot be enabled (for example,
            because the passed connection already has an active transaction).
        sqlite3.Error: If DDL or a trigger fails.
    """
    if isinstance(connection_or_path, _sqlite3.Connection):
        conn = connection_or_path
    else:
        path = _os.fspath(connection_or_path)
        if path != ":memory:":
            _Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = _sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    if enabled != 1:
        raise RuntimeError("SQLite foreign-key enforcement could not be enabled; use a connection outside a transaction")
    try:
        conn.executescript(create_schema_sql)
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("SQLite foreign-key enforcement was disabled during schema creation")
    conn.commit()
    return conn
