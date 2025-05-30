# WireGuard GUI Client for FreeBSD/Linux
![Screenshot](images/screenshot.png1)


This is a PyQt6-based graphical interface for managing WireGuard VPN profiles. It allows you to easily view connection details, switch between profiles, connect/disconnect from the VPN, and see live logs.

---

## Features

* Auto-refreshing connection and peer status
* Easy profile switching
* Logs with `ping` test support
* Responsive PyQt6 interface
* Selectable labels and scrollable info areas
* Improved styling via QSS (Qt stylesheets)
* Clean separation between profile list and details
- Selectable labels and scrollable info areas
- Logs with live `ping` output for connectivity checks [if configured]
- Does **not** disconnect on window close; connection persists unless manually disconnected  


---

## Filesystem Layout

The application expects:

* WireGuard profile configs in: `~/scripts/wireguard_client/profiles/*.conf`
* Runtime config copy to: `/usr/local/etc/wireguard/wg0.conf`
* Interface name is assumed to be `wg0`
* **App icon:** `wireguard.png` (use your own if you wish, placed next to `wg_gui.py`)


---

##  Requirements

### 🐍 Python

* Python 3.9+ (tested with 3.11)
* PyQt6

Install with:

```bash
python3 -m venv venv
source venv/bin/activate
pip install PyQt6
```

Or directly:

```bash
pip install PyQt6
```

###  System Dependencies

On **FreeBSD**:

```bash
sudo pkg install wireguard py39-pyqt6 doas
```

Adjust `py39-` for your version of Python.

On **Linux** (Debian/Ubuntu):

```bash
sudo apt install wireguard python3-pyqt6 doas
```

> `doas` can be replaced by `sudo` if preferred — adjust the script accordingly.

---

## Running the GUI

```bash
./wg_gui.py
```

Or make it executable:

```bash
chmod +x wg_gui.py
./wg_gui.py
```

---

##  Switching Profiles\

* When you select a new profile, the previous connection is cleanly disconnected, and the new one is brought up.  
  If the interface is already active, it is torn down first.

* **Connection persistence:**  
  If you close the GUI window, your VPN connection **remains up** — it is not torn down unless you explicitly click "Disconnect".

* **Optional:**  
  Your WireGuard profile can include a line like  
  ```
  #ping 10.0.1.1
  ```
  to test post-connection reachability, with the ping output visible in the log area.

---

##  Example Profile File

```ini
[Interface]
PrivateKey = <your-private-key>
Address = 10.0.0.2/32
DNS = 1.1.1.1

[Peer]
PublicKey = <server-public-key>
AllowedIPs = 0.0.0.0/0
Endpoint = your.server.com:51820
PersistentKeepalive = 25
#ping 10.0.0.1
```

---

##  Why This Exists

This project was created to:

* Simplify switching between multiple WireGuard configs
* Provide a visual interface for monitoring connection details
* Fill the gap for non existing other GUIs or terminal-only tools
* Built with PyQt6 for easy tweaking (stylesheets, icons, layout) and portability

It's built with PyQt6 for ease of use, portability, and extensibility.

---

## Customization

* **App Icon:**  
  Place your own PNG as `wireguard.png` alongside `wg_gui.py` to change the window icon.
* **Styles:**  
  Easily tweak appearance via the `APP_STYLESHEET` section in the script.
* **Tray Mode:**  
  (Experimental) Tray icon support can be added; see comments in the script.

---

## License
Use as you please. No restrictions.

