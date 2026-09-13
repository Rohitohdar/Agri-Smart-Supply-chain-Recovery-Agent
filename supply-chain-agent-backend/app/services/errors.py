"""Domain-level errors.

Services never import FastAPI; ``main.py`` maps these to HTTP responses.
"""


class ServiceError(Exception):
    """Base class for domain errors."""


class NotFoundError(ServiceError):
    """Raised when an entity id does not exist.

    ``detail`` overrides the default message, which is useful when the id is
    real but the caller asked the wrong resource for it.
    """

    def __init__(
        self, entity: str, entity_id: object, detail: str | None = None
    ) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(detail or f"{entity} {entity_id} not found")


class ConflictError(ServiceError):
    """Raised when a request is well-formed but infeasible right now.

    This is the error every state-changing action raises when it fails
    validation against current database state (insufficient stock, an
    unavailable route, a shipment that already landed, ...). ``reason`` is a
    stable machine-readable code so the agent layer can branch on *why* an
    action was refused instead of parsing the message; ``main.py`` maps this to
    HTTP 409.
    """

    def __init__(self, detail: str, *, reason: str = "conflict") -> None:
        self.reason = reason
        super().__init__(detail)
