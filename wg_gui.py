#!/usr/bin/env python3

# === Imports ===
import os
import sys
import platform
import shutil
import subprocess
import time
import json
import tempfile
import zipfile
import xml.etree.ElementTree as ET
import glob
import re

from PyQt6.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QTabWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QPushButton, QListWidget, QLabel,
    QListWidgetItem, QTextEdit, QFormLayout, QSplitter, QSizePolicy,
    QMessageBox, QMenu, QFileDialog, QDialog,
    QDialogButtonBox, QPlainTextEdit, QStyle, QGraphicsDropShadowEffect,
    QLineEdit, QGridLayout
)
from PyQt6.QtCore import (
    QProcess, Qt, QTimer, QRegularExpression, QEvent, QSize, QRectF
)
from PyQt6.QtGui import (
    QFont, QIcon, QAction, QTextCursor, QPixmap, QPainter, QColor,
    QSyntaxHighlighter, QTextCharFormat, QRadialGradient
)

from PyQt6.QtNetwork import QLocalServer, QLocalSocket

# === Feature Toggles ===
ENABLE_TOOLS_TAB = True  # Toggle this to False to disable Tools tab

PRIV_ESC = "sudo"  # or "doas"
# === Constants and Paths ===
WG_DIR = "/usr/local/etc/wireguard/profiles"
SYSTEM_CONF_DIR = "/usr/local/etc/wireguard"
HOME_DIR = os.path.expanduser("~")
IS_MACOS = platform.system() == "Darwin"
# SCRIPT_BASE is a symlink 
SCRIPT_BASE = "/usr/local/etc/wg-gui/scripts"
WG_MULTI_SCRIPT = os.path.join(SCRIPT_BASE, "wg-multi-macos.sh" if IS_MACOS else "wg-multi-freebsd.sh")
ACTIVE_MAP_PATH = os.path.join(SCRIPT_BASE, "active_connections.json")
WG_UTUN_DIR = "/tmp/wg-multi"
WG_UTUN_MAP = os.path.join(WG_UTUN_DIR, "wg-utun.map")

REFRESH_INTERVAL = 5000  # milliseconds
APP_INSTANCE_KEY = "wg_gui_single_instance"
PING_COUNT = "5"
APP_STYLESHEET = """
QLabel.data-label {
    font-family: "Consolas","IBM Plex Mono", "JetBrains Mono", monospace;
}
"""
ROW_HEIGHT = 28  # Tweak as needed

if platform.system() == "Darwin":
    BASH = shutil.which("bash") or "/opt/homebrew/bin/bash"
    if not BASH.endswith("/bash") or "brew" not in BASH:
        BASH = "/opt/homebrew/bin/bash"
    WG_QUICK = "/opt/homebrew/bin/wg-quick"
    SYSTEM_IFACE = "utun"
    # WG_MULTI_SCRIPT assignment is handled above
    os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ["PATH"]
else:
    BASH = "bash"
    WG_QUICK = "/usr/local/bin/wg-quick"
    SYSTEM_IFACE = "wg0"
SYSTEM_CONF = os.path.join(SYSTEM_CONF_DIR, f"{SYSTEM_IFACE}.conf")

# Key Maps (for dynamic label hiding)
IFACE_KEY_MAP = {
    "Addresses":   "addresses",
    "Listen Port": "port",
    "MTU":         "mtu",
    "DNS":         "dns",
    "Public Key":  "pubkey",
    "Private Key": "privkey",
}
PEER_KEY_MAP = {
    "Public Key":          "pubkey",
    "PreShared Key":       "preshared_key",
    "Allowed IPs":         "allowed_ips",
    "Endpoint":            "endpoint",
    "PersistentKeepalive": "persistent_keepalive",
}

active_connections = {}

# === Utilities ===

def is_dark_mode():
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
        if xdg_desktop == "xfce":
            try:
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

def is_already_running():
    socket = QLocalSocket()
    socket.connectToServer(APP_INSTANCE_KEY)
    return socket.waitForConnected(100)

def create_instance_lock():
    server = QLocalServer()
    if not server.listen(APP_INSTANCE_KEY):
        server.removeServer(APP_INSTANCE_KEY)
        server.listen(APP_INSTANCE_KEY)
    return server

def get_utun_for_profile(prof):
    if not os.path.exists(WG_UTUN_MAP):
        return None
    conf_filename = f"{prof}.conf"
    with open(WG_UTUN_MAP, "r") as f:
        for line in f:
            if "|" not in line:
                continue
            iface, conf = line.strip().split("|", 1)
            if os.path.basename(conf) == conf_filename:
                return iface
    return None

def is_low_utun(iface):
    if not iface or not iface.startswith("utun"):
        return False
    try:
        num = int(iface[4:])
        return 0 <= num <= 4
    except Exception:
        return False

def load_active_connections():
    global active_connections
    try:
        if os.path.exists(ACTIVE_MAP_PATH):
            with open(ACTIVE_MAP_PATH, "r") as f:
                active_connections = json.load(f)
    except Exception as e:
        print(f"[DEBUG] Failed to load active connections: {e}")
        active_connections = {}

def save_active_connections():
    try:
        with open(ACTIVE_MAP_PATH, "w") as f:
            json.dump(active_connections, f, indent=2)
    except Exception as e:
        print(f"[DEBUG] Failed to save active connections: {e}")

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

def parse_wg_show(iface_name=SYSTEM_IFACE):
    iface_info, peer_info = {}, {}
    try:
        out = subprocess.check_output(
            [PRIV_ESC, "wg", "show", iface_name],
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
            if not line:
                continue
            if line.lower().startswith('#ping'):
                try:
                    _, v = line.split(None, 1)
                    peer['ping'] = v.strip()
                except ValueError:
                    pass
                continue
            if line.startswith('#'):
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
                elif k.lower() == 'presharedkey':
                    peer['preshared_key'] = v    
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
                elif k.lower() == 'mtu':
                    interface['mtu'] = v    
    return interface, peer

def hide_empty_rows(form_layout, config, defaults):
    for row in range(form_layout.rowCount()):
        lbl_widget = form_layout.itemAt(row, QFormLayout.ItemRole.LabelRole).widget()
        fld_widget = form_layout.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
        label_text = lbl_widget.text().rstrip(":")
        if label_text not in defaults:
            cfg_key = label_text.lower().replace(" ", "_")
            val = config.get(cfg_key)
            if not val:
                lbl_widget.hide()
                fld_widget.hide()
            else:
                lbl_widget.show()
                fld_widget.show()

class LogTextEdit(QTextEdit):
    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

class WireGuardHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        section_format = QTextCharFormat()
        section_format.setForeground(QColor("#87CEFA"))
        section_format.setFontWeight(QFont.Weight.Bold)
        self.rules.append((QRegularExpression(r"^\s*\[.*\]\s*$"), section_format))
        key_format = QTextCharFormat()
        key_format.setForeground(QColor("#90EE90"))
        self.rules.append((QRegularExpression(r"^\s*\w+\s*="), key_format))
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#BBBBBB") if is_dark_mode() else QColor("#888888"))
        comment_format.setFontItalic(True)
        self.rules.append((QRegularExpression(r"#.*$"), comment_format))
    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            match_iter = pattern.globalMatch(text)
            while match_iter.hasNext():
                match = match_iter.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

class ProfileEditorDialog(QDialog):
    def __init__(self, parent=None, title="Edit", text="", prof_name="", pubkey="", editable_name=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(600, 400)
        self.profile_name = QLineEdit(prof_name)
        self.profile_name.setReadOnly(not editable_name)
        pubkey_label = QLabel(f"Public key: {pubkey}")
        pubkey_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        pubkey_label.setStyleSheet("QLabel {{ font-family: monospace; padding: 4px; color: #4caf50; }}")
        self.text_edit = QPlainTextEdit()

        self.text_edit.setPlainText(text)
        font = QFont("Consolas")
        if not font.exactMatch():
            font = QFont("SF Mono")
        if not font.exactMatch():
            font = QFont("Menlo")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.text_edit.setFont(font)

        self.highlighter = WireGuardHighlighter(self.text_edit.document())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Name:"))
        layout.addWidget(self.profile_name)
        layout.addWidget(pubkey_label)
        layout.addWidget(self.text_edit)
        layout.addWidget(buttons)
        self.setLayout(layout)
    def get_profile_name(self):
        return self.profile_name.text().strip()
    def get_text(self):
        return self.text_edit.toPlainText()

# ==== Main GUI ====

from PyQt6.QtCore import QThread, QObject, pyqtSignal

class ToolRunner(QThread):
    def __init__(self, script_path):
        super().__init__()
        class _Signals(QObject):
            output = pyqtSignal(str)
            error = pyqtSignal(str)
            done = pyqtSignal()
        self.script_path = script_path
        self.signals = _Signals()
        self.output = self.signals.output
        self.error = self.signals.error
        self.done = self.signals.done
        self.start_time = None

    def run(self):
        import shlex, subprocess
        try:
            process = subprocess.Popen(
                shlex.split(self.script_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            # Stream stdout
            if process.stdout:
                for line in iter(process.stdout.readline, ''):
                    if line == '':
                        break
                    self.output.emit(line.rstrip())
            # Stream stderr
            if process.stderr:
                for line in iter(process.stderr.readline, ''):
                    if line == '':
                        break
                    self.error.emit(line.rstrip())
            process.wait()
        except Exception as e:
            self.error.emit(f"❌ {e}")
        self.done.emit()

    def start(self):
        self.start_time = time.time()
        super().start()

    # ... All GUI logic goes here

class WGGui(QWidget):
    def tear_down_full_tunnels(self, prof):
        """Tear down any other active full-tunnel before connecting prof."""
        active_profiles = {}
        try:
            if os.path.exists(WG_UTUN_MAP):
                with open(WG_UTUN_MAP, "r") as f:
                    for line in f:
                        if "|" not in line:
                            continue
                        iface, conf = line.strip().split("|", 1)
                        if conf.endswith(".conf"):
                            name = os.path.splitext(os.path.basename(conf))[0]
                            active_profiles[name] = iface
        except Exception:
            pass
        for other_prof, other_iface in active_profiles.items():
            if other_prof == prof:
                continue
            try:
                other_conf = os.path.join(WG_DIR, f"{other_prof}.conf")
                with open(other_conf) as ocf:
                    if "0.0.0.0/0" in ocf.read():
                        self.log.append(f"🛑 Tearing down active full-tunnel: {other_prof}")
                        subprocess.run([PRIV_ESC, WG_MULTI_SCRIPT, "down", f"{other_prof}.conf"])
                        time.sleep(1)
            except Exception as e:
                self.log.append(f"⚠ Error tearing down {other_prof}: {e}")
    def on_active_selected(self, item, prev):
        # Called when an item in the Active tab is selected
        if not item:
            return
        prof = item.data(Qt.ItemDataRole.UserRole)
        # Optionally, select the corresponding item in the Profiles list
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == prof:
                self.list.setCurrentRow(i)
                break

    def on_profile_double_clicked(self, item):
        # Double-click: toggle activation exactly as the green button
        if not item:
            return
        prof = item.data(Qt.ItemDataRole.UserRole)
        # Select the profile
        self.list.setCurrentItem(item)
        # Determine desired state: True=connect, False=disconnect
        should_connect = not bool(self.is_interface_up(prof))
        # Invoke the toggle handler directly
        self.on_toggle_state(should_connect)

    def __init__(self):
        super().__init__()
        if platform.system() == "Darwin":
         try:
             output = subprocess.check_output(
                 ["ifconfig", "-l"],
                 stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL
             ).decode()
             utuns = [u for u in output.strip().split() if u.startswith("utun")]
             for u in utuns:
                 try:
                     subprocess.check_call(
                         [PRIV_ESC, "wg", "show", u],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL
                     )
                 except subprocess.CalledProcessError:
                     print(f"Cleaning up orphaned {u}...", file=sys.stderr)
                     subprocess.run(
                         [PRIV_ESC, "ifconfig", u, "destroy"],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL
                     )
         except Exception as e:
             print(f"Orphan utun cleanup error: {e}", file=sys.stderr)

        # --- Icons and resources ---
        icon_names = ["wireguard_off.png", "wg_connected.png"]
        candidate_dirs = [
            os.path.join(os.path.dirname(__file__), "Icons"),
            os.path.join(os.getcwd(), "Resources", "Icons"),
        ]
        if getattr(sys, 'frozen', False):
            bundle_dir = os.path.dirname(sys.executable)
            candidate_dirs.insert(0, os.path.normpath(os.path.join(bundle_dir, '..', 'Resources', 'Icons')))
        resource_dir = next((d for d in candidate_dirs if all(os.path.exists(os.path.join(d, n)) for n in icon_names)), None)
        if not resource_dir:
            QMessageBox.critical(None, "WireGuardClient Error",
                "Can't find required icon files in:\n\n" +
                "\n".join(candidate_dirs) +
                "\n\nMissing files: " + ", ".join(icon_names)
            )
            sys.exit(2)
        self.resource_dir = resource_dir
        self.icon_disconnected_path = os.path.join(resource_dir, "wireguard_off.png")
        self.icon_connected_path = os.path.join(resource_dir, "wg_connected.png")
        self.setWindowIcon(QIcon(os.path.join(resource_dir, "wireguard_off.png")))
        self.setWindowTitle("WireGuard Client")
        self.resize(900, 700)
        self.setMinimumHeight(600)
        self.quitting = False
        self.active_profile = None

        # --- System Tray ---
        theme_suffix = "dark" if is_dark_mode() else "light"
        tray_menu = QMenu()
        self.act_show = QAction(QIcon(os.path.join(resource_dir, f"eye_{theme_suffix}.svg")), "Show", self)
        self.act_disconnect = QAction(QIcon(os.path.join(resource_dir, f"plug-off_{theme_suffix}.svg")), "Disconnect", self)
        self.act_disconnect_all = QAction(QIcon(os.path.join(resource_dir, f"plug-off_{theme_suffix}.svg")), "Disconnect All", self)
        self.act_disconnect_quit = QAction(QIcon(os.path.join(resource_dir,  f"power_{theme_suffix}.svg")), "Disconnect + Quit", self)
        self.act_quit_only = QAction(QIcon(os.path.join(resource_dir, f"logout_{theme_suffix}.svg")), "Quit", self)

        tray_menu.addAction(self.act_show)
        tray_menu.addAction(self.act_disconnect)
        tray_menu.addAction(self.act_disconnect_all)
        tray_menu.addSeparator()
        tray_menu.addAction(self.act_disconnect_quit)
        tray_menu.addAction(self.act_quit_only)

        self.tray_icon = QSystemTrayIcon(QIcon(self.icon_disconnected_path), self)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

        self.act_show.triggered.connect(self.show_and_raise)
        self.act_disconnect.triggered.connect(self.on_disconnect)
        self.act_disconnect_all.triggered.connect(self.on_disconnect_all)
        self.act_disconnect_quit.triggered.connect(self.quit_and_disconnect)
        self.act_quit_only.triggered.connect(lambda: QApplication.instance().quit())

        # --- Profile List and Buttons ---
        self.list = QListWidget()
        # self.list.setStyleSheet("...")  # StyleSheet removed per instructions
        self.list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        list_font = QFont()
        list_font.setPointSize(11)
        list_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.list.setFont(list_font)
        self.list.setSpacing(-2)
        # self.list.setMinimumWidth(300)
        # self.list.setMaximumWidth(300)
        self.list.currentItemChanged.connect(self.update_detail_panel)
        self.list.setIconSize(QSize(18, 18))
        # Double-click toggles activation state
        self.list.itemDoubleClicked.connect(self.on_profile_double_clicked)

        # --- Interface and Peer Group ---
        label_font = QFont()
        label_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        left_label_font = QFont()
        left_label_font.setBold(True)
        left_label_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

        self.intf_group = QGroupBox("Interface: -")
        intf_title_font = QFont()
        intf_title_font.setBold(True)
        self.intf_group.setFont(intf_title_font)
        self.intf_form_layout = QFormLayout()
        self.intf_form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self.intf_form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.intf_form_layout.setVerticalSpacing(8)
        self.intf_form_layout.setHorizontalSpacing(32)
        self.intf_form_layout.setSpacing(8)
        self.intf_form_layout.setContentsMargins(12, 12, 12, 12)

        # --- Status Dot Row ---
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(ROW_HEIGHT, ROW_HEIGHT)
        self.status_dot.setMinimumSize(ROW_HEIGHT, ROW_HEIGHT)
        self.status_text = QLabel()
        self.status_text.setMinimumHeight(ROW_HEIGHT)
        self.status_text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_text)
        status_row.setMinimumHeight(ROW_HEIGHT)
        status_row.setMaximumHeight(ROW_HEIGHT)

        # --- Data Labels ---
        self.lbl_pubkey = QLabel()
        self.lbl_port = QLabel()
        self.lbl_addresses = QLabel()
        self.lbl_dns = QLabel()
        self.lbl_mtu = QLabel()
        for lbl in (self.status_text, self.lbl_pubkey, self.lbl_port,
                    self.lbl_addresses, self.lbl_dns, self.lbl_mtu):
            lbl.setFont(label_font)
            lbl.setProperty("class", "data-label")
            lbl.setWordWrap(False)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setMinimumHeight(ROW_HEIGHT)

        # --- Add Rows to Interface Form ---
        for name, widget in [
            ("Status:", status_row),
            ("Public Key:", self.lbl_pubkey),
            ("Listen Port:", self.lbl_port),
            ("Addresses:", self.lbl_addresses),
            ("MTU:", self.lbl_mtu),
            ("DNS Servers:", self.lbl_dns),
        ]:
            label = QLabel(name)
            label.setFont(left_label_font)
            label.setMinimumWidth(130)
            label.setMaximumWidth(130)
            label.setMinimumHeight(ROW_HEIGHT)
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.intf_form_layout.addRow(label, widget)

        # --- Activate/Deactivate Toggle Button with custom shadowed label ---
        self.btnToggle = QPushButton()
        self.btnToggle.setText("")  # Clear built-in text

        # Create a QLabel inside the button for shadowed text
        shadow_label = QLabel("<b>Activate</b>", self.btnToggle)
        shadow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Apply drop shadow effect to the label
        effect = QGraphicsDropShadowEffect()
        effect.setBlurRadius(4)
        effect.setOffset(0, 0)
        effect.setColor(QColor(0, 0, 0, 160))
        shadow_label.setGraphicsEffect(effect)

        # Center the label within the button
        btnToggleLayout = QHBoxLayout(self.btnToggle)
        btnToggleLayout.setContentsMargins(0, 0, 0, 0)
        btnToggleLayout.addWidget(shadow_label)

        # Make the button checkable and wire up toggle state
        self.btnToggle.setCheckable(True)
        self.btnToggle.setChecked(False)
        self.btnToggle.toggled.connect(self.on_toggle_state)

        # Restore original color styles on the button
        self.btnToggle.setStyleSheet("""
		QPushButton {
		    /* use the widget’s own palette for a native grey look */
		    background-color: palette(button);
		    color: palette(button-text);
		    border: 1px solid transparent;  /* preserves the shape */
		    border-radius: 11px;
		    padding: 2px 12px 3px 12px;
		    min-width: 70px;
		    max-width: 150px;
		    min-height: 16px;
		    max-height: 16px;
		}
		QPushButton:hover {
		    background-color: palette(light);
		}
		QPushButton:checked {
		    background: qlineargradient(
		        x1:0, y1:0, x2:0, y2:1,
		        /* 200/255 ≈ 78% opacity */
		        stop:0 rgba(49,217,0,200),
		        stop:1 rgba(1,150,1,200)
		    );
		    color:  #fff;
		    border: 1px solid #218c4a;
		}
		        """)

        # Reapply drop shadow to the button widget
        button_shadow = QGraphicsDropShadowEffect()
        button_shadow.setBlurRadius(8)
        button_shadow.setOffset(1, 2)
        button_shadow.setColor(QColor(0, 0, 0, 160))
        self.btnToggle.setGraphicsEffect(button_shadow)

        # Keep a reference for updating text later
        self.btnToggleLabel = shadow_label

        # Add the button to its parent layout
        toggle_btn_layout = QHBoxLayout()
        toggle_btn_layout.setContentsMargins(170, 0, 0, 0)
        toggle_btn_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        toggle_btn_layout.addWidget(self.btnToggle)

        intf_layout = QVBoxLayout()
        intf_layout.addLayout(self.intf_form_layout)
        intf_layout.addLayout(toggle_btn_layout)
        self.intf_group.setLayout(intf_layout)
        self.intf_group.setMinimumHeight(220)
        # --- Peer Group ---
        self.peer_group = QGroupBox("Peer:")
        peer_title_font = QFont()
        peer_title_font.setBold(True)
        self.peer_group.setFont(peer_title_font)
        self.peer_form_layout = QFormLayout()
        self.peer_form_layout.setHorizontalSpacing(32)
        self.peer_form_layout.setVerticalSpacing(8)
        intf_layout.setContentsMargins(12, 12, 12, 12)

        self.peer_form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.peer_form_layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self.peer_form_layout.setSpacing(0)
        self.lbl_peer_key = QLabel()
        self.lbl_allowed_ips = QLabel()
        self.lbl_endpoint = QLabel()
        self.lbl_handshake = QLabel()
        self.lbl_transfer = QLabel()
        self.lbl_preshared = QLabel()
        for lbl in (self.lbl_peer_key, self.lbl_allowed_ips, self.lbl_endpoint,
                    self.lbl_handshake, self.lbl_transfer, self.lbl_preshared):
            lbl.setFont(label_font)
            lbl.setProperty("class", "data-label")
            lbl.setWordWrap(False)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setMinimumHeight(18)
        for name, widget in [
            ("Public Key:", self.lbl_peer_key),
            ("PreShared Key:", self.lbl_preshared),
            ("Allowed IPs:", self.lbl_allowed_ips),
            ("Endpoint:", self.lbl_endpoint),
            ("Last Handshake:", self.lbl_handshake),
            ("Transfer:", self.lbl_transfer),
        ]:
            label = QLabel(name)
            label.setFont(left_label_font)
            label.setMinimumWidth(130)
            label.setMaximumWidth(130)
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            widget.setContentsMargins(20, 0, 0, 0)
            self.peer_form_layout.addRow(label, widget)
        self.peer_group.setLayout(self.peer_form_layout)
        self.peer_group.layout().setContentsMargins(26, 26, 26, 26)

        # --- Action Buttons (Single Helper Setup) ---
        def setup_btn(icon, tooltip, cb, width=30, use_custom_icon=False):
            btn = QPushButton()
            if use_custom_icon:
                btn.setIcon(QIcon(icon))
            else:
                btn.setIcon(self.style().standardIcon(icon))
            btn.setToolTip(tooltip)
            btn.setFixedWidth(width)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(cb)
            return btn

        self.btnEdit = setup_btn(QStyle.StandardPixmap.SP_FileDialogContentsView, "Edit Profile", self.edit_selected_profile)
        btnAdd = setup_btn(QStyle.StandardPixmap.SP_FileDialogNewFolder, "Add Profile", self.add_profile)
        btnDelete = setup_btn(QStyle.StandardPixmap.SP_TrashIcon, "Delete Profile", self.delete_profile)
        btnUpload = setup_btn(QStyle.StandardPixmap.SP_ArrowUp, "Upload Profile", self.upload_profile)
        btnDownload = setup_btn(QStyle.StandardPixmap.SP_DialogSaveButton, "Download All Profiles", self.download_profiles)        
        self.btnConnect = setup_btn(QStyle.StandardPixmap.SP_MediaPlay, "Connect", self.on_connect)
        self.btnDisconnect = setup_btn(QStyle.StandardPixmap.SP_MediaStop, "Disconnect", self.on_disconnect)
        red_x_icon_path = os.path.join(self.resource_dir, f"logout_{theme_suffix}.svg")        
        self.btnQuit = setup_btn(red_x_icon_path, "Quit", lambda: QApplication.instance().quit(), use_custom_icon=True)


        # --- Left Panel Layout ---
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        left.setMinimumWidth(300)
        left.setMaximumWidth(300)
        left_layout = QVBoxLayout(left)

        self.list_tab = QTabWidget()
        self.list_tab.setTabPosition(QTabWidget.TabPosition.North)
        self.list_tab.setDocumentMode(True)
        self.list_tab.addTab(self.list, "Profiles")
        # --- Optional Tools Tab ---
        if ENABLE_TOOLS_TAB:
            tools_tab = QWidget()
            tools_layout = QVBoxLayout()
            tools_layout.setContentsMargins(0, 0, 0, 0)
            tools_layout.setSpacing(4)
            tools_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            self.tools_output = QPlainTextEdit()
            self.tools_output.setReadOnly(True)
            self.tools_output.setPlaceholderText("Script output will appear here...")
            self.tools_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.tools_output.setContentsMargins(0, 0, 0, 0)
            self.tools_output.setStyleSheet("""
                QPlainTextEdit {
                    background-color: #121212;
                    color: #FFFFFF;
                    border: 1px solid #333;
                    border-radius: 2px;
                    padding: 6px;
                }
            """)
            font = QFont("Consolas, SF Mono, Menlo, monospace", 10)
            font.setStyleHint(QFont.StyleHint.Monospace)
            self.tools_output.setFont(font)
            self.tools_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            from PyQt6.QtGui import QTextOption
            self.tools_output.setWordWrapMode(QTextOption.WrapMode.NoWrap)
            tools_path = os.path.join(os.path.dirname(__file__), "tools")
            if os.path.isdir(tools_path):
                script_paths = sorted(glob.glob(os.path.join(tools_path, "*.sh")) + glob.glob(os.path.join(tools_path, "*.py")))
                if not script_paths:
                    label = QLabel("No .sh or .py scripts found in tools/ directory.")
                    tools_layout.addWidget(label)
                else:
                    # --- Place grid inside a group box for border/box effect
                    btn_box = QGroupBox("")
                    btn_box.setStyleSheet("""
                        QGroupBox {
                            border: 1px solid #555;
                            border-radius: 6px;
                            margin-top: 2px;
                            background: #1a1a1a;
                        }
                    """)
                    btn_grid = QGridLayout()
                    btn_grid.setHorizontalSpacing(2)
                    btn_grid.setVerticalSpacing(2)
                    btn_grid.setContentsMargins(4, 4, 4, 4)
                    col_count = 2  # two columns
                    for i, script_path in enumerate(script_paths):
                        script_name = os.path.basename(script_path)
                        btn = QPushButton(f"{script_name}")
                        btn.setStyleSheet("""
                            QPushButton {
                                background-color: #232323;
                                color: #eee;
                                border: 1px solid #444;
                                border-radius: 3px;
                                padding: 1px 6px 1px 6px;
                                font-weight: normal;
                                font-size: 10px;
                                min-width: 70px;
                                min-height: 18px;
                            }
                            QPushButton:hover {
                                background-color: #333;
                            }
                            QPushButton:pressed {
                                background-color: #151515;
                            }
                        """)
                        btn.clicked.connect(lambda _, s=script_path: self.run_tool_script(s))
                        row = i // col_count
                        col = i % col_count
                        btn_grid.addWidget(btn, row, col)
                    btn_box.setLayout(btn_grid)
                    tools_layout.addWidget(btn_box)
            else:
                label = QLabel("tools/ directory not found. Create it to add custom scripts.")
                tools_layout.addWidget(label)
            tools_layout.addWidget(self.tools_output)
            tools_tab.setLayout(tools_layout)
            tools_tab.setContentsMargins(0, 0, 0, 0)
            self.list_tab.addTab(tools_tab, "Tools")
            # --- Active Connections Tab ---
            active_tab = QWidget()
            active_layout = QVBoxLayout(active_tab)
            self.active_tab_list = QListWidget()
            self.active_tab_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            active_layout.setContentsMargins(0, 0, 0, 0)
            active_layout.setSpacing(0)
            self.active_tab_list.setStyleSheet("""
                QListWidget {
                    border: 1px solid #444;
                    border-radius: 1px;
                    padding: 8px;
                }
                QListWidget::item {
                    margin-bottom: 4px;
                }
            """)
            self.active_tab_list.setContentsMargins(8, 8, 8, 8)
            # connect signals
            self.active_tab_list.currentItemChanged.connect(self.on_active_selected)
            self.active_tab_list.itemDoubleClicked.connect(self.on_profile_double_clicked)
            active_layout.addWidget(self.active_tab_list)
            self.list_tab.addTab(active_tab, "Active")
        self.list.setStyleSheet("""
        QListWidget {
            border: 1px solid #444;
            border-radius: 1px;
            padding: 8px;
        }
        QListWidget::item {
            margin-bottom: 4px;
        }
        """)

        left_layout.addWidget(self.list_tab, stretch=1)

        # --- Unified Button Bar in QGroupBox (native, no title, no stylesheet) ---
        button_bar_group = QGroupBox("")
        # No styleSheet is set on button_bar_group; native, unstyled group box.
        button_bar_layout = QHBoxLayout(button_bar_group)
        button_bar_layout.setContentsMargins(8, 4, 8, 4)
        button_bar_layout.setSpacing(8)
        button_bar_layout.addWidget(self.btnEdit)
        button_bar_layout.addWidget(btnAdd)
        button_bar_layout.addWidget(btnDelete)
        button_bar_layout.addWidget(btnUpload)
        button_bar_layout.addWidget(btnDownload)
        button_bar_layout.addStretch(1)
        button_bar_layout.addWidget(self.btnConnect)
        button_bar_layout.addWidget(self.btnDisconnect)
        button_bar_layout.addWidget(self.btnQuit)

        left_layout.addWidget(button_bar_group)

        self.list.setContentsMargins(8, 8, 8, 8)      # <--- Padding inside list
        left_layout.setContentsMargins(0, 0, 4, 0)    # <--- Padding around left panel
        left_layout.setSpacing(8)

        # --- Right Panel Layout ---
        right = QWidget()
        right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right.setMinimumWidth(550)
        # right.setMaximumWidth(900)  # <-- REMOVED maximum width restriction
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(4)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.intf_group, 1)
        right_layout.addWidget(self.peer_group, 1)

        # Set minimum width for group boxes:
        self.intf_group.setMinimumWidth(500)
        self.peer_group.setMinimumWidth(500)
        # --- Match Groupbox Widths ---
        def match_groupbox_widths():
            all_forms = [self.intf_form_layout, self.peer_form_layout]
            label_widgets = [form.itemAt(i, QFormLayout.ItemRole.LabelRole).widget()
                             for form in all_forms for i in range(form.rowCount()) if form.itemAt(i, QFormLayout.ItemRole.LabelRole)]
            label_w = max((label.sizeHint().width() for label in label_widgets if label), default=110)
            label_w = max(label_w, 130)  # Never shrink below 130
            for label in label_widgets:
                if label:
                    label.setMinimumWidth(label_w)
                    label.setMaximumWidth(label_w)
                    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            widest = max(self.intf_group.sizeHint().width(), self.peer_group.sizeHint().width(), 500)
            self.intf_group.setMinimumWidth(widest)
            self.peer_group.setMinimumWidth(widest)
        match_groupbox_widths()
        # --- Splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 600])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; width: 10px; }")

        splitter.setMinimumHeight(500)  # Try 400, 500, 600; adjust until it matches your desired min
        splitter.setMaximumHeight(500)
        self.intf_group.setMinimumHeight(200)  # Adjust if needed
        self.peer_group.setMinimumHeight(200)  # Adjust if needed


        # --- Logs and Multi List Tabs ---
        self.log = LogTextEdit(readOnly=True)
        mono = QFont("Consolas")
        if not mono.exactMatch():
            mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.log.setFont(mono)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(18)
        main_layout.addWidget(splitter)
        tabs = QTabWidget()
        tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        logs_tab = QWidget()
        logs_layout = QVBoxLayout(logs_tab)
        logs_layout.setContentsMargins(8, 8, 8, 8)
        logs_layout.addWidget(self.log)
        tabs.addTab(logs_tab, "Logs")
        list_tab = QWidget()
        list_layout = QVBoxLayout(list_tab)
        list_layout.setContentsMargins(8, 8, 8, 8)
        self.multi_list = QTextEdit(readOnly=True)
        self.multi_list.setFont(mono)
        list_layout.addWidget(self.multi_list)
        tabs.addTab(list_tab, "WG-Multi List")
        main_layout.addWidget(tabs)
        # --- Process and Timer ---
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)
        self.process.finished.connect(self.run_next)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(REFRESH_INTERVAL)
        self.commands = []
        self.cmd_index = 0
        self.load_profiles()
        QTimer.singleShot(100, self.refresh_status)
        self.update_multi_list()
        # --- Update Active Connections Tab ---
        if hasattr(self, 'active_tab_list'):
            self.active_tab_list.clear()
            for i in range(self.list.count()):
                prof = self.list.item(i).data(Qt.ItemDataRole.UserRole)
                iface = get_utun_for_profile(prof)
                if iface:
                    display_text = f"{iface}: {prof}"
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.ItemDataRole.UserRole, prof)
                    self.active_tab_list.addItem(item)
        self.log.viewport().installEventFilter(self)
    # --- Tray, Window, and Utility Methods ---
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
        self.on_disconnect_all()
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
        any_active = any(self.is_interface_up(self.list.item(i).data(Qt.ItemDataRole.UserRole))
                         for i in range(self.list.count()))
        icon_path = self.icon_connected_path if any_active else self.icon_disconnected_path
        self.tray_icon.setIcon(QIcon(icon_path))
    def is_interface_up(self, prof=None):
        prof = prof or self.active_profile
        if not prof:
            return False
        iface = get_utun_for_profile(prof)
        return iface if iface else False
    # --- Profile Management and Status ---
    def load_profiles(self):
        self.list.clear()
        for conf in sorted(os.listdir(WG_DIR)):
            if conf.endswith('.conf'):
                profile = conf[:-5]
                item = QListWidgetItem(profile)
                item.setData(Qt.ItemDataRole.UserRole, profile)
                font = QFont()
                font.setBold(False)
                font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
                item.setFont(font)
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self.list.addItem(item)
    def refresh_status(self):
        for i in range(self.list.count()):
            itm = self.list.item(i)
            prof = itm.data(Qt.ItemDataRole.UserRole)
            utun_iface = self.is_interface_up(prof)
            if utun_iface and is_low_utun(utun_iface):
                self.log.append(f"⚠ WARNING: Profile '{prof}' is using a low-number utun interface ({utun_iface}).\n")
            font = QFont()
            font.setBold(bool(utun_iface))
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            size = 10
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            color = QColor('#60FF60') if utun_iface else QColor('#888888')
            painter.setBrush(color)
            painter.drawEllipse(1, 1, size - 2, size - 2)
            painter.end()
            itm.setIcon(QIcon(pixmap))
            itm.setFont(font)
            itm.setText(prof)
        # --- Update Active Connections Tab ---
        if hasattr(self, 'active_tab_list'):
            self.active_tab_list.clear()
            for i in range(self.list.count()):
                prof = self.list.item(i).data(Qt.ItemDataRole.UserRole)
                iface = get_utun_for_profile(prof)
                if not iface:
                    continue
                display_text = f"{iface}: {prof}"
                item = QListWidgetItem(display_text)
                size = 10
                pixmap = QPixmap(size, size)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor('#60FF60'))
                painter.drawEllipse(1, 1, size-2, size-2)
                painter.end()
                item.setIcon(QIcon(pixmap))
                item.setData(Qt.ItemDataRole.UserRole, prof)
                self.active_tab_list.addItem(item)
        current = self.list.currentItem()
        self.interface_up = bool(self.is_interface_up(current.data(Qt.ItemDataRole.UserRole)) if current else False)
        self.update_detail_panel()
        self.update_tray_icon()
        any_active = any(self.is_interface_up(self.list.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.list.count()))
        self.btnDisconnect.setEnabled(any_active)
        self.btnDisconnect.setDefault(any_active)
        self.btnDisconnect.setAutoDefault(any_active)
        self.update_multi_list()
    def update_multi_list(self):
        # Asynchronously fetch the wg-multi list so the UI doesn’t block
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.finished.connect(lambda code, status: self.handle_multi_list_finished(proc))
        proc.start(PRIV_ESC, [WG_MULTI_SCRIPT, "list"])

    def handle_multi_list_finished(self, proc: QProcess):
        """Called when ‘wg-multi list’ completes—refresh the text view."""
        try:
            raw = proc.readAllStandardOutput().data().decode()
        except Exception as e:
            self.append_log(f"⚠ Error reading WG-Multi output: {e}\n")
            return

        # Display raw output in the text widget
        self.multi_list.clear()
        self.multi_list.setPlainText(raw)
    def update_detail_panel(self):
        item = self.list.currentItem()
        show_profile = item.data(Qt.ItemDataRole.UserRole) if item else None
        utun_iface = self.is_interface_up(show_profile)
        show_iface = utun_iface or "-"
        self.intf_group.setTitle(f"Interface: {show_iface} / Profile: {show_profile or '-'}")
        self.btnDisconnect.setEnabled(bool(utun_iface))
        #self.btnToggle.setChecked(bool(utun_iface))
        #self.btnToggleLabel.setText("Deactivate" if utun_iface else "Activate")
        # block the toggled signal so we don't accidentally call on_disconnect()
        self.btnToggle.blockSignals(True)
        self.btnToggle.setChecked(bool(utun_iface))
        self.btnToggle.blockSignals(False)
        self.btnToggleLabel.setText("Deactivate" if utun_iface else "Activate")
        
        if utun_iface and is_low_utun(utun_iface):
            self.log.append(f"⚠ WARNING: Selected profile is using {utun_iface} (reserved for macOS system use).")
        self.status_dot.clear()
        self.status_text.clear()
        self.lbl_pubkey.setText("-")
        self.lbl_port.setText("-")
        self.lbl_addresses.setText("-")
        self.lbl_dns.setText("-")
        self.lbl_peer_key.setText("-")
        self.lbl_allowed_ips.setText("-")
        self.lbl_endpoint.setText("-")
        self.lbl_handshake.setText("-")
        self.lbl_transfer.setText("-")
        self.lbl_mtu.setText("-")
        self.lbl_preshared.setText("-")
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
            self.lbl_mtu.setText(iface_conf.get('mtu', "-"))
            self.lbl_preshared.setText(peer_conf.get('preshared_key', "-"))
            conf_port = iface_conf.get('port', "-")
            self.lbl_port.setText(conf_port)
            hide_empty_rows(self.intf_form_layout, iface_conf, {"Status", "Public Key", "Listen Port", "Addresses", "DNS Servers"})
            hide_empty_rows(self.peer_form_layout, peer_conf, {"Public Key", "Allowed IPs", "Endpoint", "Last Handshake", "Transfer"})
        # --- Interface Status Dot: Aqua-Style ---
        DOT_SIZE = 12
        DOT_GREEN = "#019601"
        DOT_RED = "#B80404"
        DOT_GRAY = '#AAAAAA'
        pix = QPixmap(DOT_SIZE, DOT_SIZE)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Choose main color
        if utun_iface:
            base = QColor(DOT_GREEN)
        elif self.active_profile:
            base = QColor(DOT_RED)
        else:
            base = QColor(DOT_GRAY)

        # Aqua: draw a radial gradient for glassy effect
        grad = QRadialGradient(DOT_SIZE/2, DOT_SIZE/2, DOT_SIZE/2, DOT_SIZE/3, DOT_SIZE/3)
        grad.setColorAt(0.0, QColor(255, 255, 255, 190))    # inner highlight
        grad.setColorAt(0.6, base.lighter(110))
        grad.setColorAt(1.0, base.darker(130))
        p.setBrush(grad)
        p.setPen(Qt.GlobalColor.transparent)
        p.drawEllipse(0, 0, DOT_SIZE, DOT_SIZE)

        # Draw a subtle white reflection spot
        p.setBrush(QColor(255,255,255,120))
        p.setPen(Qt.GlobalColor.transparent)
        spot = QRectF(DOT_SIZE*0.18, DOT_SIZE*0.16, DOT_SIZE*0.48, DOT_SIZE*0.28)
        p.drawEllipse(spot)
        p.end()

        self.status_dot.setPixmap(pix)
        self.status_dot.setFixedSize(DOT_SIZE, DOT_SIZE)
        self.status_dot.setMinimumSize(DOT_SIZE, DOT_SIZE)
        self.status_text.setText("Up" if utun_iface else ("Down" if self.active_profile else ""))
        self.status_text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status_text.setMinimumHeight(ROW_HEIGHT)
        self.status_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        if utun_iface:
            try:
                out = subprocess.check_output([PRIV_ESC, 'wg', 'show', utun_iface]).decode()
                iface, peer = {}, {}
                for line in out.splitlines():
                    line = line.strip()
                    if line.lower().startswith("interface:"):
                        iface['name'] = line.split(":", 1)[1].strip()
                    elif line.startswith("public key:"):
                        iface['pubkey'] = line.split(":", 1)[1].strip()
                    elif line.startswith("listening port:"):
                        iface['port'] = line.split(":", 1)[1].strip()
                    elif line.startswith("peer:"):
                        peer['pubkey'] = line.split(":", 1)[1].strip()
                    elif line.startswith("endpoint:"):
                        peer['endpoint'] = line.split(":", 1)[1].strip()
                    elif line.startswith("allowed ips:"):
                        peer['allowed_ips'] = line.split(":", 1)[1].strip()
                    elif line.startswith("latest handshake:"):
                        peer['handshake'] = line.split(":", 1)[1].strip()
                    elif line.startswith("transfer:"):
                        peer['transfer'] = line.split(":", 1)[1].strip()
                self.lbl_pubkey.setText(iface.get('pubkey', "-"))
                self.lbl_port.setText(iface.get('port', conf_port) or "-")
                self.lbl_handshake.setText(peer.get('handshake', "-"))
                self.lbl_transfer.setText(peer.get('transfer', "-"))
            except Exception:
                pass
        self.interface_up = bool(utun_iface)
        self.update_tray_icon()
    # --- Connect, Disconnect, and Toggle Logic ---
    def on_connect(self):
        itm = self.list.currentItem()
        if not itm:
            self.log.append("⚠ Select a profile first.\n")
            return
        prof = itm.data(Qt.ItemDataRole.UserRole)
        iface_up = self.is_interface_up(prof)
        if iface_up:
            if is_low_utun(iface_up):
                self.log.append(
                    f"[!] Refusing to use reserved utun device {iface_up} "
                    f"for '{prof}'. Try cleaning up or rebooting."
                )
                return
            self.log.append(f"⚠ Profile '{prof}' already active (utun: {iface_up}).\n")
            return

        conf_path = os.path.join(WG_DIR, f"{prof}.conf")
        with open(conf_path) as f:
            is_full = "0.0.0.0/0" in f.read()
        if is_full:
            self.tear_down_full_tunnels(prof)

        self.active_profile = prof
        self.pending_connect_profile = prof

        # Log exactly what file is being passed
        self.log.append(f"▶ Bringing up profile: {prof}.conf")
        # Start the QProcess
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)
        self.process.finished.connect(self.on_connect_finished)
        self.process.start(PRIV_ESC, [WG_MULTI_SCRIPT, 'up', f"{prof}.conf"])

    def on_connect_finished(self):
        prof = getattr(self, "pending_connect_profile", None)
        if self.process.exitCode() != 0:
            self.append_log(f"[!] Failed to bring up interface for profile: {prof}\nReturn code: {self.process.exitCode()}\n")
            self.active_profile = None
        else:
            conf_path = os.path.join(WG_DIR, f"{prof}.conf")
            iface_conf, peer_conf = parse_wg_conf(conf_path)
            QTimer.singleShot(2000, lambda: self.after_connect_tasks(prof, iface_conf, peer_conf))
            self.btnToggle.setChecked(True)
            self.btnToggleLabel.setText("Deactivate")
        self.refresh_status()

    def after_connect_tasks(self, prof, iface_conf, peer_conf):
        # Perform post-connection ping(s) if requested by the config
        ping_targets = []
        if 'ping' in peer_conf:
            ping_targets.append(peer_conf['ping'])
        if 'addresses' in iface_conf:
            ping_targets.extend(addr.split('/')[0] for addr in iface_conf['addresses'])
        for ip in ping_targets:
            self.log.append(f"🔍 Pinging {ip} (background)...")
            QTimer.singleShot(100, lambda ip=ip: self.run_ping(ip))
        self.btnToggle.setChecked(True)
        self.btnToggleLabel.setText("Deactivate")
        self.refresh_status()

    def run_ping(self, ip):
        try:
            proc = QProcess(self)
            proc.readyReadStandardOutput.connect(
                lambda: self.append_log(proc.readAllStandardOutput().data().decode().rstrip("\n")))
            proc.readyReadStandardError.connect(
                lambda: self.append_log(proc.readAllStandardError().data().decode().rstrip("\n")))
            proc.start("ping", ["-c", "3", ip])
        except Exception as e:
            self.log.append(f"⚠ Exception while running ping for {ip}: {e}")

    def on_disconnect(self):
        # Try to disconnect the currently selected or active profile
        itm = self.list.currentItem()
        prof = itm.data(Qt.ItemDataRole.UserRole) if itm else self.active_profile
        if not prof:
            self.append_log("⚠ Select a profile to disconnect.\n")
            return
        if not os.path.exists(WG_MULTI_SCRIPT):
            self.append_log(f"[!] WireGuard multi-script not found at {WG_MULTI_SCRIPT}")
            return

        self.active_profile = prof
        # Log exactly what file is being passed
        self.log.append(f"▶ Bringing down profile: {prof}.conf")

        # If a process is already running, terminate it first (safety)
        if hasattr(self, "process") and self.process is not None:
            try:
                self.process.kill()
                self.process.deleteLater()
            except Exception:
                pass

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)

        def finished_cb():
            self.update_toggle_button()
            self.tray_icon.setIcon(QIcon(self.icon_disconnected_path))
            self.btnToggleLabel.setText("Activate")
            self.btnToggle.setChecked(False)
            self.refresh_status()

        self.process.finished.connect(finished_cb)
        self.process.start(PRIV_ESC, [WG_MULTI_SCRIPT, "down", f"{prof}.conf"])

    def on_disconnect_all(self):
        # Disconnect all WireGuard profiles (best effort), blocking until each is down
        for conf_path in glob.glob(os.path.join(WG_DIR, '*.conf')):
            prof = os.path.splitext(os.path.basename(conf_path))[0]
            try:
                self.append_log(f"🛑 Disconnecting {prof}...\n")
                subprocess.run([PRIV_ESC, WG_MULTI_SCRIPT, 'down', f"{prof}.conf"], check=False)
            except Exception as e:
                self.append_log(f"⚠ Error disconnecting {prof}: {e}\n")


    
    def on_toggle_state(self, checked):
        if checked:
            self.on_connect()
        else:
            self.on_disconnect()
    def update_toggle_button(self):
        item = self.list.currentItem()
        prof = item.data(Qt.ItemDataRole.UserRole) if item else None
        
        #utun_iface = self.is_interface_up(prof)
        #self.btnToggle.setChecked(bool(utun_iface))
        #self.btnToggleLabel.setText("Deactivate" if utun_iface else "Activate")
        
        # block the toggled signal so we don't accidentally call on_disconnect()
        utun_iface = self.is_interface_up(prof)
        # again, suppress toggled() while syncing UI
        self.btnToggle.blockSignals(True)
        self.btnToggle.setChecked(bool(utun_iface))
        self.btnToggle.blockSignals(False)
        self.btnToggleLabel.setText("Deactivate" if utun_iface else "Activate")

        
    # --- Log Output and Event Filter ---
    def append_log(self, text):
        scrollbar = self.log.verticalScrollBar()
        at_bottom = scrollbar.value() == scrollbar.maximum()
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log.setTextCursor(cursor)
        self.log.insertPlainText(text if text.endswith("\n") else text + "\n")
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())
    def eventFilter(self, obj, event):
        if obj is self.log and event.type() == QEvent.Type.MouseButtonDblClick:
            sb = self.log.verticalScrollBar()
            sb.setValue(sb.maximum())
            return True
        return super().eventFilter(obj, event)
    def on_stdout(self):
        out = self.process.readAllStandardOutput().data().decode()
        scrollbar = self.log.verticalScrollBar()
        at_bottom = scrollbar.value() == scrollbar.maximum()
        self.log.insertPlainText(out)
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())
    def on_stderr(self):
        err = self.process.readAllStandardError().data().decode()
        scrollbar = self.log.verticalScrollBar()
        at_bottom = scrollbar.value() == scrollbar.maximum()
        self.log.insertPlainText(err)
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())
    # --- Profile Editor Dialogs (Unified) ---
    def edit_selected_profile(self):
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
        privkey = ""
        in_interface = False
        for line in content.splitlines():
            lstripped = line.strip()
            if lstripped.lower().startswith("[interface]"):
                in_interface = True
                continue
            if lstripped.startswith("[") and not lstripped.lower().startswith("[interface]"):
                in_interface = False
            if in_interface and lstripped.lower().startswith("privatekey"):
                _, privkey = lstripped.split("=", 1)
                privkey = privkey.strip()
                break
        pubkey = "(invalid)"
        if privkey:
            try:
                pubkey = subprocess.run(["wg", "pubkey"], input=privkey.encode(), stdout=subprocess.PIPE).stdout.decode().strip()
            except Exception:
                pass
        dlg = ProfileEditorDialog(self, title=f"Edit Profile: {prof}", text=content, prof_name=prof, pubkey=pubkey, editable_name=False)
        if dlg.exec():
            try:
                new_text = dlg.get_text()
                with tempfile.NamedTemporaryFile("w", delete=False) as tmpf:
                    tmpf.write(new_text)
                    tmp_path = tmpf.name
                subprocess.run([PRIV_ESC, "cp", tmp_path, conf_path])
                os.remove(tmp_path)
                self.log.append(f"✅ Saved changes to {prof}.conf\n")
            except Exception as e:
                self.log.append(f"⚠ Failed to save profile: {e}\n")
    def add_profile(self):
        try:
            privkey = subprocess.check_output(["wg", "genkey"]).decode().strip()
            pubkey = subprocess.run(["wg", "pubkey"], input=privkey.encode(), stdout=subprocess.PIPE).stdout.decode().strip()
        except Exception as e:
            QMessageBox.warning(self, "Key Generation Failed", f"Failed to generate keys:\n{e}")
            return

        template = f"""[Interface]
Address = 
PrivateKey = {privkey}
ListenPort = 
DNS = 
"""

        dlg = ProfileEditorDialog(self, title="New WireGuard Profile", text=template, prof_name="", pubkey=pubkey, editable_name=True)
        if dlg.exec():
            prof = dlg.get_profile_name()
            if not prof:
                QMessageBox.warning(self, "Invalid Name", "Profile name cannot be empty.")
                return

            conf_path = os.path.join(WG_DIR, f"{prof}.conf")
            if os.path.exists(conf_path):
                QMessageBox.warning(self, "Error", f"Profile '{prof}' already exists.")
                return

            try:
                # Write to temporary file first
                with tempfile.NamedTemporaryFile("w", delete=False) as tmpf:
                    tmpf.write(dlg.get_text())
                    tmp_path = tmpf.name

                # Move it with doas/sudo
                subprocess.run([PRIV_ESC, "mv", tmp_path, conf_path], check=True)
                self.log.append(f"✅ Created profile: {prof}.conf\n")
                self.load_profiles()
            except Exception as e:
                self.log.append(f"⚠ Failed to create profile: {e}\n")
    def delete_profile(self):
        item = self.list.currentItem()
        if not item:
            self.log.append("⚠ No profile selected to delete.\n")
            return

        prof = item.data(Qt.ItemDataRole.UserRole)
        conf_path = os.path.join(WG_DIR, f"{prof}.conf")

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete profile '{prof}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                subprocess.run([PRIV_ESC, "rm", "-f", conf_path], check=True)
                self.log.append(f"🗑️ Deleted profile: {prof}\n")
                self.load_profiles()
            except Exception as e:
                self.log.append(f"⚠ Failed to delete profile {prof}: {e}\n")
    def upload_profile(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Upload Profile", "", "WireGuard Config (*.conf)")
        if file_path:
            dst_path = os.path.join(WG_DIR, os.path.basename(file_path))
            try:
                shutil.copy(file_path, dst_path)
                self.log.append(f"📤 Uploaded profile to {dst_path}\n")
                self.load_profiles()
            except Exception as e:
                self.log.append(f"⚠ Failed to upload: {e}\n")
    def download_profiles(self):
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
    # --- Command Chaining for Advanced Use ---
    def run_next(self):
        if self.cmd_index >= len(self.commands):
            return
        cmd = self.commands[self.cmd_index]
        self.append_log(f"> {' '.join(cmd)}")
        if hasattr(self, "process") and self.process is not None:
            self.process.readyReadStandardOutput.disconnect()
            self.process.readyReadStandardError.disconnect()
            self.process.finished.disconnect()
            self.process.kill()
            self.process.deleteLater()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.on_stdout)
        self.process.readyReadStandardError.connect(self.on_stderr)
        self.process.finished.connect(self.run_next_finished)
        self.process.start(cmd[0], cmd[1:])
    def run_next_finished(self):
        self.cmd_index += 1
        self.run_next()


    # --- Run Tool Script for Tools Tab ---
    def run_tool_script(self, script_path):
        self.append_tool_output(f"▶ Running {os.path.basename(script_path)}...\n")

        self.tool_runner = ToolRunner(script_path)
        self.tool_runner.output.connect(self.append_tool_output)
        self.tool_runner.error.connect(self.append_tool_output)
        self.tool_runner.done.connect(self.on_tool_done)
        self.tool_runner.start()

    def on_tool_done(self):
        self.append_tool_output("✅ Done.\n")

    def append_tool_output(self, text):
        if hasattr(self, 'tools_output') and self.tools_output:
            self.tools_output.appendPlainText(text)
            scrollbar = self.tools_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    # --- Remove old Profiles double-click handler ---
    # def on_profiles_double_clicked(self, item):
    #     ...

if __name__ == "__main__":
    if is_already_running():
        print("🚫 WireGuard Client is already running.")
        sys.exit(0)
    instance_lock = create_instance_lock()
    load_active_connections()
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    gui = WGGui()
    gui.show()
    sys.exit(app.exec())		

    def tear_down_full_tunnels(self, prof):
        """Tear down any other active full-tunnel before connecting prof."""
        # Load active profiles from WG_UTUN_MAP
        active_profiles = {}
        try:
            if os.path.exists(WG_UTUN_MAP):
                with open(WG_UTUN_MAP, "r") as f:
                    for line in f:
                        if "|" not in line:
                            continue
                        iface, conf = line.strip().split("|", 1)
                        if conf.endswith(".conf"):
                            name = os.path.splitext(os.path.basename(conf))[0]
                            active_profiles[name] = iface
        except Exception:
            pass
        # For each other full-tunnel, bring it down
        for other_prof, other_iface in active_profiles.items():
            if other_prof == prof:
                continue
            other_conf = os.path.join(WG_DIR, f"{other_prof}.conf")
            try:
                with open(other_conf) as ocf:
                    if "0.0.0.0/0" in ocf.read():
                        self.log.append(f"🛑 Tearing down active full-tunnel: {other_prof}")
                        subprocess.run([PRIV_ESC, WG_MULTI_SCRIPT, "down", f"{other_prof}.conf"])
                        time.sleep(1)
            except Exception as e:
                self.log.append(f"⚠ Error tearing down {other_prof}: {e}")