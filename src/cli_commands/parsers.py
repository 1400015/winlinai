"""Argument parser definitions for the CLI.

Extracted from cli.py to keep the CLIApp class focused on command dispatch
and handlers.
"""

import argparse
from pathlib import Path

from ..diagnostics import PROBES


def build_parser():
    """Build and return the top-level CLI argument parser."""
    parser = argparse.ArgumentParser(
        description='Linux AI Assistant - Interface de Linha de Comandos',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  %(prog)s chat "What is my operating system?"
  %(prog)s chat --provider openrouter "Usa OpenRouter"
  %(prog)s expert "Como configurar o firewall?"
  %(prog)s capture --ocr
  %(prog)s system info
  %(prog)s system commands
  %(prog)s history
  %(prog)s stats
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Command: chat
    chat_parser = subparsers.add_parser('chat', help='Chat with the AI')
    chat_parser.add_argument('message', nargs='*', help='Message to send')
    chat_parser.add_argument('--provider', '-p', default=None,
                             help='AI provider (default: from configuration)')
    chat_parser.add_argument('--model', '-m', default=None,
                             help='Model to use')
    chat_parser.add_argument('--expert', '-e', action='store_true',
                             help='Use expert mode')
    chat_parser.add_argument('--stream', '-s', action='store_true',
                             help='Show the response as a stream')
    chat_parser.add_argument('--no-history', action='store_true',
                             help='Do not save to history')

    # Command: capture
    capture_parser = subparsers.add_parser('capture', help='Capture the screen')
    capture_parser.add_argument('--ocr', action='store_true',
                                help='Extract text from the capture')
    capture_parser.add_argument('--output', '-o', default=None,
                                help='Output file')
    capture_parser.add_argument('--window', '-w', action='store_true',
                                help='Capture the active window')

    # Command: expert
    expert_parser = subparsers.add_parser('expert', help='Expert mode')
    expert_parser.add_argument('message', nargs='*', help='Question for the expert')
    expert_parser.add_argument('--provider', '-p', default=None,
                               help='AI provider')
    expert_parser.add_argument('--model', '-m', default=None,
                               help='Model to use')

    for message_parser in (chat_parser, expert_parser):
        message_parser.add_argument('--image', type=Path, help='Select a PNG, JPEG or WebP image; show metadata and destination before sending')
        message_parser.add_argument('--send-image', action='store_true', help='Explicitly send the selected image with this question')
        message_parser.add_argument('--documents', action='store_true', help='Retrieve passages from explicitly indexed local documents')
        message_parser.add_argument('--send-document-context', action='store_true', help='Explicitly send matching document passages to the configured model')
        selection = message_parser.add_mutually_exclusive_group()
        selection.add_argument('--session', help='Conversation identifier to resume')
        selection.add_argument('--new-session', action='store_true', help='Start a new conversation')
        source = message_parser.add_mutually_exclusive_group()
        source.add_argument('--stdin', action='store_true', help='Read text from stdin (up to 64 KiB)')
        source.add_argument('--input', type=Path, help='Read a UTF-8 text file (up to 64 KiB)')
    expert_parser.add_argument('--no-history', action='store_true', help='Do not save the exchange')
    expert_parser.add_argument('--stream', action='store_true', help='Stream the answer')

    sessions = subparsers.add_parser('sessions', help='Manage independent conversations')
    actions = sessions.add_subparsers(dest='session_action', required=True)
    actions.add_parser('list', help='List conversations, including archived ones')
    new = actions.add_parser('new', help='Create and select a conversation')
    new.add_argument('title', nargs='?', default='New conversation')
    for action in ('use', 'archive', 'restore', 'delete'):
        action_parser = actions.add_parser(action)
        action_parser.add_argument('id', help='Conversation identifier')
    rename = actions.add_parser('rename')
    rename.add_argument('id')
    rename.add_argument('title')
    search = actions.add_parser('search')
    search.add_argument('query')
    export = actions.add_parser('export')
    export.add_argument('--session')
    export.add_argument('--format', choices=('markdown', 'json'), default='markdown')
    export.add_argument('--output', type=Path, help='New output file (existing files are never overwritten)')
    imported = actions.add_parser('import', help='Import a versioned JSON or application Markdown conversation')
    imported.add_argument('path', type=Path)
    import_approval = imported.add_mutually_exclusive_group()
    import_approval.add_argument('--preview', action='store_true', help='Validate and show the conversation without importing')
    import_approval.add_argument('--yes', action='store_true', help='Approve the reviewed import')
    documents = subparsers.add_parser('documents', help='Manage selected local document snapshots without a model service')
    document_actions = documents.add_subparsers(dest='document_action', required=True)
    add_documents = document_actions.add_parser('add', help='Index only the files explicitly named')
    add_documents.add_argument('paths', type=Path, nargs='+')
    document_actions.add_parser('list')
    search_documents = document_actions.add_parser('search', help='Show local passages with source references')
    search_documents.add_argument('query', nargs='+')
    remove_document = document_actions.add_parser('remove')
    remove_document.add_argument('id')
    reindex_documents = document_actions.add_parser('reindex', help='Explicitly refresh selected snapshots')
    reindex_documents.add_argument('ids', nargs='*')
    clear_documents = document_actions.add_parser('clear')
    clear_documents.add_argument('--yes', action='store_true', help='Confirm removing all local snapshots')
    mode = subparsers.add_parser('mode', help='Show or select assistance mode')
    mode.add_argument('value', nargs='?', choices=('auto', 'offline', 'local', 'remote'))
    mode.add_argument('--check', action='store_true', help='Test the local model connection')
    subparsers.add_parser('local-models', help='List models installed on the configured local server')
    knowledge = subparsers.add_parser('knowledge', help='Search bundled guides without any AI service')
    knowledge.add_argument('query', nargs='+')
    subparsers.add_parser('knowledge-verify', help='Validate bundled YAML schemas and references offline')
    audit_parser = subparsers.add_parser('actions', help='Review operations in the current conversation')
    audit_actions = audit_parser.add_subparsers(dest='audit_action', required=True)
    audit_actions.add_parser('list')
    audit_actions.add_parser('show').add_argument('id')

    trials = subparsers.add_parser(
        'trials', help='Record local test cases and review evidence without AI',
    )
    trial_actions = trials.add_subparsers(dest='trial_action', required=True)
    trial_start = trial_actions.add_parser('start', help='Start a local test run')
    trial_start.add_argument('--title', required=True, help='Name of the test run')
    trial_start.add_argument('--environment', required=True, help='Test environment identifier')
    trial_start.add_argument('--build', default='', help='Commit or package build under test')
    trial_start.add_argument('--type', dest='test_type',
                             choices=('physical', 'vm', 'wsl', 'fixture', 'unknown'),
                             default='unknown', help='Kind of environment under test')
    trial_actions.add_parser('status', help='Show the selected test run')
    trial_actions.add_parser('list', help='List locally recorded test runs')
    trial_use = trial_actions.add_parser('use', help='Select a locally recorded test run')
    trial_use.add_argument('id', help='Test run identifier')
    trial_begin = trial_actions.add_parser('begin', help='Begin a case in the selected run')
    trial_begin.add_argument('case_id', help='Case identifier from the test protocol')
    trial_begin.add_argument('--session', help='Conversation to associate; defaults to the active conversation')
    trial_begin.add_argument('--variant', default='', help='Case variant or repetition')
    trial_begin.add_argument('--notes', default='', help='Initial observations')
    trial_end = trial_actions.add_parser('end', help='Record a result and collect case evidence')
    trial_end.add_argument('--result', required=True,
                           choices=('PASS', 'FAIL', 'BLOCKED', 'NOT_RUN', 'N/A'))
    trial_end.add_argument('--notes', default='', help='Expected and observed behavior')
    trial_end.add_argument('--operation', help='Restrict action evidence to one operation')
    trial_end.add_argument('--logs', action='store_true',
                           help='Also collect a bounded application log excerpt; review before sharing')
    trial_actions.add_parser('finish', help='Finish the run after closing the current case')
    trial_preview = trial_actions.add_parser('preview', help='Review all content eligible for export')
    trial_preview.add_argument('--output', type=Path,
                               help='New private preview file; existing files are never replaced')
    trial_attach = trial_actions.add_parser('attach', help='Add one explicitly selected evidence file')
    trial_attach.add_argument('path', type=Path)
    trial_exclude = trial_actions.add_parser('exclude', help='Exclude an attachment from export')
    trial_exclude.add_argument('id', help='Attachment identifier')
    trial_export = trial_actions.add_parser('export', help='Export a reviewed run as a new local ZIP')
    trial_export.add_argument('--output', type=Path, required=True, help='New ZIP destination')
    trial_export.add_argument('--reviewed', action='store_true',
                              help='Confirm that trials preview content and attachments have been reviewed')

    diagnose = subparsers.add_parser('diagnose', help='Prepare a local, redacted diagnostic report without AI')
    diagnose.add_argument('symptom', nargs='*')
    diagnostic_input = diagnose.add_mutually_exclusive_group()
    diagnostic_input.add_argument('--input', type=Path, help='UTF-8 log excerpt, up to 64 KiB')
    diagnostic_input.add_argument('--stdin', action='store_true')
    diagnose.add_argument('--collect', action='append', choices=tuple(PROBES), default=[],
                          help='Explicitly collect one fixed local read probe (repeatable)')
    diagnose.add_argument('--format', choices=('markdown', 'json'), default='markdown')
    diagnose.add_argument('--output', type=Path, help='New private export file; existing files are never replaced')
    changes = subparsers.add_parser('changes', help='Review approved file writes and recover their contents')
    change_actions = changes.add_subparsers(dest='change_action', required=True)
    change_list = change_actions.add_parser('list')
    change_list.add_argument('--archived', action='store_true', help='Also list archived changes')
    change_archive = change_actions.add_parser('archive', help='Preserve completed changes and free journal capacity')
    change_archive.add_argument('--yes', action='store_true', help='Approve moving completed records to a private archive')
    for action in ('show', 'restore'):
        change_parser = change_actions.add_parser(action)
        change_parser.add_argument('id')
        if action == 'restore':
            change_parser.add_argument('--yes', action='store_true', help='Approve recovery after reviewing changes show <id>')

    # Command: system
    system_parser = subparsers.add_parser('system', help='System information')
    system_subparsers = system_parser.add_subparsers(dest='system_command')

    # system info
    system_subparsers.add_parser('info', help='Full system information')
    system_subparsers.add_parser('context', help='Observed system components and evidence (JSON)')

    # system commands
    system_subparsers.add_parser('commands', help='List of allowed commands')

    # system processes
    system_subparsers.add_parser('processes', help='List of processes')

    # system network
    system_subparsers.add_parser('network', help='Network information')

    # system exec
    exec_parser = system_subparsers.add_parser('exec', help='Run a command')
    exec_parser.add_argument('command', nargs='+', help='Command to run')

    # Command: history
    history_parser = subparsers.add_parser('history', help='View conversation history')
    history_parser.add_argument('history_action', nargs='?', choices=('recover',),
                                help='Back up the complete history file privately and start fresh')
    history_parser.add_argument('--yes', action='store_true',
                                help='Approve history recover after reading the error and preserving the original')
    history_parser.add_argument('--limit', '-n', type=int, default=20,
                                help='Number of messages to show')
    history_parser.add_argument('--clear', action='store_true',
                                help='Clear history')

    # Command: stats
    stats_parser = subparsers.add_parser('stats', help='Usage statistics')
    stats_parser.add_argument('--reset', action='store_true',
                              help='Reset statistics')

    # Command: config
    config_parser = subparsers.add_parser('config', help='Configuration')
    config_subparsers = config_parser.add_subparsers(dest='config_command')

    # config list
    config_subparsers.add_parser('list', help='List the current configuration')

    # config set
    set_parser = config_subparsers.add_parser('set', help='Set a configuration value')
    set_parser.add_argument('key', help='Configuration key (e.g. api.default_provider)')
    set_parser.add_argument('value', help='Value to set')

    # config get
    get_parser = config_subparsers.add_parser('get', help='Get a configuration value')
    get_parser.add_argument('key', help='Configuration key')

    # Command: providers
    subparsers.add_parser('providers', help='List the available AI providers')

    # Command: tokens
    tokens_parser = subparsers.add_parser('tokens', help='Token management')
    tokens_subparsers = tokens_parser.add_subparsers(dest='tokens_command')
    tokens_subparsers.add_parser('usage', help='Show token usage')
    tokens_subparsers.add_parser('reset', help='Reset the token count')

    return parser
