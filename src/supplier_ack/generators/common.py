"""Shared deterministic generation helpers; no global RNG is used here."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence

import pandas as pd

from supplier_ack.schema import ENTITIES


def active_scale_config(cfg: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the selected scale block from a full YAML configuration."""
    scale = str(cfg.get("active_scale", cfg.get("workflow", {}).get("default_scale", "starter")))
    scales = cfg.get("scales")
    if not isinstance(scales, Mapping) or scale not in scales:
        raise ValueError(f"unknown generation scale {scale!r}; expected one of {tuple(scales or {})}")
    block = scales[scale]
    if not isinstance(block, Mapping):
        raise ValueError(f"configuration block for scale {scale!r} must be a mapping")
    return block


def get_config(cfg: Mapping[str, Any], *path: str, default: Any = None) -> Any:
    value: Any = cfg
    for part in path:
        if not isinstance(value, Mapping) or part not in value:
            return default
        value = value[part]
    return value


def iso_utc(value: datetime) -> str:
    """Return a canonical timezone-aware ISO-8601 UTC datetime string."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def at_utc(day: date, hour: int = 9, minute: int = 0) -> str:
    return iso_utc(datetime.combine(day, time(hour, minute), tzinfo=timezone.utc))


def frame_for_entity(entity_name: str, records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Create an entity DataFrame with columns exactly in schema dictionary order."""
    if entity_name not in ENTITIES:
        raise KeyError(f"unknown schema entity: {entity_name}")
    columns = [field.name for field in ENTITIES[entity_name].fields]
    normalized: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        missing = set(columns) - set(record)
        extra = set(record) - set(columns)
        if missing or extra:
            raise ValueError(
                f"{entity_name} record {index} fields do not match schema: "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        normalized.append({column: record[column] for column in columns})
    return pd.DataFrame(normalized, columns=columns)


def require_rng(rng: Any) -> None:
    """Fail early if a caller did not inject an RNG-like object."""
    required = ("choice", "integers", "random", "uniform", "beta", "lognormal", "permutation")
    missing = [name for name in required if not callable(getattr(rng, name, None))]
    if missing:
        raise TypeError(f"rng must be a numpy.random.Generator-compatible object; missing {missing}")


def assert_probability_distribution(values: Mapping[str, Any], name: str) -> tuple[list[str], list[float]]:
    labels = list(values)
    probabilities = [float(values[label]) for label in labels]
    if not labels or any(p < 0 or p > 1 for p in probabilities):
        raise ValueError(f"{name} probabilities must all be in [0, 1]")
    if abs(sum(probabilities) - 1.0) > 1e-8:
        raise ValueError(f"{name} probabilities must sum to 1.0; received {sum(probabilities)}")
    return labels, probabilities
