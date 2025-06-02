#!/usr/bin/env python3
import sys
import os
import subprocess
import time
import platform
import shutil

# Configuration
WG_DIR = os.path.expanduser("~/scripts/wireguard_client/profiles")
SYSTEM_CONF_DIR = "/usr/local/etc/wireguard"
SYSTEM_IFACE = "wg0"
SYSTEM_CONF = os.path.join(SYSTEM_CONF_DIR, f"{SYSTEM_IFACE}.conf")
PING_COUNT = "5"
REFRESH_INTERVAL = 5000  # milliseconds

# Platform-aware binary selection
APP_INSTANCE_KEY = "wg_gui_single_instance"

if platform.system() == "Darwin":
    BASH = shutil.which("bash") or "/opt/homebrew/bin/bash"
    if not BASH.endswith("/bash") or "brew" not in BASH:
        BASH = "/opt/homebrew/bin/bash"
    WG_QUICK = "/opt/homebrew/bin/wg-quick"
else:
    BASH = "bash"
    WG_QUICK = "/usr/local/bin/wg-quick"
# --- Theme detection for tray icons ---
def is_dark_mode():
    # Manual override via environment variable
    env_override = os.environ.get("WG_GUI_FORCE_THEME", "").lower()
    if env_override in ("dark", "light"):
        return env_override == "dark"
    if platform.system() == "Darwin":
        try:
            mode = subprocess.check_output([
                "defaults", "read", "-g", "AppleInterfaceStyle"
            ]).decode().strip()
            return mode.lower() == "dark"
        except subprocess.CalledProcessError:
            return False
    xdg_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if xdg_desktop in ("gnome", "kde", "xfce"):
        theme = os.environ.get("GTK_THEME", "").lower()
        if "dark" in theme:
            return True

# XFCE-specific detection: parse xsettings.xml for ThemeName
        if xdg_desktop == "xfce":
            try:
                import xml.etree.ElementTree as ET
                xsettings_path = os.path.expanduser("~/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml")
                if os.path.exists(xsettings_path):
                    tree = ET.parse(xsettings_path)
                    root = tree.getroot()
                    for prop in root.findall(".//property"):
                        if prop.attrib.get("name") == "ThemeName":
                            value = prop.attrib.get("value", "").lower()
                            if "dark" in value or "black" in value:
                                return True
            except Exception:
                pass
    return False
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QLabel, QFormLayout, QGroupBox, QSplitter, QSizePolicy,
    QMessageBox, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import QProcess, Qt, QTimer
from PyQt6.QtGui import QFont, QIcon, QAction, QTextCursor, QPixmap, QPainter, QColor
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

# Additional imports for syntax highlighting
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor
from PyQt6.QtCore import QRegularExpression

def is_already_running():
    socket = QLocalSocket()
    socket.connectToServer(APP_INSTANCE_KEY)
    running = socket.waitForConnected(100)
    return running

def create_instance_lock():
    server = QLocalServer()
    if not server.listen(APP_INSTANCE_KEY):
        server.removeServer(APP_INSTANCE_KEY)
        server.listen(APP_INSTANCE_KEY)
    return server

def time_ago(epoch):
    delta = time.time() - epoch
    if delta < 60:
        return f"{int(delta)}s ago"
    elif delta < 3600:
        return f"{int(delta // 60)}m ago"
    elif delta < 86400:
        return f"{int(delta // 3600)}h ago"
    else:
        return f"{int(delta // 86400)}d ago"

def parse_wg_show():
    iface_info, peer_info = {}, {}
    try:
        out = subprocess.check_output(
            ["wg", "show", SYSTEM_IFACE],
        ).decode().strip()
        lines = out.splitlines()
        for line in lines:
            line = line.strip()
            if line.lower().startswith("interface:"):
                iface_info['name'] = line.split(":", 1)[1].strip()
            elif line.startswith("public key:"):
                iface_info['pubkey'] = line.split(":", 1)[1].strip()
            elif line.startswith("listening port:"):
                iface_info['port'] = line.split(":", 1)[1].strip()
            elif line.startswith("peer:"):
                peer_info['pubkey'] = line.split(":", 1)[1].strip()
            elif line.startswith("endpoint:"):
                peer_info['endpoint'] = line.split(":", 1)[1].strip()
            elif line.startswith("allowed ips:"):
                peer_info['allowed_ips'] = line.split(":", 1)[1].strip()
            elif line.startswith("latest handshake:"):
                peer_info['handshake'] = line.split(":", 1)[1].strip()
            elif line.startswith("transfer:"):
                peer_info['transfer'] = line.split(":", 1)[1].strip()
    except subprocess.CalledProcessError:
        pass
    return iface_info, peer_info

def parse_wg_conf(profile_path):
    interface = {}
    peer = {}
    in_peer = False
    with open(profile_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.lower() == '[interface]':
                in_peer = False
                continue
            if line.lower() == '[peer]':
                in_peer = True
                continue
            if '=' not in line:
                continue
            k, v = (i.strip() for i in line.split('=', 1))
            if in_peer:
                if k.lower() == 'publickey':
                    peer['pubkey'] = v
                elif k.lower() == 'allowedips':
                    peer['allowed_ips'] = v
                elif k.lower() == 'endpoint':
                    peer['endpoint'] = v
            else:
                if k.lower() == 'address':
                    interface.setdefault('addresses', []).append(v)
                elif k.lower() == 'dns':
                    interface.setdefault('dns', []).append(v)
                elif k.lower() == 'privatekey':
                    interface['privatekey'] = v
                elif k.lower() == 'listenport':
                    interface['port'] = v
    return interface, peer

APP_STYLESHEET = """
QLabel.data-label {
    font-family: "Consolas","IBM Plex Mono", "JetBrains Mono", monospace;
    text-shadow: 2px 2px 2px rgba(0, 0, 0, 0);

}

"""

class WGGui(QWidget):
    def __init__(self):
        super().__init__()

# --- Robust icon resource location ---
        icon_names = ["wireguard_off.png", "wg_connected.png"]
        icon_paths = []

# Try all possible locations where the icons might live
        candidate_dirs = []
        if getattr(sys, 'frozen', False):
            bundle_dir = os.path.dirname(sys.executable)
            candidate_dirs.append(os.path.normpath(os.path.join(bundle_dir, '..', 'Resources', 'Icons')))
        candidate_dirs.append(os.path.join(os.path.dirname(__file__), "Icons"))

# Just in case, check also a flat 'Resources/Icons' under cwd
        candidate_dirs.append(os.path.join(os.getcwd(), "Resources", "Icons"))

        resource_dir = None
        for d in candidate_dirs:
            missing = [name for name in icon_names if not os.path.exists(os.path.join(d, name))]
            if not missing:
                resource_dir = d
                break
        if not resource_dir:

# Give up: show dialog, print error, exit
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(None, "WireGuardClient Error",
                "Can't find required icon files in:\n\n" +
                "\n".join(candidate_dirs) +
                "\n\nMissing files: " + ", ".join(icon_names)
            )
            sys.exit(2)
        print("USING ICON DIR:", resource_dir)
        print("ICON FILES:", os.listdir(resource_dir))

        self.resource_dir = resource_dir
        self.icon_disconnected_path = os.path.join(self.resource_dir, "wireguard_off.png")
        self.icon_connected_path = os.path.join(self.resource_dir, "wg_connected.png")

# Initialize active_profile early so update_tray_icon never errors
        self.active_profile = None
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), "wireguard.png")))
        self.setWindowTitle("WireGuard Client")
        self.resize(900, 700)
        self.setMinimumHeight(600)
        self.quitting = False  # <-- NEW LINE to track if user explicitly quit

# ----- System Tray Setup -----

# Set icon paths for connected/disconnected states
        self.icon_disconnected_path = os.path.join(resource_dir, "wireguard_off.png")
        self.icon_connected_path = os.path.join(resource_dir, "wg_connected.png")
    
# Debug print for icon path existence
        print("DEBUG: Loading tray icon from", self.icon_disconnected_path, "exists:", os.path.exists(self.icon_disconnected_path), file=sys.stderr)
        
# Initialize tray icon with the disconnected icon
        disconnected_icon = QIcon(self.icon_disconnected_path)
        self.tray_icon = QSystemTrayIcon(disconnected_icon, self)

# Explicitly set the icon to make sure it’s recognized
        self.tray_icon.setIcon(QIcon(self.icon_disconnected_path))

# Ensure the tray icon is visible
        self.tray_icon.show()

# Update icon based on current status
        self.update_tray_icon()

# Build the context menu with theme-aware icons
        theme_suffix = "dark" if is_dark_mode() else "light"
        tray_menu = QMenu()
        self.act_show = QAction(QIcon(os.path.join(self.resource_dir, f"eye_{theme_suffix}.svg")), "Show", self)
        self.act_disconnect = QAction(QIcon(os.path.join(self.resource_dir, f"plug-off_{theme_suffix}.svg")), "Disconnect", self)
        self.act_quit = QAction(QIcon(os.path.join(self.resource_dir, f"logout_{theme_suffix}.svg")), "Disconnect & Quit", self)
        tray_menu.addAction(self.act_show)
        tray_menu.addAction(self.act_disconnect)
        tray_menu.addSeparator()
        tray_menu.addAction(self.act_quit)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)

# Connect actions to methods
        self.act_show.triggered.connect(self.show_and_raise)
        self.act_disconnect.triggered.connect(self.on_disconnect)
        self.act_quit.triggered.connect(self.quit_and_disconnect)

        self.tray_icon.show()

        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        self.list.setMaximumHeight(400)
        list_font = QFont()

# List font size        
        list_font.setPointSize(10)  # Try 9 or 8 for even smaller rows
        list_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.list.setFont(list_font)

        self.list.setSpacing(-1)
        self.list.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.list.setMinimumWidth(300)
        self.list.setMaximumWidth(300)
        self.list.currentItemChanged.connect(self.update_detail_panel)

        label_font = QFont()
        label_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

        self.intf_group = QGroupBox("Interface: -")
        intf_title_font = QFont()
        intf_title_font.setBold(True)
        intf_title_font.setPointSize(11)
        intf_title_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.intf_group.setFont(intf_title_font)
        self.intf_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        intf_form = QFormLayout()
        self.intf_form_layout = intf_form

        intf_form.setVerticalSpacing(12)
        intf_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        intf_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        intf_form.setHorizontalSpacing(40)
        intf_form.setSpacing(2)
        intf_form.setContentsMargins(0, 0, 0, 0)

# Status: dot + text
        self.status_dot = QLabel()
        self.status_text = QLabel()
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(6)
        status_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_text)
        status_layout.setSpacing(4)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_container = QWidget()
        status_container.setLayout(status_layout)
        self.lbl_pubkey = QLabel()
        self.lbl_port = QLabel()
        self.lbl_addresses = QLabel()
        self.lbl_dns = QLabel()

        for lbl in (self.status_dot, self.status_text, self.lbl_pubkey, self.lbl_port,
                    self.lbl_addresses, self.lbl_dns):
            lbl.setFont(label_font)
            lbl.setProperty("class", "data-label")
            lbl.setWordWrap(False)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setMinimumHeight(28)

        for name, widget in [
            ("Status:", status_container),
            ("Public Key:", self.lbl_pubkey),
            ("Listen Port:", self.lbl_port),
            ("Addresses:", self.lbl_addresses),
            ("DNS Servers:", self.lbl_dns)
        ]:
            label = QLabel(name)
            label.setMinimumWidth(130)
            label.setMaximumWidth(130)
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            widget.setContentsMargins(20, 0, 0, 0)
            intf_form.addRow(label, widget)

# Toggle-style button using QPushButton
        self.btnToggle = QPushButton("Activate")
        self.btnToggle.setCheckable(True)
        self.btnToggle.setChecked(False)
        self.btnToggle.toggled.connect(self.on_toggle_state)
        self.btnToggle.setFixedWidth(90)
        self.btnToggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btnToggle.setStyleSheet(f"""
            QPushButton {{
                background-color: qlineargradient(
                    spread:pad, x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(180, 255, 255, 255),
                    stop:1 rgba(100, 200, 255, 255)
                );
                color: black;
                border: 1px solid #3399cc;
                border-radius: 6px;
                padding: 42x 2px;
                font-weight: bold;
            }}
            QPushButton:checked {{
                background-color: qlineargradient(
                    spread:pad, x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(150, 255, 150, 255),
                    stop:1 rgba(60, 200, 120, 255)
                );
                color: black;
                border: 1px solid #339966;
            }}
        """)

# Apply drop shadow to the toggle button (pillbox and text)
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect

        toggle_shadow = QGraphicsDropShadowEffect()
        toggle_shadow.setBlurRadius(8)
        toggle_shadow.setOffset(1, 2)
        toggle_shadow.setColor(QColor(0, 0, 0, 160))
        self.btnToggle.setGraphicsEffect(toggle_shadow)

        intf_layout = QVBoxLayout()
        intf_layout.addLayout(intf_form)

# Corrected toggle button layout: align to right edge of value column
# Use a horizontal layout, pad left to match label width + spacing
        toggle_btn_layout = QHBoxLayout()
        toggle_btn_layout.setContentsMargins(130 + 40, 0, 0, 0)  # label width + spacing
        toggle_btn_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        toggle_btn_layout.addWidget(self.btnToggle)

        intf_layout.addLayout(toggle_btn_layout)
        self.intf_group.setLayout(intf_layout)
        self.intf_group.setMinimumHeight(220)

        self.peer_group = QGroupBox("Peer:")
        peer_title_font = QFont()
        peer_title_font.setBold(True)
        peer_title_font.setPointSize(11)
        peer_title_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.peer_group.setFont(peer_title_font)
        self.peer_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        peer_form = QFormLayout()
        self.peer_form_layout = peer_form

        peer_form.setHorizontalSpacing(40)
        peer_form.setVerticalSpacing(12)    # match interface section vertical spacing
        peer_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        peer_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        peer_form.setSpacing(2)

        self.lbl_peer_key = QLabel()
        self.lbl_allowed_ips = QLabel()
        self.lbl_endpoint = QLabel()
        self.lbl_handshake = QLabel()
        self.lbl_transfer = QLabel()

        for lbl in (self.lbl_peer_key, self.lbl_allowed_ips,
                    self.lbl_endpoint, self.lbl_handshake, self.lbl_transfer):
            lbl.setFont(label_font)
            lbl.setProperty("class", "data-label")
            lbl.setWordWrap(False)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setMinimumHeight(28)

        for name, widget in [
            ("Public Key:", self.lbl_peer_key),
            ("Allowed IPs:", self.lbl_allowed_ips),
            ("Endpoint:", self.lbl_endpoint),
            ("Last Handshake:", self.lbl_handshake),
            ("Transfer:", self.lbl_transfer)
        ]:
            label = QLabel(name)
            label.setMinimumWidth(130)
            label.setMaximumWidth(130)
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            widget.setContentsMargins(20, 0, 0, 0)
            peer_form.addRow(label, widget)
        self.peer_group.setLayout(peer_form)

        btn_box = QHBoxLayout()

# Profile toggle button ("Connect")
        self.btnProfileToggle = QPushButton("Connect")
        self.btnProfileToggle.setCheckable(True)
        self.btnProfileToggle.setChecked(False)
        self.btnProfileToggle.setFixedWidth(90)

        self.btnProfileToggle.toggled.connect(self.on_profile_toggle)

        self.btnQuit = QPushButton("Quit")
        self.btnQuit.setFixedWidth(90)
        self.btnQuit.clicked.connect(self.quit_and_disconnect)

        self.btnEdit = QPushButton("Edit")
        self.btnEdit.setFixedWidth(90)
        self.btnEdit.clicked.connect(self.edit_selected_profile)

# Insert btnProfileToggle as the first widget, keep it in the same row as btnEdit and btnQuit
        btn_box.addWidget(self.btnProfileToggle)
        btn_box.addWidget(self.btnEdit)
        btn_box.addWidget(self.btnQuit)

        left = QWidget()
        self.list.setMinimumWidth(260)
        self.list.setMaximumWidth(300)
        left.setMinimumWidth(300)
        left.setMaximumWidth(300)
        left_layout = QVBoxLayout(left)
        profiles_label = QLabel("Profiles")

        profiles_label.setProperty("class", "section-title")

        profiles_font = QFont()
        profiles_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        profiles_label.setFont(profiles_font)

# Insert profiles_header_layout here

        profiles_header_layout = QHBoxLayout()
        profiles_header_layout.addWidget(profiles_label)
        profiles_header_layout.addStretch()

        from PyQt6.QtWidgets import QStyle

 # --- Profile Management Buttons ---

        btnAdd = QPushButton()
        btnAdd.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
        btnAdd.setToolTip("Add Profile")
        btnAdd.clicked.connect(self.add_profile)

        btnDelete = QPushButton()
        btnDelete.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        btnDelete.setToolTip("Delete Profile")
        btnDelete.clicked.connect(self.delete_profile)

        btnUpload = QPushButton()
        btnUpload.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        btnUpload.setToolTip("Upload Profile")
        btnUpload.clicked.connect(self.upload_profile)

        btnDownload = QPushButton()
        btnDownload.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        btnDownload.setToolTip("Download All Profiles")
        btnDownload.clicked.connect(self.download_profiles)

        for btn in (btnAdd, btnDelete, btnUpload, btnDownload):
            btn.setFixedWidth(30)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            profiles_header_layout.addWidget(btn)

        left_layout.addLayout(profiles_header_layout)
        
# Add top margin spacer to align Interface group with Profiles header
        left_layout.addSpacing(12)

# left_layout.addWidget(profiles_label)  # Removed to avoid adding the label twice
        left_layout.addWidget(self.list)
        left_layout.addLayout(btn_box)

        right = QWidget()
        right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(12)
        right_layout.setContentsMargins(10, 12, 0, 0)
        right_layout.addWidget(self.intf_group)
        right_layout.addWidget(self.peer_group)
        right_layout.addStretch()
        def match_groupbox_widths():
            intf_form = self.intf_form_layout
            peer_form = self.peer_form_layout

            all_forms = [intf_form, peer_form]

# Collect label widgets
            label_widgets = []
            for form in all_forms:
                for i in range(form.rowCount()):
                    item = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
                    if item:
                        label_widgets.append(item.widget())

# Determine the widest label
            label_w = max((label.sizeHint().width() for label in label_widgets if label), default=110)

# Apply width to all labels
            for label in label_widgets:
                if label:
                    label.setMinimumWidth(label_w)
                    label.setMaximumWidth(label_w)
                    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

# Optional: ensure groupboxes align
            widest = max(self.intf_group.sizeHint().width(), self.peer_group.sizeHint().width(), 520)
            self.intf_group.setMinimumWidth(widest)
            self.peer_group.setMinimumWidth(widest)
        match_groupbox_widths()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setMinimumHeight(400)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background: transparent;
                width: 1px;
            }
        """)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)

        self.log = QTextEdit(readOnly=True)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        main_layout.addWidget(splitter)
        logs_label = QLabel("Logs")

        logs_label.setProperty("class", "section-title")

        logs_font = QFont()
        logs_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        logs_label.setFont(logs_font)
        main_layout.addWidget(logs_label)
        main_layout.addWidget(self.log)

# self.btnConnect.clicked.connect(self.on_connect)
# self.btnDisconnect.clicked.connect(self.on_disconnect)
# self.btnQuit.clicked.connect(self.quit_and_disconnect)

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)
        self.process.finished.connect(self.run_next)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(REFRESH_INTERVAL)

        self.active_profile = None
        self.commands = []
        self.cmd_index = 0

        self.load_profiles()
        QTimer.singleShot(100, self.refresh_status)

# Fade-in effect for the profile list
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        from PyQt6.QtCore import QPropertyAnimation

        self.list_opacity_effect = QGraphicsOpacityEffect(self.list)
        self.list.setGraphicsEffect(self.list_opacity_effect)
        self.list_opacity_effect.setOpacity(0.0)

        self.fade_anim = QPropertyAnimation(self.list_opacity_effect, b"opacity")
        self.fade_anim.setDuration(500)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()


    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_and_raise()

    def show_and_raise(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_and_disconnect(self):
        self.quitting = True
        if self.is_interface_up():
            self.on_disconnect()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
        else:
            self.hide()
            self.tray_icon.showMessage(
                "WireGuard Client",
                "App is still running in the tray. Right-click for options.",
                QSystemTrayIcon.MessageIcon.Information,
                5000
            )
            event.ignore()

    def update_tray_icon(self):
        connected = self.active_profile and self.is_interface_up()
        icon_path = self.icon_connected_path if connected else self.icon_disconnected_path
        self.tray_icon.setIcon(QIcon(icon_path))

# Base tooltip
        tooltip = [f"WireGuard: {'Connected' if connected else 'Disconnected'}"]

        if self.active_profile:
            tooltip.append(f"Profile: {self.active_profile}")

        if connected:
            try:
                _, peer = self.parse_wg_show()
                endpoint = peer.get("endpoint", "")
                handshake = peer.get("handshake", "")
                transfer = peer.get("transfer", "")

                if endpoint:
                    tooltip.append(f"Endpoint: {endpoint}")
                if handshake:
                    tooltip.append(f"Handshake: {handshake}")
                if transfer:
                    tooltip.append(f"Transfer: {transfer}")
            except Exception as e:
                tooltip.append("⚠ Failed to read status")

        self.tray_icon.setToolTip("\n".join(tooltip))

    
    def load_profiles(self):
        self.list.clear()
        for conf in sorted(os.listdir(WG_DIR)):
            if conf.endswith('.conf'):
                profile = conf[:-5]
                item = QListWidgetItem(profile)
                item.setData(Qt.ItemDataRole.UserRole, profile)
                font = QFont()
                font.setBold(True)
                font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
                item.setFont(font)
                self.list.addItem(item)

    def refresh_status(self):
        up = self.is_interface_up()
        for i in range(self.list.count()):
            itm = self.list.item(i)
            prof = itm.data(Qt.ItemDataRole.UserRole)
            font = QFont()
            font.setBold(up and prof == self.active_profile)
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            
# Draw a clean circle with fully transparent background
            size = 10
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)

# use a soft gray when not active, green when active
            color = QColor('#60FF60') if (up and prof == self.active_profile) else QColor('#888888')
            painter.setBrush(color)

# Inset a bit to prevent edge artifacts
            painter.drawEllipse(1, 1, size - 2, size - 2)
            painter.end()
            itm.setIcon(QIcon(pixmap))

            itm.setFont(font)
            itm.setText(prof)
        self.update_detail_panel()
        
# Tray icon connected
        self.update_tray_icon()
        
# Update tray menu icons for theme
        self.update_tray_menu_icons()
    def update_tray_menu_icons(self):
        """Update tray menu icons based on current theme."""
        theme_suffix = "dark" if is_dark_mode() else "light"
        self.act_show.setIcon(QIcon(os.path.join(self.resource_dir, f"eye_{theme_suffix}.svg")))
        self.act_disconnect.setIcon(QIcon(os.path.join(self.resource_dir, f"plug-off_{theme_suffix}.svg")))
        self.act_quit.setIcon(QIcon(os.path.join(self.resource_dir, f"logout_{theme_suffix}.svg")))

    def is_interface_up(self):
        try:
            out = subprocess.check_output(["wg", "show", SYSTEM_IFACE]).decode()
            return "interface:" in out
        except subprocess.CalledProcessError:
            return False

    def update_detail_panel(self):
        show_profile = self.active_profile if self.is_interface_up() and self.active_profile else None
        if not show_profile:
            item = self.list.currentItem()
            show_profile = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.status_dot.clear()
        self.status_text.clear()
        self.intf_group.setTitle(f"Interface: {show_profile}")
        self.lbl_pubkey.setText("-")
        self.lbl_port.setText("-")
        self.lbl_addresses.setText("-")
        self.lbl_dns.setText("-")
        self.lbl_peer_key.setText("-")
        self.lbl_allowed_ips.setText("-")
        self.lbl_endpoint.setText("-")
        self.lbl_handshake.setText("-")
        self.lbl_transfer.setText("-")
        if not show_profile:
            return
        conf_path = os.path.join(WG_DIR, f"{show_profile}.conf")
        conf_port = "-"
        if os.path.exists(conf_path):
            iface_conf, peer_conf = parse_wg_conf(conf_path)
            self.lbl_addresses.setText(", ".join(iface_conf.get('addresses', [])) or "-")
            self.lbl_dns.setText(", ".join(iface_conf.get('dns', [])) or "-")
            self.lbl_peer_key.setText(peer_conf.get('pubkey', "-"))
            self.lbl_allowed_ips.setText(peer_conf.get('allowed_ips', "-"))
            self.lbl_endpoint.setText(peer_conf.get('endpoint', "-"))
            conf_port = iface_conf.get('port', "-")
            self.lbl_port.setText(conf_port)
        if self.is_interface_up() and show_profile == self.active_profile:
            iface, peer = self.parse_wg_show()
            # Add green circle next to "Up"
            pix = QPixmap(12, 12)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor('#60FF60'))
            p.setPen(Qt.GlobalColor.transparent)
            p.drawEllipse(0, 0, 12, 12)
            p.end()
            self.status_dot.setPixmap(pix)
            self.status_text.setText("Up")
            self.status_text.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
            self.status_dot.setFixedSize(12, 12)
            self.lbl_pubkey.setText(iface.get('pubkey', "-"))
            self.lbl_port.setText(iface.get('port') or conf_port or "-")
            self.lbl_handshake.setText(peer.get('handshake', "-"))
            self.lbl_transfer.setText(peer.get('transfer', "-"))
        else:

# Always set dot to a fixed 12x12 transparent pixmap with red fill
            pix = QPixmap(12, 12)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor('#FF5050') if self.active_profile else QColor('#AAAAAA'))
            p.setPen(Qt.GlobalColor.transparent)
            p.drawEllipse(0, 0, 12, 12)
            p.end()
            self.status_dot.setPixmap(pix)
            self.status_dot.setFixedSize(12, 12)

# Set status text
            self.status_text.setText("Down" if self.active_profile else "")
            self.status_text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.status_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)



    def on_connect(self):
        itm = self.list.currentItem()
        if not itm:
            self.log.append("⚠ Select a profile first.\n")
            return
        prof = itm.data(Qt.ItemDataRole.UserRole)
        self.active_profile = prof
        src = os.path.join(WG_DIR, f"{prof}.conf")
        
# Kill any previous route_monitor.sh processes for wg0
        subprocess.run(["pkill", "-f", "route_monitor.sh start wg0"], shell=True)

        cmds = []

# Always use wg0 by copying the selected profile to the system path
        cmds.append(["doas", "cp", src, SYSTEM_CONF])
        if self.is_interface_up():
            cmds.append(["doas", WG_QUICK, "down", SYSTEM_IFACE])
            cmds.append(["sleep", "1"])
        cmds.append(["doas", WG_QUICK, "up", SYSTEM_IFACE])
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        POSTUP_SCRIPT = os.path.join(SCRIPT_DIR, "scripts", "global_postup.sh")
        cmds.append([POSTUP_SCRIPT, SYSTEM_IFACE])
        with open(src) as f:
            for ln in f:
                if ln.startswith("#ping "):
                    parts = ln.strip().split()
                    if len(parts) >= 2:
                        ip = parts[1]
                        cmds.append(["ping", "-c", PING_COUNT, ip])

        self.commands, self.cmd_index = cmds, 0
        self.log.clear()
        self.run_next()
        self.update_tray_icon()

# Update toggle button state and text
        self.btnToggle.setChecked(True)
        self.btnToggle.style().unpolish(self.btnToggle)
        self.btnToggle.style().polish(self.btnToggle)
        self.btnToggle.update()
        self.btnToggle.setText("Deactivate")  # Ensure this is last

# --- Synchronize secondary toggle button ---
        self.btnProfileToggle.setChecked(True)
        self.btnProfileToggle.setText("Disconnect")
        print("DEBUG: btnToggle text set to:", self.btnToggle.text(), file=sys.stderr)

# Flush routes on disconnect
    def on_disconnect(self): 
        self.log.append("🔻 Disconnecting interface and flushing routes...\n")
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        FLUSH_SCRIPT = os.path.join(SCRIPT_DIR, "scripts", "flush_wg_routes.sh")
        self.commands = [
            [WG_QUICK, "down", SYSTEM_IFACE],
            [FLUSH_SCRIPT, SYSTEM_IFACE]
        ]
        self.cmd_index = 0
        self.active_profile = None
        self.log.clear()
        self.run_next()

# Reset toggle button state
        self.btnToggle.setChecked(False)
        self.btnToggle.setText("Activate")
        self.btnProfileToggle.setChecked(False)
        self.btnProfileToggle.setText("Connect")

    def on_toggle(self):
        if self.is_interface_up():
            self.on_disconnect()
        else:
            self.on_connect()

    def on_toggle_state(self, checked):
        print("DEBUG: toggle_state changed to", checked, file=sys.stderr)
        if checked:
            self.on_connect()
        else:
            self.on_disconnect()

    def on_profile_toggle(self, checked):
        print("DEBUG: profile_toggle changed to", checked, file=sys.stderr)
        if checked:
            self.on_connect()
            self.btnProfileToggle.setText("Disconnect")
        else:
            self.on_disconnect()
            self.btnProfileToggle.setText("Connect")
            
    def run_next(self):
        if self.cmd_index < len(self.commands):
            c = self.commands[self.cmd_index]
            self.cmd_index += 1
            self.log.append(f"> {' '.join(c)}\n")
            self.process.start(c[0], c[1:])
        else:

# All commands done; refresh status after short delay
            QTimer.singleShot(500, self.refresh_status)

    def on_stdout(self):
        out = self.process.readAllStandardOutput().data().decode()
        self.log.insertPlainText(out)
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def on_stderr(self):
        err = self.process.readAllStandardError().data().decode()
        self.log.insertPlainText(err)
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def parse_wg_show(self):
        return parse_wg_show()

    def edit_selected_profile(self):
        """Open the selected profile in a QPlainTextEdit dialog."""
        itm = self.list.currentItem()
        if not itm:
            self.log.append("⚠ Select a profile to edit.\n")
            return
        prof = itm.data(Qt.ItemDataRole.UserRole)
        conf_path = os.path.join(WG_DIR, f"{prof}.conf")
        if not os.path.exists(conf_path):
            self.log.append(f"⚠ Profile file not found: {conf_path}\n")
            return

        try:
            with open(conf_path, "r") as f:
                content = f.read()
        except Exception as e:
            self.log.append(f"⚠ Failed to read profile: {e}\n")
            return

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QDialogButtonBox, QPlainTextEdit
        from PyQt6.QtGui import QFont

        class WireGuardHighlighter(QSyntaxHighlighter):
            def __init__(self, document):
                super().__init__(document)

                self.rules = []

                # Section headers
                section_format = QTextCharFormat()
                section_format.setForeground(QColor("#87CEFA"))  # Light blue
                section_format.setFontWeight(QFont.Weight.Bold)
                self.rules.append((QRegularExpression(r"^\[.*\]"), section_format))

                # Key = value
                key_format = QTextCharFormat()
                key_format.setForeground(QColor("#90EE90"))  # Light green
                self.rules.append((QRegularExpression(r"^\s*\w+\s*="), key_format))

                # Comments
                comment_format = QTextCharFormat()
                # Adjust comment color for dark mode
                if is_dark_mode():
                    comment_format.setForeground(QColor("#BBBBBB"))  # Lighter gray for dark mode
                else:
                    comment_format.setForeground(QColor("#888888"))  # Gray
                comment_format.setFontItalic(True)
                self.rules.append((QRegularExpression(r"#.*$"), comment_format))

            def highlightBlock(self, text):
                for pattern, fmt in self.rules:
                    match_iter = pattern.globalMatch(text)
                    while match_iter.hasNext():
                        match = match_iter.next()
                        self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

        class EditorDialog(QDialog):
            def __init__(self, parent=None, title="Edit", text=""):
                super().__init__(parent)
                self.setWindowTitle(title)
                self.setMinimumSize(600, 400)

                self.text_edit = QPlainTextEdit()
                self.text_edit.setPlainText(text)

                # Monospace font
                font = QFont("monospace")
                font.setStyleHint(QFont.StyleHint.TypeWriter)
                self.text_edit.setFont(font)

                # Apply syntax highlighting
                WireGuardHighlighter(self.text_edit.document())

                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
                buttons.accepted.connect(self.accept)
                buttons.rejected.connect(self.reject)

                layout = QVBoxLayout()
                layout.addWidget(self.text_edit)
                layout.addWidget(buttons)
                self.setLayout(layout)

            def get_text(self):
                return self.text_edit.toPlainText()

        dlg = EditorDialog(self, title=f"Edit Profile: {prof}", text=content)
        if dlg.exec():
            try:
                with open(conf_path, "w") as f:
                    f.write(dlg.get_text())
                self.log.append(f"✅ Saved changes to {prof}.conf\n")
            except Exception as e:
                self.log.append(f"⚠ Failed to save profile: {e}\n")

# Add new profile
    def add_profile(self):
        
        from PyQt6.QtWidgets import QInputDialog, QDialog, QVBoxLayout, QDialogButtonBox, QPlainTextEdit
        from PyQt6.QtGui import QFont

        prof, ok = QInputDialog.getText(self, "New Profile", "Enter profile name:")
        if not ok or not prof:
            return
        conf_path = os.path.join(WG_DIR, f"{prof}.conf")
        if os.path.exists(conf_path):
            QMessageBox.warning(self, "Error", f"Profile '{prof}' already exists.")
            return

        template = "[Interface]\nAddress = \nPrivateKey = \nListenPort = \nDNS = \n\n[Peer]\nPublicKey = \nAllowedIPs = \nEndpoint = \n"

        class EditorDialog(QDialog):
            def __init__(self, parent=None, title="New Profile", text=""):
                super().__init__(parent)
                self.setWindowTitle(title)
                self.setMinimumSize(600, 400)

                self.text_edit = QPlainTextEdit()
                self.text_edit.setPlainText(text)

                font = QFont("monospace")
                font.setStyleHint(QFont.StyleHint.TypeWriter)
                self.text_edit.setFont(font)

                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
                buttons.accepted.connect(self.accept)
                buttons.rejected.connect(self.reject)

                layout = QVBoxLayout()
                layout.addWidget(self.text_edit)
                layout.addWidget(buttons)
                self.setLayout(layout)

            def get_text(self):
                return self.text_edit.toPlainText()

        dlg = EditorDialog(self, title=f"New Profile: {prof}", text=template)
        if dlg.exec():
            try:
                with open(conf_path, "w") as f:
                    f.write(dlg.get_text())
                self.log.append(f"✅ Created profile: {prof}.conf\n")
                self.load_profiles()
            except Exception as e:
                self.log.append(f"⚠ Failed to create profile: {e}\n")

# Delete profile
    def delete_profile(self):
        item = self.list.currentItem()
        if not item:
            self.log.append("⚠ No profile selected to delete.\n")
            return
        prof = item.data(Qt.ItemDataRole.UserRole)
        conf_path = os.path.join(WG_DIR, f"{prof}.conf")
        try:
            os.remove(conf_path)
            self.log.append(f"🗑️ Deleted profile: {prof}\n")
            self.load_profiles()
        except Exception as e:
            self.log.append(f"⚠ Failed to delete profile {prof}: {e}\n")

# Upload profile
    def upload_profile(self):
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(self, "Upload Profile", "", "WireGuard Config (*.conf)")
        if file_path:
            dst_path = os.path.join(WG_DIR, os.path.basename(file_path))
            try:
                shutil.copy(file_path, dst_path)
                self.log.append(f"📤 Uploaded profile to {dst_path}\n")
                self.load_profiles()
            except Exception as e:
                self.log.append(f"⚠ Failed to upload: {e}\n")

# Download profiles .zip
    def download_profiles(self):
        from PyQt6.QtWidgets import QFileDialog
        import zipfile

        file_path, _ = QFileDialog.getSaveFileName(self, "Save ZIP Archive", "wireguard_profiles.zip", "ZIP Archive (*.zip)")
        if not file_path:
            return
        try:
            with zipfile.ZipFile(file_path, 'w') as zipf:
                for conf in os.listdir(WG_DIR):
                    if conf.endswith(".conf"):
                        full_path = os.path.join(WG_DIR, conf)
                        zipf.write(full_path, arcname=conf)
            self.log.append(f"📦 Downloaded all profiles to {file_path}\n")
        except Exception as e:
            self.log.append(f"⚠ Failed to create ZIP archive: {e}\n")

if __name__ == "__main__":
    if is_already_running():
        print("🚫 WireGuard Client is already running.")
        sys.exit(0)

    instance_lock = create_instance_lock()

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)  # <-- Apply styles
    gui = WGGui()
    gui.show()
    sys.exit(app.exec())
