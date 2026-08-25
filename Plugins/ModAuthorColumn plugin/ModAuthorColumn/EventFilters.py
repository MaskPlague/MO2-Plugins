
try:
    from PyQt6.QtCore import Qt, QObject, QEvent, QSortFilterProxyModel
    from PyQt6.QtWidgets import QMenu, QCheckBox, QWidgetAction, QTreeView
except ImportError:
    from PyQt5.QtCore import Qt, QObject, QEvent, QSortFilterProxyModel
    from PyQt5.QtWidgets import QMenu, QCheckBox, QWidgetAction, QTreeView

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PyQt6.QtCore import Qt, QObject, QEvent, QSortFilterProxyModel
    from PyQt6.QtWidgets import QMenu, QCheckBox, QWidgetAction, QTreeView

class ContextMenuEventFilter(QObject):
    def __init__(self, isHidden, setHideAuthorColumn, get_header_text, model: QSortFilterProxyModel):
        self._isHidden = isHidden
        self._setHideAuthorColumn = setHideAuthorColumn
        self._header_text = get_header_text
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
                checkBox.setText(self._get_header_text())
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

    def _get_header_text(self):
        return self._header_text()

class ScrollBarEventFilter(QObject):
    def __init__(self, modAuthorCol:QTreeView = None):
        self._modAuthorCol = modAuthorCol
        super().__init__()

    def eventFilter(self, obj: QObject, event: QEvent):
        if event.type() == QEvent.Type.Show:
            self._modAuthorCol.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        elif event.type() == QEvent.Type.Hide:
            self._modAuthorCol.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return False

class LeaveEventFilter(QObject):
    def __init__(self, modAuthorCol:QTreeView = None):
        self._modAuthorCol = modAuthorCol
        super().__init__()

    def eventFilter(self, obj: QObject, event: QEvent):
        if event.type() == QEvent.Type.Leave:
            self._modAuthorCol._author_col_delegate._hovered = None
            self._modAuthorCol.viewport().update()
        return False
    