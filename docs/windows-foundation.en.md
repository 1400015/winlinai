# Windows Foundation

WinLinAI adapts the Linux_AI core to a Qt interface on Windows. This first
stage addresses startup blockers, persistence, probe execution and
distribution. The GTK interface and Linux-specific operations continue to be
verified separately.

Windows support is experimental. The existence of native tests in CI allows
detection of regressions; it does not replace an installation and trial on a
Windows machine with a real graphical session.

## Development installation

With Python 3.12 and Git installed, open PowerShell as a normal user:

```powershell
git clone https://github.com/1400015/winlinai.git
cd winlinai
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install ".[qt]"
.\venv\Scripts\python.exe -m src.app --ui qt
```

It is not necessary to activate the virtual environment or change the
PowerShell execution policy to use these commands. `--ui auto` selects Qt on
native Windows and GTK on Linux or inside WSL. Running from the terminal keeps
startup error messages visible.

The `qt` extra installs PySide6. Windows persistence dependencies are selected
by the package through platform markers: `pywin32` is installed only on Windows
for ACL helpers, file identity and locks. Without these helpers, operations
that require protection must fail explicitly. GTK and Linux services should not
be required to start the Qt interface.

## Scope of this stage

Status: **I** = implemented, **INT** = integrated in a real caller, **CI** = tested on Windows CI, **AR** = accepted on a real machine.

| Capability | Status | Notes |
| --- | --- | --- |
| Qt startup without GTK | I/INT/CI | Explicit contract, including initialization failures |
| Configuration and history | I/INT/CI | Native Windows backend, protection and persistence tests |
| Bounded execution | I/INT/CI | Windows backend for timeouts, output limits and descendant processes |
| Python distribution | I/CI | Complete wheel and out-of-checkout trial |
| Qt conversation (offline + AI) | I/INT/CI | Offline assistance, history, `ai_client` provider with fallback, cancellation via `cancel_event` |
| PowerShell/WSL diagnostics | I/INT/CI | Host boundary and probe catalog; normalization in `src/platform/pwsh_output.py`; `-EncodedCommand` via `launch_script` |
| Tray and autostart | I/INT/CI | Expert Mode, Statistics, SVG icon, platform tooltip, autostart checkbox in Settings |
| Updater | I/INT/CI | Update check in Settings and on startup; no auto-download |
| File writes (file blocks) | I/INT/CI | Expert-mode flow: parse, preview, confirmation, atomic write with backup |
| Windows installer | I/CI/AR | Scripts validated by `tests/test_installer_assets.py`. The Inno Setup installer `WinLinAI-1.4.2-Setup.exe` (1.4.2) was compiled, installed, and started on this machine: the window opened and the process was then closed. No .msi was produced. |

Commands remain subject to local policy. Text from a model or documentation
does not authorize execution. Privileged Linux operations, Linux package
managers and polkit helpers are not Windows features. Failures to protect
state or initialize a backend must be presented as an error, without producing
a seemingly functional window with essential services missing.

Inside a WSL distribution, POSIX probes run directly in that distribution.
Only the native Windows host can use the PowerShell path or the `wsl.exe`
bridge; the bridge requires an explicitly chosen distribution and accepts
only probes from the catalog. It does not allow mutation commands or arbitrary
file reads from the distribution.

Windows persistence uses ACLs and handles to validate files and directories,
cross-process locks and publication by rename followed by file flush. Windows
does not offer a supported equivalent of POSIX directory `fsync`; it is not
guaranteed that all directory metadata survives a sudden power loss on any
filesystem. A failure after publication is reported as an uncertain result,
because the file may already have been changed.

Job Objects limit Windows processes and descendants. They do not prove
termination of Linux processes that `wsl.exe` started through the WSL service.
If a WSL probe is interrupted by timeout or excess output, the result retains
an uncertain cleanup warning; the distribution must be checked before repeating
the operation. The application does not automatically terminate the
distribution.

## Automated verification

The `.github/workflows/test.yml` workflow separates three capabilities:

- **Core Linux:** the complete suite on Python 3.8, 3.10 and 3.12, including
  contracts without GUI dependencies. Skips due to absence of GTK/Qt or native
  Windows are expected in this environment.
- **GTK Linux:** the Linux/GTK suite with virtual display. Qt and the
  `test_windows_foundation*.py` modules belong to their own job. Only the two
  tests that deliberately exercise the absence of GTK can be skipped, by exact
  identifier and reason; other skips or failures fail the job.
- **Windows/Qt:** native Windows and Python 3.12 with PySide6. Discovers
  `test_windows_foundation*.py` and `test_qt_*.py`. A skip of Windows
  capability or Qt import fails the job. Only three tests that deliberately
  exercise the absence of PySide6 can be skipped, by exact identifier and
  reason.

To run the Windows verification in the checkout:

```powershell
.\venv\Scripts\python.exe -m pip install build "setuptools>=61" wheel
$env:QT_QPA_PLATFORM = "offscreen"
.\venv\Scripts\python.exe scripts/run_windows_tests.py
```

The runner requires native Windows: running it in WSL or Linux does not verify
Windows APIs. Qt tests without a display verify widget construction and
behavior; tray availability and normal desktop interaction require a separate
graphical trial.

CI also builds a wheel, installs it with the Qt extra in a clean virtual
environment and runs `scripts/smoke_installed_package.py` from that
environment, outside the checkout. The trial requires the packaged platform,
knowledge and theme modules, a Qt window with real backends, persistent
configuration and an offline question/answer saved in history. A successful
import of a window without its services is not enough.

## Acceptance on a Windows machine

After native CI passes, verify with a normal account and record Windows
version, Python version and commit used:

1. Install following the commands above in a new folder and start without GTK.
2. Search for `pesquisar conhecimento DNS`, confirm a response and verify
   that history remains when closing and reopening the application.
3. Change a setting, close normally and confirm it was preserved.
4. Confirm that an initialization/persistence failure presents an
   identifiable error and preserves the original files.
5. Verify the execution of an allowed probe, a policy refusal and the result
   of timeout/output limit tests in the terminal.

## Corrections in this iteration (2026-10-07)

### Qt Tray (`src/qt_tray.py`)
- **Expert Mode**: checkbox in menu (parity with GTK tray), synchronized via `update_expert_mode()`
- **Statistics**: menu item to open the statistics dialog
- **Icon**: loaded from bundled SVG in `assets/` (fallback to theme/window)
- **Tooltip**: shows the platform (e.g. "Linux AI Assistant — Windows")
- **Full menu**: Show/Hide, Expert Mode, Settings, History, Statistics, Quit

### Autostart (`src/windows_autostart.py`)
- `is_autostart_enabled()`: checks current status in Registry
- `set_autostart()`: high-level wrapper with real backends
- `default_powershell_exe()` / `default_script_path()`: detect paths automatically
- Integration in `QtSettingsDialog`: "Start with Windows" checkbox (Windows only)

### PowerShell Normalization (`src/platform/pwsh_output.py`)
- `wrap_cmdlet_json()`: wraps cmdlets with `ConvertTo-Json -Compress`
- `parse_json_output()`: parses PowerShell JSON output, handles errors
- Normalizers: `normalize_service`, `normalize_process`, `normalize_volume`, `normalize_network_adapter`, `normalize_ip_config`
- `run_probe()`: executes validated probe and returns normalized data

### Qt Dialogs (`src/qt_dialogs.py`)
- `QtSettingsDialog`: API Keys section + Startup (autostart) section + Appearance (theme) section
- `QtStatisticsDialog`: statistics dialog with reset (GTK parity)
- `statistics_rows()`: pure presentation logic for token usage

### Qt Chat (`src/qt_chat.py`)
- AI provider integration with automatic fallback to offline
- Image attachments (attach button, screenshot button, drag & drop)
- Thinking indicator during AI calls
- Context menu with conversation actions

### Visual Themes (`src/qt_theme.py`)
- Load `themes/*.json` (same format as GTK track)
- Convert theme colors to Qt stylesheets (QSS)
- Theme selector in Settings with live preview

### Conversation Actions (`src/qt_conversation_actions.py`)
- Export conversation to Markdown/JSON/Text
- Copy last response to clipboard
- Clear/new conversation
- Show conversation summary

### Windows Screenshot (`src/windows_screenshot.py`)
- Screen capture via PIL.ImageGrab
- Region capture support
- Size limits (64MB, 16384px edge, 32M pixels)

### Windows System Actions (`src/windows_system_actions.py`)
- List services (Get-Service)
- List processes (Get-Process)
- System info (OS, memory, disks, network)
- List/search packages (winget)

### Tests
- `tests/test_qt_phase4c.py`: +15 tests (expert mode, platform label, autostart high-level, statistics rows, tray actions)
- `tests/test_pwsh_output.py`: 30 tests for PowerShell output normalization
- `tests/test_qt_theme.py`: 19 tests for theme loading, colors, QSS generation
- `tests/test_qt_chat.py`: 18 tests for provider integration, fallback logic
- `tests/test_qt_conversation_actions.py`: 18 tests for conversation actions
- `tests/test_windows_screenshot.py`: 8 tests for screenshot capture
- `tests/test_windows_system_actions.py`: 15 tests for system actions
- `tests/test_qt_e2e.py`: 14 end-to-end integration tests

## Improvements in this iteration (2026-10-07, second pass)

After an honest code self-assessment, four improvement phases were executed:

### Phase A — Stabilization
- `installer/build-installer.ps1`: fixed stray `'n'` typo that broke the script
- `assets/io.github.linux_ai_assistant.ico`: generated (Pillow, multi-size) — was referenced but did not exist
- `installer/winlinai.spec`: removed PyInstaller-6-removed options (`win_no_prefer_redirects`, `win_private_assemblies`)
- `src/updater.py`: fixed `and`/`or` precedence in Windows asset detection via new pure `_is_windows_installer_asset()`
- `tests/test_installer_assets.py`: 14 tests (.iss references, .spec validity, PowerShell syntax via PS parser, asset presence)

### Phase B — Architecture (extraction = migration)
- `src/theme_utils.py` integrated into `src/main_window.py` (-185 lines); `build_gtk_css()` moved there; golden test `tests/test_theme_golden.py` (byte-identical CSS for 4 themes)
- `src/main_window_themes.py` integrated into `MainWindow` (-92 lines); local copies and regexes removed
- `src/providers/` (unintegrated spike) removed; documented in `docs/spikes/providers.md` with continuation path (local_llm pilot)
- File-block write flow wired into Qt chat: `_offer_file_blocks`, `preview_diff`, `confirm_file_write_qt`, atomic write + backup
- Updater wired: "Updates" section in `QtSettingsDialog`, startup check (`_maybe_check_updates`), notification via system message

### Phase C — Security and concurrency
- `src/windows_system_actions.py`: winget no longer uses `subprocess.run` directly; goes through `run_bounded` with allowlist (`list`/`search`) and query validation
- `src/qt_worker.py` (new): generic Worker with typed signals (`finished`/`failed`); replaces `QMetaObject.invokeMethod` with signals
- `src/qt_chat.py`: `_ProviderWorker` + `cancel_event` (threading.Event); "Stop" button during calls; `provider_reply_text` maps `AIRequestCancelled` → `"cancelled"`
- `src/platform/shell_pwsh.py`: new `launch_script()` extracts `-EncodedCommand` encoding; `pwsh_output.wrap_cmdlet_json` reuses it; `run_probe` accepts `probe_key` and normalizes
- `src/qt_dialogs.py`: `QtCore.Qt.Checked` instead of magic number `2`

## Still missing

- **Acceptance on a real Windows machine**: validate tray, autostart, icons and updater with a graphical session (CI covers widget construction and behavior, not desktop interaction)
- **.msi packaging**: not produced. The Inno Setup installer `WinLinAI-1.4.2-Setup.exe` (1.4.2) was compiled, installed, and started on this machine: the window opened and the process was then closed.
- **Qt conversation management consolidation**: complete parity with GTK (sessions, export, search)
- **Parity with GTK actions**: `conversation_actions` and `service_actions` (file blocks already integrated; winget via `windows_system_actions`)
- **Screen capture**: Windows equivalent to the Wayland portal is implemented (`src/windows_screenshot.py`); real-machine trial pending
- **Qt visual themes**: loading `themes/*.json` as Qt stylesheets is implemented (`src/qt_theme.py`); visual trial on a real machine pending
- **Local provider (local_llm)**: complete local AI parity (remote providers already integrated)
