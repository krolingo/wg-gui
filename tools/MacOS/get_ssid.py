#!/opt/homebrew/bin/python3
"""
get_wifi_ssid.py

Description:
    Retrieves and prints the current connected Wi-Fi SSID on macOS using the CoreWLAN API.

Usage:
    python get_wifi_ssid.py [interface_name]

    - interface_name: (optional) the name of your Wi-Fi interface (default: en0)

Requirements:
    - macOS
    - Python with PyObjC (to access CoreWLAN), e.g.:
        pip install pyobjc-framework-CoreWLAN
"""

import sys
import CoreWLAN

def main():
    # Allow specifying a different interface via command-line
    iface_name = sys.argv[1] if len(sys.argv) > 1 else "en0"
    
    wifi_interface = CoreWLAN.CWInterface.interfaceWithName_(iface_name)
    if wifi_interface:
        ssid = wifi_interface.ssid()
        print(ssid if ssid else "Not connected to any Wi-Fi network.")
    else:
        print(f"No Wi-Fi interface named '{iface_name}' found.")

if __name__ == "__main__":
    main()
