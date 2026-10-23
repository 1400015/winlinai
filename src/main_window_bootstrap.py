"""Window bootstrap extracted from MainWindow.__init__.

`MainWindow.__init__` still calls Gtk.Window.__init__ first; this module
then applies geometry, dock mode, state and history wiring in the original
order, so construction behaves exactly as before.
"""

import logging
import threading

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')

from gi.repository import GLib

from . import dock, offline_assistant
from .change_journal import ChangeJournal
from .conversation_actions import ConversationActions
from .history_store import HistoryStore

logger = logging.getLogger(__name__)

__all__ = ["initialize_window"]


def initialize_window(window, app, config_manager, ai_client, system_utils, history_store=None):
    from .desktop_icons import ICON_NAME, configure_application_icon
    configure_application_icon()
    window.set_icon_name(ICON_NAME)

    window.app = app
    window.config = config_manager
    window.ai_client = ai_client
    window.system_utils = system_utils
    # Answers basic questions and offers local tasks when no API key is
    # configured or the provider cannot be reached.
    window.offline = offline_assistant.OfflineAssistant(system_utils, config_manager)
    window.change_journal = ChangeJournal()

    # Configurar janela
    window.set_default_size(
        config_manager.get("app.width", 400),
        config_manager.get("app.height", 500)
    )

    # Posicionar janela
    window.move(
        config_manager.get("app.x_position", 100),
        config_manager.get("app.y_position", 100)
    )

    # Configure transparency
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if visual:
        window.set_visual(visual)
        window.set_opacity(config_manager.get("app.opacity", 0.9))

    # Make window always visible
    window.set_keep_above(config_manager.get("app.always_on_top", True))
    window.stick()

    # Docked mode: pin to an edge and reserve screen space.
    # O gtk-layer-shell exige init ANTES de realize: em Wayland tentamos
    # aplicar já no __init__ (apply_dock confirma is_layer_window e cai
    # para o fallback se não tiver efeito); em X11 os struts precisam do
    # GdkWindow, pelo que ficam para _on_realize_dock().
    window._dock_edge = config_manager.get("app.dock_edge", "right")
    window._dock_width = config_manager.get("app.width", 400)
    window.dock_method = None
    if config_manager.get("app.dock_mode", "float") == "dock":
        window.set_decorated(False)
        if dock.apply_dock(window, window._dock_edge, window._dock_width) == "layer-shell":
            window.dock_method = "layer-shell"
            logger.info("Dock applied pre-realize via layer-shell")
        else:
            window.connect("realize", window._on_realize_dock)
    else:
        window.set_decorated(True)

    # Make window resizable
    window.set_resizable(True)

    # Configurar estilo
    window._setup_style()

    # Configure notifications
    window._setup_notifications()

    # State variables
    # Expert mode is persisted (app.expert_mode); `features.expert_mode`
    # only controls whether the button is shown at all.
    window.expert_mode = bool(window.config.get("app.expert_mode", False))
    window.conversation_history = []
    window.streaming = False
    window.is_loading = False
    # Per-request state: each send gets a new id and its own cancel event,
    # so a cancelled worker can never re-arm itself or corrupt the next
    # request (see _process_message / _finalize_response).
    window._request_seq = 0
    window._active_request = 0
    window._cancel_event = threading.Event()
    window._pending_image = None
    window._pending_image_destination = None
    window._document_store = None
    # Settings dialog currently open (or None); lets the "Manage Themes"
    # button switch tabs instead of opening a second dialog.
    window._settings_notebook = None
    # Interval (start, end) of the "Thinking..." placeholder and the
    # streamed body offset vivem no ChatView (ver _create_ui).
    # History is persisted from a single background writer (FIFO) owned
    # by HistoryStore (GTK-free), so the GTK main loop never blocks on a
    # full file rewrite per message.
    window.history_store = history_store if history_store is not None else HistoryStore()
    window.history_store.list_sessions()
    window._history_recovering = False
    window._file_action_controllers = []
    from .system_context import detect_system_context
    window.system_context = detect_system_context(window.offline.distro)
    window.offline.set_system_context(window.system_context)
    window.actions = ConversationActions(window.history_store, window.offline.distro.pkg_manager, context=window.system_context,
                                       independent_display_watchdog=window.config.get('app.display_independent_watchdog', False))
    window._refreshing_sessions = False

    # Create interface
    window._create_ui()
    window._setup_style()

    # Connect signals
    window.connect("delete-event", window.on_delete_event)
    # NB: apenas `configure-event` — já reporta x/y/width/height; ligar
    # também `size-allocate` duplicava a escrita de app.width/height por
    # evento de layout.
    window.connect("configure-event", window.on_configure_event)

    # Keyboard shortcuts
    window._setup_keybindings()

    # Load conversation history
    window._load_conversation_history()
    window._refresh_session_controls()
    window._refresh_mode_status()
    window._history_watch_source = GLib.timeout_add_seconds(1, window._check_history_writer)
    window.connect('destroy', window._stop_history_watch)

    logger.info("Main window initialized")
