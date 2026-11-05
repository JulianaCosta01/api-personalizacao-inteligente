"""Limites das etapas locais do pipeline, iguais aos padrões de produção.

Testes que rodam a extração e o PDF reais usam estes limites, e não o timeout do Gemini,
para não dependerem da velocidade da máquina.
"""

from typing import Any

from infrastructure.config.settings import Settings

LIMITES_LOCAIS_DE_PRODUCAO: dict[str, Any] = {
    "timeout_extracao_segundos": Settings.model_fields[
        "pipeline_timeout_extracao_segundos"
    ].default,
    "timeout_pdf_segundos": Settings.model_fields["pipeline_timeout_pdf_segundos"].default,
}
