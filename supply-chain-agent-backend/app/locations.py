"""The shared location id namespace.

``Route`` and ``Shipment`` reference locations as plain integers, because an
endpoint can be a supplier, a warehouse or a dealer. This module is the single
canonical definition of that namespace; keep the ranges disjoint so an id always
resolves to exactly one entity without an extra ``location_type`` column.
"""

import enum
from typing import Optional

LOCATION_NAMESPACE_HELP = (
    "Route/shipment endpoints use a shared location namespace: "
    "suppliers 1-99, warehouses 101-199, dealers 201-299."
)


class LocationKind(str, enum.Enum):
    """Which kind of entity a location id refers to."""

    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    DEALER = "dealer"


class LocationRange:
    """Inclusive id range reserved for one kind of location."""

    SUPPLIER = (1, 99)
    WAREHOUSE = (101, 199)
    DEALER = (201, 299)


#: kind -> (first id, last id), inclusive.
RANGES: dict[LocationKind, tuple[int, int]] = {
    LocationKind.SUPPLIER: LocationRange.SUPPLIER,
    LocationKind.WAREHOUSE: LocationRange.WAREHOUSE,
    LocationKind.DEALER: LocationRange.DEALER,
}


def kind_of(location_id: int) -> Optional[LocationKind]:
    """Return which kind of location ``location_id`` is, or ``None`` if unassigned."""
    for kind, (first, last) in RANGES.items():
        if first <= location_id <= last:
            return kind
    return None


def in_range(location_id: int, kind: LocationKind) -> bool:
    """Whether ``location_id`` falls inside the range reserved for ``kind``."""
    first, last = RANGES[kind]
    return first <= location_id <= last
