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
APPROVER_ROLES = ("planner", "operations_manager")
NOTIFICATION_TARGET_ROLES = (
    "supplier", "planner", "carrier_warehouse_operator",
    "logistics_analyst", "operations_manager",
)
CURRENCIES = ("INR", "USD", "EUR", "GBP", "SGD", "JPY", "AUD", "CAD")
UNITS_OF_MEASURE = ("EA", "BOX", "KG", "G", "L", "ML", "M", "CM", "M2", "M3", "PALLET", "SET")
ANOMALY_TYPES = (
    "MISSING_ACK", "DATE_CONFLICT", "DATE_SLIP_REQUIRES_APPROVAL",
    "QUANTITY_MISMATCH", "OVER_ACKNOWLEDGEMENT", "PRICE_SPIKE",
    "PRICE_MISMATCH", "INVALID_TRANSITION", "DUPLICATE_REVISION",
    "MISSING_APPROVAL", "LATE_ACKNOWLEDGEMENT", "LEAD_TIME_BREACH",
    "FOREIGN_KEY_MISMATCH", "LINE_TOTAL_MISMATCH", "NOTIFICATION_FAILURE",
    "PROJECTED_SHORTAGE", "PROMISE_BEFORE_ORDER", "STATUS_DATE_MISMATCH",
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
    "ProductionOrder": ("DRAFT", "RELEASED", "SCHEDULED", "IN_PROGRESS", "PARTIALLY_COMPLETED", "ON_HOLD", "COMPLETED", "CANCELLED", "CLOSED"),
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


def _check_foreign_key(value: Any, record: Mapping[str, Any], context: Mapping[str, Any], field: FieldSpec) -> str | None:
    if not field.foreign_key or not context: return None
    table, key = field.foreign_key.split(".", 1)
    rows = context.get(table)
    if rows is None: return None
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
    "int_1_99": _bounded_int(1, 99, "int_1_99"),
    "int_1_9999": _bounded_int(1, 9999, "int_1_9999"),
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
_make_id_check("purchase_order_id_format", r"PO-\d{4}-\d{6}")
_make_id_check("po_line_id_format", r"PO-\d{4}-\d{6}-L\d{2}")
_make_id_check("acknowledgement_id_format", r"ACK-PO-\d{4}-\d{6}-\d{2}")
_make_id_check("promise_date_id_format", r"PD-ACK-PO-\d{4}-\d{6}-\d{2}-\d{2,4}")
_make_id_check("change_request_id_format", r"CHG-PO-\d{4}-\d{6}-\d{6}")
_make_id_check("approval_id_format", r"APR-CHG-PO-\d{4}-\d{6}-\d{6}-\d{2}")
_make_id_check("inventory_plan_id_format", r"IP-PO-\d{4}-\d{6}-L\d{2}-\d{2}")
_make_id_check("production_order_id_format", r"PRO-\d{4}-\d{6}")
_make_id_check("notification_id_format", r"NOT-\d{4}-\d{6}")
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
    F("lead_time_days", "INTEGER", True, "0–365 inclusive", "calendar days", "Not unique", "integer in [0,365]", "int_0_365"),
    F("default_currency", "CHAR(3)", True, ", ".join(CURRENCIES), "ISO-4217 alphabetic code", "Not unique", "must be in supported currency list", "enum", CURRENCIES),
    F("data_owner_role", "ENUM", True, ", ".join(ACTOR_ROLES), "none", "Not unique", "must identify an owning actor role", "enum", ACTOR_ROLES),
    F("created_at", "DATETIME", True, "ISO-8601 datetime with timezone", "UTC recommended", "Not unique", "parseable timezone-aware datetime", "iso_datetime"),
    F("updated_at", "DATETIME", True, "ISO-8601 datetime with timezone", "UTC recommended", "Not unique", "must be >= created_at", "iso_datetime"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise one of: " + ", ".join(ANOMALY_TYPES), "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], unique=(("supplier_code",),), full="120", starter="120", description="Supplier master and contact/ownership data." )

_entity("PurchaseOrder", "purchase_orders", "po_id", [
    F("po_id", "VARCHAR(16)", True, "PO-YYYY- followed by exactly 6 digits, e.g. PO-2026-000001", "none", "Primary key; globally unique", "fullmatch ^PO-\\d{4}-\\d{6}$", "purchase_order_id_format", primary_key=True),
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
    F("po_line_id", "VARCHAR(25)", True, "<PO-id>-L followed by 2-digit line number, e.g. PO-2026-000001-L01", "none", "Primary key; globally unique", "fullmatch ^PO-\\d{4}-\\d{6}-L\\d{2}$", "po_line_id_format", primary_key=True),
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
], status="status", unique=(("po_id", "line_no"),), full="30,000 (3 per PO)", starter="600 (3 per PO)", description="Purchase order line quantities and values at requested, acknowledged, promised and projected stages." )

_entity("Acknowledgement", "acknowledgements", "ack_id", [
    F("ack_id", "VARCHAR(30)", True, "ACK-<PO-id>-NN, e.g. ACK-PO-2026-000001-01", "none", "Primary key; unique per PO revision", "ID PO portion equals po_id and suffix equals revision_no", "acknowledgement_id_format", primary_key=True),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id", "must reference an existing PO", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("supplier_id", "VARCHAR(10)", True, "Existing Supplier.supplier_id and same supplier as parent PO", "none", "Foreign key to suppliers.supplier_id", "must equal parent PO supplier_id", "foreign_key", foreign_key="suppliers.supplier_id"),
    F("po_line_id", "VARCHAR(25)", False, "Existing PO line belonging to po_id; NULL for header-level acknowledgement", "none", "Optional foreign key to po_lines.po_line_id", "if supplied, line must belong to same po_id", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("revision_no", "INTEGER", True, "Integer >= 1; formatted as 2 digits in ack_id", "revision number per PO", "Unique per po_id", "integer >= 1; ack_id suffix equals revision_no", "positive_int"),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["Acknowledgement"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.Acknowledgement", "enum", STATUS_ENUMS["Acknowledgement"]),
    F("acknowledged_at", "DATETIME", False, "Timezone-aware ISO datetime; NULL before supplier response", "UTC recommended", "Not unique", "NULL or >= created_at", "iso_datetime"),
    F("response_due_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "response_due_at >= created_at", "iso_datetime"),
    F("requested_qty", "DECIMAL(14,3)", True, "0.001–99999999999.999; sum of PO line requested_qty", "quantity across PO lines or scoped line", "Not unique", "finite decimal > 0; reconciles when final", "positive_decimal"),
    F("ack_accepted_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity", "Not unique", "finite decimal >= 0; requested = accepted + rejected for final status", "nonnegative_decimal"),
    F("ack_rejected_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity", "Not unique", "finite decimal >= 0; requested = accepted + rejected for final status", "nonnegative_decimal"),
    F("promised_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity", "Not unique", "finite decimal >= 0; promised_qty <= ack_accepted_qty for final status", "nonnegative_decimal"),
    F("projected_qty", "DECIMAL(14,3)", True, "0–99999999999.999", "quantity", "Not unique", "finite decimal >= 0; same UOM basis as requested_qty", "nonnegative_decimal"),
    F("requested_value", "DECIMAL(16,2)", True, "0.00–99999999999999.99", "PO currency", "Not unique", "must equal sum of PO line_total for header acknowledgements", "nonnegative_decimal"),
    F("acknowledged_value", "DECIMAL(16,2)", True, "0.00–99999999999999.99", "PO currency", "Not unique", "finite non-negative amount; based on accepted quantities and acknowledged prices", "nonnegative_decimal"),
    F("promised_value", "DECIMAL(16,2)", True, "0.00–99999999999999.99", "PO currency", "Not unique", "finite non-negative amount; based on promised quantities/prices", "nonnegative_decimal"),
    F("projected_value", "DECIMAL(16,2)", True, "0.00–99999999999999.99", "PO currency", "Not unique", "finite non-negative amount; based on downstream projected quantities/prices", "nonnegative_decimal"),
    F("supplier_note", "TEXT", False, "Free text up to application limit of 4,000 characters", "none", "Not unique", "string or NULL; maximum 4,000 characters", "text_max_4000"),
    F("superseded_by", "VARCHAR(30)", False, "ACK id of a later revision for the same PO; NULL if current/non-superseded", "none", "Self foreign key to acknowledgements.ack_id", "SUPERSEDED requires a later same-PO acknowledgement; non-SUPERSEDED has NULL", "foreign_key", foreign_key="acknowledgements.ack_id"),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime; <= acknowledged_at when acknowledged_at is set", "iso_datetime"),
    F("created_by_role", "ENUM", True, ", ".join(ACTOR_ROLES), "none", "Not unique", "value in ACTOR_ROLES", "enum", ACTOR_ROLES),
    F("created_by_actor_id", "VARCHAR(10)", True, "Actor ID associated with created_by_role", "none", "Foreign key to actors.actor_id", "must reference actor and role must match", "foreign_key", foreign_key="actors.actor_id"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise listed anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(("po_id", "revision_no"),), full="10,000 initial rows; + amendment revisions", starter="200 initial rows; + amendment revisions", description="PO-level supplier response revision; line-specific quantities are also captured on POLine." )

_entity("PromiseDate", "promise_dates", "promise_date_id", [
    F("promise_date_id", "VARCHAR(40)", True, "PD-<ACK-id>-NN, e.g. PD-ACK-PO-2026-000001-01-01", "none", "Primary key; sequence unique within acknowledgement", "ID embeds ack_id and a 2–4 digit sequence; suffix is unique under ack_id", "promise_date_id_format", primary_key=True),
    F("ack_id", "VARCHAR(30)", True, "Existing Acknowledgement.ack_id", "none", "Foreign key to acknowledgements.ack_id", "must reference existing acknowledgement", "foreign_key", foreign_key="acknowledgements.ack_id"),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id; same as acknowledgement PO", "none", "Foreign key to purchase_orders.po_id", "must equal referenced acknowledgement.po_id", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("po_line_id", "VARCHAR(25)", True, "Existing PO line belonging to po_id", "none", "Foreign key to po_lines.po_line_id", "must reference a line belonging to same po_id", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("sequence_no", "INTEGER", True, "Integer 1–9999 per ack_id; 2 digits minimum in ID", "sequence under ACK", "Unique per ack_id", "integer [1,9999]; suffix embedded in promise_date_id", "int_1_9999"),
    F("revision_no", "INTEGER", True, "Integer >= 1 per po_line_id", "promise revision", "Unique per (ack_id, po_line_id, revision_no)", "integer >= 1 and increments when line promise changes", "positive_int"),
    F("promised_date", "DATE", True, "Valid date >= PO order_date", "calendar date", "Not unique", "promised_date >= purchase_orders.order_date; no invalid pre-order promise", "iso_date"),
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
], status="status", unique=(("ack_id", "sequence_no"),), full="30,000 initial line promises; additional revisions", starter="600 initial line promises; additional revisions", description="Line-specific promised dates, independently versioned and traceable to acknowledgement and PO line." )

_entity("ChangeRequest", "change_requests", "change_request_id", [
    F("change_request_id", "VARCHAR(40)", True, "CHG-<PO-id>- followed by 6 digits, e.g. CHG-PO-2026-000001-000001", "none", "Primary key; globally unique", "fullmatch ^CHG-PO-YYYY-NNNNNN-NNNNNN$", "change_request_id_format", primary_key=True),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id", "must reference an existing PO", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("supplier_id", "VARCHAR(10)", True, "Existing Supplier.supplier_id; same as parent PO", "none", "Foreign key to suppliers.supplier_id", "must equal parent PO supplier_id", "foreign_key", foreign_key="suppliers.supplier_id"),
    F("po_line_id", "VARCHAR(25)", False, "Existing PO line belonging to po_id; NULL for PO-wide change", "none", "Optional foreign key to po_lines.po_line_id", "if supplied, line must belong to same PO", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("request_type", "ENUM", True, "QUANTITY_CHANGE, DATE_CHANGE, PRICE_CHANGE, CANCEL_LINE, CANCEL_PO", "none", "Not unique", "value in request_type enum", "enum", ("QUANTITY_CHANGE", "DATE_CHANGE", "PRICE_CHANGE", "CANCEL_LINE", "CANCEL_PO")),
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
], status="status", unique=(), full="3,600 baseline (24% of 15,000 events; amendments may add rows)", starter="72 baseline (24% of 300 events; amendments may add rows)", description="Supplier/planner change requests with before/after business values and a review lifecycle." )

_entity("Approval", "approvals", "approval_id", [
    F("approval_id", "VARCHAR(50)", True, "APR-<change_request_id>-NN, e.g. APR-CHG-PO-2026-000001-000001-01", "none", "Primary key; unique per change approval round", "ID embeds change_request_id and 2-digit approval round", "approval_id_format", primary_key=True),
    F("change_request_id", "VARCHAR(40)", True, "Existing ChangeRequest.change_request_id", "none", "Foreign key to change_requests.change_request_id", "must reference existing change request", "foreign_key", foreign_key="change_requests.change_request_id"),
    F("approval_round", "INTEGER", True, "Integer 1–99", "approval round", "Unique per change_request_id", "integer [1,99]; approval_id suffix equals approval_round", "int_1_99"),
    F("approver_role", "ENUM", True, "planner or operations_manager only", "none", "Not unique", "value in APPROVER_ROLES", "enum", APPROVER_ROLES),
    F("approver_actor_id", "VARCHAR(10)", True, "PLN-###### or OPS-######", "none", "Foreign key to actors.actor_id", "must reference actor matching approver_role", "foreign_key", foreign_key="actors.actor_id"),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["Approval"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.Approval", "enum", STATUS_ENUMS["Approval"]),
    F("requested_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime", "iso_datetime"),
    F("due_at", "DATETIME", True, "Timezone-aware ISO datetime >= requested_at", "UTC recommended", "Not unique", "due_at >= requested_at", "iso_datetime"),
    F("decided_at", "DATETIME", False, "Timezone-aware ISO datetime; NULL while PENDING", "UTC recommended", "Not unique", "PENDING requires NULL; terminal decision requires timestamp >= requested_at", "iso_datetime"),
    F("decision_reason", "TEXT", False, "0–2,000 characters; required when rejected/escalated", "none", "Not unique", "REJECTED or ESCALATED requires non-empty decision_reason; max 2,000 chars", "text_max_2000"),
    F("threshold_name", "ENUM", False, "PRICE_CHANGE_PCT, DATE_SLIP_DAYS, QUANTITY_CHANGE_PCT, CANCELLATION, MANUAL_EXCEPTION", "none", "Not unique", "NULL or recognized approval trigger", "enum", ("PRICE_CHANGE_PCT", "DATE_SLIP_DAYS", "QUANTITY_CHANGE_PCT", "CANCELLATION", "MANUAL_EXCEPTION")),
    F("threshold_value", "DECIMAL(12,3)", False, "Finite non-negative numeric threshold or NULL", "percent, days or quantity depending on threshold_name", "Not unique", "NULL or finite decimal >= 0", "nonnegative_decimal"),
    F("created_at", "DATETIME", True, "Timezone-aware ISO datetime", "UTC recommended", "Not unique", "valid datetime; created_at <= requested_at", "iso_datetime"),
    F("issue_type", "ENUM", False, "NULL for normal rows; otherwise listed anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with ground_truth", "enum", ANOMALY_TYPES),
    F("ground_truth", "ENUM", False, "NULL for normal rows; otherwise source-truth anomaly class", "none", "Not unique", "NULL or value in ANOMALY_TYPES; pairs with issue_type", "enum", ANOMALY_TYPES),
], status="status", unique=(("change_request_id", "approval_round"),), full="1,800 baseline (50% of baseline change requests; rule-dependent)", starter="36 baseline (50% of baseline change requests; rule-dependent)", description="Planner or operations-manager approval rounds for exceptions and threshold breaches." )

_entity("InventoryPlan", "inventory_plans", "inventory_plan_id", [
    F("inventory_plan_id", "VARCHAR(32)", True, "IP-<po_line_id>-NN, e.g. IP-PO-2026-000001-L01-01", "none", "Primary key; globally unique", "ID embeds po_line_id plus 2-digit plan revision", "inventory_plan_id_format", primary_key=True),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id", "must equal PO of po_line_id", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("po_line_id", "VARCHAR(25)", True, "Existing POLine.po_line_id", "none", "Foreign key to po_lines.po_line_id", "must reference existing PO line", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("plan_revision_no", "INTEGER", True, "Integer 1–99; 2-digit suffix in ID", "plan revision", "Unique per po_line_id", "integer [1,99]; suffix equals plan_revision_no", "int_1_99"),
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
], status="status", unique=(("po_line_id", "plan_revision_no"),), full="30,000 initial plans (1 per PO line)", starter="600 initial plans (1 per PO line)", description="Inventory availability, receipts, shortage projection, ownership, and downstream plan revisions." )

_entity("ProductionOrder", "production_orders", "production_order_id", [
    F("production_order_id", "VARCHAR(16)", True, "PRO-YYYY- followed by exactly 6 digits", "none", "Primary key; globally unique", "fullmatch ^PRO-\\d{4}-\\d{6}$", "production_order_id_format", primary_key=True),
    F("inventory_plan_id", "VARCHAR(32)", True, "Existing InventoryPlan.inventory_plan_id", "none", "Foreign key to inventory_plans.inventory_plan_id", "must reference existing inventory plan", "foreign_key", foreign_key="inventory_plans.inventory_plan_id"),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id", "must equal plan PO", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("po_line_id", "VARCHAR(25)", True, "Existing POLine.po_line_id", "none", "Foreign key to po_lines.po_line_id", "must equal plan PO line", "foreign_key", foreign_key="po_lines.po_line_id"),
    F("status", "ENUM", True, ", ".join(STATUS_ENUMS["ProductionOrder"]), "none", "Not unique", "enum and legal edge in STATUS_TRANSITIONS.ProductionOrder", "enum", STATUS_ENUMS["ProductionOrder"]),
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
    F("notification_id", "VARCHAR(16)", True, "NOT-YYYY- followed by exactly 6 digits", "none", "Primary key; globally unique", "fullmatch ^NOT-\\d{4}-\\d{6}$", "notification_id_format", primary_key=True),
    F("po_id", "VARCHAR(16)", True, "Existing PurchaseOrder.po_id", "none", "Foreign key to purchase_orders.po_id", "must reference an existing PO", "foreign_key", foreign_key="purchase_orders.po_id"),
    F("ack_id", "VARCHAR(30)", False, "Acknowledgement id or NULL when notification is not ack-specific", "none", "Optional foreign key to acknowledgements.ack_id", "if supplied, acknowledgement must belong to po_id", "foreign_key", foreign_key="acknowledgements.ack_id"),
    F("change_request_id", "VARCHAR(40)", False, "ChangeRequest id or NULL when unrelated to a change", "none", "Optional foreign key to change_requests.change_request_id", "if supplied, change request must belong to po_id", "foreign_key", foreign_key="change_requests.change_request_id"),
    F("source_event_id", "VARCHAR(40)", False, "Runtime event identifier or NULL for direct notifications", "none", "Optional foreign key to events.event_id", "if supplied, event must exist in event ledger", "foreign_key", foreign_key="events.event_id"),
    F("target_role", "ENUM", True, ", ".join(NOTIFICATION_TARGET_ROLES), "none", "Not unique", "value in NOTIFICATION_TARGET_ROLES", "enum", NOTIFICATION_TARGET_ROLES),
    F("target_actor_id", "VARCHAR(10)", True, "Actor ID associated with target_role", "none", "Foreign key to actors.actor_id", "must reference actor matching target_role", "foreign_key", foreign_key="actors.actor_id"),
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
], status="status", unique=(), full="15,000 initial notifications (one per generated event; recipient fan-out may add rows)", starter="300 initial notifications (one per generated event; recipient fan-out may add rows)", description="Traceable notification fan-out to supplier and operational role recipients, with delivery/retry outcome." )

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
    due = _datetime(record.get("response_due_at"))
    if created and acknowledged and acknowledged < created: errors.append("acknowledged_at must be >= created_at")
    if created and due and due < created: errors.append("response_due_at must be >= created_at")
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
    if isinstance(pid, str) and isinstance(aid, str) and seq is not None and pid != f"PD-{aid}-{seq:02d}": errors.append("promise_date_id must equal f'PD-{ack_id}-{sequence_no:02d}' (suffix may use 2-4 digits)")
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
    if kind == "QUANTITY_CHANGE":
        previous_qty, requested_qty = _decimal(record.get("previous_qty")), _decimal(record.get("requested_qty"))
        if previous_qty is None or requested_qty is None: errors.append("QUANTITY_CHANGE requires both previous_qty and requested_qty")
        elif previous_qty < 0 or requested_qty <= 0: errors.append("QUANTITY_CHANGE requires previous_qty >= 0 and requested_qty > 0")
    if kind == "PRICE_CHANGE":
        if _decimal(record.get("previous_unit_price")) is None or _decimal(record.get("requested_unit_price")) is None: errors.append("PRICE_CHANGE requires previous_unit_price and requested_unit_price")
    if kind == "DATE_CHANGE" and _as_date(record.get("requested_promised_date")) is None: errors.append("DATE_CHANGE requires requested_promised_date")
    if kind == "DATE_CHANGE":
        requested_promise = _as_date(record.get("requested_promised_date"))
        pos = context.get("purchase_orders", ())
        parent = next((p for p in pos if isinstance(p, Mapping) and p.get("po_id") == record.get("po_id")), None)
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
    if isinstance(line_id, str) and rev is not None and isinstance(ipid, str) and ipid != f"IP-{line_id}-{rev:02d}": errors.append("inventory_plan_id must equal f'IP-{po_line_id}-{plan_revision_no:02d}'")
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
    (actors/items/warehouses/carriers/events) may be provided the same way.
    """
    errors=[]
    context=dict(records_by_entity)
    for entity_name, rows in records_by_entity.items():
        if entity_name not in ENTITIES:
            continue
        spec=ENTITIES[entity_name]
        # Accept either entity-keyed or table-name-keyed contexts.
        context.setdefault(spec.table_name, rows)
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
            if name == "PromiseDate":
                ack=ack_rows.get(row.get("ack_id"))
                if ack and (ack.get("po_id") != po_id): errors.append(f"PromiseDate[{index}]: po_id must match acknowledgement.po_id")
                parent_po=po_rows.get(po_id)
                promised=_as_date(row.get("promised_date")); order_date=_as_date(parent_po.get("order_date")) if parent_po else None
                if promised and order_date and promised < order_date: errors.append(f"PromiseDate[{index}]: promised_date must be >= parent PO order_date")
            if name == "ChangeRequest" and po_id in po_rows and row.get("supplier_id") != po_rows[po_id].get("supplier_id"):
                errors.append(f"ChangeRequest[{index}]: supplier_id must match its purchase order")
            if name == "InventoryPlan" and line_id in line_rows and line_rows[line_id].get("po_id") != po_id:
                errors.append(f"InventoryPlan[{index}]: po_id must match po_lines.po_id")
            if name == "ProductionOrder":
                plan=plan_rows.get(row.get("inventory_plan_id"))
                if plan and (plan.get("po_id") != po_id or plan.get("po_line_id") != line_id): errors.append(f"ProductionOrder[{index}]: po_id and po_line_id must match referenced inventory plan")
            if name == "Notification":
                if row.get("ack_id") in ack_rows and ack_rows[row.get("ack_id")].get("po_id") != po_id: errors.append(f"Notification[{index}]: ack_id must belong to po_id")
                if row.get("change_request_id") in change_rows and change_rows[row.get("change_request_id")].get("po_id") != po_id: errors.append(f"Notification[{index}]: change_request_id must belong to po_id")
                if row.get("source_event_id") and "events" in context and row.get("source_event_id") not in {r.get("event_id") for r in context["events"] if isinstance(r, Mapping)}:
                    errors.append(f"Notification[{index}]: source_event_id must exist in events ledger")
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
        "Notification": (("target_actor_id", "target_role"),),
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
           "- Foreign keys naming support tables (`actors`, `items`, `warehouses`, `carriers`, `events`) refer to supporting operational/master tables outside the ten core entities. Actor role values are `supplier`, `planner`, `carrier_warehouse_operator`, `logistics_analyst`, and `operations_manager`.",
           "- On `Acknowledgement`, a header-level row has `po_line_id = NULL`; when a line is the focus of an exception, it may be populated and must belong to `po_id`. Per-line commitments are persisted in `PromiseDate` and `POLine`.",
           "- `issue_type` and `ground_truth` are both `NULL` for intentionally normal rows. Labelled anomaly rows populate both from `ANOMALY_TYPES`. This supports auditable synthetic anomaly cohorts.",
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
    lines += ["## Machine-checkable validation API", "",
              "```python", "from supplier_ack.schema import ENTITIES, validate_record, validate_dataset, is_legal_transition", "", "spec = ENTITIES['POLine']", "print(spec.fields[0].validator)  # real callable", "errors = validate_record('POLine', row, context={'purchase_orders': [po_row]})", "dataset_errors = validate_dataset({'PurchaseOrder': [po_row], 'POLine': [row]})", "assert is_legal_transition('PurchaseOrder', 'ISSUED', 'ACKNOWLEDGED')", "```", ""]
    return "\n".join(lines)
