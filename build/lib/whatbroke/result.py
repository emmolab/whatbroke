from dataclasses import dataclass, field
from typing import List, Optional

SEVERITY: dict = {"OK": 0, "WARN": 1, "BROKE": 2, "CRIT": 3}
VALID_STATUSES = frozenset(SEVERITY)


def escalate(current: str, candidate: str) -> str:
    """Return the more severe of two statuses."""
    return candidate if SEVERITY[candidate] > SEVERITY[current] else current


@dataclass
class Result:
    name: str
    status: str
    message: str
    details: List[str] = field(default_factory=list)
    remediation: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {self.status!r}")
