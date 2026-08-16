from fastapi import APIRouter

from presentation.api.routers.aluno import router as aluno_router
from presentation.api.routers.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(aluno_router)
