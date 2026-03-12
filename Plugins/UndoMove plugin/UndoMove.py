#Written by MaskPlague
import mobase
import time

try:
    from PyQt6.QtCore import QCoreApplication, QTimer
    from PyQt6.QtGui import QIcon, QShortcut, QKeySequence
    from PyQt6.QtWidgets import QKeySequenceEdit, QLabel, QGridLayout, QDialog, QPushButton, QWidget, QHBoxLayout, QCheckBox
except ImportError:
    from PyQt5.QtCore import QCoreApplication, QTimer
    from PyQt5.QtGui import QIcon, QShortcut, QKeySequence
    from PyQt5.QtWidgets import QKeySequenceEdit, QLabel, QGridLayout, QDialog, QPushButton, QWidget, QHBoxLayout, QCheckBox

class UndoMove(mobase.IPluginTool):

    def __init__(self):
        self.pluginNames = []
        super(UndoMove, self).__init__()
        self.__parentWidget = None
    
    def init(self, organiser=mobase.IOrganizer):
        self.debug = False
        self.num = 0
        self.last_time = 0
        self.enabled_mod_list = []
        self.enabled_plugin_list = []
        self.disabled_mod_list = []
        self.disabled_plugin_list = []
        self.priority_changed_mod_list = []
        self.priority_changed_plugin_list = []
        self.separators = []
        self.crossed_sep = False

        self.refresh_timer = QTimer()
        self.refresh_timer.setInterval(1500)
        self.refresh_timer.timeout.connect(self.refresh_and_stop)

        self.toggle_timer = QTimer()
        self.toggle_timer.setInterval(100)
        self.toggle_timer.timeout.connect(self.toggle_timer_done)
        self.toggle_timer_running = False

        self.priority_timer = QTimer()
        self.priority_timer.setInterval(100)
        self.priority_timer.timeout.connect(self.priority_timer_done)
        self.priority_timer_running = False

        self._organizer = organiser
        self.modList: mobase.IModList = self._organizer.modList()
        self.pluginList: mobase.IPluginList = self._organizer.pluginList()
        self.history_mod_list = []
        self.history_plugin_list = []
        self.undone_history_mod_list = []
        self.undone_history_plugin_list = []
        self.redo_plugin_shortcut = QShortcut(None)
        self.redo_plugin_shortcut.activated.connect(lambda: self.do_redo("p"))
        self.redo_mod_shorcut = QShortcut(None)
        self.redo_mod_shorcut.activated.connect(lambda: self.do_redo("m"))
        self.making_changes = False

        self.undo_plugin_shorcut = QShortcut(None)
        self.undo_plugin_shorcut.activated.connect(lambda: self.do_undo("p"))
        self.undo_mod_shorcut = QShortcut(None)
        self.undo_mod_shorcut.activated.connect(lambda: self.do_undo("m"))

        self.modList.onModMoved(lambda name, old_priority, new_priority: self.add_to_history_priority('m_reset', name, old_priority, new_priority))
        self.modList.onModStateChanged(lambda state_change: self.add_to_history_toggle('m_reset', state_change))
        self.pluginList.onPluginMoved(lambda name, old_priority, new_priority: self.add_to_history_priority('p_reset', name, old_priority, new_priority))
        self.pluginList.onPluginStateChanged(lambda state_change: self.add_to_history_toggle('p_reset', state_change))
        self._organizer.onUserInterfaceInitialized(lambda window: self.update_shortcuts(window))
        self._organizer.onUserInterfaceInitialized(lambda window: self.create_and_install_buttons(window))
        self._organizer.onPluginSettingChanged(lambda str, str2, Movariant, Movariant2: self.update_shortcuts(self.__parentWidget))

        self.create_key_sequence_getter()

        return True
    
    def refresh_and_stop(self):
        self.refresh_timer.stop()
        self.crossed_sep = False
        self._organizer.refresh()
    
    def add_to_history_priority(self, list_type, mod_name, old_priority, new_priority):
        if self.making_changes:
            return
        if list_type in ('m', 'm_reset'):
            mods = self.modList.allModsByProfilePriority(self._organizer.profile())
            self.separators.clear()
            for i, mod in enumerate(mods):
                if mod.endswith('_separator'):
                    self.separators.append(i)
        if not self.priority_timer_running:
            self.priority_timer_running = True
            self.priority_timer.start()
        if list_type == "m_reset":
            self.undone_history_mod_list.clear()
            list_type = "m"
        elif list_type == "p_reset":
            self.undone_history_plugin_list.clear()
            list_type = "p"
        if list_type == 'm':
            self.priority_changed_mod_list.insert(0, {'name': mod_name, 'prev': old_priority, 'current': new_priority})
        else:
            self.priority_changed_plugin_list.insert(0, {'name': mod_name, 'prev': old_priority, 'current': new_priority})
        
    def priority_timer_done(self):
        self.priority_timer.stop()
        if len(self.priority_changed_mod_list) > 0:
            self.history_mod_list.append({'type': 'priority', 'changes': self.priority_changed_mod_list.copy()})
        if len(self.priority_changed_plugin_list) > 0:
            self.history_plugin_list.append({'type': 'priority', 'changes': self.priority_changed_plugin_list.copy()})
        self.priority_changed_mod_list.clear()
        self.priority_changed_plugin_list.clear()
        self.priority_timer_running = False

    def add_to_history_toggle(self, list_type, state_changes: dict, reverse=False):
        if self.making_changes:
            return
        if not self.toggle_timer_running:
            self.toggle_timer_running = True
            self.toggle_timer.start()
        if not reverse:
            for mod_name, state in state_changes.items():
                if (state in (33, 35) and list_type in ('m', 'm_reset')) or (state in (1, 2) and list_type in ('p', 'p_reset')):
                    if list_type == 'm_reset':
                        self.undone_history_mod_list.clear()
                        list_type = 'm'
                    elif list_type == 'p_reset':
                        self.undone_history_plugin_list.clear()
                        list_type = 'p'
                    if state in (2, 35):
                        if list_type == 'm':
                            self.enabled_mod_list.append(mod_name)
                        else:
                            self.enabled_plugin_list.append(mod_name)
                    else:
                        if list_type == 'm':
                            self.disabled_mod_list.append(mod_name)
                        else:
                            self.disabled_plugin_list.append(mod_name)
        else:
            if list_type == 'm':
                self.enabled_mod_list.extend(state_changes['disabled'])
                self.disabled_mod_list.extend(state_changes['enabled'])
            else:
                self.enabled_plugin_list.extend(state_changes['disabled'])
                self.disabled_plugin_list.extend(state_changes['enabled'])

    def toggle_timer_done(self):
        self.toggle_timer.stop()
        if len(self.disabled_mod_list) > 0 or len(self.enabled_mod_list) > 0:
            self.history_mod_list.append({'type': 'toggle', 'disabled': self.disabled_mod_list.copy(), 'enabled': self.enabled_mod_list.copy()})
        if len(self.disabled_plugin_list) > 0 or len(self.enabled_plugin_list) > 0:
            self.history_plugin_list.append({'type': 'toggle', 'disabled': self.disabled_plugin_list.copy(), 'enabled': self.enabled_plugin_list.copy()})
        self.enabled_mod_list.clear()
        self.disabled_mod_list.clear()
        self.enabled_plugin_list.clear()
        self.disabled_plugin_list.clear()
        self.toggle_timer_running = False

    def add_to_undone_history(self, list_type, undone):
        if undone['type'] == 'priority':
            switched = []
            for change in undone['changes']:
                switched.insert(0, {'name': change['name'], 'prev': change['current'], 'current': change['prev']})
            new_dict = {'type': 'priority', 'changes': switched}
        else:
            new_dict = {'type': 'toggle', 'disabled': undone['enabled'], 'enabled': undone['disabled']}
        if list_type == 'm':
            self.undone_history_mod_list.append(new_dict)
        else:
            self.undone_history_plugin_list.append(new_dict)

    def change_state(self, list_type, to_change):
        self.making_changes = True
        priority_changes = []
        set_priority = self.modList.setPriority if list_type == 'm' else self.pluginList.setPriority
        enable_or_disable = self.modList.setActive if list_type == 'm' else self.pluginList.setState

        if to_change['type'] == 'priority':
            if len(to_change['changes']) > 0:
                for change in to_change['changes']:
                    set_priority(change['name'], change['prev'])
                    priority_changes.append((change['prev'], change['current'])) 
                    time.sleep(0.01)
        else:   
            if list_type == 'm':
                if len(to_change['disabled']) > 0:
                    enable_or_disable(to_change['disabled'], True) 
                if len(to_change['enabled']) > 0:
                    enable_or_disable(to_change['enabled'], False)
            else:
                for mod in to_change['disabled']:
                    enable_or_disable(mod, 2)
                    time.sleep(0.01)
                for mod in to_change['enabled']:
                    enable_or_disable(mod, 1)
                    time.sleep(0.01)
                if self.esp_list:
                    self.esp_list.setFocus()
        self.making_changes = False
        if self.crossed_sep:
            self.refresh_timer.stop()
            self.refresh_timer.start()
        if list_type == 'm' and len(priority_changes) > 0 and not self.crossed_sep:
            if any(any(prev <= sep <= curr or prev >= sep >= curr
                   for sep in self.separators)
                   for prev, curr in priority_changes
                   ):
                if self.immediate_refresh:
                    self.crossed_sep = False
                    self._organizer.refresh()
                else:
                    self.crossed_sep = True
                    self.refresh_timer.start()

    def do_undo(self, list_type):
        if list_type == 'm' and len(self.history_mod_list) > 0 or list_type == 'p' and len(self.history_plugin_list) > 0:
            to_undo = self.history_mod_list.pop() if list_type == 'm' else self.history_plugin_list.pop()
            self.add_to_undone_history(list_type, to_undo)
            self.change_state(list_type, to_undo)

    def do_redo(self, list_type):
        if (list_type == 'm' and len(self.undone_history_mod_list) > 0) or (list_type == 'p' and len(self.undone_history_plugin_list) > 0):
            to_redo = self.undone_history_mod_list.pop() if list_type == 'm' else self.undone_history_plugin_list.pop()
            if to_redo['type'] == 'priority':
                for change in to_redo['changes']:
                    self.add_to_history_priority(list_type, change['name'], change['current'], change['prev'])
            else:
                self.add_to_history_toggle(list_type, to_redo, reverse=True)
            self.change_state(list_type, to_redo)

    def create_key_sequence_getter(self):
        main_layout = QGridLayout()

        immediate_refresh_label = QLabel("Immediate Refresh")
        immediate_refresh_label.setToolTip("Immediately refresh when a mod crosses a separator.\nOtherwise, after no undo/redo input for 1.5 seconds.")
        self.immediate_refresh_check_box = QCheckBox()
        self.immediate_refresh_check_box.setToolTip("Immediately refresh when a mod crosses a separator.\nOtherwise, after no undo/redo input for 1.5 seconds.")
        self.immediate_refresh_check_box.setChecked(self._organizer.pluginSetting(self.name(), "Immediate Refresh"))
        self.immediate_refresh = self.immediate_refresh_check_box.isChecked()
        main_layout.addWidget(immediate_refresh_label, 0, 0)
        main_layout.addWidget(self.immediate_refresh_check_box, 0, 1)

        self.undo_m_sequence = self.create_sequence(main_layout, "Undo Modlist Change Shortcut", 1)
        self.redo_m_sequence = self.create_sequence(main_layout, "Redo Modlist Change Shortcut", 2)
        self.undo_p_sequence = self.create_sequence(main_layout, "Undo Plugin List Change Shortcut", 3)
        self.redo_p_sequence = self.create_sequence(main_layout, "Redo Plugin List Change Shortcut", 4)

        self.reset_defaults = QPushButton("Reset Shortcuts")
        self.reset_defaults.setMaximumSize(150, 30)
        self.reset_defaults.clicked.connect(self.reset_to_defaults)
        main_layout.addWidget(self.reset_defaults, 5, 0)

        self.main_widget = QDialog()
        self.main_widget.setWindowTitle("UndoMove Shortcut Manager")
        self.main_widget.setLayout(main_layout)
        self.main_widget.hide()

        self.immediate_refresh_check_box.stateChanged.connect(self.update_settings)

    def create_sequence(self, layout: QGridLayout, key: str, row: int):
        label = QLabel(key)
        sequence = QKeySequenceEdit(QKeySequence(self._organizer.pluginSetting(self.name(), key)))
        sequence.keySequenceChanged.connect(self.update_settings)
        layout.addWidget(label, row, 0)
        layout.addWidget(sequence, row, 1)
        return sequence

    def reset_to_defaults(self):
        self.undo_m_sequence.setKeySequence("Ctrl+Alt+Z")
        self.redo_m_sequence.setKeySequence("Ctrl+Alt+Shift+Z")
        self.undo_p_sequence.setKeySequence("Ctrl+Alt+X")
        self.redo_p_sequence.setKeySequence("Ctrl+Alt+Shift+X")

    def name(self) -> str:
        return "UndoMove"
    
    def author(self) -> str:
        return "MaskPlague"

    def description(self) -> str:
        return self.tr(".")
    
    def version(self):
        return mobase.VersionInfo(0, 3, 3, mobase.ReleaseType.FINAL)
    
    def settings(self):
        return [
            mobase.PluginSetting("Undo Modlist Change Shortcut", self.tr("Shortcut"), "Ctrl+Alt+Z"),
            mobase.PluginSetting("Redo Modlist Change Shortcut", self.tr("Shortcut"), "Ctrl+Alt+Shift+Z"),
            mobase.PluginSetting("Undo Plugin List Change Shortcut", self.tr("Shortcut"), "Ctrl+Alt+X"),
            mobase.PluginSetting("Redo Plugin List Change Shortcut", self.tr("Shortcut"), "Ctrl+Alt+Shift+X"),
            mobase.PluginSetting("Immediate Refresh", self.tr("Immediately refresh when a mod crosses a separator.\nOtherwise, after no undo/redo input for 1.5 seconds."), False),
            ]
    
    def displayName(self):
        return self.tr("UndoMove")
    
    def tooltip(self):
        return self.tr("Displays shortcut editor for UndoMove")
    
    def icon(self):
        return QIcon(None)
    
    def display(self):
        self.main_widget.show()
        return
    
    def tr(self, str):
        return QCoreApplication.translate("UndoMove", str)

    def update_shortcuts(self, parent):
        if self.__parentWidget != parent: 
            self.__parentWidget = parent

        self.undo_mod_shorcut.setParent(parent)
        self.undo_mod_shorcut.setKey(self.undo_m_sequence.keySequence())

        self.redo_mod_shorcut.setParent(parent)
        self.redo_mod_shorcut.setKey(self.redo_m_sequence.keySequence())

        self.undo_plugin_shorcut.setParent(parent)
        self.undo_plugin_shorcut.setKey(self.undo_p_sequence.keySequence())

        self.redo_plugin_shortcut.setParent(parent)
        self.redo_plugin_shortcut.setKey(self.redo_p_sequence.keySequence())

    def create_button(self, icon_path, tool_tip, function, list_type):
        button = QPushButton()
        button.setIcon(QIcon(icon_path))
        button.setToolTip(self.tr(tool_tip))
        button.clicked.connect(lambda: function(list_type))
        return button

    def create_and_install_buttons(self, parent):
        if self.__parentWidget != parent:
            self.__parentWidget = parent
        undo_icon_path: str = self._organizer.pluginDataPath().replace('plugins/data', 'plugins/UndoMove Icons/undo_icon.ico')
        redo_icon_path = undo_icon_path.replace('/undo_icon.ico', '/redo_icon.ico')

        undo_button_mod_list = self.create_button(undo_icon_path, "Undo mod list change.", self.do_undo, 'm')
        undo_button_plugin_list = self.create_button(undo_icon_path, "Undo plugin list change.", self.do_undo, 'p')

        redo_button_mod_list = self.create_button(redo_icon_path, "Redo mod list change.", self.do_redo, 'm')
        redo_button_plugin_list = self.create_button(redo_icon_path, "Redo plugin list change.", self.do_redo, 'p')
        
        mod_list_buttons_inserted = False
        plugin_list_buttons_inserted = False
        esp_list_retrieved = False
        categories_splitter = None
        splitter = None
        layout_widget = None
        layout = None
        hlayout = None
        layout_widget_2 = None
        tab_widget = None
        tabwidget_stacked = None
        esp_tab = None
        esp_layout = None
        h_esp_layout = None
        esp_list = None
        self.esp_list = None
        central_widget = self._parentWidget().findChild(QWidget, 'centralWidget')
        if central_widget:
            categories_splitter = central_widget.findChild(QWidget, 'categoriesSplitter')
            if categories_splitter:
                splitter = categories_splitter.findChild(QWidget, 'splitter')
                if splitter:
                    layout_widget = splitter.findChild(QWidget, 'layoutWidget')
                    if layout_widget:
                        layout = layout_widget.layout()
                        hlayout: QHBoxLayout = layout.children()[0]
                        hlayout.insertWidget(3, undo_button_mod_list)
                        hlayout.insertWidget(4, redo_button_mod_list)
                        mod_list_buttons_inserted = True
                    layout_widget_2 = splitter.findChild(QWidget, 'layoutWidget_2')
                    if layout_widget_2:
                        tab_widget = layout_widget_2.findChild(QWidget, 'tabWidget')
                        if tab_widget:
                            tabwidget_stacked = tab_widget.findChild(QWidget, 'qt_tabwidget_stackedwidget')
                            if tabwidget_stacked:
                                esp_tab = tabwidget_stacked.findChild(QWidget, 'espTab')
                                if esp_tab:
                                    esp_layout = esp_tab.layout()
                                    h_esp_layout: QHBoxLayout = esp_layout.children()[0]
                                    h_esp_layout.insertWidget(2, undo_button_plugin_list)
                                    h_esp_layout.insertWidget(3, redo_button_plugin_list)
                                    plugin_list_buttons_inserted = True
                                    esp_list = esp_tab.findChild(QWidget, 'espList')
                                    if esp_list:
                                        self.esp_list = esp_list
                                        esp_list_retrieved = True

        if not mod_list_buttons_inserted:
            self.log("Failed to insert buttons into mod list.")
        if not plugin_list_buttons_inserted:
            self.log("Failed to insert buttons into plugin list.")
        if not esp_list_retrieved:
            self.log("Failed to retrieve espList widget.")
        if any(widget == None 
               for widget in [categories_splitter,splitter,layout_widget, layout, hlayout, layout_widget_2, 
                              tab_widget, tabwidget_stacked, esp_tab, esp_layout, h_esp_layout, esp_list]):
            self.log(f"\n\t{categories_splitter=}\n\t{splitter=}\n\t{layout_widget=}\n\t{layout=}\n"+
                    f"\t{hlayout=}\n\t{layout_widget_2=}\n\t{tab_widget=}\n\t{tabwidget_stacked=}\n"+
                    f"\t{esp_tab=}\n\t{esp_layout=}\n\t{h_esp_layout=}\n\t{esp_list=}")

    def log(self, text):
        print(self.tr(f"UndoMove: {text}"))

    def update_settings(self):
        self.immediate_refresh = self.immediate_refresh_check_box.isChecked()
        self._organizer.setPluginSetting(self.name(), "Immediate Refresh", self.immediate_refresh)
        self._organizer.setPluginSetting(self.name(), "Undo Modlist Change Shortcut", self.undo_m_sequence.keySequence().toString())
        self._organizer.setPluginSetting(self.name(), "Redo Modlist Change Shortcut", self.redo_m_sequence.keySequence().toString())
        self._organizer.setPluginSetting(self.name(), "Undo Plugin List Change Shortcut", self.undo_p_sequence.keySequence().toString())
        self._organizer.setPluginSetting(self.name(), "Redo Plugin List Change Shortcut", self.redo_p_sequence.keySequence().toString())

def createPlugin() -> mobase.IPlugin:
    return UndoMove()
