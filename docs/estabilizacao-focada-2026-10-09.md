# WinLinAI — entregas focadas e pendências, 9 de outubro de 2026

A branch `fix/focused-stabilization` reúne cinco entregas implementadas e verificadas, com base em `master` no commit `92b88334c2c7fc3ff8f7308699f243c653bb3b70`. Cada entrega conserva um commit próprio. Esta é a sequência revista após a análise do Grok.

## Alterações implementadas

| Entrega | Problema e resultado |
| --- | --- |
| Sonda `Get-Service` | A serialização dos objetos completos podia percorrer dependências e esgotar o prazo. A projeção dos quatro campos consumidos pelo chat evita essas leituras e usa JSON com profundidade 2. Consultas individuais conservam o escaping existente; outros cmdlets conservam profundidade 10, prazo de 30 segundos e limite de 1 MiB. |
| Descoberta Windows do updater | `test_updater.py` não entrava no runner nativo. Os 41 testes passam a ser descobertos; a fixture de downloads usa uma home temporária. |
| Gate mypy com Qt real | O gate instala `.[dev,qt]`, exige imports reais e verifica os mesmos 22 módulos para Linux/win32. Corrige os diagnósticos dos cinco módulos Qt, incluindo enums, slots, atributos opcionais, a colisão com `tray.icon()` e o tratamento tipado de drag/drop. |
| Suite Qt/Linux completa | Um novo job executa todos os módulos `test_qt_*.py` com Qt real. O runner exige bindings, um event loop, descoberta não vazia e apenas os três skips inversos exatos. Quatro fixtures de caminhos POSIX foram alinhadas ao cabeçalho da fence, conforme o contrato do parser. |
| Falha de criação de conversa | `clear_conversation()` continuava a apagar o ecrã e o contexto quando `create_session()` falhava. Um `return` conserva a conversa atual; cinco regressões verificam publicação recusada, limite de sessões, pedido seguinte, sucesso e limpeza sem histórico. |

A home implícita continua autorizada quando `allowed_edit_dirs` está vazio. O parser mantém POSIX no cabeçalho da fence; `/usr/bin/env python3` na primeira linha do corpo continua sem gerar uma oferta de escrita. As propostas anteriores de mudança de autorização e de arquitetura das transações não integram estas entregas.

## Validação do conjunto

Ambiente local: Linux, Python 3.12.14, PySide6/Qt 6.12.0 e PowerShell 7.6.6 para o fixture de serialização. Os testes não executam alterações a serviços nem pedidos a providers externos.

| Verificação após integração | Resultado |
| --- | --- |
| Suite Qt/Linux completa | 217 descobertos, 214 aprovados, zero falhas e os três skips inversos previstos |
| Serviços, updater e contratos dos runners | 103 descobertos, 102 aprovados e um skip Windows nativo em Linux |
| Suite core completa, Python 3.8.20 | 1778 descobertos, 1610 aprovados e 168 skips de plataforma/dependências opcionais |
| Mypy Linux e win32 | Zero erros nos 22 módulos, para cada alvo; análise executada em Linux |
| Ruff, byte-compilation e diff-check | Aprovados |

As regressões foram reproduzidas antes das correções: os getters PowerShell eram lidos durante a serialização; o updater não era descoberto; havia 44 diagnósticos Qt por alvo; três testes de blocos de ficheiros falhavam em Qt/Linux; três dos cinco novos testes de criação de conversa falhavam.

O utilizador comunicou a aceitação de `Get-Service` em Windows PowerShell 5.1.26100.9549: 301 serviços, consulta direta em 1,12 s e sonda em 1,38 s, consulta individual coincidente e zero leituras de dependências; 52 testes aprovados. É evidência externa comunicada, descrita em [get-service-2026-10-09.md](get-service-2026-10-09.md). A validação local do conjunto não constitui uma execução Windows nativa. Os jobs GitHub devem executar a suite Windows, a matriz core, GTK, Qt/Linux e o gate de tipos desta branch.

A primeira execução GitHub expôs uma dependência de sistema ausente no runner Ubuntu: `libEGL.so.1`, necessária para importar QtGui/QtWidgets. Os jobs Qt/Linux e mypy instalam agora `libegl1` explicitamente antes de importar os bindings. O preflight continua a recusar imports falhados.

Com `.[dev,qt]` instalado, os principais comandos são:

```bash
QT_QPA_PLATFORM=offscreen python scripts/run_qt_tests.py
python -m unittest tests.test_pwsh_output tests.test_windows_foundation_service_probe tests.test_windows_foundation_service_serialization tests.test_windows_ci_runner tests.test_updater tests.test_qt_ci_runner -v
python -m mypy --config-file pyproject.toml --platform linux
python -m mypy --config-file pyproject.toml --platform win32
python -m ruff check src tests plugins scripts
```

Em Windows nativo, com `.[qt]` instalado, executar também `python scripts/run_windows_tests.py`. O teste da sonda exige explicitamente o motor inbox Windows PowerShell 5.1 Desktop.

## Próximas correções, uma entrega por caso

| Ordem | Pendência e prova a obter |
| --- | --- |
| 1 | Arquivar/eliminar a conversa ativa deve sincronizar ecrã e contexto. O pedido seguinte não pode incluir mensagens da conversa anterior. |
| 2 | Rever a janela entre o fim da thread e a aplicação do callback: resultados em fila, cancelamento e respostas antigas não podem afetar outro pedido. |
| 3 | Reconciliar falhas após publicação do histórico. A reprodução de `JsonWriteCommittedError` conserva ID/contexto locais, mas o disco já contém uma nova sessão ativa: uma sessão passou para duas quando `_sync_publication` falhou. A preservação da conversa local está corrigida; a reconciliação com o disco continua pendente. |
| 4 | Garantir que a imagem revista corresponde aos bytes enviados, que a substituição do caminho não muda o payload e que erros de capacidade visual têm mensagem própria. |
| 5 | Corrigir resíduos de backend/containment POSIX e padrões Credentials/INetCookies, preservando a política da home. Rever conflitos entre preview e publicação e limpeza de temporários mediante regressões concretas. |
| 6 | Ensaiar concorrência Windows de publicação/recovery: troca do pai imediato e atualização externa não podem causar perda silenciosa. A prova POSIX ou emulada não fecha esta aceitação nativa. |
| 7 | Rever separadamente routing de providers/modos, diagnóstico por sessão, arquivo/restauro/export, ícone/autostart e helpers updater. |

O instalador exige a sua própria compilação, instalação e arranque em Windows. A prova nativa de `Get-Service` necessária antes dessa entrega foi comunicada e passou; a documentação de distribuição só deve anunciar um EXE/installer aceite depois da prova do artefacto. As alterações de build devem limitar-se aos bloqueios confirmados e continuar em entrega própria.
