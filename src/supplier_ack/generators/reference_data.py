"""Synthetic reference masters: items, actors, warehouses, and carriers."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
from numpy.random import Generator

from supplier_ack.generators.common import active_scale_config, get_config, require_rng

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
_CARRIER_NAMES = (
    "BlueRoute Logistics", "Deccan Freight Network", "Meridian Cargo Services",
    "Apex Roadways", "Northstar Transport", "Swiftline Carriers", "Pioneer Freight",
    "Silverpath Logistics", "Reliable Transit Group", "EastWest Cargo Partners",
    "Cobalt Supply Chain", "Summit Distribution Services", "Redwood Transport Works",
    "Granite Freight Lines", "ClearTrack Logistics", "Skybridge Cargo", "PrimeHaul Network",
    "Vertex Transport Solutions", "RapidLink Freight", "Harborline Logistics",
)
_WAREHOUSES = (
    ("Hyderabad Central Distribution Centre", "HYD-DC-01"),
    ("Pune Regional Warehouse", "PUN-WH-01"),
    ("Bengaluru Components Hub", "BLR-HUB-01"),
    ("Chennai Industrial Stores", "MAA-IS-01"),
    ("Mumbai Western Distribution Centre", "BOM-DC-01"),
    ("Delhi North Logistics Park", "DEL-LP-01"),
    ("Ahmedabad Parts Warehouse", "AMD-WH-01"),
    ("Kolkata Eastern Supply Hub", "CCU-HUB-01"),
)


def _unique_person_names(rng: Generator, count: int) -> list[str]:
    combinations = [f"{first} {last}" for first in _FIRST_NAMES for last in _LAST_NAMES]
    if count > len(combinations):
        raise ValueError(f"requested {count} distinct actor names but only {len(combinations)} combinations are available")
    order = rng.permutation(len(combinations))
    return [combinations[int(index)] for index in order[:count]]


def generate_item_master(rng: Generator, cfg: Mapping[str, Any]) -> pd.DataFrame:
    """Generate item records with per-item unit-price bands and UOMs."""
    require_rng(rng)
    scale = active_scale_config(cfg)
    item_count = int(scale["item_count"])
    catalog = get_config(cfg, "distributions", "item_catalog", "categories", default={})
    templates: list[tuple[str, str, float, float]] = []
    for category, spec in catalog.items():
        for item_name in spec.get("names", []):
            templates.append((str(category), str(item_name), float(spec["min_unit_price"]), float(spec["max_unit_price"])))
    if not templates:
        raise ValueError("distributions.item_catalog.categories must contain at least one item template")
    if item_count > len(templates):
        for offset in range(item_count - len(templates)):
            category, name, minimum, maximum = templates[offset % len(templates)]
            templates.append((category, f"{name} Variant {offset + 1:02d}", minimum, maximum))
    template_order = rng.permutation(len(templates))[:item_count]
    currency = str(get_config(cfg, "distributions", "default_currency", default="INR"))
    rows: list[dict[str, Any]] = []
    for seq, template_index in enumerate(template_order, start=1):
        category, name, category_min, category_max = templates[int(template_index)]
        span = category_max - category_min
        price_min = round(float(rng.uniform(category_min, category_min + span * 0.30)), 2)
        price_max = round(float(rng.uniform(category_min + span * 0.65, category_max)), 2)
        if price_max < price_min:
            price_max = price_min
        category_cfg = catalog[category]
        rows.append({
            "item_id": f"ITEM-{seq:06d}",
            "item_name": name,
            "default_uom": str(category_cfg["default_uom"]),
            "item_status": "ACTIVE",
            "unit_price_min": price_min,
            "unit_price_max": price_max,
            "price_currency": currency,
            "created_at": "2025-12-01T08:00:00+00:00",
        })
    return pd.DataFrame(rows, columns=[
        "item_id", "item_name", "default_uom", "item_status", "unit_price_min",
        "unit_price_max", "price_currency", "created_at",
    ])


def generate_carriers(rng: Generator, cfg: Mapping[str, Any]) -> pd.DataFrame:
    require_rng(rng)
    count = int(active_scale_config(cfg)["carrier_count"])
    if count < 1 or count > len(_CARRIER_NAMES):
        raise ValueError(f"carrier_count must be between 1 and {len(_CARRIER_NAMES)}")
    order = rng.permutation(len(_CARRIER_NAMES))
    rows = []
    for index, source_index in enumerate(order[:count], start=1):
        name = _CARRIER_NAMES[int(source_index)]
        rows.append({
            "carrier_id": f"CAR-{index:06d}",
            "carrier_name": name,
            "carrier_code": f"CARRIER-{index:03d}",
            "is_active": 1,
            "created_at": "2025-12-01T08:00:00+00:00",
        })
    return pd.DataFrame(rows, columns=["carrier_id", "carrier_name", "carrier_code", "is_active", "created_at"])


def generate_warehouses(rng: Generator, cfg: Mapping[str, Any]) -> pd.DataFrame:
    require_rng(rng)
    count = int(active_scale_config(cfg)["warehouse_count"])
    if count < 1 or count > len(_WAREHOUSES):
        raise ValueError(f"warehouse_count must be between 1 and {len(_WAREHOUSES)}")
    order = rng.permutation(len(_WAREHOUSES))
    rows = []
    for index, source_index in enumerate(order[:count], start=1):
        name, site_code = _WAREHOUSES[int(source_index)]
        rows.append({
            "warehouse_id": f"WH-{index:04d}",
            "warehouse_name": name,
            "site_code": f"{site_code}-{index:02d}",
            "timezone": "Asia/Kolkata",
            "is_active": 1,
            "created_at": "2025-12-01T08:00:00+00:00",
        })
    return pd.DataFrame(rows, columns=["warehouse_id", "warehouse_name", "site_code", "timezone", "is_active", "created_at"])


def generate_actor_roster(rng: Generator, cfg: Mapping[str, Any], suppliers: pd.DataFrame) -> pd.DataFrame:
    """Create actors for supplier contacts and all four operational actor roles."""
    require_rng(rng)
    scale = active_scale_config(cfg)
    roles = (
        ("planner", "PLN", int(scale["planner_count"])),
        ("carrier_warehouse_operator", "CWH", int(scale["carrier_warehouse_operator_count"])),
        ("logistics_analyst", "LOG", int(scale["logistics_analyst_count"])),
        ("operations_manager", "OPS", int(scale["operations_manager_count"])),
    )
    extra_count = sum(count for _, _, count in roles)
    names = iter(_unique_person_names(rng, extra_count))
    rows: list[dict[str, Any]] = []
    for supplier in suppliers.to_dict(orient="records"):
        rows.append({
            "actor_id": supplier["supplier_id"],
            "actor_role": "supplier",
            "actor_name": supplier["supplier_contact_name"],
            "email": supplier["supplier_contact_email"],
            "supplier_id": supplier["supplier_id"],
            "is_active": 1 if supplier["supplier_status"] == "ACTIVE" else 0,
            "created_at": supplier["created_at"],
        })
    for role, prefix, count in roles:
        for seq in range(1, count + 1):
            actor_name = next(names)
            rows.append({
                "actor_id": f"{prefix}-{seq:06d}",
                "actor_role": role,
                "actor_name": actor_name,
                "email": f"{prefix.lower()}{seq:03d}@example.test",
                "supplier_id": None,
                "is_active": 1,
                "created_at": "2025-12-01T08:00:00+00:00",
            })
    return pd.DataFrame(rows, columns=["actor_id", "actor_role", "actor_name", "email", "supplier_id", "is_active", "created_at"])


def generate_reference_data(rng: Generator, cfg: Mapping[str, Any], suppliers: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Generate all supporting master datasets from the same injected RNG stream."""
    return {
        "items": generate_item_master(rng, cfg),
        "carriers": generate_carriers(rng, cfg),
        "warehouses": generate_warehouses(rng, cfg),
        "actors": generate_actor_roster(rng, cfg, suppliers),
    }
