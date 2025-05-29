#!/usr/bin/env python3
import sys
import os
import subprocess
import time
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QLabel, QFormLayout, QGroupBox, QSplitter, QSizePolicy
)
from PyQt6.QtCore import QProcess, Qt, QTimer
from PyQt6.QtGui import QTextCursor, QFont

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
        out = subprocess.check_output(["wg", "show", SYSTEM_IFACE, "dump"]).decode().strip()
        lines = out.splitlines()
        if lines:
            iface_parts = lines[0].split()
            iface_info = {
                'pubkey': iface_parts[1],
                'port': iface_parts[3]
            }
            if len(lines) > 1:
                peer_parts = lines[1].split()
                peer_pubkey = peer_parts[0] if peer_parts[0] != '(none)' else '-'
                allowed_ips = peer_parts[3] if len(peer_parts) > 3 else '-'
                endpoint = peer_parts[2] if len(peer_parts) > 2 else '-'

                try:
                    epoch = int(peer_parts[4])
                    if 1000000000 < epoch < 2000000000:
                        handshake = time_ago(epoch)
                    else:
                        handshake = '-'
                except (ValueError, IndexError):
                    handshake = '-'

                try:
                    rx = int(peer_parts[5])
                    tx = int(peer_parts[6])
                    transfer = f"{rx / 1024:.2f} KiB RX, {tx / 1024:.2f} KiB TX"
                except (ValueError, IndexError):
                    transfer = "-"

                peer_info = {
                    'pubkey': peer_pubkey,
                    'allowed_ips': allowed_ips,
                    'endpoint': endpoint,
                    'handshake': handshake,
                    'transfer': transfer
                }
    except subprocess.CalledProcessError:
        pass
    return iface_info, peer_info

class WGGui(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WireGuard Client")
        self.resize(800, 600)

        self.list = QListWidget()
        self.list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.list.currentItemChanged.connect(self.update_detail_panel)

        label_font = QFont()
        label_font.setBold(False)

        self.intf_group = QGroupBox("Interface Details")
        intf_form = QFormLayout()
        intf_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        intf_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        intf_form.setHorizontalSpacing(20)

        self.lbl_status = QLabel()
        self.lbl_pubkey = QLabel()
        self.lbl_port = QLabel()
        self.lbl_addresses = QLabel()
        self.lbl_dns = QLabel()

        for label in [self.lbl_status, self.lbl_pubkey, self.lbl_port,
                      self.lbl_addresses, self.lbl_dns]:
            label.setFont(label_font)
            label.setWordWrap(True)
            label.setMinimumWidth(460)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
            label.setMaximumHeight(1000)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        for lbl, widget in [
            ("Status:", self.lbl_status),
            ("Public Key:", self.lbl_pubkey),
            ("Listen Port:", self.lbl_port),
            ("Addresses:", self.lbl_addresses),
            ("DNS Servers:", self.lbl_dns)
        ]:
            intf_form.addRow(lbl, widget)
        self.intf_group.setLayout(intf_form)

        self.peer_group = QGroupBox("Peer Details")
        peer_form = QFormLayout()
        peer_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        peer_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        peer_form.setHorizontalSpacing(20)

        self.lbl_peer_key = QLabel()
        self.lbl_allowed_ips = QLabel()
        self.lbl_endpoint = QLabel()
        self.lbl_handshake = QLabel()
        self.lbl_transfer = QLabel()

        for label in [self.lbl_peer_key, self.lbl_allowed_ips,
                      self.lbl_endpoint, self.lbl_handshake, self.lbl_transfer]:
            label.setFont(label_font)
            label.setWordWrap(True)
            label.setMinimumWidth(460)
            label.setMaximumWidth(460)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
            label.setMaximumHeight(1000)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        for lbl, widget in [
            ("Public Key:", self.lbl_peer_key),
            ("Allowed IPs:", self.lbl_allowed_ips),
            ("Endpoint:", self.lbl_endpoint),
            ("Last Handshake:", self.lbl_handshake),
            ("Transfer:", self.lbl_transfer)
        ]:
            peer_form.addRow(lbl, widget)
        self.peer_group.setLayout(peer_form)

        btn_box = QHBoxLayout()
        self.btnConnect = QPushButton("Connect")
        self.btnDisconnect = QPushButton("Disconnect")
        self.btnQuit = QPushButton("Quit")
        btn_box.addWidget(self.btnConnect)
        btn_box.addWidget(self.btnDisconnect)
        btn_box.addWidget(self.btnQuit)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Profiles"))
        left_layout.addWidget(self.list)
        left_layout.addLayout(btn_box)

        right = QWidget()
        right.setFixedWidth(590)
        right.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.intf_group)
        right_layout.addWidget(self.peer_group)
        right_layout.addStretch()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setHandleWidth(0)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([200, 600])

        self.log = QTextEdit(readOnly=True)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(splitter)
        main_layout.addWidget(QLabel("Logs"))
        main_layout.addWidget(self.log)

        self.btnConnect.clicked.connect(self.on_connect)
        self.btnDisconnect.clicked.connect(self.on_disconnect)
        self.btnQuit.clicked.connect(self.close)

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
        self.refresh_status()

    def parse_wg_show(self):
        return parse_wg_show()

    def load_profiles(self):
        self.list.clear()
        for conf in sorted(os.listdir(WG_DIR)):
            if conf.endswith('.conf'):
                profile = conf[:-5]
                item = QListWidgetItem(f"⚪ {profile}")
                item.setData(Qt.ItemDataRole.UserRole, profile)
                self.list.addItem(item)

    def refresh_status(self):
        interface_up = self.is_interface_up()
        for idx in range(self.list.count()):
            item = self.list.item(idx)
            profile = item.data(Qt.ItemDataRole.UserRole)
            icon = '🟢' if interface_up and profile == self.active_profile else '⚪'
            item.setText(f"{icon} {profile}")
        self.update_detail_panel()

    def is_interface_up(self):
        try:
            output = subprocess.check_output(["wg", "show", "interfaces"]).decode()
            return SYSTEM_IFACE in output.strip().split()
        except subprocess.CalledProcessError:
            return False

    def update_detail_panel(self):
        iface, peer = self.parse_wg_show()
        self.lbl_status.setText("Up" if iface else "Down")
        self.lbl_pubkey.setText(iface.get('pubkey', '-'))
        self.lbl_port.setText(iface.get('port', '-'))

        profile = self.list.currentItem().data(Qt.ItemDataRole.UserRole) if self.list.currentItem() else None
        addresses, dns_servers = [], []
        if profile:
            with open(os.path.join(WG_DIR, f"{profile}.conf")) as f:
                for line in f:
                    if line.startswith("Address"):
                        addresses.append(line.split('=', 1)[1].strip())
                    if line.startswith("DNS"):
                        dns_servers.append(line.split('=', 1)[1].strip())
        self.lbl_addresses.setText(", ".join(addresses) or '-')
        self.lbl_dns.setText(", ".join(dns_servers) or '-')

        self.lbl_peer_key.setText(peer.get('pubkey', '-'))
        self.lbl_allowed_ips.setText(peer.get('allowed_ips', '-'))
        self.lbl_endpoint.setText(peer.get('endpoint', '-'))
        self.lbl_handshake.setText(peer.get('handshake', '-'))
        self.lbl_transfer.setText(peer.get('transfer', '-'))

    def on_connect(self):
        item = self.list.currentItem()
        if not item:
            self.log.append("⚠ Select a profile first.\n")
            return

        profile = item.data(Qt.ItemDataRole.UserRole)
        self.active_profile = profile
        conf_src = os.path.join(WG_DIR, f"{profile}.conf")

        cmds = []
        if self.is_interface_up():
            cmds.append(["doas", "wg-quick", "down", SYSTEM_IFACE])
            cmds.append(["sleep", "1"])  # ensure the interface is fully released

        cmds.append(["doas", "cp", conf_src, SYSTEM_CONF])
        cmds.append(["doas", "wg-quick", "up", SYSTEM_IFACE])

        with open(conf_src) as f:
            for line in f:
                if line.startswith("#ping "):
                    ip = line.split()[1]
                    cmds.append(["ping", "-c", PING_COUNT, ip])

        self.commands, self.cmd_index = cmds, 0
        self.log.clear()
        self.run_next()



    def on_disconnect(self):
        cmds = [["doas", "wg-quick", "down", SYSTEM_IFACE]]
        self.commands, self.cmd_index = cmds, 0
        self.active_profile = None
        self.log.clear()
        self.run_next()

    def run_next(self):
        if self.cmd_index < len(self.commands):
            cmd = self.commands[self.cmd_index]
            self.cmd_index += 1
            self.log.append(f"> {' '.join(cmd)}\n")
            self.process.start(cmd[0], cmd[1:])

    def on_stdout(self):
        self.log.insertPlainText(self.process.readAllStandardOutput().data().decode())
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def on_stderr(self):
        self.log.insertPlainText(self.process.readAllStandardError().data().decode())
        self.log.moveCursor(QTextCursor.MoveOperation.End)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = WGGui()
    gui.show()
    sys.exit(app.exec())
