#Written by MaskPlauge
import mobase
import os

try:
    from PyQt6.QtCore import QCoreApplication, QObject, Qt, QEvent, QItemSelectionModel, QTimer
    from PyQt6.QtGui import QIcon, QCursor, QAction
    from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget, QTreeView, QApplication, QMenu, QPushButton, QHBoxLayout, QMessageBox

    # Compatibility flags
    SELECT_FLAG = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
    BLOCKED_EVENTS = {
        QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, 
        QEvent.Type.MouseButtonDblClick, QEvent.Type.Wheel, QEvent.Type.HoverEnter, 
        QEvent.Type.HoverLeave, QEvent.Type.HoverMove, QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
    }
    WAIT_CURSOR = Qt.CursorShape.WaitCursor

except ImportError:
    from PyQt5.QtCore import QCoreApplication, QObject, Qt, QEvent, QItemSelectionModel, QTimer
    from PyQt5.QtGui import QIcon, QCursor, QAction
    from PyQt5.QtWidgets import QMainWindow, QTabWidget, QWidget, QTreeView, QApplication, QMenu, QPushButton, QHBoxLayout, QMessageBox

    # Compatibility flags
    SELECT_FLAG = QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows
    BLOCKED_EVENTS = {
        QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease, 
        QEvent.MouseButtonDblClick, QEvent.Wheel, QEvent.HoverEnter, 
        QEvent.HoverLeave, QEvent.HoverMove, QEvent.KeyPress, QEvent.KeyRelease,
    }
    WAIT_CURSOR = Qt.WaitCursor

DEBUG = False
FILENAME_COLUMN = 0

class ContextMenuEventFilter(QObject):
    def __init__(self, download_view, plugin_instance):
        super().__init__()
        self.download_view: QTreeView = download_view
        self.plugin: QueryAllInfo = plugin_instance
        self.action = QAction("Query All Info")
        self.action.triggered.connect(self.plugin._queryAllInfo)
        self.buttons: list[QPushButton] = []
        self.active_file = None

    def eventFilter(self, obj: QObject, event: QEvent):
        if getattr(self.plugin, 'is_auto_querying', False):
            if event.type() in BLOCKED_EVENTS:
                return True

        if event.type() == QEvent.Type.Show and isinstance(obj, QMenu) and not self.plugin.processing_events:
            if obj.parent() == self.download_view:
                if getattr(self.plugin, 'is_auto_querying', False):
                    QTimer.singleShot(0, lambda:self.auto_trigger_menu(obj))
                    self.buttons.clear()
                    return False
                elif getattr(self.plugin, "insert_action_in_context_menus", False):
                    self.insert_action(obj)
        elif event.type() == QEvent.Type.Show and not self.plugin.processing_events and getattr(self.plugin, 'is_auto_querying', False):
            if isinstance(obj, QPushButton):
                self.buttons.append(obj)
            elif obj.objectName() == 'QInputDialogClassWindow':
                QTimer.singleShot(0, self.close_window)
                
        return False
    
    def close_window(self):
        if len(self.buttons) == 2:
            self.buttons[1].click()
            QTimer.singleShot(0, self.plugin._onDownloadComplete)
        self.buttons.clear()
        if self.active_file != None:
            self.plugin.make_fake_metadata(self.active_file)
    
    def insert_action(self, menu:QMenu):
        selection_model = self.download_view.selectionModel()
        if not selection_model.hasSelection():
            return
        index = selection_model.currentIndex()
        icon = index.sibling(index.row(), FILENAME_COLUMN).data(Qt.ItemDataRole.DecorationRole)
        if icon != None:
            actions = menu.actions()
            menu.insertAction(actions[2], self.action)

    def auto_trigger_menu(self, menu: QMenu):
        try:
            file_name = None
            self.active_file = None
            selection_model = self.download_view.selectionModel()
            if not selection_model.hasSelection():
                QTimer.singleShot(50, self.plugin._process_next)
                return
            index = selection_model.currentIndex()
            icon = index.sibling(index.row(), FILENAME_COLUMN).data(Qt.ItemDataRole.DecorationRole)
            if icon != None: #If icon is not None then the file is missing meta info and we want to query it.
                file_name = index.sibling(index.row(), FILENAME_COLUMN).data(Qt.ItemDataRole.DisplayRole)
                if file_name in self.plugin.queried_filenames:
                    return
                actions = menu.actions()
                if len(actions) > 1 and file_name:
                    query_action = actions[1]
                    if 'Nexus' not in query_action.text():
                        self.plugin.queried_filenames.append(file_name)
                        self.active_file = file_name
                        self.plugin._log(f"Querying info for {file_name}")
                        query_action.trigger()
                    else:
                        self.plugin._log(f"Failed to get correct query action for {file_name}")
                        self.plugin.pending_files.clear()
                        menu.close()
                        QTimer.singleShot(500, self.plugin._queryAllInfo)
                        return
            menu.close()
        except:
            menu.close()
           
class QueryAllInfo(mobase.IPlugin):

    def __init__(self):
        super(QueryAllInfo, self).__init__()
        self._parentWidget = None
    
    def init(self, organiser = mobase.IOrganizer):
        self._organizer = organiser
        self.is_auto_querying = False
        self.refresh_button = None
        self.queried_filenames = []
        self.download_dir: mobase.IDownloadManager = self._organizer.downloadsPath()
        self.insert_action_in_context_menus = self._organizer.pluginSetting(self.name(), "InsertActionInContextMenus")
        self.insert_button_in_download_tab = self._organizer.pluginSetting(self.name(), "InsertButtonInDownloadTab")
        self.fake_metadata = self._organizer.pluginSetting(self.name(), "FakeMetadataForNonNexus")
        self._organizer.downloadManager().onDownloadComplete(self._onDownloadComplete)
        self._organizer.onUserInterfaceInitialized(self._onUserInterfaceInitialized)
        self._organizer.onPluginSettingChanged(self._onPluginSettingChanged)
        self.button = QPushButton("Query All Info")
        self.button.adjustSize()
        self.button.clicked.connect(self._queryAllInfo)
        self.message_box = QMessageBox()
        self.message_box.setWindowTitle("Querying All Info")
        self.message_box.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.FramelessWindowHint
        )
        self.processing_events = False
        return True

    def name(self) -> str:
        return "QueryAllInfo"
    
    def localizedName(self) -> str:
        return self.tr("QueryAllInfo")
    
    def author(self) -> str:
        return "MaskPlague"

    def description(self):
        return self.tr("Adds a Query All Info button.")
    
    def version(self) -> mobase.VersionInfo:
        return mobase.VersionInfo(1, 2, 0, mobase.ReleaseType.ALPHA)
    
    def settings(self):
        return [
            mobase.PluginSetting("InsertActionInContextMenus", 
                                 'If the "Query All Info" action should be inserted in relevant context menus (changing requires restarting MO2).',
                                 False),
            mobase.PluginSetting("InsertButtonInDownloadTab", 
                                 'If the "Query All Info" button should be inserted at the top of the downloads tab (changing requires restarting MO2).', 
                                 True),
            mobase.PluginSetting("FakeMetadataForNonNexus",
                                 'If the plugin should create a fake file.zip.meta file for mods that are not from the Nexus.',
                                 False)
            ]
    
    def displayName(self):
        return self.tr("QueryAllInfo")
    
    def tooltip(self):
        return ""
    
    def icon(self):
        return QIcon()
    
    def display(self):
        return

    def tr(self, str):
        return QCoreApplication.translate("QueryAllInfo", str)
    
    def _log(self, string): #for debugging
        if DEBUG:
            print("QueryAllInfo log: " + string)

    def _onPluginSettingChanged(self, plugin, setting_changed, _3, new_val):
        if plugin == self.name():
            if setting_changed == "FakeMetadataForNonNexus":
                self.fake_metadata = new_val

    def _onUserInterfaceInitialized(self, main_window: QMainWindow):
        self.main_window = main_window
        tabWidget = main_window.findChild(QTabWidget, "tabWidget")
        downloadTab = tabWidget.findChild(QWidget, "downloadTab")
        downloadView = downloadTab.findChild(QTreeView, "downloadView")
        if self.insert_button_in_download_tab:
            self.holder = downloadTab.findChild(QWidget, "refreshHolder")
            if not self.holder:
                self.refresh_button = downloadTab.findChild(QPushButton, "btnRefreshDownloads")
                self.widget_rep = QWidget()
                self.widget_rep.setObjectName("refreshHolder")
                downloadTab.layout().replaceWidget(self.refresh_button, self.widget_rep)
                layout = QHBoxLayout()
                layout.addWidget(self.refresh_button)
                layout.addWidget(self.button)
                self.widget_rep.setLayout(layout)
            else:
                layout = self.holder.layout()
                layout.addWidget(self.button)
        
        self.downloadView: QTreeView = downloadView
        self.selection_model = self.downloadView.selectionModel()
        self.event_filter = ContextMenuEventFilter(
            downloadView, 
            self
        )
        QApplication.instance().installEventFilter(self.event_filter)

    def _queryAllInfo(self):
        self.button.setEnabled(False)
        self._log("Starting Auto Query...")
        self.is_auto_querying = True
        self.pending_files = []
        self.queried_filenames.clear()
        model = self.downloadView.model()
        rowCount = model.rowCount()
        rootIndex = self.downloadView.rootIndex()
        QApplication.restoreOverrideCursor()
        QApplication.setOverrideCursor(QCursor(WAIT_CURSOR))

        for row in range(0, rowCount):
            index = model.index(row, 0, rootIndex)
            icon = index.sibling(index.row(), FILENAME_COLUMN).data(Qt.ItemDataRole.DecorationRole)
            
            if icon != None:
                file_name = index.sibling(index.row(), FILENAME_COLUMN).data(Qt.ItemDataRole.DisplayRole)
                if file_name:
                    self.pending_files.append(file_name)
        
        self._log(f"Found {len(self.pending_files)} files to query.")
        self.message_box.setText(f"Querying {len(self.pending_files)} files. Please wait.")
        self.message_box.show()
        self._process_next()

    def _onDownloadComplete(self, *args):
        if not self.is_auto_querying:
            return
        if not self.processing_events:
            self.processing_events = True
            QApplication.processEvents()
            self.processing_events = False
        self._process_next()

    def _process_next(self):
        if not self.is_auto_querying:
            return
        if not self.pending_files:
            self.is_auto_querying = False
            self._log("Finished processing all queries.")
            self.message_box.hide()
            QApplication.restoreOverrideCursor()
            if hasattr(self, 'main_window') and self.main_window:
                self.main_window.activateWindow()
                self.main_window.raise_()
                self.downloadView.setFocus()
            self.button.setEnabled(True)
            return
        self.message_box.setText(f"Querying {len(self.pending_files)} files. Please wait.")
        target_file = self.pending_files.pop(0)
        model = self.downloadView.model()
        rowCount = model.rowCount()
        rootIndex = self.downloadView.rootIndex()
        index = None
        for row in range(rowCount):
            idx = model.index(row, 0, rootIndex)
            name = idx.sibling(row, FILENAME_COLUMN).data(Qt.ItemDataRole.DisplayRole)
            if name == target_file:
                index = idx
                break
        if index is None or not index.isValid():
            self._log(f"Could not find {target_file} in view anymore! Skipping.")
            QTimer.singleShot(50, self._process_next)
            return

        self.selection_model.setCurrentIndex(index, SELECT_FLAG)
        self.downloadView.scrollTo(index)
        rect = self.downloadView.visualRect(index)
        center_pos = rect.center()
        self.downloadView.customContextMenuRequested.emit(center_pos)

    def make_fake_metadata(self, file_name):
        if not self.fake_metadata:
            return
        path = os.path.join(self.download_dir, file_name) + '.meta'
        with open(path, "a+") as f:
            f.seek(0)
            lines = f.readlines()
            if len(lines) <= 2:
                f.seek(0)
                f.truncate(0)
                f.write("[General]\n"+
                    "removed=false\n"+
                    "gameName=\n"+
                    "modID=0\n"+
                    "fileID=0}\n"+
                    "url=\n"+
                    "name=\n"+
                    "description=\n"+
                    "modName=\n"+
                    "version=0.0.0.0\n"+
                    "newestVersion=0.0.0.0\n"+
                    f"fileTime=@DateTime({r'\0\0\0\x10\0\x80\0\0\0\0\0\0\0\xff\xff\xff\xff\0'})\n"+
                    "fileCategory=0\n"+
                    "category=0\n"+
                    "repository=NotNexus\n"+
                    f"userData=@Variant({r'\0\0\0\b\0\0\0\0'})\n"+
                    "installed=false\n"+
                    "uninstalled=false\n"+
                    "paused=false")
            f.close()
        return            

def createPlugin():
    return QueryAllInfo()
