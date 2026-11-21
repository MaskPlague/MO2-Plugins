try:
    from PyQt6.QtCore import QObject, QEvent, QTimer
except ImportError:
    from PyQt5.QtCore import QObject, QEvent, QTimer


class ColumnContextMenuFilter(QObject):
    """
    Intercepts right clicks on one column of a view's viewport.

    `handler(index, global_pos) -> bool` is called for right clicks on that column and
    `double_click_handler(index) -> bool` for double clicks; if it returns True the event is consumed,
    otherwise MO2 handles it as usual.
    """

    def __init__(self, view, column_getter, handler, double_click_handler, parent=None):
        super().__init__(parent)
        self._double_click_handler = double_click_handler
        self._view = view
        self._column_getter = column_getter
        self._handler = handler

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ContextMenu and obj is self._view.viewport():
            index = self._view.indexAt(event.pos())
            if index.isValid() and index.column() == self._column_getter():
                return bool(self._handler(index, event.globalPos()))
        if (event.type() == QEvent.Type.MouseButtonDblClick and obj is self._view.viewport()):
            point = event.position().toPoint() if hasattr(event, "position") else event.pos()
            index = self._view.indexAt(point)
            if index.isValid() and index.column() == self._column_getter():
                return bool(self._double_click_handler(index))
        return False

class StyleSheetOverlay(QObject):
    def __init__(self, widget, active_getter, overlay: str):
        super().__init__(widget)
        self._widget = widget
        self._active = active_getter
        self._overlay = overlay
        self._base = ""
        self._pending = False
        widget.installEventFilter(self)

    def update(self):
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self._apply)

    def _apply(self):
        self._pending = False
        current = self._widget.styleSheet()
        if self._active():
            if current != self._overlay:
                self._base = current
                self._widget.setStyleSheet(self._overlay)
        elif current == self._overlay:
            self._widget.setStyleSheet(self._base)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.StyleChange and self._widget.styleSheet() != self._overlay:
            self.update()
        return False
