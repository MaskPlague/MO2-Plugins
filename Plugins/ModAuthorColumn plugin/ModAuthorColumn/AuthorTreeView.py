from .Global import (UNKNOWN_AUTHOR, MINIMUM_COL_WIDTH, 
                     DEFAULT_MOD_NAME_COL_WIDTH, DEFAULT_AUTHOR_NAME_COL_WIDTH)
try:
    from PyQt6.QtCore import Qt, QModelIndex, QPersistentModelIndex, QTimer, QItemSelectionModel, QItemSelection, pyqtSignal
    from PyQt6.QtGui import QColor, QStandardItemModel, QStandardItem
    from PyQt6.QtWidgets import QTreeView, QAbstractItemView, QStyledItemDelegate, QHeaderView
except ImportError:
    from PyQt5.QtCore import Qt, QModelIndex, QPersistentModelIndex, QTimer, QItemSelectionModel, QItemSelection, pyqtSignal
    from PyQt5.QtGui import QColor, QStandardItemModel, QStandardItem
    from PyQt5.QtWidgets import QTreeView, QAbstractItemView, QStyledItemDelegate, QHeaderView
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PyQt6.QtCore import Qt, QModelIndex, QPersistentModelIndex, QTimer, QItemSelectionModel, QItemSelection, pyqtSignal
    from PyQt6.QtGui import QColor, QStandardItemModel, QStandardItem
    from PyQt6.QtWidgets import QTreeView, QAbstractItemView, QStyledItemDelegate, QHeaderView

#Prevent right most column from being click dragged
class LockedEdgeHeader(QHeaderView):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.min_width = 100
        self.setMinimumSectionSize(self.min_width)
        self.setStretchLastSection(False)
        self.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

    def mousePressEvent(self, event):
        if self.is_on_last_outer_edge(event.position().x()):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_on_last_outer_edge(event.position().x()):
            #self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        super().mouseMoveEvent(event)

    def is_on_last_outer_edge(self, mouse_x):
        count = self.count()
        if count <= 0:
            return False
        last_col_right_edge = sum(self.sectionSize(i) for i in range(count))
        return abs(mouse_x - last_col_right_edge) <= 4

class SyncHeightDelegate(QStyledItemDelegate):
    def __init__(self, modlist_widget, parent=None):
        super().__init__(parent)
        self.modlist_widget = modlist_widget

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        h = self.modlist_widget.sizeHintForRow(0)
        size.setHeight(h if h > 0 else 22)
        return size

class ModAuthorTreeView(QTreeView):
    # Second data role on column 0's item: the internal MO2 mod name
    # (Qt.UserRole already holds the QPersistentModelIndex).
    _INTERNAL_NAME_ROLE = Qt.ItemDataRole.UserRole + 1

    modeChanged = pyqtSignal(bool)
    tableWidthChanged = pyqtSignal(int)

    def __init__(self:QTreeView, modlist_widget: QTreeView, 
                 order_provider, author_lookup, tr_func, 
                 load_column_width, save_column_width,
                 width_detached: int = 300,
                 parent=None):
        super().__init__(parent)
        self._modlist_widget = modlist_widget
        self._order_provider = order_provider
        self._author_lookup = author_lookup
        self._tr = tr_func
        self._load_column_width = load_column_width
        self._save_column_width = save_column_width

        self._width_detached = width_detached

        self._sync_lock = False
        self._synced_to_modlist = True
        self._changing_modes = False
        self._sort_order = Qt.SortOrder.AscendingOrder

        self.setObjectName("ModAuthorColumnTree")
        self._height_delegate = SyncHeightDelegate(self._modlist_widget, self)
        self.setItemDelegate(self._height_delegate)

        self._model = QStandardItemModel()
        self._model.setColumnCount(2)
        self._model.setHorizontalHeaderLabels([self._tr("Mod Name"), self._tr("Author")])
        self.setModel(self._model)

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(self._modlist_widget.selectionMode())
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)

        self.locked_header = LockedEdgeHeader(Qt.Orientation.Horizontal, self)
        self.setHeader(self.locked_header)
        self.header().setHighlightSections(False)
        self.header().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self._is_adjusting = False

        self.header().setMinimumSectionSize(MINIMUM_COL_WIDTH)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setItemsExpandable(False)

        self.header().sectionResized.connect(self._onSectionResize)

        self.setFrameShape(self._modlist_widget.frameShape())
        self.setContentsMargins(0, 0, 0, 0)
        self.setSortingEnabled(False)  # we sort manually
        self.header().setSectionsClickable(True)  # still need to be able to click the section to sort manually
        self.setColumnHidden(0, True)  # hidden while synced; shown while detached

        self.header().setMinimumHeight(self._modlist_widget.header().minimumHeight())
        self.header().setMaximumHeight(self._modlist_widget.header().maximumHeight())
        

        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._restore_column_widths()
        self.set_table_width(self.columnWidth(1))

        self.header().sectionClicked.connect(self._on_header_clicked)
        self.doubleClicked.connect(self._on_cell_clicked)

        self._connect_modlist_sort_sync()
        self._connect_scroll_sync()
        self._connect_selection_sync()
        self._connect_collapse_sync()
        self._connect_separator_color_polling()

    def _fullFrameWidth(self):
        return self.frameWidth() * 2

    def _get_overhead(self):
        scrollbar_width = self.verticalScrollBar().sizeHint().width()
        return self._fullFrameWidth() + scrollbar_width

    def set_table_width(self, width: int):
        self.setFixedWidth(width)
        if self._synced_to_modlist:
            self.setColumnWidth(1, width)
        else:
            w1 = self.columnWidth(1)
            w0 = width - w1 - self._get_overhead()
            self.setColumnWidth(0, w0)
        self.tableWidthChanged.emit(width)

    @property
    def is_synced(self) -> bool:
        return self._synced_to_modlist

    def _load_width(self, column: int):
        return self._load_column_width(column)

    def _save_width(self, column: int, width: int):
        self._save_column_width(column, width)

    def _restore_column_widths(self):
        for column in (0, 1):
            saved = self._load_width(column)
            if saved is not None:
                self.setColumnWidth(column, saved)

    def _onSectionResize(self, index, old_size, new_size):
        if self._is_adjusting or self._changing_modes or self.header().count() <= 1 or new_size == 0:
            return
        
        self._is_adjusting = True
        
        max_width = self.viewport().width()
        col_count = self.header().count()
        
        # 1. Calculate space used by all columns to the LEFT of the one being dragged
        left_space = sum(self.header().sectionSize(i) for i in range(index))
        
        # 2. Calculate the absolute maximum size this dragged column can physically take
        # (Assuming all columns to its right are squished to their minimum widths)
        remaining_right_cols = col_count - 1 - index
        max_possible_size = max_width - left_space - (remaining_right_cols * MINIMUM_COL_WIDTH)
        
        # Cap the dragged column if it tries to push too far right
        if new_size > max_possible_size:
            new_size = max_possible_size
            self.header().resizeSection(index, int(new_size))
            
        # 3. Dynamically steal/give space to the columns to the RIGHT
        current_left_total = left_space + new_size
        remaining_budget = max_width - current_left_total
        
        # Distribute the remaining pixel budget among the right-side columns
        for i in range(index + 1, col_count):
            if i == col_count - 1:
                # The very last column consumes whatever exact pixels remain to perfectly hit the border
                target_size = max(MINIMUM_COL_WIDTH, remaining_budget)
            else:
                # Proportional or standard assignment for middle columns
                target_size = self.header().sectionSize(i)
                if remaining_budget < (col_count - i) * MINIMUM_COL_WIDTH:
                    target_size = MINIMUM_COL_WIDTH
                remaining_budget -= target_size
                
            self.header().resizeSection(i, int(target_size))
            
        self._is_adjusting = False
        if index == 0:
            self._save_width(1, self.columnWidth(1))
        self._save_width(index, new_size)

    # populating / repopulating the table

    def refresh_from_modlist(self):
        display_names, internal_names, indexes = self._order_provider()
        self.populate_in_order(display_names, internal_names, indexes)

    def populate_in_order(self, display_names: list, internal_names: list, indexes: list):
        self._model.setRowCount(len(display_names))
        for row, display_name in enumerate(display_names):
            name_item = QStandardItem(display_name)
            if row < len(indexes) and indexes[row] is not None:
                name_item.setData(indexes[row], Qt.ItemDataRole.UserRole)
            if row < len(internal_names):
                name_item.setData(internal_names[row], self._INTERNAL_NAME_ROLE)

            author_item = QStandardItem("")
            author_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._model.setItem(row, 0, name_item)
            self._model.setItem(row, 1, author_item)
            self.update_row_display(row)
        self.apply_row_visibility()

    def current_order(self) -> list:
        return [self._model.item(row, 0).text() for row in range(self._model.rowCount())]

    def resize_columns(self: QTreeView):
        for column in (0, 1):
            if self._load_width(column) is None:
                self.resizeColumnToContents(column)

    # separator detection + row rendering

    def _is_separator(self, internal_name: str) -> bool:
        if not internal_name:
            return False
        return internal_name.endswith("_separator")

    def _format_author_cell_text(self, display_name: str, internal_name: str, persistent_index, is_separator: bool) -> str:
        if not is_separator:
            return self._author_lookup(internal_name, display_name)
        if persistent_index is not None and persistent_index.isValid():
            idx = QModelIndex(persistent_index)
            model = self._modlist_widget.model()
            if model and model.hasChildren(idx):
                arrow = "\u25be" if self._modlist_widget.isExpanded(idx) else "\u25b8"
                return f"{arrow} {display_name}"
        return f"\u2014 {display_name} \u2014"

    def _get_row_background_color(self, persistent_index):
        if persistent_index is None or not persistent_index.isValid():
            return None, None, None
        model = self._modlist_widget.model()
        if model is None:
            return None, None, None
        idx = QModelIndex(persistent_index)
        return (model.data(idx, Qt.ItemDataRole.BackgroundRole),
                model.data(idx, Qt.ItemDataRole.ForegroundRole),
                model.data(idx, Qt.ItemDataRole.FontRole))

    def _apply_row_colors(self, row: int):
        item0 = self._model.item(row, 0)
        if item0 is None:
            return
        persistent_index = item0.data(Qt.ItemDataRole.UserRole)
        background, forground, font = self._get_row_background_color(persistent_index)

        author_item = self._model.item(row, 1)
        for item in (item0, author_item):
            if item is None:
                continue

            if background:
                item.setBackground(background)
            if forground:
                item.setForeground(forground)
            if font:
                item.setFont(font)
            if background and isinstance(background, QColor):
                # taken directcly from MO2's github
                # src/settings.cpp ColorSettings::idealTextColor (line 1369 as of now)
                if background.alpha() < 50:
                    continue
                iLuminance = ((background.red() * 0.299) +
                                (background.green() * 0.587) +
                                (background.blue() * 0.114))
                if iLuminance <= 128:
                    item.setForeground(QColor('white'))

    def update_row_display(self, row: int):
        item0 = self._model.item(row, 0)
        if item0 is None:
            return
        display_name = item0.text()
        internal_name = item0.data(self._INTERNAL_NAME_ROLE)
        persistent_index = item0.data(Qt.ItemDataRole.UserRole)
        is_sep = self._is_separator(internal_name)

        author_item = self._model.item(row, 1)
        if author_item is None:
            author_item = QStandardItem()
            self._model.setItem(row, 1, author_item)
        author_text = self._format_author_cell_text(display_name, internal_name, persistent_index, is_sep)
        author_item.setText(author_text)
        if author_text != UNKNOWN_AUTHOR:
            author_item.setToolTip(author_text)
        self._apply_row_colors(row)

    def sync_separator_colors(self):
        for row in range(self._model.rowCount()):
            item0 = self._model.item(row, 0)
            if item0 is None:
                continue

            internal_name = item0.data(self._INTERNAL_NAME_ROLE)

            if self._is_separator(internal_name):
                self._apply_row_colors(row)

    def find_row_for_index(self, persistent: QPersistentModelIndex):
        for row in range(self._model.rowCount()):
            item0 = self._model.item(row, 0)
            if item0 is None:
                continue
            stored = item0.data(Qt.ItemDataRole.UserRole)
            if stored is not None and stored == persistent:
                return row
        return None

    def find_row_for_internal_name(self, internal_name: str):
        for row in range(self._model.rowCount()):
            item0 = self._model.item(row, 0)
            if item0 is None:
                continue
            if item0.data(self._INTERNAL_NAME_ROLE) == internal_name:
                return row
        return None

    def _refresh_row_text_for_index(self, idx: QModelIndex):
        row = self.find_row_for_index(QPersistentModelIndex(idx))
        if row is not None:
            self.update_row_display(row)

    # click handling: toggle expand/collapse on separator rows
    def _on_cell_clicked(self, index: QModelIndex):
        row = index.row()
        item0 = self._model.item(row, 0)
        if item0 is None:
            return
        persistent_index = item0.data(Qt.ItemDataRole.UserRole)
        if persistent_index is None or not persistent_index.isValid():
            return
        idx = QModelIndex(persistent_index)
        model = self._modlist_widget.model()
        if model is None or not model.hasChildren(idx):
            return  # not a (non-empty) separator row -- nothing to toggle
        self._modlist_widget.setExpanded(idx, not self._modlist_widget.isExpanded(idx))

    # row visibility: mirror collapsed separators from the tree

    def _connect_collapse_sync(self):
        self._modlist_widget.collapsed.connect(self._on_modlist_expand_changed)
        self._modlist_widget.expanded.connect(self._on_modlist_expand_changed)

    def _on_modlist_expand_changed(self, idx: QModelIndex):
        self.apply_row_visibility()
        self._refresh_row_text_for_index(idx)

    def _is_visible_in_modlist(self, persistent_index) -> bool:
        if persistent_index is None or not persistent_index.isValid():
            return True
        idx = QModelIndex(persistent_index)
        parent = idx.parent()
        while parent.isValid():
            if not self._modlist_widget.isExpanded(parent):
                return False
            parent = parent.parent()
        return True

    def apply_row_visibility(self):
        for row in range(self._model.rowCount()):
            item = self._model.item(row, 0)
            if item is None:
                continue
            persistent_index = item.data(Qt.ItemDataRole.UserRole)
            hidden = not self._is_visible_in_modlist(persistent_index)
            self.setRowHidden(row, QModelIndex(), hidden)

    # modlist -> table sync

    def _connect_modlist_sort_sync(self):
        model = self._modlist_widget.model()
        if not model:
            return
        model.layoutChanged.connect(self._on_modlist_reordered)
        model.modelReset.connect(self._on_modlist_reordered)
        model.rowsMoved.connect(lambda *_: self._on_modlist_reordered())

    def _connect_separator_color_polling(self):
        # model.dataChanged never fires for MO2's modlist due to whatever they're
        # doing with delegates, so we poll instead via QTimer every one second.
        self._separator_color_timer = QTimer(self)
        self._separator_color_timer.setInterval(1000)
        self._separator_color_timer.timeout.connect(self.sync_separator_colors)
        self._separator_color_timer.start()

    def _on_modlist_reordered(self):
        if self._sync_lock or not self._synced_to_modlist:
            return
        self._sync_lock = True
        try:
            self.refresh_from_modlist()
        finally:
            self._sync_lock = False

    # author column header click, sort by author column

    def _on_header_clicked(self, logical_index: int):
        if logical_index == 0:  # Mod Name, only clickable while detached
            self.enter_synced_mode()
            return

        if self._synced_to_modlist:
            self.enter_detached_mode()

        self._sort_order = (
            Qt.SortOrder.DescendingOrder
            if self._sort_order == Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )
        self._model.sort(logical_index, self._sort_order)
        self.apply_row_visibility()

    def _detached_layout(self) -> tuple[int, int, int]:
        overhead = self._get_overhead()

        saved_author = self._load_width(1)
        
        author_width = saved_author if saved_author is not None else DEFAULT_AUTHOR_NAME_COL_WIDTH

        saved_mod_name = self._load_width(0)
        mod_name_width = saved_mod_name if saved_mod_name is not None else DEFAULT_MOD_NAME_COL_WIDTH

        total_width = mod_name_width + author_width + overhead

        return total_width, mod_name_width, author_width

    def enter_detached_mode(self):
        self._changing_modes = True
        total_width, mod_name_width, author_width = self._detached_layout()
        self.setColumnHidden(0, False)  # show Mod Name so you can see what's sorted
        # Set explicitly rather than resize_columns(): resizeColumnToContents
        # would re-expand Mod Name to its full content width and push Author
        # back out of view.
        print(f"{total_width=}, {mod_name_width=}, {author_width=}")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.set_table_width(total_width)
        self.setColumnWidth(0, mod_name_width)
        self.setColumnWidth(1, author_width)
        self._synced_to_modlist = False
        self.modeChanged.emit(False)
        self._changing_modes = False

    def enter_synced_mode(self):
        self._changing_modes = True
        self._save_width(0, self.columnWidth(0))
        self.set_table_width(self.columnWidth(1) + self._fullFrameWidth())
        self.setColumnHidden(0, True)
        self.refresh_from_modlist()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._synced_to_modlist = True
        self.modeChanged.emit(True)
        self._changing_modes = False

    # scroll sync

    def _mirror_scrollbar_value(self, source_bar, target_bar):
        target_bar.setValue(source_bar.value())

    def _connect_scroll_sync(self):
        tree_bar = self._modlist_widget.verticalScrollBar()
        table_bar = self.verticalScrollBar()

        def sync(source_bar, target_bar):
            if self._sync_lock or not self._synced_to_modlist:
                return
            self._sync_lock = True
            try:
                self._mirror_scrollbar_value(source_bar, target_bar)
            finally:
                self._sync_lock = False

        tree_bar.valueChanged.connect(lambda v: sync(tree_bar, table_bar))
        table_bar.valueChanged.connect(lambda v: sync(table_bar, tree_bar))

    # selection sync

    def _connect_selection_sync(self):
        modlist_sel_model = self._modlist_widget.selectionModel()
        if modlist_sel_model:
            modlist_sel_model.selectionChanged.connect(self._on_modlist_selection_changed)

        table_sel_model = self.selectionModel()
        if table_sel_model:
            table_sel_model.selectionChanged.connect(self._on_table_selection_changed)

    def select_rows(self, rows: list, current_row=None):
        sel_model = self.selectionModel()
        if sel_model is None:
            return
        selection = QItemSelection()
        last_col = max(self._model.columnCount() - 1, 0)
        for row in rows:
            top_left = self._model.index(row, 0)
            if not top_left.isValid():
                continue
            bottom_right = self._model.index(row, last_col)
            selection.select(top_left, bottom_right if bottom_right.isValid() else top_left)

        sel_model.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)

        if current_row is not None:
            current_idx = self._model.index(current_row, 0)
            if current_idx.isValid():
                sel_model.setCurrentIndex(current_idx, QItemSelectionModel.SelectionFlag.NoUpdate)

    def _select_modlist_indexes(self, indexes: list, current_index=None):
        sel_model = self._modlist_widget.selectionModel()
        model = self._modlist_widget.model()
        if sel_model is None or model is None:
            return
        selection = QItemSelection()
        for idx in indexes:
            if not idx.isValid():
                continue
            last_col = max(model.columnCount(idx.parent()) - 1, 0)
            top_left = idx.sibling(idx.row(), 0)
            bottom_right = idx.sibling(idx.row(), last_col)
            selection.select(top_left, bottom_right if bottom_right.isValid() else top_left)

        sel_model.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)

        if current_index is not None and current_index.isValid():
            sel_model.setCurrentIndex(current_index, QItemSelectionModel.SelectionFlag.NoUpdate)

    def _on_modlist_selection_changed(self, selected, deselected):
        if self._sync_lock:
            return
        sel_model = self._modlist_widget.selectionModel()
        if sel_model is None:
            return
        selected_source_rows = sel_model.selectedRows(0)

        table_rows = []
        for idx in selected_source_rows:
            row = self.find_row_for_index(QPersistentModelIndex(idx))
            if row is not None:
                table_rows.append(row)

        current_source = self._modlist_widget.currentIndex()
        current_table_row = None
        if current_source.isValid():
            current_table_row = self.find_row_for_index(QPersistentModelIndex(current_source.siblingAtColumn(0)))

        self._sync_lock = True
        try:
            self.select_rows(table_rows, current_table_row)
            if current_table_row is not None:
                idx = self._model.index(current_table_row, 0)
                self.scrollTo(idx)
                if self._synced_to_modlist:
                    self._mirror_scrollbar_value(self._modlist_widget.verticalScrollBar(), self.verticalScrollBar())
        finally:
            self._sync_lock = False

    def _on_table_selection_changed(self, selected, deselected):
        if self._sync_lock:
            return
        sel_model = self.selectionModel()
        if sel_model is None:
            return
        selected_table_rows = sel_model.selectedRows(0)

        target_indexes = []
        for table_idx in selected_table_rows:
            item0 = self._model.item(table_idx.row(), 0)
            persistent_index = item0.data(Qt.ItemDataRole.UserRole) if item0 else None
            if persistent_index is not None and persistent_index.isValid():
                target_indexes.append(QModelIndex(persistent_index))

        current_table_idx = self.currentIndex()
        current_target_idx = None
        if current_table_idx.isValid():
            item0 = self._model.item(current_table_idx.row(), 0)
            persistent_index = item0.data(Qt.ItemDataRole.UserRole) if item0 else None
            if persistent_index is not None and persistent_index.isValid():
                current_target_idx = QModelIndex(persistent_index)

        self._sync_lock = True
        try:
            self._select_modlist_indexes(target_indexes, current_target_idx)
            if current_target_idx is not None:
                self._modlist_widget.scrollTo(current_target_idx, QAbstractItemView.ScrollHint.EnsureVisible)
                if self._synced_to_modlist:
                    self._mirror_scrollbar_value(self.verticalScrollBar(), self._modlist_widget.verticalScrollBar())
        finally:
            self._sync_lock = False