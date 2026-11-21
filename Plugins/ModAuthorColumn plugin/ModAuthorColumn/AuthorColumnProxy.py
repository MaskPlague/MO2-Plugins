try:
    from PyQt6.QtCore import QAbstractProxyModel, QModelIndex, QMimeData, QPersistentModelIndex, Qt
    from PyQt6.QtGui import QBrush, QColor
except ImportError:
    from PyQt5.QtCore import QAbstractProxyModel, QModelIndex, QMimeData, QPersistentModelIndex, Qt
    from PyQt5.QtGui import QBrush, QColor

from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtCore import QAbstractProxyModel, QModelIndex, QMimeData, QPersistentModelIndex, Qt
    from PyQt6.QtGui import QBrush, QColor

# PyQt6 enums are enum.Flag (have .value), PyQt5 enums are plain ints.
_ALIGN_CENTER = getattr(Qt.AlignmentFlag.AlignCenter, "value", Qt.AlignmentFlag.AlignCenter)


class TreeExtraColumnProxy(QAbstractProxyModel):
    """
    Adds one extra column after the source model's columns.

    value_getter(name) -> str | None
        Raw value for the row named `name` (the row's column-0 display text).
        None means "no entry for this row" (blank cell); "" means "known but empty"
        (shown as `unknown_text`).
    value_setter(name, value) -> bool
        Called when the user edits the cell.
    editable_getter(name) -> bool
        Whether the cell of this row may be edited.
    """

    def __init__(
            self,
            header_title: str,
            value_getter: Callable[[str], Optional[str]],
            value_setter: Callable[[str, str], bool],
            editable_getter: Callable[[str], bool],
            unknown_text: str,
            parent=None,
        ):
        super().__init__(parent)
        self._header_title = header_title
        self._get_value = value_getter
        self._set_value = value_setter
        self._is_editable = editable_getter
        self._unknown_text = unknown_text
        # Store pure-Python (parent_row, parent_col) tuples and never clear this dict,
        # preventing C++ internalPointer() from ever referencing a deleted QModelIndex.
        self._parent_tuples: dict[tuple[int, int], tuple[int, int]] = {}
        self._layout_snapshot: list = []
        # Sorting by the extra column: per source-parent permutation of rows (built lazily).
        self._sort_active = False
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._perm_cache: dict = {}
        self._flattening = False
        self._filter_text = ""
        self.editing_allowed = False  # see flags()

    # --- public helpers ---

    def set_header_title(self, title: str) -> None:
        self._header_title = title
        col = self.extra_column()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, col, col)

    def extra_column(self) -> int:
        """Column number of the added column (valid for the top level, which is what the header uses)."""
        src = self.sourceModel()
        return src.columnCount(QModelIndex()) if src else 0

    def item_name(self, index: QModelIndex) -> str:
        """Display text of column 0 for the row `index` is on."""
        name_idx = self.index(index.row(), 0, index.parent())
        src_idx = self.mapToSource(name_idx)
        val = self.sourceModel().data(src_idx, Qt.ItemDataRole.DisplayRole) if src_idx.isValid() else None
        return str(val) if val is not None else ""

    def refresh_column(self, parent: QModelIndex = QModelIndex()) -> None:
        """Tell views that every cell of the extra column (all levels) may have changed."""
        if self._remapped and not parent.isValid():
            self._begin_relayout()  # values changed, so the order may have too
            self._end_relayout()
            return
        n = self.rowCount(parent)
        if n <= 0:
            return
        col = self.columnCount(parent) - 1
        self.dataChanged.emit(self.index(0, col, parent), self.index(n - 1, col, parent), [])
        for row in range(n):
            child = self.index(row, 0, parent)
            if self.hasChildren(child):
                self.refresh_column(child)

    @property
    def _remapped(self) -> bool:
        return self._sort_active or bool(self._filter_text)

    def set_filter(self, text: str) -> None:
        """Only show rows whose extra-column value contains `text` (and separators containing such rows)."""
        text = text.strip().casefold()
        if text == self._filter_text:
            return
        self._begin_relayout()
        self._filter_text = text
        self._end_relayout()

    @property
    def filter_text(self) -> str:
        return self._filter_text

    @property
    def sort_active(self) -> bool:
        return self._sort_active

    @property
    def sort_order(self):
        return self._sort_order

    def set_extra_sort(self, order=None) -> None:
        """Sort every level by the extra column (order=None switches the sort off)."""
        active = order is not None
        if self._flattening:
            return  # MO2 reacting to our flatten request must not switch our sort off again
        if active == self._sort_active and (not active or order == self._sort_order):
            return
        src = self.sourceModel()
        if active and not self._sort_active and src:
            # In MO2's priority sort the modlist is a tree of separators. Sorting by any other
            # column makes MO2 flatten it, so ask for a name sort (ties then end up name-ordered)
            # and sort by our column on top of the flat list.
            self._flattening = True
            try:
                src.sort(0, Qt.SortOrder.AscendingOrder)
            finally:
                self._flattening = False
        self._begin_relayout()
        self._sort_active = active
        if active:
            self._sort_order = order
        self._end_relayout()

    def _row_matches(self, src, index: QModelIndex) -> bool:
        if src.hasChildren(index):
            return any(self._row_matches(src, src.index(r, 0, index)) for r in range(src.rowCount(index)))
        name = src.data(index, Qt.ItemDataRole.DisplayRole)
        value = self._get_value(str(name) if name is not None else "") or ""
        return self._filter_text in value.casefold()

    def _perm(self, src_parent: QModelIndex):
        """(proxy_row -> source_row, source_row -> proxy_row or -1 if hidden) for children of src_parent."""
        if not self._remapped:
            return None
        src = self.sourceModel()
        key = []
        node = src_parent
        while node.isValid():  # full path, so a leaf never shares a cache entry with a separator
            key.append((node.row(), node.column()))
            node = node.parent()
        key = tuple(key)
        perm = self._perm_cache.get(key)
        if perm is None:
            count = src.rowCount(src_parent)
            rows = list(range(count))
            if self._filter_text:
                rows = [r for r in rows if self._row_matches(src, src.index(r, 0, src_parent))]
            if self._sort_active:
                filled, blank = [], []
                for row in rows:
                    name = src.data(src.index(row, 0, src_parent), Qt.ItemDataRole.DisplayRole)
                    value = self._get_value(str(name) if name is not None else "") or ""
                    (filled if value else blank).append((value.casefold(), row))
                filled.sort(key=lambda item: item[0], reverse=self._sort_order == Qt.SortOrder.DescendingOrder)
                rows = [row for _, row in filled] + [row for _, row in blank]
            from_src = [-1] * count
            for proxy_row, src_row in enumerate(rows):
                from_src[src_row] = proxy_row
            perm = self._perm_cache[key] = (rows, from_src)
        return perm

    def _row_to_source(self, src_parent: QModelIndex, row: int) -> int:
        perm = self._perm(src_parent)
        return perm[0][row] if perm and row < len(perm[0]) else row

    def _row_from_source(self, src_parent: QModelIndex, row: int) -> int:
        perm = self._perm(src_parent)
        return perm[1][row] if perm and row < len(perm[1]) else row

    # --- internals ---

    def _parent_token(self, src_parent: QModelIndex) -> tuple[int, int] | None:
        if not src_parent.isValid():
            return None
        key = (src_parent.row(), src_parent.column())
        token = self._parent_tuples.get(key)
        if token is None:
            self._parent_tuples[key] = key
            token = key
        return token

    def _source_parent_from_proxy(self, proxy_index: QModelIndex) -> QModelIndex:
        src = self.sourceModel()
        if not proxy_index.isValid() or not src:
            return QModelIndex()
        ptr = proxy_index.internalPointer()
        if isinstance(ptr, tuple):
            p_row, p_col = ptr
            return src.index(p_row, p_col, QModelIndex())
        return QModelIndex()

    def _extra_col(self, parent: QModelIndex = QModelIndex()) -> int:
        src = self.sourceModel()
        if not src:
            return 0
        return src.columnCount(self.mapToSource(parent))

    # --- source model wiring ---

    _SIGNAL_SLOTS = (
        ("dataChanged", "_on_source_data_changed"),
        ("modelAboutToBeReset", "_on_source_about_to_reset"),
        ("modelReset", "_on_source_reset"),
        ("layoutAboutToBeChanged", "_on_source_layout_about_to_be_changed"),
        ("layoutChanged", "_on_source_layout_changed"),
        ("rowsAboutToBeInserted", "_on_rows_about_to_be_inserted"),
        ("rowsInserted", "_on_rows_inserted"),
        ("rowsAboutToBeRemoved", "_on_rows_about_to_be_removed"),
        ("rowsRemoved", "_on_rows_removed"),
        ("rowsAboutToBeMoved", "_on_rows_about_to_be_moved"),
        ("rowsMoved", "_on_rows_moved"),
    )

    def setSourceModel(self, source_model) -> None:
        """Meant to be called once; the source model is never swapped afterwards."""
        super().setSourceModel(source_model)
        for signal, slot in self._SIGNAL_SLOTS:
            getattr(source_model, signal).connect(getattr(self, slot))

    def _on_source_about_to_reset(self) -> None:
        self.beginResetModel()

    def _on_source_reset(self) -> None:
        self._perm_cache.clear()
        self.endResetModel()

    # Persistent indexes (selection, current index, ...) must follow their items through a
    # layout change (e.g. the modlist being sorted), exactly like QIdentityProxyModel does.
    def _on_source_layout_about_to_be_changed(self, *_) -> None:
        self._begin_relayout()

    def _on_source_layout_changed(self, *_) -> None:
        self._end_relayout()

    def _begin_relayout(self) -> None:
        self._layout_snapshot = [
            (QPersistentModelIndex(p), QPersistentModelIndex(self.mapToSource(p)), p.column())
            for p in self.persistentIndexList()
        ]
        self.layoutAboutToBeChanged.emit()

    def _end_relayout(self) -> None:
        self._perm_cache.clear()
        snapshot, self._layout_snapshot = self._layout_snapshot, []
        for old_persistent, src_persistent, column in snapshot:
            src_idx = QModelIndex(src_persistent)
            new_idx = QModelIndex()
            if src_idx.isValid():
                mapped = self.mapFromSource(src_idx)
                if mapped.isValid():
                    new_idx = self.index(mapped.row(), column, mapped.parent())
            self.changePersistentIndex(QModelIndex(old_persistent), new_idx)
        self.layoutChanged.emit()

    def _on_source_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles=None) -> None:
        if self._remapped:
            parent = self.mapFromSource(top_left.parent())
            n = self.rowCount(parent)
            if n:
                self.dataChanged.emit(self.index(0, 0, parent), self.index(n - 1, self.columnCount(parent) - 1, parent), roles or [])
            return
        self.dataChanged.emit(
            self.mapFromSource(top_left),
            self.mapFromSource(bottom_right),
            roles or [],
        )
        # The extra column is derived from column 0 (the name), so refresh it too.
        if top_left.column() <= 0 <= bottom_right.column():
            parent = self.mapFromSource(top_left.parent())
            col = self._extra_col(parent)
            self.dataChanged.emit(
                self.index(top_left.row(), col, parent),
                self.index(bottom_right.row(), col, parent),
                [],
            )

    def _on_rows_about_to_be_inserted(self, src_parent: QModelIndex, first: int, last: int) -> None:
        if self._remapped:
            self._begin_relayout()
            return
        self.beginInsertRows(self.mapFromSource(src_parent), first, last)

    def _on_rows_inserted(self, src_parent: QModelIndex, first: int, last: int) -> None:
        if self._remapped:
            self._end_relayout()
            return
        self.endInsertRows()

    def _on_rows_about_to_be_removed(self, src_parent: QModelIndex, first: int, last: int) -> None:
        if self._remapped:
            self._begin_relayout()
            return
        self.beginRemoveRows(self.mapFromSource(src_parent), first, last)

    def _on_rows_removed(self, src_parent: QModelIndex, first: int, last: int) -> None:
        if self._remapped:
            self._end_relayout()
            return
        self.endRemoveRows()

    def _on_rows_about_to_be_moved(
        self, src_parent: QModelIndex, start: int, end: int, dest_parent: QModelIndex, dest_row: int
    ) -> None:
        if self._remapped:
            self._begin_relayout()
            return
        self.beginMoveRows(
            self.mapFromSource(src_parent), start, end, self.mapFromSource(dest_parent), dest_row
        )

    def _on_rows_moved(
        self, src_parent: QModelIndex, start: int, end: int, dest_parent: QModelIndex, dest_row: int
    ) -> None:
        if self._remapped:
            self._end_relayout()
            return
        self.endMoveRows()

    # --- Sorting ---

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        src = self.sourceModel()
        if not src:
            return
        if column == self.extra_column():
            self.set_extra_sort(order)
        else:
            self.set_extra_sort(None)
            src.sort(column, order)

    # --- Drag-and-Drop Forwarding ---

    def supportedDropActions(self) -> Qt.DropAction:
        src = self.sourceModel()
        return src.supportedDropActions() if src else Qt.DropAction.IgnoreAction

    def supportedDragActions(self) -> Qt.DropAction:
        src = self.sourceModel()
        return src.supportedDragActions() if src else Qt.DropAction.IgnoreAction

    def mimeTypes(self) -> list[str]:
        src = self.sourceModel()
        return src.mimeTypes() if src else []

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData | None:
        src = self.sourceModel()
        if not src:
            return None
        mapped: list[QModelIndex] = []
        seen: set[tuple[int, int, int]] = set()
        for idx in indexes:
            if not idx.isValid():
                continue
            src_idx = self.mapToSource(idx)
            if src_idx.isValid():
                p = src_idx.parent()
                key = (src_idx.row(), p.row() if p.isValid() else -1, p.column() if p.isValid() else -1)
                if key not in seen:
                    seen.add(key)
                    mapped.append(src_idx)
        return src.mimeData(mapped)

    def canDropMimeData(
        self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: QModelIndex
    ) -> bool:
        src = self.sourceModel()
        if not src or self._remapped:
            return False
        src_col = 0 if column >= self._extra_col(parent) else column
        return src.canDropMimeData(data, action, row, src_col, self.mapToSource(parent))

    def dropMimeData(
        self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: QModelIndex
    ) -> bool:
        src = self.sourceModel()
        if not src or self._remapped:
            return False
        src_col = 0 if column >= self._extra_col(parent) else column
        return src.dropMimeData(data, action, row, src_col, self.mapToSource(parent))

    # --- Tree & Model Structure ---

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        src = self.sourceModel()
        if not src:
            return 0
        if parent.isValid() and parent.column() > 0:
            return 0
        src_parent = self.mapToSource(parent)
        perm = self._perm(src_parent)
        return len(perm[0]) if perm else src.rowCount(src_parent)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        src = self.sourceModel()
        if not src:
            return 0
        if parent.isValid() and parent.column() > 0:
            return 0
        return src.columnCount(self.mapToSource(parent)) + 1

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        src = self.sourceModel()
        if not src:
            return False
        if parent.isValid() and parent.column() > 0:
            return False
        if self._remapped:
            return self.rowCount(parent) > 0
        return src.hasChildren(self.mapToSource(parent))

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        src = self.sourceModel()
        if not src or row < 0 or column < 0:
            return QModelIndex()
        if parent.isValid() and parent.column() > 0:
            return QModelIndex()

        src_parent = self.mapToSource(parent)
        if row >= self.rowCount(parent) or column >= src.columnCount(src_parent) + 1:
            return QModelIndex()

        token = self._parent_token(src_parent)
        return self.createIndex(row, column, token)

    def parent(self, child: QModelIndex) -> QModelIndex:
        if not child.isValid() or not self.sourceModel():
            return QModelIndex()
        src_parent = self._source_parent_from_proxy(child)
        if not src_parent.isValid():
            return QModelIndex()
        return self.mapFromSource(src_parent)

    def mapToSource(self, proxy_index: QModelIndex) -> QModelIndex:
        src = self.sourceModel()
        if not proxy_index.isValid() or not src:
            return QModelIndex()
        src_parent = self._source_parent_from_proxy(proxy_index)
        col = proxy_index.column()
        max_cols = src.columnCount(src_parent)
        if col >= max_cols:
            col = 0
        return src.index(self._row_to_source(src_parent, proxy_index.row()), col, src_parent)

    def mapFromSource(self, source_index: QModelIndex) -> QModelIndex:
        if not source_index.isValid() or not self.sourceModel():
            return QModelIndex()
        src_parent = source_index.parent()
        token = self._parent_token(src_parent)
        row = self._row_from_source(src_parent, source_index.row())
        if row < 0:
            return QModelIndex()  # hidden by the filter
        return self.createIndex(row, source_index.column(), token)

    def buddy(self, index: QModelIndex) -> QModelIndex:
        # Views edit the buddy of a cell. The default forwards to the source model, which only knows
        # column 0 for our extra column, so the editor would open on the wrong cell.
        if index.isValid() and index.column() == self._extra_col(index.parent()):
            return index
        return super().buddy(index)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            src = self.sourceModel()
            return src.flags(QModelIndex()) if src else Qt.ItemFlag.NoItemFlags
        if index.column() == self._extra_col(index.parent()):
            base_flags = super().flags(self.index(index.row(), 0, index.parent()))
            flags = base_flags | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            # Never inherit the name column's editability. The cell only counts as editable while
            # `editing_allowed` is set, so that no view edit trigger (slow second click, F2, ...) can open an
            # editor on its own; values are still written through setData().
            flags &= ~Qt.ItemFlag.ItemIsEditable
            if self.editing_allowed and self._is_editable(self.item_name(index)):
                flags |= Qt.ItemFlag.ItemIsEditable
            return flags
        return super().flags(index)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and section == self._extra_col():
            if role == Qt.ItemDataRole.DisplayRole:
                return self._header_title
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return _ALIGN_CENTER
            return None
        src = self.sourceModel()
        return src.headerData(section, orientation, role) if src else None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if index.column() != self._extra_col(index.parent()):
            return super().data(index, role)

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ToolTipRole):
            value = self._get_value(self.item_name(index))
            if value is None:
                return None
            if role == Qt.ItemDataRole.EditRole:
                return value
            return value if value else self._unknown_text
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _ALIGN_CENTER
        if role >= Qt.ItemDataRole.UserRole:
            # MO2's custom roles (mod index, scroll-bar mark, ...) describe the whole row; its
            # conflict colouring reads the mod index from whichever cell it is painting.
            src = self.sourceModel()
            src_col0 = self.mapToSource(self.index(index.row(), 0, index.parent()))
            return src.data(src_col0, role) if src and src_col0.isValid() else None
        if role in (
            Qt.ItemDataRole.BackgroundRole,
            Qt.ItemDataRole.ForegroundRole,
            Qt.ItemDataRole.FontRole,
            Qt.ItemDataRole.SizeHintRole,
        ):
            src = self.sourceModel()
            src_col0 = self.mapToSource(self.index(index.row(), 0, index.parent()))
            if not src or not src_col0.isValid():
                return None
            if role == Qt.ItemDataRole.ForegroundRole:
                color = self._ideal_foreground(src.data(src_col0, Qt.ItemDataRole.BackgroundRole))
                if color is not None:
                    return color
            return src.data(src_col0, role)
        return None

    @staticmethod
    def _ideal_foreground(background):
        # Same rule as MO2's ColorSettings::idealTextColor: white text on dark backgrounds.
        if isinstance(background, QBrush):
            background = background.color()
        if not isinstance(background, QColor) or background.alpha() < 50:
            return None
        luminance = background.red() * 0.299 + background.green() * 0.587 + background.blue() * 0.114
        return QColor("white") if luminance <= 128 else None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or index.column() != self._extra_col(index.parent()):
            return super().setData(index, value, role)
        if role == Qt.ItemDataRole.EditRole:
            name = self.item_name(index)
            if not self._is_editable(name) or not self._set_value(name, str(value)):
                return False
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
            return True
        return False
