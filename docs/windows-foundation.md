# Primeira base Windows

O WinLinAI adapta o núcleo do Linux_AI para uma interface Qt em Windows. Esta
primeira etapa trata os bloqueios de arranque, persistência, execução de sondas
e distribuição. A interface GTK e as operações específicas de Linux continuam
a ser verificadas separadamente.

O suporte Windows é experimental. A existência de testes nativos no CI permite
detetar regressões; não substitui uma instalação e um ensaio numa máquina
Windows com uma sessão gráfica real.

## Instalação de desenvolvimento

Com Python 3.12 e Git instalados, abrir PowerShell como utilizador normal:

```powershell
git clone https://github.com/1400015/winlinai.git
cd winlinai
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install ".[qt]"
.\venv\Scripts\python.exe -m src.app --ui qt
```

Não é necessário ativar o ambiente virtual nem alterar a política de execução
PowerShell para usar estes comandos. `--ui auto` escolhe Qt em Windows nativo
e GTK em Linux ou dentro de WSL. Executar a partir do terminal mantém visíveis
as mensagens de erro de arranque.

O extra `qt` instala PySide6. As dependências de persistência Windows são
selecionadas pelo pacote através de marcadores de plataforma: `pywin32` é
instalado apenas em Windows para os helpers de ACL, identidade de ficheiros e
bloqueios. Sem esses helpers, as operações que exigem proteção devem falhar
explicitamente. O GTK e os serviços Linux não devem ser necessários para
arrancar a interface Qt.

## Âmbito da etapa

Estado: **I** = implementado, **INT** = integrado num caller real, **CI** = testado em CI Windows, **AR** = aceite em máquina real (pendente).

| Capacidade | Estado | Notas |
| --- | --- | --- |
| Arranque Qt sem GTK | I/INT/CI | Contrato explícito, incluindo falhas de inicialização |
| Configuração e histórico | I/INT/CI | Backend Windows nativo, testes de proteção e persistência |
| Execução limitada | I/INT/CI | Backend Windows para prazos, limites de saída e processos descendentes |
| Distribuição Python | I/CI | Wheel completo e ensaio fora do checkout |
| Conversa Qt (offline + IA) | I/INT/CI | Assistência offline, histórico, provider `ai_client` com fallback, cancelamento via `cancel_event` |
| Diagnósticos PowerShell/WSL | I/INT/CI | Fronteira do host e catálogo de sondas; normalização em `src/platform/pwsh_output.py`; `-EncodedCommand` via `launch_script` |
| Tray e autostart | I/INT/CI | Expert Mode, Statistics, ícone SVG, tooltip com plataforma, checkbox de autostart em Settings |
| Updater | I/INT/CI | Verificação de updates em Settings e arranque; sem auto-download |
| Escrita de ficheiros (file blocks) | I/INT/CI | Fluxo expert-mode: parse, preview, confirmação, escrita atómica com backup |
| Instalador Windows | I/CI | Scripts PowerShell corrigidos e validados (`tests/test_installer_assets.py`); `.ico` gerado; empacotamento .msi/.exe pendente |

Os comandos continuam sujeitos à política local. O texto de um modelo ou de
uma documentação não autoriza execução. As operações Linux com privilégios,
os gestores de pacotes Linux e os helpers polkit não são funcionalidades
Windows. Falhas em proteger estado ou inicializar um backend devem ser
apresentadas como erro, sem produzir uma janela aparentemente funcional com
serviços essenciais ausentes.

Dentro de uma distribuição WSL, as sondas POSIX executam diretamente nessa
distribuição. Só o host Windows nativo pode usar o caminho PowerShell ou a
ponte `wsl.exe`; a ponte exige uma distribuição explicitamente escolhida e
aceita apenas as sondas do catálogo. Não permite comandos de alteração nem
leituras arbitrárias de ficheiros da distribuição.

A persistência Windows usa ACLs e handles para validar ficheiros e diretórios,
bloqueios entre processos e publicação por rename seguida de flush do
ficheiro. Windows não oferece um equivalente suportado de `fsync` de
diretório POSIX; não se garante que toda a metadata de diretório sobreviva a
uma perda súbita de energia em qualquer filesystem. Uma falha após publicação
é comunicada como resultado incerto, pois o ficheiro já pode ter sido alterado.

Os Job Objects limitam processos e descendentes Windows. Não comprovam o fim
dos processos Linux que `wsl.exe` iniciou através do serviço WSL. Se uma sonda
WSL for interrompida por prazo ou excesso de saída, o resultado conserva um
aviso de encerramento incerto; é necessário verificar a distribuição antes de
repetir a operação. A aplicação não termina automaticamente a distribuição.

## Verificação automatizada

O workflow `.github/workflows/test.yml` separa três capacidades:

- **Core Linux:** a suite completa em Python 3.8, 3.10 e 3.12, incluindo
  contratos sem dependências GUI. Omissões por ausência de GTK/Qt ou Windows
  nativo são esperadas neste ambiente.
- **GTK Linux:** a suite Linux/GTK com display virtual. Qt e os módulos
  `test_windows_foundation*.py` pertencem ao job próprio. Só os dois testes
  que exercitam deliberadamente a ausência de GTK podem ser omitidos, pelo
  identificador e motivo exatos; outras omissões ou falhas reprovam o job.
- **Windows/Qt:** Windows nativo e Python 3.12 com PySide6. Descobre
  `test_windows_foundation*.py` e `test_qt_*.py`. Uma omissão de capacidade
  Windows ou de importação Qt reprova o job. Só três testes que exercitam
  deliberadamente a ausência de PySide6 podem ser omitidos, pelo identificador
  e motivo exatos.

Para executar a verificação Windows no checkout:

```powershell
.\venv\Scripts\python.exe -m pip install build "setuptools>=61" wheel
$env:QT_QPA_PLATFORM = "offscreen"
.\venv\Scripts\python.exe scripts/run_windows_tests.py
```

O runner exige Windows nativo: executá-lo em WSL ou Linux não verifica as APIs
Windows. Os testes Qt sem display verificam construção e comportamento de
widgets; a disponibilidade da tray e a interação normal com o desktop precisam
de ensaio gráfico separado.

O CI também constrói um wheel, instala-o com o extra Qt num ambiente virtual
limpo e executa `scripts/smoke_installed_package.py` a partir desse ambiente,
fora do checkout. O ensaio exige os módulos de plataforma, conhecimento e
temas empacotados, uma janela Qt com backends reais, configuração persistente
e uma pergunta/resposta offline guardadas no histórico. Um import bem-sucedido
de uma janela sem os seus serviços não basta.

## Aceitação numa máquina Windows

Após o CI nativo passar, verificar com uma conta normal e registar versão do
Windows, versão do Python e commit utilizado:

1. Instalar seguindo os comandos acima numa pasta nova e arrancar sem GTK.
2. Procurar `pesquisar conhecimento DNS`, confirmar uma resposta e verificar
   que o histórico permanece ao fechar e reabrir a aplicação.
3. Alterar uma definição, fechar normalmente e confirmar que foi preservada.
4. Confirmar que uma falha de inicialização/persistência apresenta um erro
   identificável e preserva os ficheiros originais.
5. Verificar a execução de uma sonda permitida, uma recusa por política e o
   resultado dos testes de prazo/limite de saída no terminal.

## Correções desta iteração (2026-10-07)

### Tray Qt (`src/qt_tray.py`)
- **Expert Mode**: checkbox no menu (paridade com GTK), sincronizado via `update_expert_mode()`
- **Statistics**: item de menu para abrir o diálogo de estatísticas
- **Ícone**: carregado do SVG empacotado em `assets/` (fallback para tema/janela)
- **Tooltip**: mostra a plataforma (ex: "Linux AI Assistant — Windows")
- **Menu completo**: Show/Hide, Expert Mode, Settings, History, Statistics, Quit

### Autostart (`src/windows_autostart.py`)
- `is_autostart_enabled()`: verifica o estado atual no Registry
- `set_autostart()`: wrapper de alto nível com backends reais
- `default_powershell_exe()` / `default_script_path()`: detecta caminhos automaticamente
- Integração em `QtSettingsDialog`: checkbox "Start with Windows" (só em Windows)

### Normalização PowerShell (`src/platform/pwsh_output.py`)
- `wrap_cmdlet_json()`: envolve cmdlets com `ConvertTo-Json -Compress`
- `parse_json_output()`: parseia output JSON do PowerShell, tratando erros
- Normalizadores por tipo: `normalize_service`, `normalize_process`, `normalize_volume`, `normalize_network_adapter`, `normalize_ip_config`
- `run_probe()`: executa sonda validada e retorna dados normalizados

### Diálogos Qt (`src/qt_dialogs.py`)
- `QtSettingsDialog`: seção de API Keys + seção de Startup (autostart)
- `QtStatisticsDialog`: diálogo de estatísticas com reset (paridade com GTK)
- `statistics_rows()`: lógica pura de apresentação de uso de tokens

### Testes
- `tests/test_qt_phase4c.py`: +15 testes (expert mode, platform label, autostart high-level, statistics rows, tray actions)
- `tests/test_pwsh_output.py`: 30 testes para normalização de output PowerShell

## Melhorias desta iteração (2026-10-07, segunda passagem)

Após uma autoavaliação honesta do código, foram executadas quatro fases de melhoria:

### Fase A — Estabilização
- `installer/build-installer.ps1`: corrigido typo (`'n'` solto) que quebrava o script
- `assets/io.github.linux_ai_assistant.ico`: gerado (Pillow, multi-size) — estava referenciado mas não existia
- `installer/winlinai.spec`: removidas opções PyInstaller 6 removidas (`win_no_prefer_redirects`, `win_private_assemblies`)
- `src/updater.py`: corrigida precedência `and`/`or` na deteção de assets Windows via nova função pura `_is_windows_installer_asset()`
- `tests/test_installer_assets.py`: 14 testes (referências .iss, validade .spec, sintaxe PowerShell via PS parser, presença de assets)

### Fase B — Arquitetura (extração = migração)
- `src/theme_utils.py` integrado em `src/main_window.py` (-185 linhas); `build_gtk_css()` movido para lá; teste dourado `tests/test_theme_golden.py` (CSS byte-identical para 4 temas)
- `src/main_window_themes.py` integrado em `MainWindow` (-92 linhas); cópias locais e regexes removidos
- `src/providers/` (spike não integrado) removido; documentado em `docs/spikes/providers.md` com caminho de continuação (pilot local_llm)
- Fluxo de escrita de ficheiros (file blocks) ligado ao chat Qt: `_offer_file_blocks`, `preview_diff`, `confirm_file_write_qt`, escrita atómica + backup
- Updater ligado: secção "Updates" em `QtSettingsDialog`, verificação no arranque (`_maybe_check_updates`), notificação via mensagem de sistema

### Fase C — Segurança e concorrência
- `src/windows_system_actions.py`: winget deixa de usar `subprocess.run` diretamente; passa por `run_bounded` com allowlist (`list`/`search`) e validação de query
- `src/qt_worker.py` (novo): Worker genérico com sinais tipados (`finished`/`failed`); substitui `QMetaObject.invokeMethod` por sinais
- `src/qt_chat.py`: `_ProviderWorker` + `cancel_event` (threading.Event); botão "Stop" durante chamadas; `provider_reply_text` mapeia `AIRequestCancelled` → `"cancelled"`
- `src/platform/shell_pwsh.py`: nova `launch_script()` extrai encoding `-EncodedCommand`; `pwsh_output.wrap_cmdlet_json` reutiliza-a; `run_probe` aceita `probe_key` e normaliza
- `src/qt_dialogs.py`: `QtCore.Qt.Checked` em vez de número mágico `2`

## Ainda falta

- **Aceitação em máquina Windows real**: validar tray, autostart, ícones e updater com sessão gráfica (CI cobre construção e comportamento de widgets, não interação desktop)
- **Empacotamento .msi/.exe**: Inno Setup/NSIS (scripts e assets já validados por testes)
- **Consolidação da gestão de conversas Qt**: paridade completa com GTK (sessões, export, procura)
- **Paridade com ações GTK**: `conversation_actions` e `service_actions` (file blocks já integrados; winget via `windows_system_actions`)
- **Captura de ecrã**: equivalente Windows ao portal Wayland está implementado (`src/windows_screenshot.py`); falta ensaio em máquina real
- **Temas visuais Qt**: carregar `themes/*.json` como stylesheets Qt está implementado (`src/qt_theme.py`); falta ensaio visual em máquina real
- **Provider local (local_llm)**: paridade de IA local completa (providers remotos já integrados)
