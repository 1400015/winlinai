"""Command handlers for the CLI.

Extracted from cli.py to keep the CLIApp class focused on initialization,
argument parsing and command dispatch. Each function receives the CLIApp
instance as its first argument (``app``).
"""

import sys
import json
import time
import getpass
import logging
import select
from typing import Any, Optional, Dict

from .. import offline_assistant
from ..ai_client import AIProviderError, AIImageRequestError, AIRequestCancelled, AIResponseLimitError
from ..device_actions import (
    choose_numbered, confirmed, format_command_offer, printer_add_argv,
    queue_name_for, split_offer, wifi_needs_password,
)
from ..i18n import _, get_language
from ..assistant_context import build_system_message
from ..conversation_io import read_conversation, write_conversation
from ..diagnostics import build_report, export_report
from ..document_context import MAX_DOCUMENT_CONTEXT_CHARS, display_document_context, with_document_context
from ..image_attachments import prepare_image

logger = logging.getLogger(__name__)


def _cli_attr(name):
    """Look up a patchable name on the src.cli module (test compatibility)."""
    cli = sys.modules.get('src.cli')
    if cli is not None and hasattr(cli, name):
        return getattr(cli, name)
    raise AttributeError(name)


class _ActionResult(str):
    """Keep action text compatible with callers while carrying its outcome.

    No action (including a non-interactive proposal) and user cancellation
    are not execution failures. Only an attempted operation that fails gives
    the chat command a nonzero exit code.
    """

    status: str

    def __new__(cls, text: str = "", status: str = "none") -> "_ActionResult":
        result = super().__new__(cls, text)
        result.status = status
        return result

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "failed" else 0


def handle_diagnose(app, args):
    pasted = ''
    if args.input:
        if not args.input.is_file():
            raise ValueError('Input must be a regular file')
        with args.input.open('rb') as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError('Diagnostic input exceeds 64 KiB')
        pasted = data.decode('utf-8')
    elif args.stdin:
        pasted = sys.stdin.read(65537)
    report = build_report(' '.join(args.symptom), pasted, app.offline.distro, get_language(),
                          args.collect, app.system_utils, session_id=app._store().active_session_id)
    content = export_report(report, args.format)
    if args.output:
        write_conversation(args.output, content)
        print(str(args.output))
    else:
        print(content)
    return 0

def _trial_recorder(app):
    from ..trial_recorder import make_recorder
    return make_recorder(app._store(), app.config, app.offline.distro)

def handle_trials(app, args):
    """Explicit local collection, with logs and sharing review opt-in."""
    try:
        recorder = app._trial_recorder()
        action = args.trial_action
        if action == 'start':
            run = recorder.start(args.title, args.environment,
                                 build_ref=args.build, test_type=args.test_type)
            print(run['id'])
        elif action == 'status':
            print(json.dumps(recorder.current(), ensure_ascii=False, indent=2))
        elif action == 'list':
            print(json.dumps(recorder.list_runs(), ensure_ascii=False, indent=2))
        elif action == 'use':
            print(json.dumps(recorder.select(args.id), ensure_ascii=False, indent=2))
        elif action == 'begin':
            session_id = args.session or app._store().active_session_id
            print(json.dumps(recorder.begin_case(
                args.case_id, session_id, variant=args.variant,
                interface='cli', notes=args.notes,
            ), ensure_ascii=False, indent=2))
        elif action == 'end':
            print(json.dumps(recorder.end_case(
                args.result, notes=args.notes, operation_id=args.operation,
                collect_logs=args.logs,
            ), ensure_ascii=False, indent=2))
        elif action == 'finish':
            print(json.dumps(recorder.finish(), ensure_ascii=False, indent=2))
        elif action == 'preview':
            content = recorder.preview()
            if args.output:
                write_conversation(args.output, content)
                print(str(args.output))
            else:
                print(content)
        elif action == 'attach':
            print(json.dumps(recorder.attach(args.path), ensure_ascii=False, indent=2))
        elif action == 'exclude':
            recorder.exclude_attachment(args.id)
            print(args.id)
        elif action == 'export':
            if not args.reviewed:
                print('Review trials preview and selected attachments first; '
                      '--reviewed is required to export.', file=sys.stderr)
                return 1
            print(str(recorder.export(args.output, reviewed=True)))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print('Cannot record or export the test run: {}'.format(exc), file=sys.stderr)
        return 1

def handle_changes(app, args):
    journal = _cli_attr('ChangeJournal')()
    def allowed():
        return app.config.get('permissions.allowed_edit_dirs', [])
    if args.change_action == 'list':
        print(json.dumps(journal.list_changes(include_archived=getattr(args, 'archived', False)), ensure_ascii=False, indent=2))
        return 0
    if args.change_action == 'archive':
        if not args.yes:
            print('--yes is required to preserve completed changes in a private archive.', file=sys.stderr)
            return 1
        print(json.dumps(journal.archive(), ensure_ascii=False, indent=2))
        return 0
    if args.change_action == 'show':
        record = next((item for item in journal.list_changes(include_archived=True) if item['id'] == args.id), None)
        if record is None:
            raise KeyError('Unknown change')
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    if not args.yes:
        print('Review changes show <id> first; --yes is required to approve recovery.', file=sys.stderr)
        return 1
    print(json.dumps(journal.restore(args.id, allowed), ensure_ascii=False, indent=2))
    return 0

def handle_sessions(app, args):
    store = app._store()
    action = args.session_action
    if action == 'list':
        for session in store.list_sessions(include_archived=True):
            marker = '*' if session['id'] == store.active_session_id else ' '
            archived = ' [archived]' if session['archived'] else ''
            print('{} {}  {} ({} messages){}'.format(marker, session['id'], session['title'], session['message_count'], archived))
    elif action == 'new':
        print(store.create_session(args.title)['id'])
    elif action == 'use':
        print(store.select_session(args.id)['id'])
    elif action == 'rename':
        store.rename_session(args.id, args.title)
    elif action in ('archive', 'restore'):
        store.archive_session(args.id, action == 'archive')
    elif action == 'delete':
        store.delete_session(args.id)
    elif action == 'search':
        print(json.dumps(store.search(args.query, include_archived=True), ensure_ascii=False, indent=2))
    elif action == 'export':
        content = store.export_session(args.session, args.format)
        if args.output:
            write_conversation(args.output, content)
            print(args.output)
        else:
            print(content)
    elif action == 'import':
        text = read_conversation(args.path)
        preview = store.preview_import(text)
        if getattr(args, 'preview', False):
            print(preview['preview_text'])
            return 0
        if not getattr(args, 'yes', False):
            print(preview['preview_text'])
            print(_("Review this conversation, then repeat the import with --yes."))
            return 1
        print(store.import_session(text)['id'])
    return 0

def handle_documents(app, args):
    store = None
    try:
        store = _cli_attr('DocumentStore')()
        action = args.document_action
        if action == 'add':
            print(json.dumps(store.add(args.paths), ensure_ascii=False, indent=2))
        elif action == 'list':
            print(json.dumps(store.list_documents(), ensure_ascii=False, indent=2))
        elif action == 'search':
            result = store.context(' '.join(args.query), max_chars=MAX_DOCUMENT_CONTEXT_CHARS)
            print(display_document_context(result) if result else _("No matching passages in the selected documents."))
            return 0 if result else 1
        elif action == 'remove':
            if not store.remove(args.id):
                print(_("Document snapshot not found."), file=sys.stderr)
                return 1
            print(_("Document snapshot removed."))
        elif action == 'reindex':
            print(json.dumps(store.reindex(args.ids or None), ensure_ascii=False, indent=2))
        elif action == 'clear':
            if not args.yes:
                print(_("Use documents clear --yes to remove all local snapshots."))
                return 1
            store.clear()
            print(_("All document snapshots removed."))
        return 0
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()

def _build_request_messages(app, message: str):
    """Assemble the request context: system prompt + capped history + message."""
    context = app._get_context_message(message)
    # Cap the context the same way the GUI does - never re-send the whole
    # conversation on every turn.
    try:
        max_messages = max(2, min(500, int(app.config.get("context.max_messages", 20))))
    except (TypeError, ValueError):
        max_messages = 20
    history = [
        {"role": m.get("role"), "content": m.get("content", "")}
        for m in app.conversation_history[-max_messages:]
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
    ]
    try:
        max_chars = max(1000, min(400000, int(app.config.get('context.max_chars', 12000))))
    except (TypeError, ValueError):
        max_chars = 12000
    total = sum(len(item['content']) for item in history) + len(message)
    while history and total > max_chars:
        total -= len(history.pop(0)['content'])
    full_history = ([context] + history) if context else history
    full_history.append({"role": "user", "content": message})
    return full_history

def _record_exchange(app, message: str, response_text: str):
    """Append a user/assistant exchange to the in-memory history."""
    exchange = [
        {'role': 'user', 'content': message, 'timestamp': time.time()},
        {'role': 'assistant', 'content': response_text, 'timestamp': time.time()},
    ]
    app.conversation_history.extend(exchange)
    app._pending_exchanges.extend(exchange)
    app.conversation_history = app.conversation_history[-1000:]

def _run_offline(app, message: str) -> _ActionResult:
    """Answer from local knowledge and, on a terminal, offer to run the action."""
    reply = app.offline.handle(message, get_language())
    print(f"\n[OFFLINE]\n{reply.text}\n")
    extra = app._offer_action(reply)
    if extra:
        return _ActionResult(reply.text + "\n\n" + extra, extra.status)
    return _ActionResult(reply.text, extra.status)

def _offer_model_action(app, message: str) -> _ActionResult:
    """Offer a catalog action for the user's sentence, not for model text."""
    propose = getattr(app.offline, "propose", None)
    if not callable(propose):
        return _ActionResult()
    try:
        reply = propose(message, get_language())
    except Exception as exc:
        logger.error("Could not prepare a confirmed action: %s", exc, exc_info=True)
        return _ActionResult()
    interaction, commands = split_offer(reply)
    if not interaction and not commands:
        return _ActionResult()
    if getattr(reply, "text", ""):
        print(f"\n{reply.text}\n")
    return app._offer_action(reply)

def _offer_action(app, reply) -> _ActionResult:
    """Print the exact argv. Run it only after a confirmation on a TTY.

    A pipe or a unit test is not a terminal: the commands are shown and
    nothing is scanned or executed.
    """
    interaction, commands = split_offer(reply)
    if interaction:
        if not sys.stdin.isatty():
            app._print_commands(commands)
            print(_("This step needs an interactive terminal."))
            return _ActionResult()
        if interaction == "wifi":
            return app._choose_wifi()
        if interaction == "printer":
            return app._choose_printer(commands)
        if interaction == "scanner":
            return app._choose_scanner(commands)
        return _ActionResult()
    if not commands:
        return _ActionResult()
    app._print_commands(commands)
    if not sys.stdin.isatty():
        print(_("This step needs an interactive terminal."))
        return _ActionResult()
    return app._confirm_and_run(commands)

def _print_commands(app, commands):
    if not commands:
        return
    print(format_command_offer(
        commands,
        _("These changes need administrator rights (pkexec):"),
        _("Run suggested commands?"),
    ))
    print()

def _ask(app, prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""

def _confirm_and_run(app, commands) -> _ActionResult:
    if not commands:
        return _ActionResult()
    if not confirmed(app._ask(_("Run these commands? [y/N] "))):
        print(_("Cancelled"))
        return _ActionResult(status="cancelled")
    chunks = []
    status = "success"
    for command in commands:
        ok, output = offline_assistant.OfflineAssistant.run_command(command)
        line = f"$ {command.display()}"
        detail = output or (_("Done.") if ok else _("Failed."))
        print(line)
        print(detail)
        chunks.append(line)
        chunks.append(detail)
        if not ok:
            status = "failed"
            break
    return _ActionResult("\n".join(chunks), status)

def _choose_wifi(app) -> _ActionResult:
    networks, error = _cli_attr('collect_wifi')()
    if not networks:
        text = error or _("No Wi-Fi networks found.")
        print(text)
        return _ActionResult(text, "failed" if error else "none")
    index = choose_numbered(
        networks, app._ask, sys.stdout.write,
        lambda network: (
            f"{network.ssid}  {network.signal}%  {network.security or '--'}"
        ),
        prompt=_("Number (Enter cancels): "),
    )
    if index is None:
        print(_("Cancelled"))
        return _ActionResult(status="cancelled")
    network = networks[index]
    secret = ""
    if wifi_needs_password(network):
        try:
            secret = getpass.getpass(_("Password: "))
        except EOFError:
            secret = ""
        if not secret:
            print(_("Cancelled"))
            return _ActionResult(status="cancelled")
    ok, output = _cli_attr('connect_wifi')(network.ssid, secret or None)
    secret = ""
    if ok:
        text = _("Connected to {ssid}.").format(ssid=network.ssid)
    else:
        text = _("Could not connect to {ssid}.").format(ssid=network.ssid)
        if output:
            text = text + "\n" + output
    print(text)
    return _ActionResult(text, "success" if ok else "failed")

def _choose_printer(app, commands) -> _ActionResult:
    devices, error = _cli_attr('collect_printers')()
    if not devices:
        if commands:
            app._print_commands(commands)
            return app._confirm_and_run(commands)
        text = error or _("No printers found.")
        print(text)
        return _ActionResult(text, "failed" if error else "none")
    index = choose_numbered(
        devices, app._ask, sys.stdout.write,
        lambda device: device.uri + ("" if device.driverless else " (driver)"),
        prompt=_("Number (Enter cancels): "),
    )
    if index is None:
        print(_("Cancelled"))
        return _ActionResult(status="cancelled")
    device = devices[index]
    default = queue_name_for(device.uri)
    typed = app._ask(_("Queue name [{name}]: ").format(name=default)).strip()
    try:
        argv = printer_add_argv(typed or default, device.uri)
    except ValueError as exc:
        print(exc)
        return _ActionResult(str(exc), "failed")
    command = offline_assistant.Command(
        argv=argv, privileged=True, description=f"Add printer {argv[2]}",
    )
    app._print_commands([command])
    return app._confirm_and_run([command])

def _choose_scanner(app, commands) -> _ActionResult:
    devices, error = _cli_attr('collect_scanners')()
    if devices:
        lines = [f"{item.device} — {item.description}" for item in devices]
        text = "\n".join(lines)
        print(text)
        return _ActionResult(text, "success")
    if commands:
        app._print_commands(commands)
        return app._confirm_and_run(commands)
    text = error or _("No scanners found.")
    print(text)
    return _ActionResult(text, "failed" if error else "none")

def _run_conversational_action(app, message, args):
    engine = getattr(app, 'actions', None)
    if engine is None:
        return None
    reply = engine.handle(
        message, app._store().active_session_id, get_language(),
        can_execute=bool(sys.stdin.isatty() and not getattr(args, 'stdin', False)
                         and not getattr(args, 'input', None)),
        persist_choices=not args.no_history,
    )
    if reply is None:
        return None
    print("\n" + reply.text + "\n")
    if reply.change is not None:
        change = reply.change
        try:
            print(_("Keep this display change? [y/N] "), end='', flush=True)
            readable, writable, exceptional = select.select([sys.stdin], [], [], max(0, change.remaining_seconds))
            keep = bool(readable and confirmed(sys.stdin.readline()))
            ok, detail = change.confirm() if keep else change.revert()
        except (OSError, ValueError, KeyboardInterrupt):
            ok, detail = change.revert()
        print(detail)
        reply.text += "\n\n" + detail
        reply.status = "done" if ok else "failed"
    if not args.no_history:
        app._record_exchange(message, reply.text)
        app._save_history()
    return reply.exit_code

def handle_chat(app, args):
    """Process the chat command. Devolve exit code (0 sucesso, 1 falha)."""
    image_path = getattr(args, 'image', None)
    use_documents = bool(getattr(args, 'documents', False))
    if getattr(args, 'send_image', False) and image_path is None:
        print(_("Choose an image with --image before using --send-image."), file=sys.stderr)
        return 1
    if getattr(args, 'send_document_context', False) and not use_documents:
        print(_("Use --documents before approving document context."), file=sys.stderr)
        return 1
    if image_path is not None and not getattr(args, 'message', None) and not getattr(args, 'stdin', False) and not getattr(args, 'input', None):
        args.message = [_("Describe this image.")]
    message = app._message_from_args(args)
    images: tuple[Any, ...] = ()
    document_context = ''
    try:
        if image_path is not None:
            image = prepare_image(image_path)
            provider, model = app.ai_client.validate_image_request((image,), args.provider, args.model)
            print(_("Image: {name} ({width} × {height}); destination: {provider}, {model}.")
                  .format(name=image.filename, width=image.width, height=image.height, provider=provider, model=model))
            if not getattr(args, 'send_image', False):
                print(_("Review the original image, then repeat with --send-image to send this normalized snapshot."))
                return 0
            images = (image,)
        if use_documents:
            store = _cli_attr('DocumentStore')()
            try:
                document_context = store.context(message, max_chars=MAX_DOCUMENT_CONTEXT_CHARS)
            finally:
                store.close()
            if not document_context:
                print(_("No matching passages in the selected documents."))
                return 1
            if app.ai_client.provider_ready(args.provider) and not getattr(args, 'send_document_context', False):
                print(display_document_context(document_context))
                print(_("Review these excerpts, then repeat with --send-document-context to send them to the model."))
                return 0
    except (OSError, ValueError, AIProviderError) as error:
        print(str(error), file=sys.stderr)
        return 1

    app._prepare_conversation(args)

    if args.expert:
        app.expert_mode = True

    if not images and not use_documents:
        action_code = app._run_conversational_action(message, args)
        if action_code is not None:
            return action_code

    full_history = app._build_request_messages(message)
    if document_context:
        full_history = with_document_context(full_history, document_context)
    request_options = {'provider': args.provider, 'model': args.model}
    if images:
        request_options['images'] = images

    # Get the response (or answer offline when the provider is unusable)
    answered_offline = False
    action_result = _ActionResult()
    if not app.ai_client.provider_ready(args.provider):
        if images:
            print(_("The image request cannot be answered offline."), file=sys.stderr)
            return 1
        if document_context:
            response_text = _("Local document matches (no model request):") + '\n\n' + display_document_context(document_context)
            print(response_text)
        else:
            response_text = app._run_offline(message)
            action_result = response_text
        answered_offline = True
    elif args.stream:
        print("\n[AI] ", end="", flush=True)
        response_text = ""
        try:
            for chunk in app.ai_client.stream_chat(full_history, **request_options):
                print(chunk, end="", flush=True)
                response_text += chunk
            print("\n")
        except (AIImageRequestError, AIRequestCancelled, AIResponseLimitError) as error:
            print(str(error), file=sys.stderr)
            return 1
        except AIProviderError as e:
            # Falha estruturada (rede/HTTP/config): não é conteúdo do
            # modelo — não persistir como resposta, cair para offline.
            print(f"\n[!] {e}\n")
            if images:
                return 1
            if document_context:
                response_text = _("The model is unavailable. Local document matches:") + '\n\n' + display_document_context(document_context)
                print(response_text)
            else:
                response_text = app._run_offline(message)
                action_result = response_text
            answered_offline = True
    else:
        try:
            response_text = app.ai_client.chat(full_history, **request_options)
        except (AIImageRequestError, AIRequestCancelled, AIResponseLimitError) as error:
            print(str(error), file=sys.stderr)
            return 1
        if response_text:
            print(f"\n[AI]\n{response_text}\n")
        else:
            if images:
                print(_("The model returned no answer for the image."), file=sys.stderr)
                return 1
            if document_context:
                response_text = _("The model is unavailable. Local document matches:") + '\n\n' + display_document_context(document_context)
                print(response_text)
            else:
                response_text = app._run_offline(message)
                action_result = response_text
            answered_offline = True

    if response_text and not answered_offline and not images and not use_documents:
        extra = app._offer_model_action(message)
        action_result = extra
        if extra:
            response_text = response_text + "\n\n" + extra

    # Save to history
    if not args.no_history:
        history_message = message
        if images:
            history_message += '\n\n' + _("[Image attached for this request; pixels are not stored.]")
        history_response = response_text
        if document_context and answered_offline:
            history_response = _("Local document matches were shown. Excerpts remain only in the local document index.")
            print(_("These local excerpts are not saved in conversation history."))
        app._record_exchange(history_message, history_response)
        app._save_history()
    return getattr(action_result, "exit_code", 0)

def handle_capture(app, args):
    """Process the capture command. Devolve exit code."""
    if args.window:
        success, image_path = app.system_utils.capture_active_window(args.output)
    else:
        success, image_path = app.system_utils.capture_screen(args.output)

    if success:
        print(f"✓ Capture saved at: {image_path}")

        if args.ocr:
            print("Extracting text from the image...")
            success, text = app.system_utils.extract_text_from_image(image_path)
            if success:
                print(f"\n[Screen Capture]\n{text}\n")
                return 0
            print(f"✗ Error extracting text: {text}")
            return 1
        return 0
    print(f"✗ Error while capturing: {image_path}")
    return 1

def handle_expert(app, args):
    """Expert uses the same routing, sessions and fallback as ordinary chat."""
    args.expert = True
    if not hasattr(args, 'stream'):
        args.stream = False
    if not hasattr(args, 'no_history'):
        args.no_history = False
    return app.handle_chat(args)

def handle_system(app, args):
    """Process the system command."""
    if not args.system_command:
        # Show the full info
        info = app.system_utils.get_system_info()
        app._print_system_info(info)
        return

    if args.system_command == 'info':
        info = app.system_utils.get_system_info()
        app._print_system_info(info)
    elif args.system_command == 'context':
        from ..system_context import detect_system_context
        print(json.dumps(detect_system_context(app.offline.distro).to_dict(), indent=2, ensure_ascii=False))
    elif args.system_command == 'commands':
        commands = app.config.get("permissions.allowed_commands", [])
        print("Allowed commands:")
        for cmd in sorted(commands):
            print(f"  - {cmd}")
    elif args.system_command == 'processes':
        processes = app.system_utils.get_process_list()
        print(f"Processes ({len(processes)}):")
        for proc in processes[:20]:  # Show the first 20
            print(f"  {proc['pid']:>8} {proc['user']:<12} {proc['cpu']:<8} {proc['memory']:<8} {proc['name']}")
        if len(processes) > 20:
            print(f"  ... and {len(processes) - 20} more processes")
    elif args.system_command == 'network':
        network_info = app.system_utils.get_network_info()
        if 'interfaces' in network_info:
            print("Network interfaces:")
            for name, stats in network_info['interfaces'].items():
                print(f"  {name}:")
                for key, value in stats.items():
                    print(f"    {key}: {value}")
        if 'connections' in network_info:
            print(f"\nConnections ({len(network_info['connections'])}):")
            for conn in network_info['connections'][:10]:
                print(f"  {conn['local_addr']:<25} -> {conn['remote_addr']:<25} (PID: {conn['pid']})")
    elif args.system_command == 'exec':
        # args.command já é a lista pós-shell: juntar com espaços e
        # re-dividir com shlex partia argumentos com espaços
        # (`grep "a b" file` virava `grep a b file`).
        success, output = app.system_utils.execute_command(args.command)
        if success:
            print(f"✓ {output}")
            return 0
        print(f"✗ {output}")
        return 1
    return 0

def _print_system_info(app, info: Dict):
    """Show system information in an organized way."""
    print("\n" + "=" * 50)
    print("SYSTEM INFORMATION")
    print("=" * 50)

    print("\nOperating System:")
    print(f"  Name: {info.get('distro', 'Unknown')}")
    print(f"  ID: {info.get('distro_id', 'Unknown')}")
    print(f"  Version: {info.get('release', 'Unknown')}")
    print(f"  Kernel: {info.get('version', 'Unknown')}")
    print(f"  Architecture: {info.get('machine', 'Unknown')} ({info.get('architecture', 'Unknown')})")

    print("\nHardware:")
    print(f"  Hostname: {info.get('hostname', 'Unknown')}")
    print(f"  CPU: {info.get('cpu_cores', 'N/A')} cores ({info.get('cpu_physical_cores', 'N/A')} physical)")
    print(f"  CPU usage: {info.get('cpu_usage', 'N/A')}")

    print("\nMemory:")
    print(f"  Total: {info.get('memory_total', 'N/A')}")
    print(f"  Used: {info.get('memory_used', 'N/A')}")
    print(f"  Available: {info.get('memory_available', 'N/A')}")
    print(f"  Usage: {info.get('memory_percent', 'N/A')}")

    print("\nDisk:")
    print(f"  Total: {info.get('disk_total', 'N/A')}")
    print(f"  Used: {info.get('disk_used', 'N/A')}")
    print(f"  Free: {info.get('disk_free', 'N/A')}")
    print(f"  Usage: {info.get('disk_percent', 'N/A')}")

    print(f"\nUptime: {info.get('uptime', 'N/A')}")

    print("\nUser:")
    print(f"  Name: {info.get('username', 'Unknown')}")
    print(f"  Is root: {info.get('is_root', False)}")

    print("\nGraphical Environment:")
    print(f"  Type: {'Wayland' if info.get('is_wayland') == 'True' else 'X11'}")
    print(f"  Display: {info.get('display', 'N/A')}")

    if info.get('is_void'):
        print("\n✓ System: Void Linux")
    if info.get('is_d77void'):
        print("✓ System: d77void")

    print("=" * 50 + "\n")

def handle_history(app, args):
    """View or clear only the current conversation."""
    if getattr(args, 'history_action', None) == 'recover':
        if not args.yes:
            print('history recover --yes is required. The complete original file will be preserved privately.', file=sys.stderr)
            return 1
        print(str(app._store().recover(confirmed=True)))
        app.conversation_history = app._store().load_entries()
        app.offline.reset_conversation()
        return 0
    store = app._store()
    if args.clear:
        store.clear_session()
        app.conversation_history = []
        app._pending_exchanges = []
        app.offline.reset_conversation()
        print('Current conversation cleared')
        return 0
    messages = store.load_entries()
    messages = messages[-args.limit:] if args.limit > 0 else []
    for item in messages:
        print('[{}]\n{}\n'.format(item['role'], item['content']))
    return 0

def _render_token_usage(app, title: str = "USAGE STATISTICS"):
    """Shared renderer for `stats` and `tokens usage`."""
    token_usage = app.ai_client.get_token_usage()

    print("\n" + "=" * 50)
    print(title)
    print("=" * 50 + "\n")

    if token_usage:
        print("Token usage by provider:\n")
        for provider, usage in token_usage.items():
            print(f"  {provider}:")
            print(f"    Input tokens:  {usage.get('input', 0):>10}")
            print(f"    Output tokens: {usage.get('output', 0):>10}")
            print(f"    Total tokens:  {usage.get('total', 0):>10}")
            print()
    else:
        print("  No statistics available\n")
    print("=" * 50 + "\n")

def handle_stats(app, args):
    """Process the stats command."""
    app._render_token_usage()
    if args.reset:
        app.ai_client.reset_token_usage()
        print("✓ Statistics reset")

def handle_config(app, args):
    """Process the config command."""
    if not args.config_command:
        # List configuration
        config = app.config.config
        print("Stored configuration (environment overrides and Secret Service keys are not shown):")
        app._print_config(config)
        return 0

    if args.config_command == 'list':
        config = app.config.config
        print("Stored configuration (environment overrides and Secret Service keys are not shown):")
        app._print_config(config)
        return 0
    elif args.config_command == 'set':
        if not args.key or not args.value:
            print("✗ You must specify both key and value")
            return

        # Convert the value
        value = args.value
        if value.lower() in ('true', 'false'):
            value = value.lower() == 'true'
        else:
            # int() also accepts negative numbers (isdigit() did not)
            try:
                value = int(value)
            except ValueError:
                try:
                    value = float(value)
                except ValueError:
                    pass

        app.config.set(args.key, value)
        app.config.flush()
        # Never return an API key in cleartext to the terminal/shell history
        if "api_key" in args.key.lower():
            shown = "*" * 12
        else:
            shown = value
        print(f"✓ Configuration updated: {args.key} = {shown}")
    elif args.config_command == 'get':
        if not args.key:
            print("✗ You must specify a key", file=sys.stderr)
            return 1
        # A missing path and a real null value are different. Check the
        # stored structure before resolving environment/key-store values.
        stored = app.config.config
        for component in args.key.split('.'):
            if not isinstance(stored, dict) or component not in stored:
                print(f"✗ Unknown configuration key: {args.key}", file=sys.stderr)
                return 1
            stored = stored[component]
        components = args.key.split('.')
        if (len(components) == 4 and components[:2] == ['api', 'providers']
                and components[3] == 'api_key'):
            value = app.config.get_api_key(components[2])
        else:
            value = app.config.get(args.key)
        # A section can contain API keys too. Redact before printing,
        # including effective credentials resolved from a vault or env.
        value = _masked_config_value(value, args.key)
        print(f"{args.key}: {value}")
        return 0

def _masked_config_value(value, key=''):
    if 'api_key' in key.lower() and value:
        return '*' * 12
    if isinstance(value, dict):
        return {name: _masked_config_value(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_masked_config_value(item) for item in value]
    return value

def _print_config(app, config: Dict, indent: int = 0):
    """Show configuration in an organized way."""
    for key, value in config.items():
        if isinstance(value, dict):
            print("  " * indent + f"{key}:")
            app._print_config(value, indent + 1)
        else:
            # Hide API keys (fixed size: does not reveal the length)
            if 'api_key' in key.lower() and value:
                value = "********"
            else:
                value = _masked_config_value(value)
            print("  " * indent + f"{key}: {value}")

def handle_providers(app, args):
    """Process the providers command."""
    providers = app.ai_client.get_supported_providers()

    print("\n" + "=" * 50)
    print("AVAILABLE AI PROVIDERS")
    print("=" * 50 + "\n")

    # Get configuration
    api_config = app.config.get("api.providers", {})
    if not isinstance(api_config, dict):
        api_config = {}
    default_provider = app.config.get("api.default_provider", "openrouter")

    for provider in providers:
        config = api_config.get(provider, {})
        if not isinstance(config, dict):
            config = {}
        # Remote chat reads the provider map; only local settings resolve
        # a model override at the individual leaf as well.
        model = (app.config.get(f"api.providers.{provider}.model", config.get("model", ""))
                 if provider == 'local_llm' else config.get("model", "N/A"))
        is_default = provider == default_provider

        marker = "✓" if is_default else " "
        key_status, source = app._provider_key_status(provider)

        print(f"{marker} {provider:<20} Model: {model:<30} Key: {key_status} ({source})")

    print("\nKey reports the effective credential; no API request or key-store unlock was performed.")
    print("A present key is not proof that the provider accepts it. The leading ✓ marks the default provider.")
    print("\n" + "=" * 50 + "\n")
    return 0

def _provider_key_status(app, provider):
    """Resolve credential presence without disclosing it or unlocking a vault."""
    if provider == 'local_llm':
        return 'N/A', 'not required'
    override = app.config.get_api_key_env_override(provider)
    if override is not None:
        present = bool(app.config.get_api_key(provider))
        source = f"environment: {override}"
        if not present:
            source += '; empty override blocks stored key'
        return ('✓' if present else '✗'), source
    from ..credential_store import CredentialStoreError
    try:
        storage = app.config.get_api_key_storage(provider)
    except CredentialStoreError:
        return '✗', 'invalid credential storage'
    present = bool(app.config.get_api_key(provider))
    source = 'Secret Service' if storage == 'secret-service' else 'config'
    if not present:
        source += '; not set or unavailable'
    return ('✓' if present else '✗'), source

def handle_tokens(app, args):
    """Process the tokens command."""
    if not args.tokens_command or args.tokens_command == 'usage':
        app._render_token_usage("TOKEN USAGE")
    elif args.tokens_command == 'reset':
        app.ai_client.reset_token_usage()
        print("✓ Token count reset")

def _get_context_message(app, query='') -> Optional[Dict[str, str]]:
    return build_system_message(app.expert_mode, app.offline.distro, query, get_language(), getattr(app, 'system_context', None))

def _save_history(app):
    store = app._store()
    for item in app._pending_exchanges:
        store.append(item['role'], item['content'], item['timestamp'])
    if not store.flush():
        raise OSError('Could not save conversation: {}'.format(store.last_error))
    store.set_diagnostic_state(app.offline.diagnostic_state())
    app._pending_exchanges = []
