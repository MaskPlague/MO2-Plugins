# Written by MaskPlague and various AI
import mobase #type: ignore
import os
import configparser

from .SettingsDialog import SettingsDialog
from .AuthorTreeView import ModAuthorTreeView
from .Global import (PRIORITY_COL, 
                     MINIMUM_COL_WIDTH, DEFAULT_AUTHOR_NAME_COL_WIDTH, 
                     DEFAULT_MOD_NAME_COL_WIDTH, DEFAULT_TABLE_WIDTH)

try:
    from PyQt6.QtCore import Qt, QCoreApplication, QModelIndex, QPersistentModelIndex, QObject, QEvent, QSortFilterProxyModel
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QTreeView, QMainWindow, QSplitter, QVBoxLayout, QPushButton, QSizePolicy,
                                  QFrame, QStackedLayout, QMenu, QApplication, QCheckBox, QWidgetAction)
except ImportError:
    from PyQt5.QtCore import Qt, QCoreApplication, QModelIndex, QPersistentModelIndex, QObject, QEvent, QSortFilterProxyModel
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QTreeView, QMainWindow, QSplitter, QVBoxLayout, QPushButton, QSizePolicy,
                                  QFrame, QStackedLayout, QMenu, QApplication, QCheckBox, QWidgetAction)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PyQt6.QtCore import Qt, QCoreApplication, QModelIndex, QPersistentModelIndex, QObject, QEvent, QSortFilterProxyModel
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QTreeView, QMainWindow, QSplitter, QVBoxLayout, QPushButton, QSizePolicy,
                                  QFrame, QStackedLayout, QMenu, QApplication, QCheckBox, QWidgetAction)

class EventFilter(QObject):
    def __init__(self, isHidden, setHideAuthorColumn, model: QSortFilterProxyModel):
        self._isHidden = isHidden
        self._setHideAuthorColumn = setHideAuthorColumn
        self._model = model
        super().__init__()

    # Since the QMenu has no parent and no name we have to check if it is the context menu of the modlist header by counting and
    # checking the structure of the children of the menu
    def eventFilter(self, obj: QObject, event: QEvent):
        if event.type() == QEvent.Type.Show and isinstance(obj, QMenu) and not obj.parent():
            if self._model.columnCount()-1 == (len(obj.children()) - 1) / 2:
                children = obj.children()
                for i in range(1, len(children), 2):
                    is_widgetAction = isinstance(children[i], QWidgetAction)
                    is_checkBox = isinstance(children[i+1], QCheckBox)
                    if not is_checkBox or not is_widgetAction:
                        return False
                checkBox = QCheckBox()
                checkBox.setText(self.tr("Author"))
                checkBox.setChecked(not self._isHidden())

                widgetAction = QWidgetAction(obj)
                widgetAction.setDefaultWidget(checkBox)
                checkBox.checkStateChanged.connect(self._checkStateChanged)
                obj.addAction(widgetAction)
        return False

    def _checkStateChanged(self, state):
        self._setHideAuthorColumn(state != Qt.CheckState.Checked)

    def _isHidden(self):
        return False

    def _setHideAuthorColumn(self, value):
        return

class TableResizeHandle(QFrame):
    def __init__(self, table, parent=None):
        super().__init__(parent)
        self._table:ModAuthorTreeView = table
        self._dragging = False
        self._start_x = 0
        self._start_width = 0
        self.setFixedWidth(3)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def _global_x(self, event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint().x()
        return event.globalPos().x()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_x = self._global_x(event)
            self._start_width = self._table.width()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = self._start_x - self._global_x(event)
            col_width = self._table.columnWidth(1)
            overhead = self._table._get_overhead()
            if self._table._synced_to_modlist:
                if self._start_width + delta > MINIMUM_COL_WIDTH:
                    self._table.set_table_width(self._start_width + delta)
                else:
                    self._table.set_table_width(MINIMUM_COL_WIDTH)
            else:
                if self._start_width + delta > MINIMUM_COL_WIDTH + col_width + overhead:
                    self._table.set_table_width(self._start_width + delta)
                else:
                    self._table.set_table_width(MINIMUM_COL_WIDTH + col_width + overhead)
            if not self._table._synced_to_modlist:
                self._table.setColumnWidth(1, col_width)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

class ModAuthorColumn(mobase.IPluginTool):
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
        return mobase.VersionInfo(0, 1, 0, mobase.ReleaseType.FINAL)

    def settings(self):
        return [
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
        dialog = SettingsDialog(self.use_uploader, self.hide_author_column)

        if dialog.exec(): 
            new_use_uploader = dialog.use_uploader_checkbox.isChecked()
            force_requery = dialog.force_requery_checkbox.isChecked()
            hide_author_column = dialog.hide_author_column.isChecked()
            reset_widths = dialog.reset_widths.isChecked()

            reset_author_cache = dialog.reset_author_cache.isChecked()
            
            if new_use_uploader != self.use_uploader:
                self.use_uploader = new_use_uploader
                self._setPluginSetting("UseUploader", new_use_uploader)
                print("ModAuthorColumn UseUploader setting updated.")

            if hide_author_column != self.hide_author_column:
                self.hide_author_column = hide_author_column
                self._setPluginSetting("HideAuthorColumn", hide_author_column)
                print("ModAuthorColumn HideAuthorColumn setting updated")
                
            if force_requery:
                print("Forcing re-query of all mods")
                self._load_authors(True)

            if reset_widths:
                self._reset_table_widths()

            if reset_author_cache:
                self._reset_author_cache()
        return

    def tr(self, str):
        return QCoreApplication.translate("ModAuthorColumn", str)

    def __init__(self):
        super(ModAuthorColumn, self).__init__()
        self._requested_mods = set()

    def init(self, organiser=mobase.IOrganizer):
        self._organizer = organiser
        self._organizer.onUserInterfaceInitialized(self._onUserInterfaceInitialized)
        self.use_uploader = self._organizer.pluginSetting(self.name(), "UseUploader")
        self.hide_author_column = self._organizer.pluginSetting(self.name(), "HideAuthorColumn")
        self._organizer.onPluginSettingChanged(self._onPluginSettingChanged)
        self._organizer.onPluginDisabled(self._onPluginDisabled)
        self._organizer.onPluginEnabled(self._onPluginEnabled)
        self._organizer.modList().onModInstalled(self._onModInstalled)

        self._bridge = self._organizer.createNexusBridge()
        self._bridge.descriptionAvailable.connect(self._on_request_finished)
        self._bridge.requestFailed.connect(self._on_request_failed)
        return True

    # My Methods

    def _reset_table_widths(self):
        print("Resetting table widths")
        self._table.blockSignals(True)
        table_width = (DEFAULT_AUTHOR_NAME_COL_WIDTH + self._table._fullFrameWidth()
                        if self._table._synced_to_modlist 
                        else DEFAULT_TABLE_WIDTH + self._table._get_overhead())
        self._table.setFixedWidth(table_width)
        self._table.setColumnWidth(0, DEFAULT_MOD_NAME_COL_WIDTH)
        self._table.setColumnWidth(1, DEFAULT_AUTHOR_NAME_COL_WIDTH)
        self._table.blockSignals(False)
        self._table_wrapper.setFixedWidth(table_width)
        self._save_column_width(0, DEFAULT_MOD_NAME_COL_WIDTH)
        self._save_column_width(1, DEFAULT_AUTHOR_NAME_COL_WIDTH)

    def _reset_author_cache(self):
        print("Resetting author cache")
        self._mod_authors.clear()
        for mod in self._organizer.modList().allMods():
            mod_handle = self._organizer.modList().getMod(mod)
            if mod_handle.isOverwrite() or mod_handle.isSeparator():
                continue
            mod_ini_path = os.path.join(mod_handle.absolutePath(), "meta.ini")
            if os.path.exists(mod_ini_path):
                ini = configparser.ConfigParser()
                ini.read(mod_ini_path, encoding='utf-8')
                if ini.has_section('ModAuthorColumn'):
                    ini.remove_section('ModAuthorColumn')
                    try:
                        with open(mod_ini_path, "w", encoding="utf-8") as f:
                            ini.write(f)
                        print(f"ModAuthorColumn: Removed author cache for {mod_ini_path}")
                    except OSError as exc:
                        print(f"ModAuthorColumn: Failed to remove author cache in {mod_ini_path}: {exc}")

    _COLUMN_WIDTH_KEYS = {0: "ModNameColumnWidth", 1: "AuthorColumnWidth"}

    def _load_column_width(self, column: int):
        key = self._COLUMN_WIDTH_KEYS.get(column)
        value = self._organizer.persistent(self.name(), key, None)
        return int(value) if value is not None else None

    def _save_column_width(self, column: int, width: int):
        key = self._COLUMN_WIDTH_KEYS.get(column)
        if width != 0:
            self._organizer.setPersistent(self.name(), key, width, sync=False)

    def _onPluginSettingChanged(self, *args):
        if not self.hide_author_column:
            self._load_authors()
            self._table.refresh_from_modlist()
        self._hide_table(self.hide_author_column)

    def _setPluginSetting(self, key, value):
        self._organizer.setPluginSetting(self.name(), key, value)

    def _setHideAuthorColumn(self, value):
        self.hide_author_column = value
        self._setPluginSetting("HideAuthorColumn", value)

    def _onModInstalled(self, mod_handle:mobase.IModInterface):
        self._get_author(mod_handle, True)

    def _onPluginDisabled(self, plugin:mobase.IPlugin):
        if self.name() == plugin.name():
            self._hide_table(True)

    def _onPluginEnabled(self, plugin:mobase.IPlugin):
        if self.name() == plugin.name():
            self._hide_table(self.hide_author_column)

    def _isHidden(self):
        return self.hide_author_column

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

        self.event_filter = EventFilter(self._isHidden,self._setHideAuthorColumn, self._modlist_widget.model())
        QApplication.instance().installEventFilter(self.event_filter)

        self._mod_authors: dict = {}
        self._load_authors()

        self._modlist_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table_wrapper = QWidget()
        self._table_wrapper.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._table = ModAuthorTreeView(self._modlist_widget, self._current_modlist_order, self._get_author_text, 
                                        self.tr, self._load_column_width, self._save_column_width, self._save_user_set_name,
                                        self._context_menu)
        self._table.modeChanged.connect(self._on_table_mode_changed)

        self._table.refresh_from_modlist()
        self._table.resize_columns()

        self._resync_button = QPushButton(self.tr("\u21ba Resync to modlist order"))
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

        table_wrapper_layout = QStackedLayout(self._table_wrapper)
        table_wrapper_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        table_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        table_wrapper_layout.setSpacing(0)

        # Thin draggable edge on the left side of the entire author table.
        self._table_handle = TableResizeHandle(self._table, self._table_wrapper)
        
        table_content = QWidget()
        table_content_layout = QVBoxLayout(table_content)
        table_content_layout.setContentsMargins(0, 0, 0, 0)
        table_content_layout.setSpacing(0)
        table_content_layout.addWidget(self._table)
        table_content_layout.addWidget(self._resync_button)
        table_wrapper_layout.addWidget(self._table_handle)
        table_wrapper_layout.addWidget(table_content)
        
        self._table.tableWidthChanged.connect(self._on_table_width_changed)

        self._modlist_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.h_layout.addWidget(self._modlist_widget, 1)
        self.h_layout.addWidget(self._table_wrapper, 0)
        self.h_layout.addWidget(self._scrollbar)

        parent_layout.insertWidget(idx, container, original_stretch)

        self._hide_table(self.hide_author_column)

    def _context_menu(self, position):
        menu = QMenu()
        def create_checkbox(text, state):
            checkbox = QCheckBox()
            checkbox.setText(text)
            checkbox.setChecked(state)
            action = QWidgetAction(menu)
            action.setDefaultWidget(checkbox)
            menu.addAction(action)
            return checkbox
        visibility_checkBox = create_checkbox(self.tr("Show Author Col"), not self._isHidden())
        def _visibilityStateChanged(state):
            self._setHideAuthorColumn(state != Qt.CheckState.Checked)
        visibility_checkBox.checkStateChanged.connect(_visibilityStateChanged)

        uploader_checkBox = create_checkbox(self.tr("Uploader Instead"), self.use_uploader)
        def _uploaderStateChanged(state):
            value = state == Qt.CheckState.Checked
            self.use_uploader = value
            self._setPluginSetting("UseUploader", value)
        uploader_checkBox.checkStateChanged.connect(_uploaderStateChanged)

        width_checkBox = create_checkbox(self.tr("Reset Width"), False)
        def _resetWidthClicked(state):
            self._reset_table_widths()
            width_checkBox.setChecked(False)
        
        width_checkBox.clicked.connect(_resetWidthClicked)

        menu.exec(self._table.viewport().mapToGlobal(position))

    def _on_table_width_changed(self, width: int):
        self._table_wrapper.setFixedWidth(width)

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
            self._table_wrapper.hide()
            self._resync_button.hide()
        else:
            self._table_wrapper.show()
            if not self._table.is_synced:
                self._resync_button.show()

    # data helpers

    def _get_author_from_nexus(self, game_name, mod_id, mod_name, ini_path):
        self._requested_mods.add(mod_name)
        self._bridge.requestDescription(game_name, mod_id, (mod_name, ini_path))
        return

    def _save_user_set_name(self, mod_name:str, set_name:str):
        if self._mod_authors[mod_name] == set_name.strip():
            return set_name
        mod_handle = self._organizer.modList().getMod(mod_name)
        if mod_handle:
            ini_path = os.path.join(mod_handle.absolutePath(), "meta.ini")
            if os.path.exists(ini_path):
                ini = configparser.ConfigParser()
                ini.read(ini_path, encoding='utf-8')
                if not ini.has_section("ModAuthorColumn"):
                    ini.add_section("ModAuthorColumn")
                key = "usersetauthor" if not self.use_uploader else "usersetuploader"
                if set_name == '':
                    if ini.has_option("ModAuthorColumn", key):
                        ini.remove_option("ModAuthorColumn", key)
                    key = "author" if not self.use_uploader else "uploader"
                    set_name = ini.get("ModAuthorColumn", key, fallback=None)
                    self._mod_authors[mod_name] = set_name
                else:
                    ini.set("ModAuthorColumn", key, set_name)
                try:
                    with open(ini_path, "w", encoding="utf-8") as f:
                        ini.write(f)
                except:
                    pass
        return set_name

    def _on_request_finished(self, *args):
        # args: 0:game_name, 1:mod_id, 2:user_data(mod_name, ini_path), 3:nexus json data
        mod_name = args[2][0]
        ini_path = args[2][1]
        description:dict = args[3]
        author = description.get('author', None)
        uploaded_by = description.get('uploaded_by', None)

        if self.use_uploader:
            self._mod_authors[mod_name] = uploaded_by
        else:
            self._mod_authors[mod_name] = author

        # Save the author back to the mod's meta.ini so we don't need to re-request it from Nexus.
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

        self._requested_mods.discard(mod_name)

        if (author is not None or uploaded_by is not None) and getattr(self, "_table", None) is not None:
            row = self._table.find_row_for_internal_name(mod_name)
            if row is not None:
                self._table.update_row_display(row)

        if not self._requested_mods and getattr(self, "_table", None) is not None:
            self._table.resize_columns()
            print("ModAuthorColumn: Querying of Mods Complete")
        return

    
    def _on_request_failed(self, *args):
        #args: game_name, mod_id, idk 0, user_data, idk 0, error message
        self._requested_mods.discard(args[3][0])
        print(f"ModAuthorColumn: Nexus Request Failed: {args[5]}")

    def _get_author(self, mod_handle:mobase.IModInterface, force_request=False):
        if mod_handle.isOverwrite() or mod_handle.isSeparator():
            return
        mod_name = mod_handle.name()
        if mod_handle.isForeign():
            if ':' in mod_name:
                self._mod_authors[mod_name] = mod_name[:mod_name.index(':')]
            return
        mod_ini_path = os.path.join(mod_handle.absolutePath(), "meta.ini")
        author = None
        uploader = None
        if not force_request and os.path.exists(mod_ini_path):
            ini = configparser.ConfigParser()
            ini.read(mod_ini_path, encoding='utf-8')
            if ini.has_section('ModAuthorColumn'):
                author = ini.get("ModAuthorColumn", "author", fallback=None)
                uploader = ini.get("ModAuthorColumn", "uploader", fallback=None)
                user_set_author = ini.get("ModAuthorColumn", "usersetauthor", fallback=None)
                user_set_uploader = ini.get("ModAuthorColumn", "usersetuploader", fallback=None)
                if not self.use_uploader:
                    self._mod_authors[mod_name] = author if not user_set_author else user_set_author
                else:
                    self._mod_authors[mod_name] = uploader if not user_set_uploader else user_set_uploader

        if author == None or uploader == None or force_request:
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

            self._get_author_from_nexus(game_name, mod_id, mod_name, mod_ini_path)

    def _load_authors(self, force_request=False) -> dict:
        self._mod_authors:dict[str,str] = {mod: (None if mod != "Overwrite" else mod) for mod in self._organizer.modList().allMods()}

        internal_instance_game_name = self._organizer.managedGame().gameName()
        instance_game_name = self._organizer.managedGame().gameNexusName()
        self.internal_to_nexus_game_names = {internal_instance_game_name: instance_game_name}

        for mod in self._mod_authors:
            mod_handle = self._organizer.modList().getMod(mod)
            self._get_author(mod_handle, force_request)
            
            
    def _get_author_text(self, internal_name: str, display_name: str) -> str:
        return self._mod_authors.get(internal_name, self._mod_authors.get(display_name, None))

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