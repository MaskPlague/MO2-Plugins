try:
    from PyQt6.QtWidgets import QVBoxLayout, QDialog, QCheckBox, QDialogButtonBox, QFrame
except ImportError:
    from PyQt5.QtWidgets import QVBoxLayout, QDialog, QCheckBox, QDialogButtonBox, QFrame

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PyQt6.QtWidgets import QVBoxLayout, QDialog, QCheckBox, QDialogButtonBox, QFrame

class SettingsDialog(QDialog):
    def __init__(self, current_use_uploader, author_column_visible, double_click_edit=False, auto_expand_separators=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("ModAuthorColumn Settings"))
        self.resize(450, 260)
        layout = QVBoxLayout(self)
        
        self.use_uploader_checkbox = QCheckBox(self.tr("Display Mod Uploader instead of Mod Author"))
        self.use_uploader_checkbox.setChecked(current_use_uploader)
        layout.addWidget(self.use_uploader_checkbox)

        self.hide_author_column = QCheckBox(self.tr("Hide Author Column"))
        self.hide_author_column.setChecked(author_column_visible)
        layout.addWidget(self.hide_author_column)


        self.double_click_edit_checkbox = QCheckBox(self.tr("Double-click an author/uploader cell to edit it"))
        self.double_click_edit_checkbox.setChecked(double_click_edit)
        layout.addWidget(self.double_click_edit_checkbox)

        self.auto_expand_checkbox = QCheckBox(self.tr("Expand separators while a filter is active"))
        self.auto_expand_checkbox.setChecked(auto_expand_separators)
        layout.addWidget(self.auto_expand_checkbox)

        layout.addSpacing(25)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        self.force_requery_checkbox = QCheckBox(self.tr("Force re-query of all mod authors/uploaders\n(user set names are kept unless the option below is checked)"))
        layout.addWidget(self.force_requery_checkbox)

        self.reset_user_names_checkbox = QCheckBox(self.tr("Also replace user set names with the name from Nexus\n(only for mods where the re-query returns a name)"))
        self.reset_user_names_checkbox.setEnabled(False)
        self.force_requery_checkbox.toggled.connect(self.reset_user_names_checkbox.setEnabled)
        self.force_requery_checkbox.toggled.connect(lambda on: on or self.reset_user_names_checkbox.setChecked(False))
        layout.addWidget(self.reset_user_names_checkbox)

        self.reset_widths = QCheckBox(self.tr("Reset author column widths"))
        layout.addWidget(self.reset_widths)

        self.reset_author_cache = QCheckBox(self.tr("Reset author cache"))
        #layout.addWidget(self.reset_author_cache)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)