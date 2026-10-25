#!/usr/bin/env python3
"""
Linux AI Assistant - Interface de Linha de Comandos (CLI)

Uso:
    python -m src.cli chat "What is my operating system?"
    python -m src.cli capture --ocr
    python -m src.cli expert "Como configurar o iptables?"
    python -m src.cli system info
    python -m src.cli --help
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict

from .config_manager import ConfigManager
from .ai_client import AIClient
from .system_utils import SystemUtils
from . import offline_assistant
from .i18n import get_language, set_language_from_config
from .history_store import HistoryStore
from .local_knowledge import PROCEDURE_BY_ID, search_procedures, render_procedure
from .conversation_actions import ConversationActions

logger = logging.getLogger(__name__)



# _ActionResult is defined in cli_commands.handlers and re-exported here for backward compatibility
from .cli_commands.handlers import _ActionResult  # noqa: F401

# Re-exports for backward compatibility with tests that patch these names on src.cli
import getpass  # noqa: F401
import select  # noqa: F401
from .device_actions import (  # noqa: F401
    choose_numbered, collect_printers, collect_scanners, collect_wifi,
    confirmed, connect_wifi, format_command_offer, printer_add_argv,
    queue_name_for, split_offer, wifi_needs_password,
)
from .change_journal import ChangeJournal  # noqa: F401
from .document_store import DocumentStore  # noqa: F401




class CLIApp:
    """Linux AI Assistant CLI application"""

    def __init__(self):
        self.config = ConfigManager()
        set_language_from_config(self.config)
        self.ai_client = AIClient(self.config)
        self.system_utils = SystemUtils(self.config)
        # Local answers when there is no key or no connection.
        self.offline = offline_assistant.OfflineAssistant(
            self.system_utils, self.config
        )
        # Load the shared history (written by the GUI too) so saving it back
        # never wipes entries from other sessions.
        self.history_store = None
        self._pending_exchanges = []
        self.conversation_history = self._load_history()
        self.expert_mode = False
        from .system_context import detect_system_context
        self.system_context = detect_system_context(self.offline.distro)
        self.offline.set_system_context(self.system_context)
        self.actions = ConversationActions(self._store(), self.offline.distro.pkg_manager, context=self.system_context,
                                           independent_display_watchdog=self.config.get('app.display_independent_watchdog', False))

    @staticmethod
    def parse_args(argv=None):
        """Parse the command-line arguments."""
        from .cli_commands.parsers import build_parser
        parser = build_parser()
        return parser.parse_args(argv)

    def run(self, args=None):
        try:
            return self._run_command(args) if args is not None else self._run_command()
        finally:
            if self.history_store is not None:
                self.history_store.close()
            self.config.flush()
            self.ai_client.flush_usage()

    def _run_command(self, args=None):
        """Run the CLI application.

        Devolve o exit code do comando (0 = sucesso): scripts que encadeiam
        o CLI (`capture --ocr && ...`) precisam de detetar falhas — antes,
        TODAS as falhas esperadas saíam com 0.
        """
        args = self.parse_args() if args is None else args

        if not args.command:
            self.print_help()
            return 0

        if args.command == 'sessions':
            return self.handle_sessions(args)
        if args.command == 'documents':
            return self.handle_documents(args)
        if args.command == 'diagnose':
            return self.handle_diagnose(args)
        if args.command == 'changes':
            return self.handle_changes(args)
        if args.command == 'trials':
            return self.handle_trials(args)
        if args.command == 'mode':
            if args.value:
                self.config.set_assistance_mode(args.value)
                self.config.flush()
            status = self.ai_client.provider_status(check_connection=args.check)
            print(json.dumps(status.__dict__, ensure_ascii=False, indent=2))
            return 1 if status.state in ('blocked', 'unreachable', 'model_missing', 'error') else 0
        if args.command == 'local-models':
            for model in self.ai_client.list_local_models():
                print(model)
            return 0
        if args.command == 'knowledge-verify':
            from .knowledge_loader import bundled_modules
            print(json.dumps({'schema': '0.1', 'modules': [item['id'] for item in bundled_modules()],
                              'validation': 'structure_and_references_only'}, indent=2))
            return 0
        if args.command == 'actions':
            try:
                print(self.actions.audit.render(self._store().active_session_id, args.id if args.audit_action == 'show' else None))
                return 0
            except (OSError, ValueError):
                print('Cannot read the operation audit.')
                return 1
        if args.command == 'knowledge':
            query = ' '.join(args.query)
            exact = PROCEDURE_BY_ID.get(query)
            matches = ((exact,) if exact and exact.applies_to(self.offline.distro)
                       else search_procedures(query, self.offline.distro, limit=5))
            result = '\n\n'.join(render_procedure(item, get_language(), self.offline.distro) for item in matches)
            print(result or ('Nenhum guia aplicável encontrado.' if get_language() == 'pt' else 'No applicable guide found.'))
            return 0 if result else 1

        # Process command
        if args.command == 'chat':
            return self.handle_chat(args)
        elif args.command == 'capture':
            return self.handle_capture(args)
        elif args.command == 'expert':
            return self.handle_expert(args)
        elif args.command == 'system':
            return self.handle_system(args)
        elif args.command == 'history':
            return self.handle_history(args)
        elif args.command == 'stats':
            return self.handle_stats(args)
        elif args.command == 'config':
            return self.handle_config(args)
        elif args.command == 'providers':
            return self.handle_providers(args)
        elif args.command == 'tokens':
            return self.handle_tokens(args)
        else:
            self.print_help()
            return 0

    def print_help(self):
        """Show the help text."""
        print("""
Linux AI Assistant - Command-Line Interface

Available commands:
  chat [message]            - Chat with the AI
  capture [options]         - Capture the screen
  expert [message]          - Expert mode
  system [subcommand]       - System information
  history [options]         - View conversation history
  sessions [subcommand]     - Manage, search and export conversations
  knowledge [query]         - Search bundled local guides
  diagnose [symptom]        - Prepare a local diagnostic report
  changes [subcommand]     - Review or recover approved file writes
  trials [subcommand]      - Record test cases and export reviewed local evidence
  mode [value]              - Show/select assistance mode
  local-models              - List installed models on the local server
  stats [options]           - Usage statistics
  config [subcommand]       - Configuration
  providers                 - List the AI providers
  tokens [subcommand]       - Token management

Use --help with any command for more information.

Examples:
  python -m src.cli chat "What is my operating system?"
  python -m src.cli capture --ocr
  python -m src.cli system info
        """)

    @staticmethod
    def _history_file() -> Path:
        return Path.home() / ".config" / "linux_ai_assistant" / "history.json"

    def _store(self):
        if self.history_store is None:
            self.history_store = HistoryStore(self._history_file())
            self.history_store.list_sessions()
        return self.history_store

    def _load_history(self):
        self.offline.restore_diagnostic(self._store().get_diagnostic_state())
        return self._store().load_entries()

    def _prepare_conversation(self, args):
        if getattr(args, 'session', None):
            self._store().select_session(args.session)
        elif getattr(args, 'new_session', False):
            self._store().create_session()
        else:
            return
        self.conversation_history = self._store().load_entries()
        self._pending_exchanges = []
        self.offline.restore_diagnostic(self._store().get_diagnostic_state())

    @staticmethod
    def _message_from_args(args):
        message = ' '.join(args.message)
        extra = ''
        if getattr(args, 'input', None):
            with args.input.open('rb') as stream:
                data = stream.read(65537)
            if len(data) > 65536:
                raise ValueError('Input file exceeds 64 KiB')
            extra = data.decode('utf-8')
        elif getattr(args, 'stdin', False):
            extra = sys.stdin.read(65537)
        message = '\n\n'.join(part for part in (message, extra) if part).strip()
        if len(message.encode('utf-8')) > 65536:
            raise ValueError('Input exceeds 64 KiB')
        if not message:
            raise ValueError('Provide a message, --stdin or --input')
        return message

    def handle_diagnose(self, args):
        from .cli_commands import handlers
        return handlers.handle_diagnose(self, args)

    def _trial_recorder(self):
        from .cli_commands import handlers
        return handlers._trial_recorder(self)

    def handle_trials(self, args):
        from .cli_commands import handlers
        return handlers.handle_trials(self, args)

    def handle_changes(self, args):
        from .cli_commands import handlers
        return handlers.handle_changes(self, args)

    def handle_sessions(self, args):
        from .cli_commands import handlers
        return handlers.handle_sessions(self, args)

    def handle_documents(self, args):
        from .cli_commands import handlers
        return handlers.handle_documents(self, args)

    def _build_request_messages(self, message: str):
        from .cli_commands import handlers
        return handlers._build_request_messages(self, message)

    def _record_exchange(self, message: str, response_text: str):
        from .cli_commands import handlers
        return handlers._record_exchange(self, message, response_text)

    def _run_offline(self, message: str):
        from .cli_commands import handlers
        return handlers._run_offline(self, message)

    def _offer_model_action(self, message: str):
        from .cli_commands import handlers
        return handlers._offer_model_action(self, message)

    def _offer_action(self, reply):
        from .cli_commands import handlers
        return handlers._offer_action(self, reply)

    def _print_commands(self, commands):
        from .cli_commands import handlers
        return handlers._print_commands(self, commands)

    def _ask(self, prompt: str) -> str:
        from .cli_commands import handlers
        return handlers._ask(self, prompt)

    def _confirm_and_run(self, commands):
        from .cli_commands import handlers
        return handlers._confirm_and_run(self, commands)

    def _choose_wifi(self):
        from .cli_commands import handlers
        return handlers._choose_wifi(self)

    def _choose_printer(self, commands):
        from .cli_commands import handlers
        return handlers._choose_printer(self, commands)

    def _choose_scanner(self, commands):
        from .cli_commands import handlers
        return handlers._choose_scanner(self, commands)

    def _run_conversational_action(self, message, args):
        from .cli_commands import handlers
        return handlers._run_conversational_action(self, message, args)

    def handle_chat(self, args):
        from .cli_commands import handlers
        return handlers.handle_chat(self, args)

    def handle_capture(self, args):
        from .cli_commands import handlers
        return handlers.handle_capture(self, args)

    def handle_expert(self, args):
        from .cli_commands import handlers
        return handlers.handle_expert(self, args)

    def handle_system(self, args):
        from .cli_commands import handlers
        return handlers.handle_system(self, args)

    def _print_system_info(self, info: Dict):
        from .cli_commands import handlers
        return handlers._print_system_info(self, info)

    def handle_history(self, args):
        from .cli_commands import handlers
        return handlers.handle_history(self, args)

    def _render_token_usage(self, title: str = "USAGE STATISTICS"):
        from .cli_commands import handlers
        return handlers._render_token_usage(self, title)

    def handle_stats(self, args):
        from .cli_commands import handlers
        return handlers.handle_stats(self, args)

    def handle_config(self, args):
        from .cli_commands import handlers
        return handlers.handle_config(self, args)

    @classmethod
    def _masked_config_value(cls, value, key=''):
        from .cli_commands.handlers import _masked_config_value as _handler
        return _handler(value, key)

    def _print_config(self, config: Dict, indent: int = 0):
        from .cli_commands import handlers
        return handlers._print_config(self, config, indent)

    def handle_providers(self, args):
        from .cli_commands import handlers
        return handlers.handle_providers(self, args)

    def _provider_key_status(self, provider):
        from .cli_commands import handlers
        return handlers._provider_key_status(self, provider)

    def handle_tokens(self, args):
        from .cli_commands import handlers
        return handlers.handle_tokens(self, args)

    def _get_context_message(self, query=''):
        from .cli_commands import handlers
        return handlers._get_context_message(self, query)

    def _save_history(self):
        from .cli_commands import handlers
        return handlers._save_history(self)




def main():
    """Main entry point for the CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    # File logging só no arranque real (não no import do pacote)
    from . import setup_file_logging
    setup_file_logging()
    app = None
    try:
        args = CLIApp.parse_args()
        # Recovery must remain available when normal initialization cannot read
        # a large, damaged or newer-format history. Do not load configuration,
        # instantiate a provider or interpret the unknown document first.
        if args.command == 'history' and args.history_action == 'recover':
            if not args.yes:
                print('history recover --yes is required. The complete original file will be preserved privately.', file=sys.stderr)
                sys.exit(1)
            backup = HistoryStore.recover_file(CLIApp._history_file(), confirmed=True)
            print(str(backup))
            sys.exit(0)
        app = CLIApp()
        code = app.run(args)
        sys.exit(code if isinstance(code, int) else 0)
    except KeyboardInterrupt:
        print("\n\n✓ Exiting...")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        if getattr(e, 'recovery_backup', None) is not None:
            print('Original history preserved at: {}'.format(getattr(e, "recovery_backup", None)))
        sys.exit(1)
    finally:
        if app is not None and getattr(app, 'actions', None) is not None:
            app.actions.close()


if __name__ == "__main__":
    main()
