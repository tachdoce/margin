from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.bootstrap import BootstrapResponse
from app.services import bootstrap_service

router = APIRouter(tags=["bootstrap"])


@router.get("/bootstrap", response_model=BootstrapResponse)
def bootstrap(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "version": settings.bootstrap_version,
        "catalogs": bootstrap_service.build_catalogs(db, user),
    }
