#!/opt/homebrew/bin/python3
import sys
import CoreWLAN

wifi_interface = CoreWLAN.CWInterface.interfaceWithName_("en0")  # Replace 'en0' with your Wi-Fi interface name
if wifi_interface:
    print(wifi_interface.ssid())
else:
    print("No Wi-Fi interface found.")
