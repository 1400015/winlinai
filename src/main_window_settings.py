"""GTK settings dialog extracted from MainWindow.

Kept as a function over the window: the dialog reads and updates the same
window state it always did, without making MainWindow grow further.
"""

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import Gtk

from .credential_settings import APIKeySettings
from .i18n import _, get_language
from .provider_settings import ProviderSettings
from .remote_model_settings import RemoteModelSettings

__all__ = ["show_settings_dialog"]


def show_settings_dialog(window):
    """Show the settings dialog for window."""
    dialog = Gtk.Dialog(
        title=_("Settings - Linux AI Assistant"),
        parent=window,
        flags=0,
        buttons=(Gtk.STOCK_OK, Gtk.ResponseType.OK)
    )

    dialog.set_default_size(500, 400)

    # Create dialog content
    content = dialog.get_content_area()

    # Notebook for sections
    notebook = Gtk.Notebook()
    content.pack_start(notebook, True, True, 0)
    # Kept so on_themes_clicked can jump to the Themes tab instead of
    # reopening a second (nested) dialog.
    window._settings_notebook = notebook

    def add_settings_page(box, title):
        # Credential warnings and model lists can exceed a small desktop.
        # Keep the dialog's confirmation button outside the scrolling page.
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(box)
        notebook.append_page(scroll, Gtk.Label(label=_(title)))

    # API section
    api_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    api_box.set_border_width(10)

    api_label = Gtk.Label(label="<b>" + _("API Configuration") + "</b>")
    api_label.set_use_markup(True)
    api_box.pack_start(api_label, False, False, 0)

    # Provider
    provider_label = Gtk.Label(label=_("AI Provider:"))
    api_box.pack_start(provider_label, False, False, 0)

    provider_combo = Gtk.ComboBoxText()
    for provider_name in window.config.get("api.providers", {}).keys():
        provider_combo.append(provider_name, provider_name)
    current_provider = window.config.get("api.default_provider", "openrouter")
    provider_combo.set_active_id(current_provider)
    api_box.pack_start(provider_combo, False, False, 0)

    credential_settings = APIKeySettings(window.config, provider_combo)
    api_box.pack_start(credential_settings, False, False, 0)

    add_settings_page(api_box, "API")
    assistance_settings = ProviderSettings(window.config, window.ai_client)
    model_settings = RemoteModelSettings(window.config, window.ai_client, provider_combo,
                                         assistance_settings.mode, credential_settings=credential_settings)
    api_box.pack_start(model_settings, False, False, 0)
    add_settings_page(assistance_settings, "Assistance")

    # Appearance section
    ui_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    ui_box.set_border_width(10)

    ui_label = Gtk.Label(label="<b>" + _("UI Configuration") + "</b>")
    ui_label.set_use_markup(True)
    ui_box.pack_start(ui_label, False, False, 0)

    # Opacity
    opacity_label = Gtk.Label(label=_("Window opacity:"))
    ui_box.pack_start(opacity_label, False, False, 0)

    opacity_scale = Gtk.Scale.new_with_range(
        Gtk.Orientation.HORIZONTAL,
        0.1, 1.0, 0.1
    )
    opacity_scale.set_value(window.config.get("app.opacity", 0.9))
    ui_box.pack_start(opacity_scale, False, False, 0)

    # Always visible
    always_on_top_check = Gtk.CheckButton(label=_("Always visible"))
    always_on_top_check.set_active(window.config.get("app.always_on_top", True))
    ui_box.pack_start(always_on_top_check, False, False, 0)

    global_shortcut_check = Gtk.CheckButton(label=_("Enable global shortcut to open the assistant"))
    global_shortcut_check.set_active(window.config.get('app.global_shortcut_enabled', False))
    ui_box.pack_start(global_shortcut_check, False, False, 0)
    global_shortcut_entry = Gtk.Entry()
    global_shortcut_entry.set_max_length(100)
    global_shortcut_entry.set_text(window.config.get('app.global_shortcut', '<Ctrl><Alt>space'))
    global_shortcut_entry.set_placeholder_text('<Ctrl><Alt>space')
    ui_box.pack_start(global_shortcut_entry, False, False, 0)
    global_shortcut_status = Gtk.Label(label=_(getattr(window.app, 'global_shortcut_status', 'Global shortcut disabled')),
                                      wrap=True, xalign=0)
    ui_box.pack_start(global_shortcut_status, False, False, 0)
    previous_shortcut_callback = getattr(window.app, 'global_shortcut_status_changed', None)

    def update_shortcut_status(status):
        global_shortcut_status.set_text(_(status))
        if callable(previous_shortcut_callback):
            previous_shortcut_callback(status)

    window.app.global_shortcut_status_changed = update_shortcut_status
    dialog.connect('destroy', lambda widget: setattr(window.app, 'global_shortcut_status_changed', previous_shortcut_callback))

    # Theme
    theme_label = Gtk.Label(label=_("Theme:"))
    ui_box.pack_start(theme_label, False, False, 0)

    theme_combo = Gtk.ComboBoxText()
    # Load available themes
    available_themes = window.config.get_available_themes()
    for theme in available_themes:
        theme_info = window.config.get_theme_info(theme)
        display_name = theme_info.get("name", theme) if theme_info else theme
        theme_combo.append(theme, display_name)

    theme_combo.set_active_id(window.config.get("app.theme", "dark"))
    ui_box.pack_start(theme_combo, False, False, 0)

    # Language selector: qualquer língua não suportada recai em inglês
    # (i18n.normalize_language); aqui o utilizador redefine explicitamente.
    lang_label = Gtk.Label(label=_("Language:"))
    ui_box.pack_start(lang_label, False, False, 0)

    from .i18n import available_languages, LANGUAGE_NAMES
    lang_combo = Gtk.ComboBoxText()
    for code in available_languages():
        lang_combo.append(code, LANGUAGE_NAMES.get(code, code))
    lang_combo.set_active_id(get_language() if get_language() in
                             available_languages() else "en")
    ui_box.pack_start(lang_combo, False, False, 0)

    # Button to manage themes
    themes_btn = Gtk.Button(label=_("Manage Themes"))
    themes_btn.connect("clicked", window.on_themes_clicked)
    ui_box.pack_start(themes_btn, False, False, 0)

    # Docked mode (dock)
    dock_check = Gtk.CheckButton(label=_("Docked (reserves screen space)"))
    dock_check.set_active(window.config.get("app.dock_mode", "float") == "dock")
    ui_box.pack_start(dock_check, False, False, 0)

    dock_edge_label = Gtk.Label(label=_("Dock edge:"))
    ui_box.pack_start(dock_edge_label, False, False, 0)

    dock_edge_combo = Gtk.ComboBoxText()
    for edge_id, edge_name in [("right", _("Right")), ("left", _("Left")),
                               ("top", _("Top")), ("bottom", _("Bottom"))]:
        dock_edge_combo.append(edge_id, edge_name)
    dock_edge_combo.set_active_id(window.config.get("app.dock_edge", "right"))
    ui_box.pack_start(dock_edge_combo, False, False, 0)

    add_settings_page(ui_box, "Appearance")

    # Themes section
    themes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    themes_box.set_border_width(10)

    themes_label = Gtk.Label(label="<b>" + _("Custom Themes") + "</b>")
    themes_label.set_use_markup(True)
    themes_box.pack_start(themes_label, False, False, 0)

    # Theme list
    window.themes_listbox = Gtk.ListBox()
    # SINGLE (not NONE): with NONE the rows can never be selected and
    # "Remove Theme" always reports "No theme selected".
    window.themes_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    window._populate_themes_list()
    themes_box.pack_start(window.themes_listbox, True, True, 0)

    # Theme buttons
    theme_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)

    add_theme_btn = Gtk.Button(label=_("Add Theme"))
    add_theme_btn.connect("clicked", window.on_add_theme_clicked)
    theme_buttons.pack_start(add_theme_btn, False, False, 0)

    remove_theme_btn = Gtk.Button(label=_("Remove Theme"))
    remove_theme_btn.connect("clicked", window.on_remove_theme_clicked)
    theme_buttons.pack_start(remove_theme_btn, False, False, 0)

    themes_box.pack_start(theme_buttons, False, False, 0)

    add_settings_page(themes_box, "Themes")

    # Features section
    features_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    features_box.set_border_width(10)

    features_label = Gtk.Label(label="<b>" + _("Features") + "</b>")
    features_label.set_use_markup(True)
    features_box.pack_start(features_label, False, False, 0)

    # Screen capture
    screen_capture_check = Gtk.CheckButton(label=_("Screen capture"))
    screen_capture_check.set_active(window.config.get("features.screen_capture", True))
    features_box.pack_start(screen_capture_check, False, False, 0)

    # OCR
    ocr_check = Gtk.CheckButton(label=_("OCR (text recognition)"))
    ocr_check.set_active(window.config.get("features.ocr_enabled", True))
    features_box.pack_start(ocr_check, False, False, 0)

    # Expert mode button visibility (the active/inactive mode is toggled
    # from the window button or the tray menu and stored in app.expert_mode)
    expert_check = Gtk.CheckButton(label=_("Show Expert Mode button"))
    expert_check.set_active(window.config.get("features.expert_mode", True))
    features_box.pack_start(expert_check, False, False, 0)

    add_settings_page(features_box, "Features")

    # Show dialog
    dialog.show_all()

    # Validate the draft before saving; Cancel never persists probe settings.
    while True:
        response = dialog.run()
        if response != Gtk.ResponseType.OK:
            break
        try:
            if (assistance_settings.mode.get_active_id() != window.config.get_assistance_mode()
                    or assistance_settings.draft() != {
                        key: window.config.get_local_model_settings()[key]
                        for key in assistance_settings.draft()
                    }):
                window._cancel_for_session_change()
            assistance_settings.save()
            model_settings.save()
            if not credential_settings.save():
                continue
            break
        except ValueError as error:
            warning = Gtk.MessageDialog(transient_for=dialog, modal=True,
                                        message_type=Gtk.MessageType.ERROR,
                                        buttons=Gtk.ButtonsType.OK, text=str(error))
            warning.run()
            warning.destroy()
    if response == Gtk.ResponseType.OK:
        # Save provider (get_active_id() is None when nothing matches)
        new_provider = provider_combo.get_active_id()
        if new_provider:
            window.config.set("api.default_provider", new_provider)

        # Save opacity
        opacity = opacity_scale.get_value()
        window.config.set("app.opacity", opacity)
        window.set_opacity(opacity)

        # Save always on top
        always_on_top = always_on_top_check.get_active()
        window.config.set("app.always_on_top", always_on_top)
        window.set_keep_above(always_on_top)
        shortcut = global_shortcut_entry.get_text().strip()
        window.config.set('app.global_shortcut_enabled', global_shortcut_check.get_active())
        window.config.set('app.global_shortcut', shortcut)
        configure_shortcut = getattr(window.app, 'configure_global_shortcut', None)
        if configure_shortcut is not None:
            status = configure_shortcut(global_shortcut_check.get_active(), shortcut)
            window._add_system_message(_(status))

        # Save theme
        theme = theme_combo.get_active_id()
        if theme:
            window.config.set("app.theme", theme)
            # Rebuild the CSS so the new theme takes effect now
            window._setup_style()

        # Save language (normalizada: não suportada -> inglês). Os textos
        # novos (mensagens, diálogos) aplicam-se de imediato; os rótulos
        # já desenhados aplicam-se após reiniciar.
        from .i18n import set_language as set_app_language
        new_lang = lang_combo.get_active_id()
        if new_lang:
            set_app_language(new_lang, window.config)

        # Save features
        window.config.set("features.screen_capture", screen_capture_check.get_active())
        window.config.set("features.ocr_enabled", ocr_check.get_active())
        window.config.set("features.expert_mode", expert_check.get_active())
        if not expert_check.get_active() and window.expert_mode:
            # Hiding the button must not leave an invisible active mode.
            window.expert_mode = False
            window.config.set("app.expert_mode", False)
            window.expert_btn.get_style_context().remove_class("expert")
            tray = getattr(window.app, "tray_icon", None)
            if tray is not None:
                tray.update_expert_mode(False)
        window._apply_feature_toggles()

        # Save docked mode
        window.config.set("app.dock_mode", "dock" if dock_check.get_active() else "float")
        window.config.set("app.dock_edge", dock_edge_combo.get_active_id() or "right")
        # Apply the new dock/float setting immediately
        window._reapply_dock()

        # Save settings
        window.config.save()
        window._refresh_mode_status()

        # Show notification
        window.show_notification("Linux AI Assistant", _("Settings saved successfully"))

    dialog.destroy()
    window._settings_notebook = None
    # O diálogo foi destruído: não deixar o listbox pendente a um widget
    # morto (qualquer uso futuro operaria sobre o objeto destruído).
    window.themes_listbox = None

