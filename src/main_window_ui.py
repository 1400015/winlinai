"""GTK widgets, styling and menu construction for MainWindow.

These builders receive the window and set the same attributes the methods
used to set, keeping application behaviour in the window itself.
"""

import logging

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import Gtk

from .chat_view import ChatView
from .change_dialog import show_file_changes
from .diagnostic_dialog import show_diagnostic_report
from .i18n import _
from .theme_utils import build_gtk_css, get_chat_style_colors, safe_font_family, safe_number
from .trial_dialog import show_trials

logger = logging.getLogger(__name__)

__all__ = [
    "build_ui",
    "build_style",
    "setup_keybindings",
    "show_menu",
]


def build_ui(window):
    """Create the window interface"""
    main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    main_box.set_property("name", "main-box")
    window.add(main_box)

    # Header
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
    header.set_property("name", "header")
    main_box.pack_start(header, False, False, 0)

    # Menu button
    menu_btn = Gtk.Button.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.MENU)
    menu_btn.connect("clicked", window.on_menu_clicked)
    menu_btn.set_tooltip_text(_("Menu"))
    header.pack_start(menu_btn, False, False, 0)

    # Title
    title_label = Gtk.Label(label=_("Linux AI Assistant"))
    title_label.set_halign(Gtk.Align.START)
    title_label.set_valign(Gtk.Align.CENTER)
    header.pack_start(title_label, True, True, 0)

    # Icon de estado
    window.status_icon = Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.MENU)
    window.status_icon.set_tooltip_text(_("Ready"))
    header.pack_end(window.status_icon, False, False, 0)

    # Close button
    close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
    close_btn.connect("clicked", lambda btn: window.on_close_clicked())
    close_btn.set_tooltip_text(_("Close"))
    header.pack_end(close_btn, False, False, 0)

    # Minimize button
    minimize_btn = Gtk.Button.new_from_icon_name("window-minimize-symbolic", Gtk.IconSize.MENU)
    minimize_btn.connect("clicked", lambda btn: window.iconify())
    minimize_btn.set_tooltip_text(_("Minimize"))
    header.pack_end(minimize_btn, False, False, 0)

    conversations = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
    main_box.pack_start(conversations, False, False, 0)
    window.session_combo = Gtk.ComboBoxText()
    window.session_combo.set_hexpand(True)
    window.session_combo.set_tooltip_text(_("Conversations"))
    window.session_combo.connect('changed', window._on_session_selected)
    conversations.pack_start(window.session_combo, True, True, 0)
    new_conversation = Gtk.Button.new_from_icon_name('document-new-symbolic', Gtk.IconSize.MENU)
    new_conversation.set_tooltip_text(_("New conversation"))
    new_conversation.connect('clicked', window._new_conversation)
    conversations.pack_start(new_conversation, False, False, 0)
    actions_button = Gtk.Button.new_from_icon_name('view-list-symbolic', Gtk.IconSize.MENU)
    actions_button.set_tooltip_text(_("Actions"))
    actions_button.connect('clicked', window._show_action_audit)
    conversations.pack_start(actions_button, False, False, 0)
    window.trials_button = Gtk.Button.new_from_icon_name('applications-science-symbolic', Gtk.IconSize.MENU)
    window.trials_button.set_tooltip_text(_("Trials / Debug"))
    window.trials_button.connect('clicked', lambda button: show_trials(window))
    conversations.pack_start(window.trials_button, False, False, 0)
    window.mode_label = Gtk.Label(xalign=0, wrap=True)
    main_box.pack_start(window.mode_label, False, False, 0)

    window.history_warning = Gtk.InfoBar()
    window.history_warning.set_message_type(Gtk.MessageType.WARNING)
    window.history_warning.set_no_show_all(True)
    warning = Gtk.Label(label=_("Conversation history could not be saved. Recover it before continuing; pending messages have not been discarded."),
                        xalign=0, wrap=True)
    window.history_warning.get_content_area().pack_start(warning, True, True, 0)
    warning.show()
    window.history_warning.add_button(_("Recover history"), Gtk.ResponseType.OK)
    window.history_warning.connect('response', window._recover_history)
    main_box.pack_start(window.history_warning, False, False, 0)

    # Chat area
    chat_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    chat_area.set_property("name", "chat-area")
    main_box.pack_start(chat_area, True, True, 0)

    # ChatView: buffer, tags, offsets, placeholder e scroll (GTK-isolado)
    window.chat_view = ChatView(
        font_family=window.config.get('ui.font_family', 'Monospace'),
        font_size=window.config.get('ui.font_size', 12),
    )
    window.chat_scrolled = window.chat_view.scrolled
    window.chat_textview = window.chat_view.textview
    chat_area.pack_start(window.chat_scrolled, True, True, 0)

    references = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    main_box.pack_start(references, False, False, 0)
    window.documents_check = Gtk.CheckButton(label=_("Use selected documents"))
    window.documents_check.set_tooltip_text(_("Review matching excerpts before sending them to the model. Offline mode shows local matches."))
    references.pack_start(window.documents_check, True, True, 0)
    documents_button = Gtk.Button.new_from_icon_name('folder-documents-symbolic', Gtk.IconSize.MENU)
    documents_button.set_tooltip_text(_("Manage selected documents"))
    documents_button.connect('clicked', window.on_documents_clicked)
    references.pack_start(documents_button, False, False, 0)
    window.attachment_label = Gtk.Label(xalign=0, wrap=True)
    main_box.pack_start(window.attachment_label, False, False, 0)
    window.remove_image_button = Gtk.Button(label=_("Remove image"))
    window.remove_image_button.connect('clicked', lambda button: window._clear_pending_image())
    window.remove_image_button.set_no_show_all(True)
    window.remove_image_button.hide()
    references.pack_start(window.remove_image_button, False, False, 0)

    # Input area
    # Keep the message field on its own row. On a narrow floating/docked
    # window, five action buttons otherwise consume most of its width.
    input_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    input_area.set_property("name", "input-area")
    main_box.pack_start(input_area, False, False, 0)

    # Entry for input
    window.input_entry = Gtk.Entry()
    # Both plain Enter and Ctrl+Enter send (the accelerator below also
    # triggers "activate"), so the old "Ctrl+Enter" hint was misleading.
    window.input_entry.set_placeholder_text(_("Type your message... (Enter to send)"))
    window.input_entry.connect("activate", window.on_input_activate)
    window.input_entry.set_hexpand(True)
    input_area.pack_start(window.input_entry, False, True, 0)

    # Action buttons
    button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
    button_box.set_halign(Gtk.Align.END)
    input_area.pack_start(button_box, False, False, 0)

    # Cancel button
    window.cancel_btn = Gtk.Button.new_from_icon_name("process-stop-symbolic", Gtk.IconSize.MENU)
    window.cancel_btn.connect("clicked", window.on_cancel_streaming)
    window.cancel_btn.set_tooltip_text(_("Cancel"))
    window.cancel_btn.set_sensitive(False)
    button_box.pack_start(window.cancel_btn, False, False, 0)

    # Screen capture button (hidden when features.screen_capture is off)
    capture_btn = Gtk.Button.new_from_icon_name("camera-photo-symbolic", Gtk.IconSize.MENU)
    capture_btn.connect("clicked", window.on_capture_screen_clicked)
    capture_btn.set_tooltip_text(_("Capture screen (Ctrl+S)"))
    button_box.pack_start(capture_btn, False, False, 0)
    window.capture_btn = capture_btn

    image_btn = Gtk.Button.new_from_icon_name('insert-image-symbolic', Gtk.IconSize.MENU)
    image_btn.connect('clicked', window.on_attach_image_clicked)
    image_btn.set_tooltip_text(_("Attach an image for the next question"))
    button_box.pack_start(image_btn, False, False, 0)

    # Expert mode button (hidden when features.expert_mode is off)
    window.expert_btn = Gtk.Button.new_from_icon_name("system-run-symbolic", Gtk.IconSize.MENU)
    window.expert_btn.connect("clicked", window.on_expert_mode_toggled)
    window.expert_btn.set_tooltip_text(_("Expert Mode (Ctrl+E)"))
    button_box.pack_start(window.expert_btn, False, False, 0)

    # Send button
    send_btn = Gtk.Button.new_from_icon_name("go-next-symbolic", Gtk.IconSize.MENU)
    send_btn.connect("clicked", lambda btn: window.on_send_clicked())
    send_btn.set_tooltip_text(_("Send (Enter)"))
    button_box.pack_start(send_btn, False, False, 0)

    # Hide the feature buttons that are disabled in settings
    window._apply_feature_toggles()
    # Restore the persisted expert mode visually (the toggle only styles
    # the button when the user clicks it).
    if window.expert_mode and hasattr(window, "expert_btn"):
        window.expert_btn.get_style_context().add_class("expert")

    # Add welcome message
    window._add_system_message(_("Welcome to Linux AI Assistant!\nType a message or press Ctrl+S to capture the screen."))

    # Auto-scroll to bottom
    window._scroll_to_bottom()

    # Choose the typing field before the window is mapped. This establishes
    # the initial keyboard target without presenting the window or changing
    # focus again when a settings/review dialog is open.
    window.set_focus(window.input_entry)

    logger.info("UI created successfully")


def build_style(window):
    """Set up window CSS styling"""
    # A screen provider also sees dialogs, menus and window decorations.
    # Scope every rule to our content so those keep their native GTK theme.
    window.get_style_context().add_class('linux-ai-main')
    # add_provider_for_screen() is cumulative: remove the previous provider
    # first so changing theme does not stack stylesheets indefinitely.
    previous = getattr(window, "_style_provider", None)
    if previous is not None:
        try:
            Gtk.StyleContext.remove_provider_for_screen(window.get_screen(), previous)
        except Exception as e:
            logger.warning(f"Could not remove previous CSS provider: {e}")
    style_provider = Gtk.CssProvider()

    # Get cores do tema
    colors = window.config.get_theme_colors()
    theme_info = window.config.get_theme_info(window.config.get("app.theme", "dark"))

    # Get settings de UI do tema
    theme_ui = {}
    if theme_info and 'ui' in theme_info:
        theme_ui = theme_info['ui']

    font_family = safe_font_family(
        theme_ui.get('font_family') or window.config.get('ui.font_family'),
        'Monospace',
    )
    font_size = safe_number(
        theme_ui.get('font_size') or window.config.get('ui.font_size'),
        12, int, minimum=4, maximum=72,
    )
    border_radius = safe_number(
        theme_ui.get('border_radius') or window.config.get('ui.border_radius'),
        10, int, minimum=0, maximum=64,
    )

    # Cores de syntax highlighting para o chat view
    if hasattr(window, 'chat_view'):
        window.chat_view.set_style(font_family, font_size,
                                 get_chat_style_colors(colors, theme_info))

    css = build_gtk_css(colors, theme_info, font_family, font_size, border_radius)

    style_provider.load_from_data(css.encode())
    Gtk.StyleContext.add_provider_for_screen(
        window.get_screen(),
        style_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    window._style_provider = style_provider
    logger.debug("CSS style applied with theme: " + window.config.get("app.theme", "dark"))


def setup_keybindings(window):
    """Set up keyboard shortcuts"""
    accel_group = Gtk.AccelGroup()
    window.add_accel_group(accel_group)

    # Ctrl+Enter also sends (plain Enter already activates the entry)
    key, mod = Gtk.accelerator_parse("<Control>Return")
    window.input_entry.add_accelerator("activate", accel_group, key, mod, Gtk.AccelFlags.VISIBLE)

    # Escape to clear input
    key, mod = Gtk.accelerator_parse("Escape")
    accel_group.connect(key, mod,
                      Gtk.AccelFlags.VISIBLE, window.on_clear_input)

    # Ctrl+E to toggle expert mode
    key, mod = Gtk.accelerator_parse("<Control>e")
    window.expert_btn.add_accelerator("clicked", accel_group, key, mod, Gtk.AccelFlags.VISIBLE)

    # Ctrl+Q to close
    key, mod = Gtk.accelerator_parse("<Control>q")
    accel_group.connect(key, mod,
                      Gtk.AccelFlags.VISIBLE, lambda *args: window.on_close_clicked())

    # Ctrl+S to capture screen
    key, mod = Gtk.accelerator_parse("<Control>s")
    accel_group.connect(key, mod,
                      Gtk.AccelFlags.VISIBLE, lambda *args: window.on_capture_screen_clicked(None))

    logger.info("Keyboard shortcuts configured")


def show_menu(window, button):
    """Show options menu"""
    menu = Gtk.Menu()

    # Settings option
    config_item = Gtk.MenuItem(label=_("Settings"))
    config_item.connect("activate", window.on_config_clicked)
    menu.append(config_item)

    # History option
    history_item = Gtk.MenuItem(label=_("Conversation History"))
    history_item.connect("activate", window.on_history_clicked)
    menu.append(history_item)

    recover_item = Gtk.MenuItem(label=_("Recover history"))
    recover_item.connect('activate', window._recover_history)
    menu.append(recover_item)

    # Statistics option
    stats_item = Gtk.MenuItem(label=_("Statistics"))
    stats_item.connect("activate", window.on_stats_clicked)
    menu.append(stats_item)

    report_item = Gtk.MenuItem(label=_("Diagnostic report"))
    report_item.connect('activate', lambda item: show_diagnostic_report(window))
    menu.append(report_item)
    trials_item = Gtk.MenuItem(label=_("Trials / Debug"))
    trials_item.connect('activate', lambda item: show_trials(window))
    menu.append(trials_item)
    changes_item = Gtk.MenuItem(label=_("File changes"))
    changes_item.connect('activate', lambda item: show_file_changes(window))
    menu.append(changes_item)
    image_item = Gtk.MenuItem(label=_("Capture an image for AI"))
    image_item.connect('activate', lambda item: window.on_capture_screen_clicked(None, for_ai=True))
    menu.append(image_item)
    documents_item = Gtk.MenuItem(label=_("Manage selected documents"))
    documents_item.connect('activate', window.on_documents_clicked)
    menu.append(documents_item)

    # Separador
    menu.append(Gtk.SeparatorMenuItem())

    # Quit option
    quit_item = Gtk.MenuItem(label=_("Quit"))
    quit_item.connect("activate", lambda *args: window.on_close_clicked())
    menu.append(quit_item)

    menu.show_all()
    menu.popup_at_pointer(None)  # Show no cursor

