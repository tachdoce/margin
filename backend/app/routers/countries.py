from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.country import Country
from app.schemas.country import CountryRead

router = APIRouter(prefix="/countries", tags=["countries"])


@router.get("", response_model=list[CountryRead])
def list_countries(db: Session = Depends(get_db)) -> list[Country]:
    return list(db.execute(select(Country).where(Country.visible.is_(True))).scalars())
