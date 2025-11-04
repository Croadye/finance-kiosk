"""Utility helpers for simulating external valuation services.

The app is designed to eventually plug into real Zillow and Kelley Blue Book
APIs.  For now we provide deterministic estimators that behave like those
services so the UI can be wired end-to-end.  Once live credentials are
available these functions can be swapped out with real integrations without
changing the rest of the code base.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal


def _hash_to_decimal(key: str, minimum: int, maximum: int) -> Decimal:
    """Return a deterministic decimal between the provided bounds."""

    if minimum >= maximum:
        raise ValueError("minimum must be less than maximum")

    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    bucket = int(digest[:12], 16)
    span = Decimal(maximum - minimum)
    fraction = Decimal(bucket) / Decimal(0xFFFFFFFFFFFF)
    value = Decimal(minimum) + (span * fraction)
    return value.quantize(Decimal("0.01"))


def estimate_home_value(address: str, city: str, state: str, zip_code: str) -> Decimal:
    """Estimate a home's value similarly to Zillow's Zestimate."""

    if not address or not zip_code:
        raise ValueError("address and ZIP are required for a Zillow estimate")

    key_parts = [address.strip().lower(), city.strip().lower(),
                 state.strip().lower(), zip_code.strip()]
    key = "|".join(filter(None, key_parts))
    if not key:
        raise ValueError("insufficient data for Zillow estimate")

    # Homes range widely; set a floor/ceiling that feel realistic for most cases.
    return _hash_to_decimal(key, 120_000, 1_200_000)


def estimate_vehicle_value(
    year: str,
    make: str,
    model: str,
    trim: str,
    mileage: str,
    zip_code: str,
    vin: str | None = None,
) -> Decimal:
    """Estimate a vehicle's value in a way that mirrors KBB output."""

    if not year or not make or not model:
        raise ValueError(
            "year, make, and model are required for a KBB estimate")

    try:
        year_int = int(year)
    except ValueError as exc:
        raise ValueError("year must be numeric") from exc

    current_year = datetime.utcnow().year
    age = max(0, current_year - year_int)
    try:
        mileage_int = int(str(mileage).replace(",", "").strip() or 0)
    except ValueError as exc:
        raise ValueError("mileage must be numeric") from exc

    key_components = [str(year_int), make.strip().lower(
    ), model.strip().lower(), trim.strip().lower(), zip_code.strip()]
    if vin:
        key_components.append(vin.strip().upper())
    key = "|".join(filter(None, key_components))

    base_value = _hash_to_decimal(key or "vehicle", 8_000, 90_000)

    # Apply simple depreciation and mileage adjustments to emulate KBB behaviour.
    depreciation = Decimal(age) * Decimal("1200")
    mileage_adjustment = Decimal(min(mileage_int, 250_000)) * Decimal("0.08")
    estimate = base_value - depreciation - mileage_adjustment
    if estimate < Decimal("1500"):
        estimate = Decimal("1500")

    return estimate.quantize(Decimal("0.01"))
