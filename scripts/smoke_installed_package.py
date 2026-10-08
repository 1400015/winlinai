"""Check a wheel installed in a clean venv, from outside the source checkout.

Copy this script into that venv and run it there with the venv's interpreter.
Real config/history backends and the Qt offline chat must work together; merely
importing a shell that catches missing backends is not sufficient.
"""

import os
from pathlib import Path
import sys
import tempfile


def main():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    import src
    package_file = Path(src.__file__).resolve()
    if Path(sys.prefix).resolve() not in package_file.parents:
        raise RuntimeError('The smoke test must import the wheel from this virtual environment')
    from src.platform import detect_platform
    from src.platform import probes, shell_pwsh, ui_selection, wsl_bridge  # noqa: F401
    from src.knowledge_loader import available_bundled_modules
    modules = {module['id'] for module in available_bundled_modules()}
    if not {'windows-core', 'shell-powershell', 'wsl-core'} <= modules:
        raise RuntimeError('The installed wheel is missing bundled Windows knowledge')
    from PySide6 import QtWidgets
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    with tempfile.TemporaryDirectory(prefix='winlinai-smoke-home-') as user_directory:
        # Pass explicit paths so the current user's state is never modified.
        from src.config_manager import ConfigManager
        from src.qt_app import QtShell
        config = ConfigManager(str(Path(user_directory) / 'config' / 'config.json'))
        config.set('app.language', 'pt')
        if not config.flush():
            raise RuntimeError('Configuration could not be persisted')
        from src import qt_theme
        themes = set(qt_theme.available_themes())
        for expected in ('dark', 'light', 'dracula', 'solarized-dark'):
            if expected not in themes:
                raise RuntimeError(
                    'The installed wheel is missing theme: ' + expected)
        light = qt_theme.load_theme('light')
        if not light.get('colors'):
            raise RuntimeError('The installed light theme is empty')
        shell = QtShell(config, detect_platform(), history_path=Path(user_directory) / 'history.json')
        try:
            if shell.chat is None or shell.chat.offline is None or shell.history_store is None:
                raise RuntimeError('The installed Qt shell did not initialize its offline and history backends')
            shell.show()
            application.processEvents()
            if not shell.isVisible():
                raise RuntimeError('The installed Qt shell did not become visible')
            question = 'pesquisar conhecimento DNS'
            shell.chat.input.setText(question)
            shell.chat._on_send()
            application.processEvents()
            shell.history_store.flush()
            messages = shell.history_store.load_messages()
            if len(messages) != 2 or messages[0]['content'] != question or not messages[1]['content'].strip():
                raise RuntimeError('The installed offline chat did not save its question and answer')
        finally:
            shell.close()
            if shell.history_store is not None:
                shell.history_store.close()
            config.flush()
            application.processEvents()
    print('Installed wheel: Qt startup, bundled knowledge, themes, config and offline history passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
