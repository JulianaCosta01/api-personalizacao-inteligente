"""Smoke test: garante que o ambiente e o pythonpath estão configurados."""

import sys

from core import __version__ as core_version


def test_python_version_e_no_minimo_3_13() -> None:
    assert sys.version_info >= (3, 13), (
        "O projeto exige Python 3.13+; ambiente atual: "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )


def test_pacote_core_e_importavel() -> None:
    assert core_version == "0.1.0"
