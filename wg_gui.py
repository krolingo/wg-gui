#!/usr/bin/env python3
import sys
import os
import subprocess
import time
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QLabel, QFormLayout, QGroupBox, QSplitter, QSizePolicy,
    QMessageBox, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import QProcess, Qt, QTimer
from PyQt6.QtGui import QFont, QIcon, QAction, QTextCursor, QPixmap, QPainter, QColor

# Configuration
WG_DIR = os.path.expanduser("~/scripts/wireguard_client/profiles")
SYSTEM_CONF_DIR = "/usr/local/etc/wireguard"
SYSTEM_IFACE = "wg0"
SYSTEM_CONF = os.path.join(SYSTEM_CONF_DIR, f"{SYSTEM_IFACE}.conf")
PING_COUNT = "5"
REFRESH_INTERVAL = 5000  # milliseconds

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
QWidget {
    background: #232427;
    color: #ddd;
    font-family: "IBM Plex Sans Medium","JetBrains Mono", monospace;
    /* font-size: 15px; */
    text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.5);

}
QGroupBox {
    border: 1px solid #444;
    border-radius: 6px;
    margin-top: 12px;
    background: #232427;
    font-weight: bold;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px 0 4px;
    background: transparent;
    color: #a7e2ff;
}
QListWidget, QTextEdit {
    background: #28292c;
    border: 1px solid #333;
    color: #e6e6e6;
}
QListWidget::item {
    padding: 2px 8px;
    min-height: 16px;
}
QListWidget::item:selected {
    background: #384452;
    color: #fff;
    border: .2px solid #60b8ff;
}
QListWidget::item:!selected {
    background: #28292c;
    color: #b7b7b7;
}
QPushButton {
    background: #212832;
    color: #e2e2e2;
    border: 1px solid #444;
    padding: 5px 18px;
    border-radius: 5px;
    font-weight: bold;
}
QPushButton:hover {
    background: #3c526b;
    color: #fff;
    border: 1px solid #60b8ff;
}
QPushButton:pressed {
    background: #60b8ff;
    color: #232427;
}
QLabel {
    color: #e0e0e0;
}
QSplitter::handle {
    background: #23272a;
}
/* --- Custom Narrow Scrollbars --- */
QScrollBar:vertical {
    border: none;
    background: #232427;
    width: 8px;
    margin: 2px 0 2px 0;
}
QScrollBar::handle:vertical {
    background: #4f6377;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
    border: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
/* Horizontal */
QScrollBar:horizontal {
    border: none;
    background: #232427;
    height: 8px;
    margin: 0 2px 0 2px;
}
QScrollBar::handle:horizontal {
    background: #4f6377;
    min-width: 20px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
    border: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}

QListWidget::item { 
    padding: 0 0px; 
    min-height: 7px;
    }

QLabel.data-label {
    /* color: #d2f8d2;*/
    color: #ffffff;
    font-family: "Consolas","IBM Plex Mono", "JetBrains Mono", monospace;
    /*font-size: 14px;*/
    text-shadow: 2px 2px 2px rgba(0, 0, 0, 0);

}

#profileList {
    background: #1c1e22;
    border: 1px solid #444;
    color: #d8d8d8;
    font-size: 12px;
    padding: 2px;
}

#profileList::item {
    padding: 4px 10px;
    min-height: 22px;
}

#profileList::item:selected {
    background: #375a7f;
    color: #ffffff;
    border: 1px solid #60b8ff;
}

#profileList::item:!selected {
    background: #1c1e22;
    color: #b0b0b0;
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

        self.icon_disconnected_path = os.path.join(resource_dir, "wireguard_off.png")
        self.icon_connected_path = os.path.join(resource_dir, "wg_connected.png")

        # Initialize active_profile early so update_tray_icon never errors
        self.active_profile = None
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), "wireguard.png")))
        self.setWindowTitle("WireGuard Client")
        self.resize(800, 600)

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

        # Build the context menu with emoji-prefixed QAction entries
        tray_menu = QMenu()
        act_show = QAction("👁 Show", self)
        act_disconnect = QAction("🔌 Disconnect", self)
        act_quit = QAction("🚭 Disconnect & Quit", self)

        tray_menu.addAction(act_show)
        tray_menu.addAction(act_disconnect)
        tray_menu.addSeparator()
        tray_menu.addAction(act_quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)

        # Connect actions to methods
        act_show.triggered.connect(self.show_and_raise)
        act_disconnect.triggered.connect(self.on_disconnect)
        act_quit.triggered.connect(self.quit_and_disconnect)

        self.tray_icon.show()

        self.list = QListWidget()
        list_font = QFont()
        list_font.setPointSize(11)  # Try 9 or 8 for even smaller rows
        self.list.setFont(list_font)

        self.list.setSpacing(-1)
        self.list.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.list.setMinimumWidth(300)
        self.list.setMaximumWidth(300)
        self.list.currentItemChanged.connect(self.update_detail_panel)

        label_font = QFont()
        label_font.setBold(True)

        self.intf_group = QGroupBox("Interface Details")
        intf_form = QFormLayout()
        intf_form.setVerticalSpacing(4)
        intf_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        intf_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        intf_form.setHorizontalSpacing(24)
        intf_form.setVerticalSpacing(7)
        self.lbl_status = QLabel()
        self.lbl_pubkey = QLabel()
        self.lbl_port = QLabel()
        self.lbl_addresses = QLabel()
        self.lbl_dns = QLabel()

        for lbl in (self.lbl_status, self.lbl_pubkey, self.lbl_port,
                    
                    self.lbl_addresses, self.lbl_dns):
            lbl.setFont(label_font)
            lbl.setProperty("class", "data-label")
            lbl.setWordWrap(False)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setMinimumHeight(16)

        for name, widget in [
            ("Status:", self.lbl_status),
            ("Public Key:", self.lbl_pubkey),
            ("Listen Port:", self.lbl_port),
            ("Addresses:", self.lbl_addresses),
            ("DNS Servers:", self.lbl_dns)
        ]:
            intf_form.addRow(name, widget)
        self.intf_group.setLayout(intf_form)

        self.peer_group = QGroupBox("Peer Details")
        peer_form = QFormLayout()
        peer_form.setVerticalSpacing(4)
        peer_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        peer_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        peer_form.setHorizontalSpacing(24)
        peer_form.setVerticalSpacing(7)
        self.lbl_peer_key = QLabel()
        self.lbl_allowed_ips = QLabel()
        self.lbl_endpoint = QLabel()
        self.lbl_handshake = QLabel()
        self.lbl_transfer = QLabel()

        for lbl in (self.lbl_peer_key, self.lbl_allowed_ips,
                    self.lbl_endpoint, self.lbl_handshake, self.lbl_transfer):
            lbl.setFont(label_font)
            lbl.setProperty("class", "data-label")
            lbl.setWordWrap(True)
            lbl.setMinimumWidth(460)
            lbl.setMaximumWidth(10000)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
            lbl.setMaximumHeight(1000)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setMinimumHeight(22)

        for name, widget in [
            ("Public Key:", self.lbl_peer_key),
            ("Allowed IPs:", self.lbl_allowed_ips),
            ("Endpoint:", self.lbl_endpoint),
            ("Last Handshake:", self.lbl_handshake),
            ("Transfer:", self.lbl_transfer)
        ]:
            peer_form.addRow(name, widget)
        self.peer_group.setLayout(peer_form)

        btn_box = QHBoxLayout()
        self.btnConnect = QPushButton("Connect")
        self.btnDisconnect = QPushButton("Disconnect")
        self.btnQuit = QPushButton("Quit")
        btn_box.addWidget(self.btnConnect)
        btn_box.addWidget(self.btnDisconnect)
        btn_box.addWidget(self.btnQuit)

        left = QWidget()
        self.list.setMinimumWidth(260)
        self.list.setMaximumWidth(300)
        left.setMinimumWidth(300)
        left.setMaximumWidth(300)
        left_layout = QVBoxLayout(left)
        profiles_label = QLabel("Profiles")
        profiles_font = QFont()
        profiles_font.setBold(True)
        profiles_label.setFont(profiles_font)
        left_layout.addWidget(profiles_label)
        left_layout.addWidget(self.list)
        left_layout.addLayout(btn_box)

        right = QWidget()
        right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.intf_group)
        right_layout.addWidget(self.peer_group)
        right_layout.addStretch()
        def match_groupbox_widths():
            intf_width = self.intf_group.sizeHint().width()
            peer_width = self.peer_group.sizeHint().width()
            widest = max(intf_width, peer_width, 520)
            self.intf_group.setMinimumWidth(widest)
            self.peer_group.setMinimumWidth(widest)
            intf_form: QFormLayout = self.intf_group.layout()
            peer_form: QFormLayout = self.peer_group.layout()
            label_w = max(
                intf_form.labelForField(self.lbl_status).sizeHint().width(),
                peer_form.labelForField(self.lbl_peer_key).sizeHint().width(),
                110
            )
            for form in [intf_form, peer_form]:
                for i in range(form.rowCount()):
                    label = form.itemAt(i, QFormLayout.ItemRole.LabelRole).widget()
                    if label:
                        label.setMinimumWidth(label_w)
                        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        match_groupbox_widths()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setMinimumHeight(400)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet("QSplitter::handle { background: #2a2a2a; }")

        self.log = QTextEdit(readOnly=True)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(splitter)
        logs_label = QLabel("Logs")
        logs_font = QFont()
        logs_font.setBold(True)
        logs_label.setFont(logs_font)
        main_layout.addWidget(logs_label)
        main_layout.addWidget(self.log)

        self.btnConnect.clicked.connect(self.on_connect)
        self.btnDisconnect.clicked.connect(self.on_disconnect)
        self.btnQuit.clicked.connect(self.quit_and_disconnect)

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
        if self.is_interface_up():
            self.on_disconnect()
        QApplication.instance().quit()

    def closeEvent(self, event):
        # Hide to tray instead of closing
        self.hide()
        self.tray_icon.showMessage(
            "WireGuard Client",
            "App is still running in the tray. Right-click for options.",
            QSystemTrayIcon.MessageIcon.Information,
            2000
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
                item.setFont(font)
                self.list.addItem(item)

    def refresh_status(self):
        up = self.is_interface_up()
        for i in range(self.list.count()):
            itm = self.list.item(i)
            prof = itm.data(Qt.ItemDataRole.UserRole)
            font = QFont()
            font.setBold(up and prof == self.active_profile)
            # Draw a small circle as icon (mac-style)
            size = 10
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            color = QColor('#60FF60') if (up and prof == self.active_profile) else QColor('#FFFFFF')
            painter.setBrush(color)
            painter.setPen(Qt.GlobalColor.transparent)
            painter.drawEllipse(0, 0, size, size)
            painter.end()
            itm.setIcon(QIcon(pixmap))
            itm.setFont(font)
            itm.setText(prof)
        self.update_detail_panel()
        # Tray icon connected
        self.update_tray_icon()


    def is_interface_up(self):
        try:
            out = subprocess.check_output(
                ["wg", "show", "interfaces"],
            ).decode().strip()
            return SYSTEM_IFACE in out.split()
        except subprocess.CalledProcessError:
            return False

    def update_detail_panel(self):
        show_profile = self.active_profile if self.is_interface_up() and self.active_profile else None
        if not show_profile:
            item = self.list.currentItem()
            show_profile = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.lbl_status.setText("-")
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
            self.lbl_status.setText("Up")
            self.lbl_pubkey.setText(iface.get('pubkey', "-"))
            self.lbl_port.setText(iface.get('port') or conf_port or "-")
            self.lbl_handshake.setText(peer.get('handshake', "-"))
            self.lbl_transfer.setText(peer.get('transfer', "-"))
        else:
            self.lbl_status.setText("Down")

    def on_connect(self):
        itm = self.list.currentItem()
        if not itm:
            self.log.append("⚠ Select a profile first.\n")
            return
        prof = itm.data(Qt.ItemDataRole.UserRole)
        self.active_profile = prof
        src = os.path.join(WG_DIR, f"{prof}.conf")
        cmds = []
        if self.is_interface_up():
            cmds += [["wg-quick","down",SYSTEM_IFACE], ["sleep","1"]]
        cmds += [["doas","cp",src,SYSTEM_CONF], ["doas","wg-quick","up",SYSTEM_IFACE]]
        with open(src) as f:
            for ln in f:
                if ln.startswith("#ping "):
                    ip = ln.split()[1]
                    cmds.append(["ping","-c",PING_COUNT,ip])
        self.commands, self.cmd_index = cmds, 0
        self.log.clear()
        self.run_next()
        # Tray icon disconnected
        self.update_tray_icon()


    def on_disconnect(self):
        self.commands, self.cmd_index = [["wg-quick","down",SYSTEM_IFACE]], 0
        self.active_profile = None
        self.log.clear()
        self.run_next()

    def run_next(self):
        if self.cmd_index < len(self.commands):
            c = self.commands[self.cmd_index]
            self.cmd_index += 1
            self.log.append(f"> {' '.join(c)}\n")
            self.process.start(c[0], c[1:])

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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    gui = WGGui()
    gui.show()
    sys.exit(app.exec())
