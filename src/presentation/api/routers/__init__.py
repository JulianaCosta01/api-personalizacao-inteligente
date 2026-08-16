from fastapi import APIRouter

from presentation.api.routers.aluno import router as aluno_router
from presentation.api.routers.health import router as health_router
from presentation.api.routers.material import router as material_router
from presentation.api.routers.perfil import router as perfil_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(aluno_router)
api_router.include_router(material_router)
api_router.include_router(perfil_router)
