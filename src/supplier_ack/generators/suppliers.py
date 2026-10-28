"""Supplier master generation using an injected, seeded RNG."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping

from numpy.random import Generator

from supplier_ack.ids import IDFactory
from supplier_ack.schema import REGIONS
from supplier_ack.generators.common import (
    active_scale_config, assert_probability_distribution, frame_for_entity, get_config,
    require_rng,
)

_SUPPLIER_PREFIXES = (
    "Vertex", "Apex", "Northstar", "Summit", "Pioneer", "Bluepeak", "Keystone",
    "Evergreen", "Sterling", "Crestline", "Meridian", "Atlas", "Cobalt", "Redwood",
    "Silverline", "Ironwood", "Brightforge", "Clearwater", "Westbridge", "Oakmont",
    "Primepath", "Horizon", "Granite", "Truepoint", "Goldcrest", "Skyward",
    "Ironcrest", "Vantage", "Cedarstone", "Bluehaven",
)
_SUPPLIER_SECTORS = (
    "Industrial Supplies", "Precision Components", "Engineering Materials", "Motion Systems",
    "Electrical Products", "Fluid Technologies", "Packaging Solutions", "Metal Works",
    "Automation Parts", "Mechanical Components", "Industrial Trading", "Manufacturing Supply",
    "Process Equipment", "Technical Products", "Machine Components", "Plant Services",
    "Fastener Works", "Bearing Specialists", "Control Systems", "Materials Group",
)
_FIRST_NAMES = (
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Ishaan", "Reyansh",
    "Ananya", "Diya", "Aadhya", "Saanvi", "Ira", "Meera", "Kavya", "Priya",
    "Rohan", "Kiran", "Nisha", "Rahul", "Neha", "Dev", "Maya", "Varun",
)
_LAST_NAMES = (
    "Sharma", "Reddy", "Patel", "Iyer", "Nair", "Rao", "Mehta", "Kapoor", "Gupta",
    "Joshi", "Kulkarni", "Menon", "Chopra", "Bose", "Desai", "Pillai", "Saxena",
    "Malhotra", "Bhat", "Verma", "Das", "Suri", "Shetty", "Naidu", "Mukherjee",
)


def generate_suppliers(
    rng: Generator,
    cfg: Mapping[str, Any],
    id_factory: IDFactory | None = None,
) -> "pd.DataFrame":
    """Generate exactly the configured Supplier schema columns.

    Reliability scores use a majority reliable Beta distribution plus a small
    low-reliability mixture. On-time rate is explicitly derived from reliability
    and a Beta noise component, so it is correlated rather than independent.
    """
    import pandas as pd

    require_rng(rng)
    scale = active_scale_config(cfg)
    count = int(scale["supplier_count"])
    if count < 1:
        raise ValueError("supplier_count must be >= 1")
    factory = id_factory or IDFactory()
    dist = get_config(cfg, "distributions", default={})
    lead = dist.get("supplier_lead_time", {})
    reliability_cfg = dist.get("supplier_reliability", {})
    status_cfg = dist.get("supplier_status", {"ACTIVE": 1.0})
    status_labels, status_probabilities = assert_probability_distribution(status_cfg, "supplier_status")

    low_mode = rng.uniform(0.0, 1.0, size=count) < float(reliability_cfg.get("low_reliability_probability", 0.08))
    reliability = pd.Series([0.0] * count, dtype="float64").to_numpy()
    reliable_count = int((~low_mode).sum())
    unreliable_count = int(low_mode.sum())
    if reliable_count:
        reliability[~low_mode] = rng.beta(
            float(reliability_cfg.get("reliable_beta_alpha", 8.0)),
            float(reliability_cfg.get("reliable_beta_beta", 2.0)),
            size=reliable_count,
        )
    if unreliable_count:
        reliability[low_mode] = rng.beta(
            float(reliability_cfg.get("unreliable_beta_alpha", 2.0)),
            float(reliability_cfg.get("unreliable_beta_beta", 5.0)),
            size=unreliable_count,
        )
    reliability = reliability.clip(0.01, 0.9999)
    reliability_weight = float(reliability_cfg.get("on_time_reliability_weight", 0.78))
    if not 0 <= reliability_weight <= 1:
        raise ValueError("on_time_reliability_weight must be in [0, 1]")
    noise = rng.beta(
        float(reliability_cfg.get("on_time_noise_beta_alpha", 8.0)),
        float(reliability_cfg.get("on_time_noise_beta_beta", 2.0)),
        size=count,
    )
    on_time_rate = (reliability_weight * reliability + (1.0 - reliability_weight) * noise).clip(0.01, 0.9999)

    regular_mask = rng.uniform(0.0, 1.0, size=count) < float(lead.get("regular_probability", 0.82))
    lead_times = [0] * count
    regular_n = int(regular_mask.sum())
    tail_n = count - regular_n
    if regular_n:
        lead_times_array = rng.integers(
            int(lead.get("regular_min_days", 7)),
            int(lead.get("regular_max_days", 30)) + 1,
            size=regular_n,
        )
        for i, value in zip([idx for idx, is_regular in enumerate(regular_mask) if is_regular], lead_times_array):
            lead_times[i] = int(value)
    if tail_n:
        tail_values = rng.integers(
            int(lead.get("tail_min_days", 31)), int(lead.get("tail_max_days", 90)) + 1, size=tail_n
        )
        for i, value in zip([idx for idx, is_regular in enumerate(regular_mask) if not is_regular], tail_values):
            lead_times[i] = int(value)

    carrier_count = int(scale.get("carrier_count", 1))
    if carrier_count < 1 or carrier_count > 999999:
        raise ValueError("carrier_count must be in [1, 999999]")
    carrier_ids = [f"CAR-{i:06d}" for i in range(1, carrier_count + 1)]
    # Carrier preferences themselves follow a mild popularity skew rather than uniform selection.
    carrier_weights = rng.permutation([float(i) ** -0.7 for i in range(1, carrier_count + 1)])
    carrier_weights = carrier_weights / sum(carrier_weights)
    preferred_carriers = rng.choice(carrier_ids, size=count, p=carrier_weights)

    supplier_names = [f"{prefix} {sector}" for prefix in _SUPPLIER_PREFIXES for sector in _SUPPLIER_SECTORS]
    name_order = rng.permutation(len(supplier_names))
    if count > len(supplier_names):
        raise ValueError(f"supplier_count={count} exceeds unique synthetic supplier name capacity {len(supplier_names)}")
    contact_pairs = [(first, last) for first in _FIRST_NAMES for last in _LAST_NAMES]
    contact_order = rng.permutation(len(contact_pairs))
    base_created = date(2025, 10, 1)
    records: list[dict[str, Any]] = []
    for index in range(count):
        supplier_id = factory.next_supplier_id()
        name = supplier_names[int(name_order[index])]
        first, last = contact_pairs[int(contact_order[index])]
        score = float(reliability[index])
        if score >= 0.85:
            risk_tier = "LOW"
        elif score >= 0.65:
            risk_tier = "MEDIUM"
        elif score >= 0.40:
            risk_tier = "HIGH"
        else:
            risk_tier = "CRITICAL"
        created_day = base_created + timedelta(days=int(rng.integers(0, 61)))
        updated_day = created_day + timedelta(days=int(rng.integers(0, 4)))
        records.append({
            "supplier_id": supplier_id,
            "supplier_name": name,
            "supplier_code": f"SUPP-{index + 1:06d}",
            "supplier_contact_name": f"{first} {last}",
            "supplier_contact_email": f"supplier{index + 1:04d}@example.test",
            "supplier_contact_phone": f"+91 40 {((index + 1) * 37) % 10000:04d} {((index + 1) * 73) % 10000:04d}",
            "supplier_status": str(rng.choice(status_labels, p=status_probabilities)),
            "risk_tier": risk_tier,
            "region": str(rng.choice(REGIONS)),
            "lead_time_days": int(lead_times[index]),
            "reliability_score": round(score, 4),
            "on_time_rate": round(float(on_time_rate[index]), 4),
            "ack_rate": 0.0,
            "on_time_promise_rate": 0.0,
            "avg_slip_days": 0.0,
            "preferred_carrier_id": str(preferred_carriers[index]),
            "default_currency": str(dist.get("default_currency", "INR")),
            "data_owner_role": "supplier",
            "created_at": f"{created_day.isoformat()}T09:00:00+00:00",
            "updated_at": f"{updated_day.isoformat()}T09:00:00+00:00",
            "issue_type": None,
            "ground_truth": None,
        })
    return frame_for_entity("Supplier", records)
