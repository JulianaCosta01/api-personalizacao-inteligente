"""Ferramental do teste de carga e concorrência da Fase 10, Task 2 (Documento 5, §17).

Pacote isolado de `src/`: nenhum módulo aqui é importado pela aplicação em produção, pela API ou
pelo Worker reais — só o inverso (estes scripts importam de `src/`, via PYTHONPATH=src, o mesmo
padrão já usado em `python -m worker.worker`; ver `loadtest/README.md`).
"""
