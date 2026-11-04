from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolCheck:
    name: str
    status: Literal["OK", "MISSING", "UNVERIFIED"]
    detail: str
