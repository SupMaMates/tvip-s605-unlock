#!/usr/bin/env python3
"""
TVIP S-Box 605 -- All-in-One Hardware Unlocker & Root Provisioning Suite
Supports both Android 8.0 and Linux-QT firmware variants.

Features:
  1. Permanent Hardware Unlock: Reprograms Amlogic NVRAM UnifyKeys directly via ADB.
  2. Built-in Provisioning Server: Hosts HTTP tvip_provision.xml to unlock menus
     and activate Dropbear (SSH) & Telnet root shell on Linux-QT and Android.
  3. Network Diagnostics: Probes ADB, SSH (22), and Telnet (23).
"""

import argparse
import http.server
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time

BANNER = """
============================================================
   TVIP S-Box 605 -- All-in-One Unlock & Root Shell Suite
============================================================
"""

PROVISION_TEMPLATE = """<?xml version="1.0"?>
<provision reload="86400">
  <!-- Enable Dropbear SSH and Telnet root shell -->
  <system_locks>
    <shell password="{password}" />
    <sysinfo_del locked="false" />
    <reset locked="false" />
  </system_locks>

  <!-- Enable all built-in applications -->
  <features>
    <mediaplayer enabled="true" />
    <dvr enabled="true" />
    <cctv enabled="true" />
    <vod enabled="true" />
    <navigator enabled="true" />
  </features>

  <!-- Make all TV preferences, content sources, and setup buttons visible -->
  <preferences>
    <pref_tv>
      <pref_tv_streamtype visible="true" />
      <pref_tv_udpxyaddress visible="true" />
      <pref_tv_dvr_deviceid visible="true" />
      <pref_tv_timeshift_deviceid visible="true" />
      <pref_tv_autotimeshift visible="true" />
      <pref_tv_middleware visible="true" />
      <pref_tv_button_midd_setup visible="true" />
      <pref_tv_mpegts_buffer visible="true" />
    </pref_tv>
    <pref_system>
      <pref_system_updatetype visible="true" />
      <pref_system_updateperiod visible="true" />
      <pref_system_updatebackground visible="true" />
    </pref_system>
  </preferences>
{custom_protocol}
</provision>
"""

def run_adb(cmd_list, device=None):
    base = ["adb"]
    if device:
        base.extend(["-s", device])
    full_cmd = base + cmd_list
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def get_adb_devices():
    code, out, _ = run_adb(["devices", "-l"])
    devices = []
    if code != 0:
        return devices
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serial = parts[0]
            # Prioritize TVIP devices if detected
            is_tvip = any("tvip" in p.lower() or "s6xx" in p.lower() for p in parts)
            if is_tvip or ":" in serial:
                devices.insert(0, serial)
            else:
                devices.append(serial)
    return devices

def get_local_ip(target_ip="192.168.1.1"):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target_ip, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def check_port(host, port, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def read_unifykey_ps(device=None):
    cmd = ["shell", "echo 1 > /sys/class/unifykeys/attach && echo ps > /sys/class/unifykeys/name && cat /sys/class/unifykeys/read"]
    code, out, err = run_adb(cmd, device)
    if code != 0:
        return None, err
    return out.strip(), None

def write_unifykey_ps(new_value, device=None):
    shell_script = (
        f"echo 1 > /sys/class/unifykeys/attach && "
        f"echo 1 > /sys/class/unifykeys/lock && "
        f"echo ps > /sys/class/unifykeys/name && "
        f"echo {new_value} > /sys/class/unifykeys/write && "
        f"echo 0 > /sys/class/unifykeys/lock"
    )
    code, out, err = run_adb(["shell", shell_script], device)
    return code == 0, err

def clear_tvip_data(device=None):
    code, out, err = run_adb(["shell", "pm clear tv.tvip.app"], device)
    return code == 0 and "Success" in out

def check_device_info(device=None):
    props = {}
    for p in ["ro.product.model", "ro.product.board", "ro.build.version.release", "ro.build.display.id"]:
        _, out, _ = run_adb(["shell", f"getprop {p}"], device)
        props[p] = out
    _, se, _ = run_adb(["shell", "getenforce"], device)
    props["selinux"] = se
    return props

class ProvisionHandler(http.server.BaseHTTPRequestHandler):
    xml_content = b""

    def do_GET(self):
        client_ip = self.client_address[0]
        path = self.path.split("?")[0]
        print(f"\n[HTTP GET] {client_ip} requested: {self.path}")

        if path.endswith("tvip_provision.xml") or path == "/prov" or path == "/prov/":
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(self.xml_content)))
            self.end_headers()
            self.wfile.write(self.xml_content)
            print(f"[+] Delivered custom tvip_provision.xml to {client_ip}!")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default server logs for clean CLI output

def start_provision_server(port, password, portal_url=None):
    custom_proto = ""
    if portal_url:
        custom_proto = f"""  <tv_protocols default="browser">
    <protocol type="browser" server="{portal_url}" api="mag" noui="false" combined="true" />
  </tv_protocols>"""

    xml = PROVISION_TEMPLATE.format(password=password, custom_protocol=custom_proto).encode("utf-8")
    ProvisionHandler.xml_content = xml

    server = socketserver.TCPServer(("", port), ProvisionHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return server

def run_diagnostics(target_dev, box_ip):
    print("\n--- Diagnostic Results ---")
    if target_dev:
        info = check_device_info(target_dev)
        print(f"[+] Target ADB Device: {target_dev}")
        print(f"    Model: {info.get('ro.product.model')} | Board: {info.get('ro.product.board')}")
        print(f"    OS Release: {info.get('ro.build.version.release')} | Build: {info.get('ro.build.display.id')}")
        print(f"    SELinux: {info.get('selinux')}")
        current_ps, _ = read_unifykey_ps(target_dev)
        print(f"    NVRAM Key 14 ('ps'): '{current_ps}'")
        if current_ps in ("127.0.0.1", "localhost"):
            print("    Hardware Lock Status: UNLOCKED (provisioning neutralized)")
        else:
            print(f"    Hardware Lock Status: LOCKED to operator ({current_ps})")
    else:
        print("[!] ADB Status: Not connected")

    if box_ip:
        print(f"\n[*] Probing Network Ports on {box_ip}:")
        ssh_ok = check_port(box_ip, 22)
        telnet_ok = check_port(box_ip, 23)
        adb_ok = check_port(box_ip, 5555)
        print(f"    Port 22 (Dropbear SSH): {'OPEN [Root Shell Available]' if ssh_ok else 'Closed'}")
        print(f"    Port 23 (Telnet):       {'OPEN [Root Shell Available]' if telnet_ok else 'Closed'}")
        print(f"    Port 5555 (ADB):        {'OPEN' if adb_ok else 'Closed'}")

def main():
    parser = argparse.ArgumentParser(description="TVIP S-Box 605 All-in-One Unlocker & Root Provisioning Suite")
    parser.add_argument("-s", "--device", help="ADB target device (e.g. 192.168.1.41:5555)")
    parser.add_argument("--box-ip", help="IP address of the TVIP box for network checks (e.g. 192.168.1.41)")
    parser.add_argument("--unlock", action="store_true", help="Perform permanent hardware unlock via NVRAM UnifyKeys")
    parser.add_argument("--server-ip", default="127.0.0.1", help="Target server to write to NVRAM (default: 127.0.0.1)")
    parser.add_argument("--serve", action="store_true", help="Start local provisioning server to unlock UI & enable root shell")
    parser.add_argument("--port", type=int, default=80, help="HTTP provisioning server port (default: 80)")
    parser.add_argument("--password", default="toor", help="Password to configure for SSH/Telnet root shell (default: toor)")
    parser.add_argument("--portal", help="Optional custom portal URL to inject (e.g. http://my-stalker-portal.com)")
    parser.add_argument("--check", action="store_true", help="Run read-only diagnostics")
    parser.add_argument("--reboot", action="store_true", help="Reboot device via ADB")
    args = parser.parse_args()

    print(BANNER)

    devices = get_adb_devices()
    target_dev = args.device or (devices[0] if devices else None)
    box_ip = args.box_ip
    if not box_ip and target_dev and ":" in target_dev:
        box_ip = target_dev.split(":")[0]

    # If no flags passed, default to check + unlock
    if not any([args.unlock, args.serve, args.check, args.reboot]):
        print("[*] No specific mode selected. Running diagnostics and hardware unlock...")
        args.check = True
        args.unlock = True

    if args.check:
        run_diagnostics(target_dev, box_ip)

    if args.unlock:
        if not target_dev:
            print("[!] Error: ADB device not detected. Connect device via USB or 'adb connect <ip>:5555'.")
            sys.exit(1)

        print(f"\n[*] Applying Permanent Hardware Unlock to {target_dev}...")
        current_ps, _ = read_unifykey_ps(target_dev)
        print(f"[*] Current NVRAM 'ps': '{current_ps}'")

        if current_ps == args.server_ip:
            print(f"[+] NVRAM 'ps' is already '{args.server_ip}'.")
        else:
            print(f"[*] Writing '{args.server_ip}' to Amlogic NVRAM UnifyKeys key 14 ('ps')...")
            ok, err = write_unifykey_ps(args.server_ip, target_dev)
            if not ok:
                print(f"[!] Write failed: {err}")
                sys.exit(1)
            verified, _ = read_unifykey_ps(target_dev)
            print(f"[+] Verified in NVRAM chip: '{verified}'")

        print("[*] Clearing tv.tvip.app application state...")
        if clear_tvip_data(target_dev):
            print("[+] tv.tvip.app cache and operator data wiped successfully.")
        else:
            print("[*] Note: App clear skipped or not applicable.")

        print("\n[+] HARDWARE UNLOCK APPLIED SUCCESSFULLY!")
        print("    The provider lock has been neutralized.")

    if args.serve:
        local_ip = get_local_ip(box_ip or "192.168.1.1")
        print(f"\n[*] Starting Provisioning Server on http://{local_ip}:{args.port}/prov/tvip_provision.xml")
        print(f"[*] Configured root shell password: '{args.password}'")
        if args.portal:
            print(f"[*] Configured custom portal: '{args.portal}'")

        try:
            server = start_provision_server(args.port, args.password, args.portal)
            print("[+] HTTP Server is LIVE. Waiting for TVIP box connection...")

            # If ADB is available, we can automatically set ps to our server IP!
            if target_dev:
                print(f"[*] ADB available: Setting TVIP NVRAM 'ps' to {local_ip}...")
                write_unifykey_ps(local_ip, target_dev)
                print("[*] Restarting TVIP app to trigger instant provisioning...")
                run_adb(["shell", "am force-stop tv.tvip.app && am start -n tv.tvip.app/.TvipNativeActivity"], target_dev)

            print("\nPress Ctrl+C to stop the provisioning server.")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[*] Stopping server.")
        except PermissionError:
            print(f"\n[!] Error: Port {args.port} requires administrator/root privileges.")
            print(f"    Run the terminal as Administrator or specify a port like '--port 8080'.")

    if args.reboot and target_dev:
        print("\n[*] Rebooting device...")
        run_adb(["reboot"], target_dev)
        print("[+] Reboot command sent.")

if __name__ == "__main__":
    main()
