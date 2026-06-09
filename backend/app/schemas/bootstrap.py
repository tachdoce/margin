from pydantic import BaseModel, ConfigDict


class _Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CurrencyOut(_Read):
    id: int
    name: str
    is_legal_tender: bool
    allowed_in_credit_card: bool
    symbol: str
    display_decimals: int


class ObligationTypeOut(_Read):
    id: int
    obligation_kind: str
    code: str
    name: str
    description: str
    default_priority_level: int


class IncomeTypeOut(_Read):
    id: int
    code: str
    name: str


class PriorityLevelOut(_Read):
    level: int
    name: str
    description: str


class InstitutionOut(_Read):
    id: int
    name: str


class ReviewFindingCodeOut(_Read):
    code: str
    message: str


class CreditCardNetworkOut(_Read):
    id: int
    code: str
    name: str


class CreditCardItemTypeOut(_Read):
    id: int
    code: str
    name: str
    description: str


class Catalogs(BaseModel):
    currencies: list[CurrencyOut]
    obligation_types: list[ObligationTypeOut]
    income_types: list[IncomeTypeOut]
    priority_levels: list[PriorityLevelOut]
    institutions: list[InstitutionOut]
    review_finding_codes: list[ReviewFindingCodeOut]
    credit_card_networks: list[CreditCardNetworkOut]
    credit_card_item_types: list[CreditCardItemTypeOut]


class BootstrapResponse(BaseModel):
    version: str
    catalogs: Catalogs
