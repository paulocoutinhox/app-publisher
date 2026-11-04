from enum import StrEnum
from typing import Self


class CaseInsensitiveEnum(StrEnum):
    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        if not isinstance(value, str):
            return None

        normalized = value.casefold()

        for member in cls:
            if member.value.casefold() == normalized:
                return member

        return None
