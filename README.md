  # WireGuard GUI Client for FreeBSD
  ![Screenshot](images/screenshot3.png)
  
  
  This is a PyQt6-based graphical interface for managing WireGuard VPN profiles. It allows you to easily view connection details, switch between profiles, connect/disconnect from the VPN, and see live logs.
  
  ---
  
  ## Features
  
* System tray icon with connection status (disconnected / connected)
* Toggle visibility by clicking the tray icon
* Tray icon persists even when the window is closed
* Clean, responsive interface using Qt Stylesheets (QSS)
* Auto-refreshing interface and peer status
* Selectable text in all details and logs
* Compact, monospaced layout for easy reading
* Profile list with custom styling and indicator icons
* Logs with live ping output for connectivity tests (if configured)
* Profiles are hot-switched — interface is brought down before activating a new one
* Does not disconnect on window close — connection stays active until manually stopped
* Single-instance locked Prevents multiple copies of the app from running simultaneously.
* Theme-aware tray icons (light/dark mode) [still missing light styles.]
* Dark mode detection

  ---
  
  ## Filesystem Layout

### The application expects:

* WireGuard profile configs in: `~/scripts/wireguard_client/profiles/*.conf`
* Runtime config copy to: `/usr/local/etc/wireguard/wg0.conf`
* Interface name is assumed to be `wg0`

### Icons:
* wireguard_off.png and wg_connected.png used for tray state
* Place them inside an Icons/ folder next to wg_gui.py
### App icon:
* wireguard.png is used as the main window icon

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
  
  ##  Switching Profiles
  
* When you select a new profile, the interface is safely shut down and restarted with the new config.
* If the interface is already up, it will be cleanly stopped before switching.
* The app supports #ping <host> directives in the profile for automatic post-connect testing.
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
## Tray Icon Behavior

* The app minimizes to the **system tray**, not the taskbar.
* The tray icon automatically adjusts for **light or dark mode**, using the appropriate SVGs:
  
  <img src="Icons/eye_dark.svg" width="18"/> **Show**  
  <img src="Icons/plug-off_dark.svg" width="18"/> **Disconnect**  
  <img src="Icons/logout_dark.svg" width="18"/> **Disconnect & Quit**

* The tray icon changes color/state when the connection is active.
* **Left-click** toggles visibility of the main window.
* **Right-click** shows the context menu with the options above.

  
##  Why This Exists
  
### This project was created to:
  
* Simplify switching between multiple WireGuard configs
* Provide a visual interface for monitoring connection details
* Fill the gap for non existing other GUIs or terminal-only tools
* Built with PyQt6 for easy tweaking (stylesheets, icons, layout) and portability
  
It's built with PyQt6 for ease of use, portability, and extensibility.
  
  ---  
  ## Customization
  
* **Icons:**
Replace wireguard_off.png, wg_connected.png, and wireguard.png with your own

* **Stylesheet:**
Modify APP_STYLESHEET in wg_gui.py for colors, fonts, padding, and behavior

* **Tray Behavior:**
Toggle visibility, show/hide messages, or even auto-connect on startup
  
  ---

## Automatic Route Handling

To ensure clean connection and disconnection behavior across all WireGuard profiles, the app integrates two global lifecycle scripts:

### `global_postup.sh`
This script is automatically run **after a profile is connected**, and performs:

- Logging the active interface and timestamp
- Displaying active routes for the tunnel interface (e.g. `wg0`)
- Starting a background route monitor to passively observe routing changes

Sample output (visible in GUI log):

```
[global_postup] ✅ WireGuard up: wg0
[global_postup] Routing table entries:
10.7.0.0/24     10.7.0.2     UGS     wg0
[global_postup] Starting route monitor for wg0...
[global_postup] Done.
```

---

### `flush_wg_routes.sh`
This script runs **automatically on disconnect** and:

- Identifies and removes any active routes associated with `wg0`
- Ensures the system routing table is clean after tunnel teardown

If no tunnel-specific routes are present, it exits safely:

```
[flush_wg_routes] No routes found for interface wg0
```

These scripts:

- Ensure **no stale routes or leaks** are left behind
- Improve security, reliability, and debug clarity
- Run silently unless action is needed
- Require no user configuration or toggling — they're always safe to use

  
  
  ## License
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

