"""Shared schema building blocks and the numeric bounds every request shares.

Range validation lives here so the same limit applies wherever a quantity or a
duration can be supplied, and so there is one place to change it. The bounds are
deliberately far above anything the scenario needs (thousands of bags, hours)
while still rejecting the values a fat-fingered or hostile caller would send.
"""

from pydantic import BaseModel, ConfigDict

#: Largest quantity any endpoint will accept in one request.
MAX_QUANTITY = 1_000_000

#: Largest duration in hours (one year). Bounds delivery, delay and travel times.
MAX_HOURS = 8_760.0

#: Largest monetary or carbon rate per unit.
MAX_RATE = 1_000_000.0

#: Largest route distance in kilometres (more than the Earth's circumference).
MAX_DISTANCE_KM = 100_000.0


class ORMModel(BaseModel):
    """Base for schemas that are read from / written to ORM instances."""

    model_config = ConfigDict(from_attributes=True)
