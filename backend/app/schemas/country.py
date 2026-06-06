from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CountryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    visible: bool
    vat_rate: Decimal
