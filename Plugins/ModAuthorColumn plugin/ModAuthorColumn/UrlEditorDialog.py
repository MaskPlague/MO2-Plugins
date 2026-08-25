try:
    from PyQt6.QtWidgets import QVBoxLayout, QDialog, QDialogButtonBox, QLabel, QLineEdit
except ImportError:
    from PyQt5.QtWidgets import QVBoxLayout, QDialog, QDialogButtonBox, QLabel, QLineEdit

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PyQt6.QtWidgets import QVBoxLayout, QDialog, QDialogButtonBox, QLabel, QLineEdit

class UrlDialog(QDialog):
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Edit Author Page Url"))
        #self.resize(450, 180)
        layout = QVBoxLayout(self)
        label = QLabel(self.tr("Url: (delete to reset to default)"))
        layout.addWidget(label)
        self.line_edit = QLineEdit()
        if url:
            self.line_edit.setText(url)
        layout.addWidget(self.line_edit)
        width = ((len(url) + 10) if url and len(url) >= 40 else 50) * 5
        self.line_edit.setMinimumWidth(width)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)