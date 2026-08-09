"""Modelos SQLAlchemy das sete entidades do DER (Documento 2, §4.1).

Import explícito de todos os módulos aqui garante que Base.metadata seja
populada por completo antes de qualquer uso de Alembic autogenerate ou
create_all — sem isso, um modelo nunca importado simplesmente não existiria
para o metadata, mesmo estando presente no pacote.
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
