import re
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, StringConstraints

T = TypeVar("T")


def _normalise_phone(value: object) -> object:
    """Accept 0754 000 001, +255 754 000 001 or 754000001; store 255754000001."""
    if value is None or value == "":
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 10 and digits.startswith("0"):
        digits = "255" + digits[1:]
    elif len(digits) == 9:
        digits = "255" + digits
    return digits


TzPhone = Annotated[str, BeforeValidator(_normalise_phone), StringConstraints(pattern=r"^255\d{9}$")]
NidaNo = Annotated[str, StringConstraints(pattern=r"^\d{20}$")]
Stream = Annotated[str, StringConstraints(pattern=r"^[A-Z]{1,5}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
