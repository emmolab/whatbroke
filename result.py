from dataclasses import dataclass, field
from typing import List, Optional

VALID_STATUSES = {"OK", "WARN", "BROKE", "CRIT"}

@dataclass
class Result:
    name: str
    status: str
    message: str
    details: List[str] = field(default_factory=list)
    remediation: Optional[str] = None

    def __post_init__(self):
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {self.status}")
