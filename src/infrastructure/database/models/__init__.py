"""Modelos SQLAlchemy das sete entidades do DER.

Importar todos aqui garante o Base.metadata completo para o Alembic autogenerate.
"""

from infrastructure.database.models.acesso import AcessoMaterialPersonalizado
from infrastructure.database.models.aluno import Aluno
from infrastructure.database.models.log import LogInteracao
from infrastructure.database.models.material import MaterialDidatico
from infrastructure.database.models.material_personalizado import MaterialPersonalizado
from infrastructure.database.models.perfil import PerfilAprendizagem
from infrastructure.database.models.processamento import Processamento

__all__ = [
    "AcessoMaterialPersonalizado",
    "Aluno",
    "LogInteracao",
    "MaterialDidatico",
    "MaterialPersonalizado",
    "PerfilAprendizagem",
    "Processamento",
]
