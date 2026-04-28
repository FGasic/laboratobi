from fastapi import APIRouter

from app.api.analysis import router as analysis_router
from app.api.games import router as games_router
from app.api.imports import router as imports_router
from app.api.positions import router as positions_router
from app.core.config import settings

router = APIRouter()


@router.get("/")
def read_root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "status": "running",
    }


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


router.include_router(analysis_router)
router.include_router(games_router)
router.include_router(imports_router)
router.include_router(positions_router)
