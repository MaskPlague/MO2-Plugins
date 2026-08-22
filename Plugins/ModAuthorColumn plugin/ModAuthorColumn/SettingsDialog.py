try:
    from PyQt6.QtWidgets import QVBoxLayout, QDialog, QCheckBox, QDialogButtonBox, QFrame
except ImportError:
    from PyQt5.QtWidgets import QVBoxLayout, QDialog, QCheckBox, QDialogButtonBox, QFrame

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PyQt6.QtWidgets import QVBoxLayout, QDialog, QCheckBox, QDialogButtonBox, QFrame

class SettingsDialog(QDialog):
    def __init__(self, current_use_uploader, author_column_visible, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ModAuthorColumn Settings")
        self.resize(450, 180)
        layout = QVBoxLayout(self)
        
        self.use_uploader_checkbox = QCheckBox("Display Mod Uploader instead of Mod Author")
        self.use_uploader_checkbox.setChecked(current_use_uploader)
        layout.addWidget(self.use_uploader_checkbox)

        self.hide_author_column = QCheckBox("Hide Author Column")
        self.hide_author_column.setChecked(author_column_visible)
        layout.addWidget(self.hide_author_column)


        layout.addSpacing(25)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        self.force_requery_checkbox = QCheckBox("Force re-query of all mod authors/uploaders")
        layout.addWidget(self.force_requery_checkbox)

        self.reset_widths = QCheckBox("Reset author column widths")
        layout.addWidget(self.reset_widths)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)