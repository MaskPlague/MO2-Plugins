# Written by MaskPlague and various AI
import mobase #type: ignore
import os
import configparser
import base64
import webbrowser

from .SettingsDialog import SettingsDialog
from .AuthorColumnProxy import TreeExtraColumnProxy
from .EventFilters import ColumnContextMenuFilter, StyleSheetOverlay
from .UrlEditorDialog import UrlDialog
from .Global import UNKNOWN_AUTHOR, DEFAULT_AUTHOR_COL_WIDTH

try:
    from PyQt6.QtCore import Qt, QCoreApplication, QTimer, QItemSelectionModel, QItemSelection, QModelIndex
    from PyQt6.QtGui import QIcon, QAction
    from PyQt6.QtWidgets import QTreeView, QMainWindow, QMenu, QInputDialog, QLineEdit, QHeaderView, QApplication, QPushButton, QLCDNumber
except ImportError:
    from PyQt5.QtCore import Qt, QCoreApplication, QTimer, QItemSelectionModel, QItemSelection, QModelIndex
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QTreeView, QMainWindow, QMenu, QInputDialog, QLineEdit, QHeaderView, QApplication, QPushButton, QLCDNumber, QAction

SECTION = "ModAuthorColumn"
WIDTH_KEY = "AuthorColumnWidth"
STATE_KEY = "HeaderState"


def _read_ini(path: str):
    """Read a meta.ini preserving key case and without % interpolation. None if unreadable."""
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    ini.optionxform = str  # type: ignore  # default lower-cases every key in MO2's meta.ini
    try:
        ini.read(path, encoding='utf-8')
    except (configparser.Error, OSError, UnicodeDecodeError) as exc:
        print(f"ModAuthorColumn: Could not read {path}: {exc}")
        return None
    return ini


def _write_ini(path: str, ini: configparser.ConfigParser) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            ini.write(f)
        return True
    except OSError as exc:
        print(f"ModAuthorColumn: Failed to write {path}: {exc}")
        return False


def _to_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


class ModAuthorColumn(mobase.IPluginTool):
    use_uploader = False
    hide_author_column = False
    double_click_edit = False
    auto_expand_separators = True
    _organizer: mobase.IOrganizer = None
    _modlist_widget: QTreeView = None
    _proxy: TreeExtraColumnProxy = None

    # Required IPluginTool methods

    def name(self) -> str:
        return "ModAuthorColumn"

    def author(self) -> str:
        return "MaskPlague"

    def description(self) -> str:
        return self.tr("Adds a mod author column to the modlist")

    def version(self):
        return mobase.VersionInfo(0, 2, 0, mobase.ReleaseType.FINAL)

    def settings(self):
        return [
            mobase.PluginSetting("UseUploader", "If set to True, use the Uploader instead of the Author", False),
            mobase.PluginSetting("HideAuthorColumn", "Hides the Author Column", False),
            mobase.PluginSetting("DoubleClickEdit", "Double-click an author/uploader cell to edit it", False),
            mobase.PluginSetting("AutoExpandSeparators", "Expand separators while a filter is active", True)
        ]

    def displayName(self):
        return self.tr("ModAuthorColumn")

    def tooltip(self):
        return self.tr("Adds a mod author column to the modlist")

    def icon(self):
        return QIcon(None)

    def display(self):
        dialog = SettingsDialog(self.use_uploader, self.hide_author_column, self.double_click_edit,
                                self.auto_expand_separators)

        if dialog.exec():
            new_use_uploader = dialog.use_uploader_checkbox.isChecked()
            hide_author_column = dialog.hide_author_column.isChecked()
            double_click_edit = dialog.double_click_edit_checkbox.isChecked()
            auto_expand = dialog.auto_expand_checkbox.isChecked()

            if new_use_uploader != self.use_uploader:
                self._setPluginSetting("UseUploader", new_use_uploader)
                self._apply_use_uploader(new_use_uploader)
                print("ModAuthorColumn UseUploader setting updated.")

            if hide_author_column != self.hide_author_column:
                self._setPluginSetting("HideAuthorColumn", hide_author_column)
                self._apply_hidden(hide_author_column)
                print("ModAuthorColumn HideAuthorColumn setting updated")

            if double_click_edit != self.double_click_edit:
                self.double_click_edit = double_click_edit
                self._setPluginSetting("DoubleClickEdit", double_click_edit)

            if auto_expand != self.auto_expand_separators:
                self._setPluginSetting("AutoExpandSeparators", auto_expand)
                self._apply_auto_expand(auto_expand)

            if dialog.force_requery_checkbox.isChecked():
                print("Forcing re-query of all mods")
                self._reset_names_on_request = dialog.reset_user_names_checkbox.isChecked()
                try:
                    self._load_authors(True)
                finally:
                    self._reset_names_on_request = False
                self._proxy.refresh_column()

            if dialog.reset_widths.isChecked():
                self._reset_column_width()

            if dialog.reset_author_cache.isChecked():
                self._reset_author_cache()

    def tr(self, str):
        return QCoreApplication.translate("ModAuthorColumn", str)

    def __init__(self):
        super(ModAuthorColumn, self).__init__()
        self._requested_mods = set()
        self._mod_authors: dict = {}
        self._urls: dict = {}
        self._editable_cache: dict = {}
        self.internal_to_nexus_game_names: dict = {}
        self._header_text = ""
        self._column = -1
        self._applying_visibility = False
        self._expanded_names: set = set()
        self._filter_edit = None
        self._mo2_filter_edit = None
        self._was_filtering = False
        self._touched_during_filter: set = set()
        self._hold_sizes = None      # {section: width} pinned while a filter is active
        self._held_modes: dict = {}   # sections we switched from ResizeToContents to Interactive
        self._last_sizes: dict = {}   # most recent widths seen while no filter was active
        self._guard_widths = False
        self._moving_sections = False
        self._last_state = None  # last header state we saved
        self._reset_names_on_request = False
        self._reset_names_pending: set = set()
        self._normalizing_selection = False
        self._normalize_pending = False
        self._restoring_expanded = False
        self._restore_pending = False

    def init(self, organiser=mobase.IOrganizer):
        self._organizer = organiser
        self._organizer.onUserInterfaceInitialized(self._onUserInterfaceInitialized)
        self.use_uploader = _to_bool(self._organizer.pluginSetting(self.name(), "UseUploader"))
        self.hide_author_column = _to_bool(self._organizer.pluginSetting(self.name(), "HideAuthorColumn"))
        self.double_click_edit = _to_bool(self._organizer.pluginSetting(self.name(), "DoubleClickEdit"))
        self.auto_expand_separators = _to_bool(self._organizer.pluginSetting(self.name(), "AutoExpandSeparators"))
        self._update_name_text()
        self._organizer.onPluginSettingChanged(self._onPluginSettingChanged)
        self._organizer.onPluginDisabled(self._onPluginDisabled)
        self._organizer.onPluginEnabled(self._onPluginEnabled)
        self._organizer.modList().onModInstalled(self._onModInstalled)

        self._bridge = self._organizer.createNexusBridge()
        self._bridge.descriptionAvailable.connect(self._on_request_finished)
        self._bridge.requestFailed.connect(self._on_request_failed)
        return True

    # UI setup

    def _onUserInterfaceInitialized(self, main_window: QMainWindow):
        modlist_widget = main_window.findChild(QTreeView, 'modList')
        self._modlist_widget = modlist_widget

        self._load_authors()

        self._proxy = TreeExtraColumnProxy(
            self._header_text,
            value_getter=self._get_cell_value,
            value_setter=self._save_user_set_name,
            editable_getter=self._is_editable,
            unknown_text=UNKNOWN_AUTHOR,
            parent=modlist_widget,
        )
        source_model = modlist_widget.model()
        # Swapping the view's model drops its expanded state, so remember it and re-apply it.
        expanded = self._expanded_separator_names(modlist_widget, source_model)
        self._proxy.setSourceModel(source_model)
        original_selection_model = modlist_widget.selectionModel()
        modlist_widget.setModel(self._proxy)
        # MO2 refreshes its conflict markers from the original selection model's signal, which
        # setModel replaced; relay selection changes to it so MO2 keeps highlighting.
        modlist_widget.selectionModel().selectionChanged.connect(
            lambda *_: original_selection_model.selectionChanged.emit(QItemSelection(), QItemSelection()))
        self._expanded_names = set(expanded)
        self._restore_expanded()
        # The view forgets expanded separators whenever MO2 rebuilds the tree (e.g. when the sort
        # leaves and returns to priority), so keep our own record and re-apply it.
        modlist_widget.expanded.connect(lambda i: self._track_expanded(i, True))
        modlist_widget.collapsed.connect(lambda i: self._track_expanded(i, False))
        self._proxy.modelReset.connect(self._schedule_restore_expanded)
        self._proxy.layoutChanged.connect(self._schedule_restore_expanded)
        self._proxy.rowsInserted.connect(self._schedule_restore_expanded)

        header = modlist_widget.header()
        self._column = self._proxy.extra_column()
        saved_width = self._load_column_width()
        header.resizeSection(self._column, saved_width if saved_width else DEFAULT_AUTHOR_COL_WIDTH)
        self._restore_header_state()
        self._last_sizes = {i: header.sectionSize(i) for i in range(header.count()) if not header.isSectionHidden(i)}
        self._setup_filter_box(modlist_widget)
        self._apply_hidden(self.hide_author_column)
        header.sectionResized.connect(self._on_section_resized)
        header.sectionMoved.connect(self._on_section_moved)
        header.sortIndicatorChanged.connect(self._on_sort_indicator_changed)
        # QHeaderView has no signal for hide/show, so notice toggles made through MO2's own
        # header context menu by polling.
        self._visibility_timer = QTimer(modlist_widget)
        self._visibility_timer.setInterval(1000)
        self._visibility_timer.timeout.connect(self._sync_hidden_from_header)
        self._visibility_timer.start()

        modlist_widget.selectionModel().selectionChanged.connect(self._schedule_normalize_selection)
        for signal in (self._proxy.layoutChanged, self._proxy.rowsMoved, self._proxy.rowsInserted,
                       self._proxy.rowsRemoved, self._proxy.modelReset, self._proxy.dataChanged):
            signal.connect(self._schedule_normalize_selection)

        self._menu_filter = ColumnContextMenuFilter(modlist_widget, lambda: self._column,
                                                    self._show_cell_menu, self._on_cell_double_clicked,
                                                    modlist_widget.viewport())
        modlist_widget.viewport().installEventFilter(self._menu_filter)

    def _schedule_normalize_selection(self, *_):
        if not self._normalize_pending and not self._normalizing_selection:
            self._normalize_pending = True
            QTimer.singleShot(0, self._normalize_selection)

    def _normalize_selection(self):
        """Make row selection all-or-nothing: a row with its name cell selected is selected completely.

        Partial rows appear after MO2 re-selects a dropped mod using only the columns it knows about,
        or when the selection's persistent ranges get remapped by a layout change (no selectionChanged
        signal is emitted for that), so this runs after both."""
        self._normalize_pending = False
        model = self._modlist_widget.selectionModel()
        ncols = self._proxy.columnCount()
        columns = {}  # (row, parent row, parent col) -> [row, parent, set of selected columns]
        for rng in model.selection():
            parent = rng.parent()
            if parent.isValid() and parent.model() != self._proxy:
                parent = self._proxy.mapFromSource(parent)  # index of MO2's own model
            span = range(rng.left(), min(rng.right(), ncols - 1) + 1)
            for row in range(rng.top(), rng.bottom() + 1):
                entry = columns.setdefault((row, parent.row(), parent.column()), [row, parent, set()])
                entry[2].update(span)
        flags = QItemSelectionModel.SelectionFlag
        self._normalizing_selection = True
        try:
            for row, parent, cols in columns.values():
                if len(cols) >= ncols:
                    continue
                index = self._proxy.index(row, 0, parent)
                # Name cell selected: the row is meant to be selected, complete it. Otherwise it is a
                # stray fragment (typically left behind at a moved row's old position), so clear it.
                model.select(index, (flags.Select if 0 in cols else flags.Deselect) | flags.Rows)
        finally:
            self._normalizing_selection = False

    def _setup_filter_box(self, modlist_widget: QTreeView):
        """A small Author/Uploader filter field beside MO2's own filter, which is the horizontal layout
        right below the modlist."""
        self._filter_edit = QLineEdit()
        self._update_filter_placeholder()
        self._filter_timer = QTimer(self._filter_edit)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(lambda: self._apply_author_filter(self._filter_edit.text()))
        self._filter_edit.textChanged.connect(lambda *_: self._filter_timer.start())

        layout = modlist_widget.parentWidget().layout()
        h_layout = layout.itemAt(layout.indexOf(modlist_widget) + 1).layout()
        self._mo2_filter_edit:QLineEdit = next(h_layout.itemAt(i).widget() for i in range(h_layout.count())
                                     if isinstance(h_layout.itemAt(i).widget(), QLineEdit))
        h_layout.addWidget(self._filter_edit)
        # Same broom button as MO2's own filter, shown only while our filter has text.
        mo2_clear = modlist_widget.window().findChild(QPushButton, "clearFiltersButton")
        self._clear_action = QAction(mo2_clear.icon(), "Clear", self._filter_edit)
        self._clear_action.setVisible(True)
        self._filter_edit.addAction(self._clear_action, QLineEdit.ActionPosition.TrailingPosition)
        self._clear_action.triggered.connect(self._filter_edit.clear)
        self._clear_action.setVisible(False)

        # Make "Clear all Filters" button clear our filter too and make it visible if either filter has text.
        mo2_clear.clicked.connect(self._filter_edit.clear)
        def clear_buttons_visibility(my_clear: bool):
            self._clear_action.setVisible(my_clear)
            mo2_clear.setVisible(bool(self._mo2_filter_edit.text()) or my_clear)
        self._filter_edit.textChanged.connect(lambda text: clear_buttons_visibility(bool(text)))

        # MO2 only counts the mods its own filter shows; recount whenever the visible rows change.
        self._counter = modlist_widget.window().findChild(QLCDNumber, "activeModsCounter")
        self._counter_timer = QTimer(self._counter)
        self._counter_timer.setSingleShot(True)
        self._counter_timer.setInterval(100)  # after MO2's own update, which this replaces
        self._counter_timer.timeout.connect(self._update_active_counter)
        for signal in (self._proxy.layoutChanged, self._proxy.rowsInserted, self._proxy.rowsRemoved,
                       self._proxy.modelReset, self._filter_edit.textChanged):
            signal.connect(lambda *_: self._counter_timer.start())
        # MO2 outlines the list in red while its filter is active; do the same for ours.
        filter_active = lambda: bool(self._proxy.filter_text.strip())
        self._border = StyleSheetOverlay(modlist_widget, filter_active, "QTreeView { border: 2px ridge #f00; } /* ModAuthorColumn */")
        self._counter_border = StyleSheetOverlay(self._counter, filter_active, "QLCDNumber { border: 2px ridge #f00; } /* ModAuthorColumn */")
        self._mo2_filter_edit.textChanged.connect(lambda *_: self._on_filter_state_changed())
        self._mo2_filter_edit.textChanged.connect(lambda *_: clear_buttons_visibility(bool(self._filter_edit.text())))

    def _update_active_counter(self):
        """Show how many enabled, regular mods are visible through both MO2's filter and ours."""
        mod_list = self._organizer.modList()
        count = 0
        pending = [QModelIndex()]
        while pending:
            parent = pending.pop()
            for row in range(self._proxy.rowCount(parent)):
                index = self._proxy.index(row, 0, parent)
                if self._proxy.hasChildren(index):
                    pending.append(index)
                name = self._proxy.item_name(index)
                handle = mod_list.getMod(name)
                if (handle and not (handle.isOverwrite() or handle.isSeparator() or handle.isForeign())
                        and mod_list.state(name) & mobase.ModState.ACTIVE):
                    count += 1
        self._counter.display(count)

    def _update_filter_placeholder(self):
        self._filter_edit.setPlaceholderText(self.tr("Filter by %1").replace("%1", self._header_text))

    # Filtering: header width guard and filter state

    def _apply_author_filter(self, text: str):
        if text.strip() and not self._was_filtering:
            self._begin_hold()  # before the rows change, so the old widths are what gets held
        self._proxy.set_filter(text)
        self._border.update()
        self._counter_border.update()
        self._enforce_hold()
        self._on_filter_state_changed()

    def _filter_active(self) -> bool:
        return bool(self._mo2_filter_edit.text().strip()) or bool(self._proxy.filter_text)

    def _on_filter_state_changed(self):
        active = self._filter_active()
        if active:
            self._begin_hold()
        else:
            self._end_hold()
        if active != self._was_filtering:
            self._touched_during_filter.clear()
        self._was_filtering = active
        self._schedule_restore_expanded()

    def _track_expanded(self, index, expanded: bool):
        if self._restoring_expanded:
            return
        name = self._proxy.item_name(index)
        if self._was_filtering:
            self._touched_during_filter.add(name)
        if expanded:
            self._expanded_names.add(name)
        else:
            self._expanded_names.discard(name)

    def _schedule_restore_expanded(self, *_):
        if not self._restore_pending:
            self._restore_pending = True
            QTimer.singleShot(0, self._restore_expanded)

    def _restore_expanded(self):
        """Apply the wanted expanded state to every separator.

        Without a filter that is simply the user's own record. While a filter is active every separator
        that still shows mods is expanded (when the auto-expand setting is on), except those the user toggled during the search; the
        automatic expansion is never written to the record, so it is undone when the filter clears."""
        self._restore_pending = False
        filtering = self._was_filtering
        self._restoring_expanded = True
        try:
            for row in range(self._proxy.rowCount()):
                index = self._proxy.index(row, 0)
                if not self._proxy.hasChildren(index):
                    continue
                name = self._proxy.item_name(index)
                if filtering and self.auto_expand_separators and name not in self._touched_during_filter:
                    want = True
                else:
                    want = name in self._expanded_names
                if self._modlist_widget.isExpanded(index) != want:
                    self._modlist_widget.setExpanded(index, want)
        finally:
            self._restoring_expanded = False

    @staticmethod
    def _expanded_separator_names(view: QTreeView, model) -> set:
        names = set()
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            if model.hasChildren(index) and view.isExpanded(index):
                names.add(str(model.data(index, Qt.ItemDataRole.DisplayRole)))
        return names

    # Column visibility / width

    def _apply_hidden(self, hidden: bool):
        self.hide_author_column = hidden
        if self._proxy is None:  # events can fire before the UI exists
            return
        self._applying_visibility = True
        try:
            hide = hidden or not self._organizer.isPluginEnabled(self.name())
            self._modlist_widget.header().setSectionHidden(self._column, hide)
            self._filter_edit.setVisible(not hide)
            if hide:
                self._filter_edit.clear()
                self._apply_author_filter("")
        finally:
            self._applying_visibility = False

    def _on_section_resized(self, logical: int, old_size: int, new_size: int):
        if self._guard_widths:
            return
        user_drag = QApplication.mouseButtons() != Qt.MouseButton.NoButton
        if self._hold_sizes is not None:
            if user_drag:
                self._hold_sizes[logical] = new_size
            elif new_size > 0 and logical in self._hold_sizes and new_size != self._hold_sizes[logical]:
                # Something other than the user (MO2 or Qt re-fitting after the filter) resized a column.
                self._set_section_size(logical, self._hold_sizes[logical])
                return
        elif new_size > 0:
            self._last_sizes[logical] = new_size
        if logical == self._column and new_size > 0 and not self._applying_visibility:
            self._save_column_width(new_size)

    def _set_section_size(self, logical: int, width: int):
        self._guard_widths = True
        try:
            self._modlist_widget.header().resizeSection(logical, width)
        finally:
            self._guard_widths = False

    def _begin_hold(self):
        """Pin all column widths for the duration of a filter."""
        if self._hold_sizes is not None:
            return
        header = self._modlist_widget.header()
        self._hold_sizes = {i: self._last_sizes.get(i, header.sectionSize(i))
                            for i in range(header.count()) if not header.isSectionHidden(i)}
        self._guard_widths = True
        try:
            for i in self._hold_sizes.copy():
                mode = header.sectionResizeMode(i)
                if mode == QHeaderView.ResizeMode.ResizeToContents:
                    self._held_modes[i] = mode
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        finally:
            self._guard_widths = False
        self._enforce_hold()

    def _enforce_hold(self):
        if self._hold_sizes is None:
            return
        header = self._modlist_widget.header()
        for i, width in self._hold_sizes.items():
            if header.sectionSize(i) != width and not header.isSectionHidden(i):
                self._set_section_size(i, width)

    def _end_hold(self):
        if self._hold_sizes is None:
            return
        self._hold_sizes = None
        header = self._modlist_widget.header()
        self._guard_widths = True
        try:
            for i, mode in self._held_modes.items():
                header.setSectionResizeMode(i, mode)
            self._held_modes.clear()
        finally:
            self._guard_widths = False

    def _on_sort_indicator_changed(self, section: int, order):
        # Our column sorts itself; any other column means our sort must step aside.
        self._proxy.set_extra_sort(order if section == self._column else None)
        if section == self._column:
            # MO2 may move the sort arrow to another column while flattening; put it back.
            QTimer.singleShot(0, self._restore_sort_arrow)

    def _restore_sort_arrow(self):
        header = self._modlist_widget.header()
        if self._proxy.sort_active and header.sortIndicatorSection() != self._column:
            header.blockSignals(True)
            header.setSortIndicator(self._column, self._proxy.sort_order)
            header.blockSignals(False)

    def _sync_hidden_from_header(self):
        """The user toggled the column through MO2's own header menu: remember it."""
        if self._applying_visibility or not self._organizer.isPluginEnabled(self.name()):
            return
        self._track_header_state()
        hidden = self._modlist_widget.header().isSectionHidden(self._column)
        if hidden != self.hide_author_column:
            self.hide_author_column = hidden
            self._setPluginSetting("HideAuthorColumn", hidden)

    # Header state (column order, widths, hidden columns)
    #
    # MO2 restores its own saved header state at startup, before this plugin adds its column. That state
    # was saved with the extra column included, so Qt applies sizes and hidden flags one position off for
    # every column after our column's position. We therefore save the complete header state ourselves and
    # restore it once the column exists and the column count matches again.

    def _restore_header_state(self):
        header = self._modlist_widget.header()
        raw = self._organizer.persistent(self.name(), STATE_KEY, None)
        try:
            count, _, blob = str(raw).partition("|")
            if int(count) == header.count():
                header.restoreState(base64.b64decode(blob))
        except (TypeError, ValueError):
            pass
        self._keep_off_first_position()
        self._last_state = header.saveState().data()

    def _track_header_state(self):
        if self._hold_sizes is not None:  # widths and modes are temporarily changed during a filter
            return
        header = self._modlist_widget.header()
        state = header.saveState().data()
        if state != self._last_state:
            self._last_state = state
            self._organizer.setPersistent(self.name(), STATE_KEY,
                                          f"{header.count()}|{base64.b64encode(state).decode('ascii')}", sync=False)

    def _keep_off_first_position(self):
        """Qt draws the tree's expand arrows and indentation in the visually first column, which must stay
        a real mod column, so our extra column may not be dragged to the front."""
        header = self._modlist_widget.header()
        if header.visualIndex(self._column) == 0:
            self._moving_sections = True
            try:
                header.moveSection(0, 1)
            finally:
                self._moving_sections = False

    def _on_section_moved(self, logical: int, old_visual: int, new_visual: int):
        if self._moving_sections:
            return
        self._keep_off_first_position()
        self._track_header_state()

    def _reset_column_width(self):
        self._modlist_widget.header().resizeSection(self._column, DEFAULT_AUTHOR_COL_WIDTH)
        self._save_column_width(DEFAULT_AUTHOR_COL_WIDTH)

    def _load_column_width(self):
        value = self._organizer.persistent(self.name(), WIDTH_KEY, None)
        return int(value) if value is not None else None

    def _save_column_width(self, width: int):
        if width > 0:
            self._organizer.setPersistent(self.name(), WIDTH_KEY, width, sync=False)

    # Plugin events

    def _onPluginSettingChanged(self, plugin_name, setting, old_value, new_value):
        if plugin_name != self.name():
            return
        if setting == "UseUploader":
            self._apply_use_uploader(_to_bool(new_value))
        elif setting == "HideAuthorColumn":
            self._apply_hidden(_to_bool(new_value))
        elif setting == "DoubleClickEdit":
            self.double_click_edit = _to_bool(new_value)
        elif setting == "AutoExpandSeparators":
            self._apply_auto_expand(_to_bool(new_value))

    def _apply_auto_expand(self, value: bool):
        self.auto_expand_separators = value
        self._schedule_restore_expanded()

    def _apply_use_uploader(self, value: bool):
        if value == self.use_uploader and self._header_text == self._header_for(value):
            return
        self.use_uploader = value
        self._update_name_text()
        if self._proxy is not None:
            self._load_authors()
            self._proxy.refresh_column()

    def _setPluginSetting(self, key, value):
        self._organizer.setPluginSetting(self.name(), key, value)

    def _onModInstalled(self, mod_handle: mobase.IModInterface):
        self._editable_cache.pop(mod_handle.name(), None)
        self._get_author(mod_handle, True)
        self._proxy.refresh_column()

    def _onPluginDisabled(self, plugin: mobase.IPlugin):
        if self.name() == plugin.name():
            self._apply_hidden(self.hide_author_column)

    def _onPluginEnabled(self, plugin: mobase.IPlugin):
        if self.name() == plugin.name():
            self._apply_hidden(self.hide_author_column)

    def _header_for(self, use_uploader: bool) -> str:
        return self.tr("Uploader") if use_uploader else self.tr("Author")

    def _update_name_text(self):
        self._header_text = self._header_for(self.use_uploader)
        if self._proxy is not None:  # not yet during init(), the UI does not exist then
            self._update_filter_placeholder()
            self._proxy.set_header_title(self._header_text)

    # Proxy callbacks

    def _get_cell_value(self, name: str):
        if name not in self._mod_authors:
            return None  # separators and unknown rows: blank cell
        return self._mod_authors[name] or ""

    def _is_editable(self, name: str) -> bool:
        cached = self._editable_cache.get(name)
        if cached is None:
            handle = self._organizer.modList().getMod(name)
            cached = bool(handle) and not (handle.isOverwrite() or handle.isSeparator() or handle.isForeign())
            self._editable_cache[name] = cached
        return cached

    # Cell context menu

    def _show_cell_menu(self, index, global_pos) -> bool:
        name = self._proxy.item_name(index)
        if not self._is_editable(name):
            return False  # let MO2 show its own menu

        url_info = self._urls.get(name, {})
        url = url_info.get("user") or url_info.get("default")
        label = self.tr("Uploader") if self.use_uploader else self.tr("Author")

        menu = QMenu(self._modlist_widget)
        visit = menu.addAction(self.tr("Visit Uploader Page"))
        visit.setEnabled(bool(url))
        visit.triggered.connect(lambda: webbrowser.open(url))
        edit_url = menu.addAction(self.tr("Change Page Url"))
        edit_url.triggered.connect(lambda: self._edit_url(name, url))
        edit_name = menu.addAction(self.tr("Set %1 Name").replace("%1", label))
        edit_name.triggered.connect(lambda: self._edit_name(index, name, label))
        menu.exec(global_pos)
        return True

    def _on_cell_double_clicked(self, index) -> bool:
        """Optional (setting): double-click edits the cell instead of MO2's usual double-click action."""
        if not self.double_click_edit:
            return False
        name = self._proxy.item_name(index)
        if not self._is_editable(name):
            return False
        view = self._modlist_widget
        view.setCurrentIndex(index)
        self._proxy.editing_allowed = True  # the cell is only editable while we open the editor
        try:
            view.edit(index)
        finally:
            self._proxy.editing_allowed = False
        return True

    def _edit_url(self, name: str, url):
        dialog = UrlDialog(url, self._modlist_widget)
        if dialog.exec():
            user_url = dialog.line_edit.text() or None
            if user_url != url:
                self._urls.setdefault(name, {})["user"] = user_url
                self._save_user_url(name, user_url)

    def _edit_name(self, index, name: str, label: str):
        current = self._mod_authors.get(name) or ""
        text, ok = QInputDialog.getText(self._modlist_widget, self.tr("Set %1 Name").replace("%1", label),
                                        self.tr("%1 (clear to reset to default):").replace("%1", label),
                                        QLineEdit.EchoMode.Normal, current)
        if ok:
            self._proxy.setData(index, text, Qt.ItemDataRole.EditRole)

    # meta.ini persistence

    def _meta_ini_path(self, mod_name: str):
        mod_handle = self._organizer.modList().getMod(mod_name)
        if mod_handle:
            mod_path = mod_handle.absolutePath()
            if os.path.exists(mod_path):
                return os.path.join(mod_path, "meta.ini")
        return None

    def _save_user_url(self, mod_name: str, url):
        ini_path = self._meta_ini_path(mod_name)
        if not ini_path:
            return
        ini = _read_ini(ini_path)
        if ini is None:
            return
        if not ini.has_section(SECTION):
            ini.add_section(SECTION)
        if url is None:
            ini.remove_option(SECTION, "userseturl")
        else:
            ini.set(SECTION, "userseturl", url)
        _write_ini(ini_path, ini)

    def _save_user_set_name(self, mod_name: str, set_name: str) -> bool:
        """Persist a user supplied author/uploader. Empty string resets to the queried value."""
        set_name = set_name.strip()
        if (self._mod_authors.get(mod_name) or "") == set_name:
            return True
        ini_path = self._meta_ini_path(mod_name)
        if not ini_path:
            return False
        ini = _read_ini(ini_path)
        if ini is None:
            return False
        if not ini.has_section(SECTION):
            ini.add_section(SECTION)
        user_key = "usersetuploader" if self.use_uploader else "usersetauthor"
        if set_name == '':
            ini.remove_option(SECTION, user_key)
        else:
            ini.set(SECTION, user_key, set_name)
        if not _write_ini(ini_path, ini):
            return False
        self._apply_ini(mod_name, ini)
        return True

    def _reset_author_cache(self):
        print("Resetting author cache")
        self._mod_authors.clear()
        for mod in self._organizer.modList().allMods():
            mod_handle = self._organizer.modList().getMod(mod)
            if mod_handle.isOverwrite() or mod_handle.isSeparator():
                continue
            mod_ini_path = os.path.join(mod_handle.absolutePath(), "meta.ini")
            if os.path.exists(mod_ini_path):
                ini = _read_ini(mod_ini_path)
                if ini is not None and ini.has_section(SECTION):
                    ini.remove_section(SECTION)
                    if _write_ini(mod_ini_path, ini):
                        print(f"ModAuthorColumn: Removed author cache for {mod_ini_path}")

    # Nexus requests

    def _get_author_from_nexus(self, game_name, mod_id, mod_name, ini_path):
        if mod_name not in self._mod_authors:
            self._mod_authors[mod_name] = None
        if mod_name not in self._urls:
            self._urls[mod_name] = {}
        self._requested_mods.add(mod_name)
        if self._reset_names_on_request:
            self._reset_names_pending.add(mod_name)
        self._bridge.requestDescription(game_name, mod_id, (mod_name, ini_path))

    def _apply_ini(self, mod_name: str, ini: configparser.ConfigParser):
        """Update in-memory author and url for a mod from its meta.ini section."""
        get = lambda key: ini.get(SECTION, key, fallback=None)
        author, uploader = get("author"), get("uploader")
        default_url = ("https://www.nexusmods.com/profile/" + uploader) if uploader else None
        self._urls[mod_name] = {"default": default_url, "user": get("userseturl")}
        if self.use_uploader:
            self._mod_authors[mod_name] = get("usersetuploader") or uploader
        else:
            self._mod_authors[mod_name] = get("usersetauthor") or author

    def _on_request_finished(self, *args):
        # args: 0:game_name, 1:mod_id, 2:user_data(mod_name, ini_path), 3:nexus json data
        mod_name = args[2][0]
        ini_path = args[2][1]
        description: dict = args[3]
        author = description.get('author', None)
        uploaded_by = description.get('uploaded_by', None)

        # Save to the mod's meta.ini so we don't need to re-request it from Nexus.
        ini = _read_ini(ini_path)
        if ini is not None:
            if not ini.has_section(SECTION):
                ini.add_section(SECTION)
            ini.set(SECTION, "author", author or "")
            ini.set(SECTION, "uploader", uploaded_by or "")
            if mod_name in self._reset_names_pending and (author or uploaded_by):
                for key in ("usersetauthor", "usersetuploader"):
                    ini.remove_option(SECTION, key)
            _write_ini(ini_path, ini)
            self._apply_ini(mod_name, ini)

        self._requested_mods.discard(mod_name)
        self._reset_names_pending.discard(mod_name)
        self._proxy.refresh_column()
        if not self._requested_mods:
            print("ModAuthorColumn: Querying of Mods Complete")

    def _on_request_failed(self, *args):
        # args: game_name, mod_id, idk 0, user_data, idk 0, error message
        self._requested_mods.discard(args[3][0])
        self._reset_names_pending.discard(args[3][0])
        print(f"ModAuthorColumn: Nexus Request Failed: {args[5]}")

    def _get_author(self, mod_handle: mobase.IModInterface, force_request=False):
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
        if os.path.exists(mod_ini_path):
            ini = _read_ini(mod_ini_path)
            if ini is not None and ini.has_section(SECTION):
                author = ini.get(SECTION, "author", fallback=None)
                uploader = ini.get(SECTION, "uploader", fallback=None)
                self._apply_ini(mod_name, ini)

        if author is None or uploader is None or force_request:
            mod_id = mod_handle.nexusId()
            # Not a queriable nexus mod
            if mod_id <= 0:
                return
            internal_name = mod_handle.gameName()
            if internal_name == "":
                return
            # Get nexus game name instead of mo2 internal name
            game_name = self.internal_to_nexus_game_names.get(internal_name)
            if game_name is None:
                game_plugin = self._organizer.getGame(internal_name)
                if game_plugin is None:
                    return
                game_name = game_plugin.gameNexusName()
                self.internal_to_nexus_game_names[internal_name] = game_name

            self._get_author_from_nexus(game_name, mod_id, mod_name, mod_ini_path)

    def _load_authors(self, force_request=False):
        all_mods = self._organizer.modList().allMods()
        self._mod_authors = {mod: (None if mod != "Overwrite" else mod) for mod in all_mods}
        self._urls = {mod: {} for mod in all_mods}
        self._editable_cache.clear()
        managed_game = self._organizer.managedGame()
        self.internal_to_nexus_game_names = {managed_game.gameName(): managed_game.gameNexusName()}

        for mod in all_mods:
            self._get_author(self._organizer.modList().getMod(mod), force_request)


def createPlugin() -> mobase.IPlugin:
    return ModAuthorColumn()
