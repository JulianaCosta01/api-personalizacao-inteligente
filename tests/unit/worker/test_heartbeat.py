import time
from pathlib import Path

from worker.heartbeat import atualizar_heartbeat, heartbeat_esta_valido, limite_padrao_segundos


def test_heartbeat_invalido_quando_arquivo_nao_existe(tmp_path: Path) -> None:
    caminho = tmp_path / "heartbeat"

    assert heartbeat_esta_valido(60.0, caminho=caminho) is False


def test_heartbeat_valido_logo_apos_atualizar(tmp_path: Path) -> None:
    caminho = tmp_path / "heartbeat"

    atualizar_heartbeat(caminho=caminho)

    assert heartbeat_esta_valido(60.0, caminho=caminho) is True


def test_heartbeat_invalido_quando_claramente_expirado(tmp_path: Path) -> None:
    caminho = tmp_path / "heartbeat"
    caminho.write_text(str(time.time() - 3600))  # 1 hora atrás, bem além de qualquer limite real

    assert heartbeat_esta_valido(60.0, caminho=caminho) is False


def test_heartbeat_invalido_quando_conteudo_corrompido(tmp_path: Path) -> None:
    caminho = tmp_path / "heartbeat"
    caminho.write_text("nao-e-um-timestamp-valido")

    assert heartbeat_esta_valido(60.0, caminho=caminho) is False


def test_heartbeat_respeita_a_borda_do_limite(tmp_path: Path) -> None:
    caminho = tmp_path / "heartbeat"
    caminho.write_text(str(time.time() - 30.0))

    assert heartbeat_esta_valido(60.0, caminho=caminho) is True
    assert heartbeat_esta_valido(10.0, caminho=caminho) is False


def test_comportamento_seguro_apos_reinicio_do_container(tmp_path: Path) -> None:
    # Simula um container novo: /tmp é efêmero por container, então o heartbeat da execução
    # anterior não existe mais até a primeira iteração do loop chamar atualizar_heartbeat().
    caminho = tmp_path / "heartbeat"

    assert heartbeat_esta_valido(60.0, caminho=caminho) is False

    atualizar_heartbeat(caminho=caminho)

    assert heartbeat_esta_valido(60.0, caminho=caminho) is True


def test_atualizar_heartbeat_nao_lanca_quando_caminho_e_invalido(tmp_path: Path) -> None:
    # Diretório em vez de arquivo: write_text falha com OSError/IsADirectoryError;
    # atualizar_heartbeat precisa engolir isso, não derrubar o Worker por causa disso.
    caminho_invalido = tmp_path  # é um diretório, não um arquivo

    atualizar_heartbeat(caminho=caminho_invalido)


def test_limite_padrao_deriva_de_settings_existentes_sem_valor_novo_de_configuracao() -> None:
    from core.config import get_settings

    settings = get_settings()
    esperado = (
        settings.worker_intervalo_polling_segundos
        + settings.worker_prazo_maximo_job_segundos
        + 30.0
    )

    assert limite_padrao_segundos() == esperado
    # Um job pode durar até o prazo máximo sem gravar heartbeat: o limite precisa cobri-lo.
    assert limite_padrao_segundos() > settings.worker_prazo_maximo_job_segundos
