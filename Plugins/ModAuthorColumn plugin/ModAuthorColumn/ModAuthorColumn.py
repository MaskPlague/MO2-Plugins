# Written by MaskPlague and various AI
import mobase #type: ignore
import os
import configparser
import json
from .SettingsDialog import SettingsDialog
from .AuthorTreeView import ModAuthorTreeView
from .Global import UNKNOWN_AUTHOR, PRIORITY_COL, NEXUS_API_URL

try:
    from PyQt6.QtCore import Qt, QCoreApplication, QModelIndex, QPersistentModelIndex, QUrl
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QWidget, QHBoxLayout, QTreeView, QMainWindow, QSplitter, QVBoxLayout, QPushButton, QSizePolicy, QMessageBox
    from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
except ImportError:
    from PyQt5.QtCore import Qt, QCoreApplication, QModelIndex, QPersistentModelIndex, QUrl
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QWidget, QHBoxLayout, QTreeView, QMainWindow, QSplitter, QVBoxLayout, QPushButton, QSizePolicy, QMessageBox
    from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PyQt6.QtCore import Qt, QCoreApplication, QModelIndex, QPersistentModelIndex, QUrl
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QWidget, QHBoxLayout, QTreeView, QMainWindow, QSplitter, QVBoxLayout, QPushButton, QSizePolicy, QMessageBox
    from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

class ModAuthorColumn(mobase.IPluginTool):
    key_validated = False
    api_key = ""
    use_uploader = False
    hide_author_column = False
    _organizer: mobase.IOrganizer = None
    _modlist_widget: QTreeView = None

    # Required IPluginTool methods

    def name(self) -> str:
        return "ModAuthorColumn"

    def author(self) -> str:
        return "MaskPlague"

    def description(self) -> str:
        return self.tr("Adds a mod author column to the modlist kind of...")

    def version(self):
        return mobase.VersionInfo(0, 0, 1, mobase.ReleaseType.FINAL)

    def settings(self):
        return [
            mobase.PluginSetting("api_key", "Your MO2 API key.", ""),
            mobase.PluginSetting("UseUploader", "If set to True, use the Uploader instead of the Author", False),
            mobase.PluginSetting("HideAuthorColumn", "Hides the Author Column", False)
        ]

    def displayName(self):
        return self.tr("ModAuthorColumn")

    def tooltip(self):
        return self.tr("Adds a mod author column to the modlist kinda of...")

    def icon(self):
        return QIcon(None)

    def display(self):
        # Open our custom dialog
        dialog = SettingsDialog(self.api_key, self.key_validated, self.use_uploader, self.hide_author_column)
        # exec() blocks the user from clicking the main MO2 window until they finish with the dialog
        if dialog.exec(): 
            new_key = dialog.api_key_input.text().strip()
            new_use_uploader = dialog.use_uploader_checkbox.isChecked()
            force_requery = dialog.force_requery_checkbox.isChecked()
            hide_author_column = dialog.hide_author_column.isChecked()
            self.key_validated = dialog.key_validated

            if new_key != self.api_key and self.key_validated:
                self.api_key = new_key
                self._organizer.setPluginSetting(self.name(), "api_key", new_key)
                print("ModAuthorColumn API Key updated.")
            
            if new_use_uploader != self.use_uploader:
                self.use_uploader = new_use_uploader
                self._organizer.setPluginSetting(self.name(), "UseUploader", new_use_uploader)
                print("ModAuthorColumn UseUploader setting updated.")

            if hide_author_column != self.hide_author_column:
                self.hide_author_column = hide_author_column
                self._organizer.setPluginSetting(self.name(), "HideAuthorColumn", hide_author_column)
                print("ModAuthorColumn HideAuthorColumn setting updated")
                
            if force_requery:
                print("Forcing re-query of all mods")
                self._load_authors(True)
        return

    def tr(self, str):
        return QCoreApplication.translate("ModAuthorColumn", str)

    def __init__(self):
        super(ModAuthorColumn, self).__init__()
        self.manager = QNetworkAccessManager()
        self.manager.finished.connect(self._on_request_finished)
        self.base_url: str = NEXUS_API_URL
        self._requested_mods = set()

    def init(self, organiser=mobase.IOrganizer):
        self._organizer = organiser
        self._organizer.onUserInterfaceInitialized(self._onUserInterfaceInitialized)
        self.api_key = self._organizer.pluginSetting(self.name(), "api_key")
        self.use_uploader = self._organizer.pluginSetting(self.name(), "UseUploader")
        self.hide_author_column = self._organizer.pluginSetting(self.name(), "HideAuthorColumn")
        self._organizer.onPluginSettingChanged(self._onPluginSettingChanged)
        self._organizer.onPluginDisabled(self._onPluginDisabled)
        self._organizer.onPluginEnabled(self._onPluginEnabled)
        self._organizer.modList().onModInstalled(self._onModInstalled)
        return True

    # My Methods

    def _onPluginSettingChanged(self, *args):
        if not self.hide_author_column:
            self._load_authors()
            self._table.refresh_from_modlist()
        self._hide_table(self.hide_author_column)

    def _onModInstalled(self, mod_handle:mobase.IModInterface):
        self._get_author(mod_handle, True)

    def _onPluginDisabled(self, plugin:mobase.IPlugin):
        if self.name() == plugin.name():
            self._hide_table(True)

    def _onPluginEnabled(self, plugin:mobase.IPlugin):
        if self.name() == plugin.name():
            self._hide_table(self.hide_author_column)

    def _check_api_key_on_startup(self):
        if not self._organizer.isPluginEnabled(self.name()):
            return
        if not self.api_key:
            self._prompt_for_api_key("API Key missing!\n\nPlease enter your Nexus Mods API key to fetch mod authors.")
            return

        request = QNetworkRequest(QUrl(f"{self.base_url}/v1/users/validate.json"))
        request.setRawHeader(b"User-Agent", b"ModAuthorColumn/1.0")
        request.setRawHeader(b"apikey", self.api_key.encode('utf-8'))
        request.setRawHeader(b"accept", b"application/json")
        reply = self.manager.get(request)
        reply.setProperty("req_type", "startup_validation")

    def _prompt_for_api_key(self, message: str):
        QMessageBox.warning(None, "ModAuthorColumn - API Key Issue", message)
        self.display()

    def _onUserInterfaceInitialized(self, main_window: QMainWindow):
        central_widget = self._parentWidget().findChild(QWidget, 'centralWidget')
        if not central_widget:
            return
        categories_splitter = central_widget.findChild(QWidget, 'categoriesSplitter')
        if not categories_splitter:
            return
        splitter: QSplitter = categories_splitter.findChild(QSplitter, 'splitter')
        if not splitter:
            return
        layout_widget = splitter.findChild(QWidget, 'layoutWidget')
        if not layout_widget:
            return
        modlist_widget = layout_widget.findChild(QTreeView, 'modList')
        if not modlist_widget:
            return
        self._modlist_widget = modlist_widget

        self._mod_authors: dict = {}
        self._load_authors()

        self._modlist_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._table = ModAuthorTreeView(self._modlist_widget, self._current_modlist_order, self._get_author_text, self.tr)
        self._table.modeChanged.connect(self._on_table_mode_changed)

        self._table.refresh_from_modlist()
        self._table.resize_columns()

        self._resync_button = QPushButton("\u21ba Resync to modlist order")
        self._resync_button.setVisible(False)
        self._resync_button.clicked.connect(self._table.enter_synced_mode)

        parent_layout: QVBoxLayout = layout_widget.layout()
        idx = parent_layout.indexOf(self._modlist_widget)
        original_stretch = parent_layout.stretch(idx)
        parent_layout.removeWidget(self._modlist_widget)

        container = QWidget()
        self.h_layout = QHBoxLayout(container)
        self.h_layout.setContentsMargins(0, 0, 0, 0)
        self.h_layout.setSpacing(0)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._scrollbar = self._modlist_widget.verticalScrollBar()
        self._modlist_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._table_wrapper = QWidget()
        table_wrapper_layout = QVBoxLayout(self._table_wrapper)
        table_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        table_wrapper_layout.setSpacing(0)
        table_wrapper_layout.addWidget(self._table)
        table_wrapper_layout.addWidget(self._resync_button)
        
        self._table_wrapper.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._modlist_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.h_layout.addWidget(self._modlist_widget, 1)
        self.h_layout.addWidget(self._table_wrapper, 0)
        self.h_layout.addWidget(self._scrollbar)

        parent_layout.insertWidget(idx, container, original_stretch)

        self._check_api_key_on_startup()
        self._hide_table(self.hide_author_column)

    def _on_table_mode_changed(self, synced: bool):
        if synced:
            self._resync_button.setVisible(False)
            #Rotate position of stolen modlist's scrollbar to right of author column
            self.h_layout.removeWidget(self._scrollbar)
            self.h_layout.addWidget(self._scrollbar, 0)
        else:
            self._resync_button.setVisible(True)
            #Rotate position of author column to right of modlist's scrollbar
            self.h_layout.removeWidget(self._table_wrapper)
            self.h_layout.addWidget(self._table_wrapper, 0)

    def _hide_table(self, hide:bool=True):
        if hide or not self._organizer.isPluginEnabled(self.name()):
            self._table.hide()
            self._resync_button.hide()
        else:
            self._table.show()
            if not self._table.is_synced:
                self._resync_button.show()

    # data helpers

    def _get_author_from_api(self, game_name, mod_id, mod_name, ini_path):
        request = QNetworkRequest(QUrl(f"{self.base_url}/v1/games/{game_name}/mods/{mod_id}.json"))
        request.setRawHeader(b"User-Agent", b"ModAuthorColumn/1.0")
        request.setRawHeader(b"apikey", self.api_key.encode('utf-8'))
        request.setRawHeader(b"accept", b"application/json")
        self._requested_mods.add(mod_name)
        reply = self.manager.get(request)
        reply.setProperty("mo2_mod_name", mod_name) 
        reply.setProperty("ini_path", ini_path)
        return reply

    def _on_request_finished(self, reply: QNetworkReply):
        if reply.property("req_type") == "startup_validation":
            status_code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if ((reply.error() != QNetworkReply.NetworkError.NoError or status_code != 200)
                and status_code is not None):
                self.key_validated = False
                self._prompt_for_api_key("Your Nexus Mods API key failed to validate.\nIt may be invalid, expired, or you are offline.\n\nPlease update it.")
            elif status_code == None:
                self.key_validated = False
                print("ModAuthorColumn: No internet connection.")
            else:
                self.key_validated = True
                self._load_authors()
                print("ModAuthorColumn: API key successfully validated in the background.")
            reply.deleteLater()
            return
        
        mod_name = reply.property("mo2_mod_name")
        if mod_name is None:
            reply.deleteLater()
            return
        
        author = None    
        uploaded_by = None
        if reply.error() == QNetworkReply.NetworkError.NoError:
            response_data = reply.readAll().data().decode('utf-8')
            
            try:
                json_data = json.loads(response_data)
                
                author = json_data.get("author", UNKNOWN_AUTHOR)
                #name = json_data.get("name", "Unknown Mod Name")
                uploaded_by = json_data.get("uploaded_by", UNKNOWN_AUTHOR)

                if self.use_uploader:
                    self._mod_authors[mod_name] = uploaded_by
                else:
                    self._mod_authors[mod_name] = author

                #print(f"Mod Name: {name}\nMod Author: {author}]\nMod Uploader: {uploadedby}")

                # Save the author back to the mod's meta.ini so we don't need to re-request it from Nexus.
                ini_path = reply.property("ini_path")
                if ini_path:
                    ini = configparser.ConfigParser()
                    ini.read(ini_path, encoding='utf-8')
                    if not ini.has_section("ModAuthorColumn"):
                        ini.add_section("ModAuthorColumn")
                    ini.set("ModAuthorColumn", "author", author)
                    ini.set("ModAuthorColumn", "uploader", uploaded_by)
                    try:
                        with open(ini_path, "w", encoding="utf-8") as f:
                            ini.write(f)
                    except OSError as exc:
                        print(f"ModAuthorColumn: Failed to write author to {ini_path}: {exc}")

            except json.JSONDecodeError:
                print("ModAuthorColumn Error: Failed to parse JSON response.")
        else:
            print(f"ModAuthorColumn Network Error: {reply.errorString()}, {str(reply.error())}")
            
        reply.deleteLater()

        self._requested_mods.discard(mod_name)

        if (author is not None or uploaded_by is not None) and getattr(self, "_table", None) is not None:
            row = self._table.find_row_for_internal_name(mod_name)
            if row is not None:
                self._table.update_row_display(row)

        if not self._requested_mods and getattr(self, "_table", None) is not None:
            self._table.resize_columns()
            print("ModAuthorColumn: Querying of Mods Complete")
        return

    def _get_author(self, mod_handle:mobase.IModInterface, force_request=False):
        if mod_handle.isOverwrite() or mod_handle.isSeparator():
            return
        mod_name = mod_handle.name()
        if mod_handle.isForeign():
            if ':' in mod_name:
                self._mod_authors[mod_name] = mod_name[:mod_name.index(':')]
            return
        mod_ini_path = os.path.join(mod_handle.absolutePath(), "meta.ini")
        author = UNKNOWN_AUTHOR
        uploader = UNKNOWN_AUTHOR
        if not force_request and os.path.exists(mod_ini_path):
            ini = configparser.ConfigParser()
            ini.read(mod_ini_path, encoding='utf-8')
            if ini.has_section('ModAuthorColumn'):
                author = ini.get("ModAuthorColumn", "author", fallback=UNKNOWN_AUTHOR)
                uploader = ini.get("ModAuthorColumn", "uploader", fallback=UNKNOWN_AUTHOR)
                if not self.use_uploader:
                    self._mod_authors[mod_name] = author
                else:
                    self._mod_authors[mod_name] = uploader
        if not self.api_key or not self.key_validated:
            return
        if author == UNKNOWN_AUTHOR or uploader == UNKNOWN_AUTHOR or force_request:
            mod_id = mod_handle.nexusId()
            #Not a queriable nexus mod
            if mod_id <= 0:
                return
            internal_name = mod_handle.gameName()
            #Not a queriable nexus mod
            if internal_name == "":
                return
            #Get nexus mod name instead of mo2 internal name
            game_name = self.internal_to_nexus_game_names.get(internal_name)
            if game_name is None:
                game_plugin = self._organizer.getGame(internal_name)
                if game_plugin is None:
                    return
                game_name = game_plugin.gameNexusName()
                self.internal_to_nexus_game_names[internal_name] = game_name

            reply = self._get_author_from_api(game_name, mod_id, mod_name, mod_ini_path)
            if not reply:
                self._requested_mods.remove(mod_name)

    def _load_authors(self, force_request=False) -> dict:
        self._mod_authors:dict[str,str] = {mod: (UNKNOWN_AUTHOR if mod != "Overwrite" else mod) for mod in self._organizer.modList().allMods()}

        internal_instance_game_name = self._organizer.managedGame().gameName()
        instance_game_name = self._organizer.managedGame().gameNexusName()
        self.internal_to_nexus_game_names = {internal_instance_game_name: instance_game_name}

        for mod in self._mod_authors:
            mod_handle = self._organizer.modList().getMod(mod)
            self._get_author(mod_handle, force_request)
            
            
    def _get_author_text(self, internal_name: str, display_name: str) -> str:
        return self._mod_authors.get(internal_name, self._mod_authors.get(display_name, UNKNOWN_AUTHOR))

    def _resolve_internal_name(self, idx: QModelIndex, display_name: str, priority_list: list) -> str:
        model = self._modlist_widget.model()
        if model is not None:
            priority_idx = idx.sibling(idx.row(), PRIORITY_COL)
            raw_priority = model.data(priority_idx, Qt.ItemDataRole.DisplayRole)
            try:
                priority = int(raw_priority)
            except (TypeError, ValueError):
                priority = None
            if priority is not None and 0 <= priority < len(priority_list):
                return priority_list[priority]
        return display_name

    def _current_modlist_order(self):
        model = self._modlist_widget.model()
        if not model:
            keys = list(self._mod_authors.keys())
            return keys, keys, [None] * len(keys)

        priority_list = self._organizer.modList().allModsByProfilePriority()

        display_names = []
        internal_names = []
        indexes = []

        def walk(parent_index):
            for row in range(model.rowCount(parent_index)):
                idx = model.index(row, 0, parent_index)
                display_name = model.data(idx, Qt.ItemDataRole.DisplayRole)
                display_names.append(display_name)
                internal_names.append(self._resolve_internal_name(idx, display_name, priority_list))
                indexes.append(QPersistentModelIndex(idx))
                if model.hasChildren(idx):
                    walk(idx)

        walk(QModelIndex())
        return display_names, internal_names, indexes

def createPlugin() -> mobase.IPlugin:
    return ModAuthorColumn()