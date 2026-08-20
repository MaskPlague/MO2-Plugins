import json

try:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWidgets import QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QDialog, QLineEdit, QCheckBox, QDialogButtonBox
    from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
except ImportError:
    from PyQt5.QtCore import QUrl
    from PyQt5.QtWidgets import QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QDialog, QLineEdit, QCheckBox, QDialogButtonBox
    from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWidgets import QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QDialog, QLineEdit, QCheckBox, QDialogButtonBox
    from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

class SettingsDialog(QDialog):
    def __init__(self, current_key, key_validated, current_use_uploader, author_column_visible, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ModAuthorColumn Settings")
        self.resize(450, 180)
        self.key_validated = key_validated
        layout = QVBoxLayout(self)
        
        key_layout = QHBoxLayout()
        self.api_key_input = QLineEdit(current_key)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Enter Nexus Mods API Key")
        
        self.validate_btn = QPushButton("Validate Key")
        
        key_layout.addWidget(QLabel("API Key:"))
        key_layout.addWidget(self.api_key_input)
        key_layout.addWidget(self.validate_btn)
        layout.addLayout(key_layout)
        
        self.status_label = QLabel("Status: Waiting for validation...")
        layout.addWidget(self.status_label)
        if self.key_validated:
            self.status_label.setText(f"Status: ✅ Valid Key!")
        
        self.use_uploader_checkbox = QCheckBox("Display Mod Uploader instead of Mod Author")
        self.use_uploader_checkbox.setChecked(current_use_uploader)
        layout.addWidget(self.use_uploader_checkbox)

        self.hide_author_column = QCheckBox("Hide Author Column")
        self.hide_author_column.setChecked(author_column_visible)
        layout.addWidget(self.hide_author_column)

        layout.addSpacing(10)

        self.force_requery_checkbox = QCheckBox("Force re-query of all mod authors/uploaders")
        layout.addWidget(self.force_requery_checkbox)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
        self.manager = QNetworkAccessManager(self)
        self.validate_btn.clicked.connect(self._on_validate_clicked)
        
    def _on_validate_clicked(self):
        api_key = self.api_key_input.text().strip()
        if not api_key:
            self.status_label.setText("Status: ❌ Please enter an API key.")
            self.status_label.setStyleSheet("color: red;")
            return
            
        self.validate_btn.setEnabled(False)
        self.status_label.setText("Status: Validating... Please wait.")
        self.status_label.setStyleSheet("")
        
        url = QUrl("https://api.nexusmods.com/v1/users/validate.json")
        request = QNetworkRequest(url)
        request.setRawHeader(b"apikey", api_key.encode('utf-8'))
        request.setRawHeader(b"accept", b"application/json")
        
        reply = self.manager.get(request)
        reply.finished.connect(lambda: self._on_validation_finished(reply))
        
    def _on_validation_finished(self, reply: QNetworkReply):
        self.validate_btn.setEnabled(True)
        status_code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        
        if reply.error() == QNetworkReply.NetworkError.NoError and status_code == 200:
            try:
                response_data = reply.readAll().data().decode('utf-8')
                json_data:dict = json.loads(response_data)
                username = json_data.get("name", "Unknown User")
                self.status_label.setText(f"Status: ✅ Valid Key! (Welcome, {username})")
                self.status_label.setStyleSheet("color: green;")
            except json.JSONDecodeError:
                self.status_label.setText("Status: ✅ Valid Key! (Failed to parse user info)")
                self.status_label.setStyleSheet("color: green;")
            self.key_validated = True
        else:
            if status_code == 401:
                self.status_label.setText("Status: ❌ Invalid API Key (401 Unauthorized).")
            else:
                self.status_label.setText(f"Status: ❌ Network Error: {reply.errorString()}")
            self.status_label.setStyleSheet("color: red;")
            self.key_validated = False
            
        reply.deleteLater()