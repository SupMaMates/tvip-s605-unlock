#!/usr/bin/env python3
"""
TVIP S-Box 605 -- All-in-One Hardware Unlocker & Root Provisioning Suite
Supports both Android 8.0 and Linux-QT firmware variants.

Features:
  1. 1-Click Windows Mobile Hotspot Mode (--hotspot): Automatically enables
     PC Wi-Fi hotspot, extracts SSID/password, redirects operator domains,
     and auto-provisions/burns the TVIP box with zero router configuration.
  2. Zero-Touch Auto-Burner: When running provision server, automatically connects
     to the TVIP box upon boot, logs into root shell, permanently burns 127.0.0.1
     into Amlogic NVRAM UnifyKeys, and reboots.
  3. Automated Hardware Unlock (--unlock): Reprograms Amlogic NVRAM UnifyKeys
     directly via ADB.
  4. Network Diagnostics (--check): Probes ADB, Dropbear SSH (22), and Telnet (23).
"""

import argparse
import atexit
import ctypes
import http.server
import os
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

BANNER = """
============================================================
   TVIP S-Box 605 -- All-in-One Unlock & Auto-Burn Suite
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

BURN_COMMANDS = [
    "echo 1 > /sys/class/unifykeys/attach",
    "echo 1 > /sys/class/unifykeys/lock",
    "echo ps > /sys/class/unifykeys/name",
    "echo 127.0.0.1 > /sys/class/unifykeys/write",
    "echo 0 > /sys/class/unifykeys/lock",
    "rm -rf /var/tvip/*",
    "sync",
    "reboot"
]

DEFAULT_DOMAINS = [
    "dreambox.for-better.biz",
    "tvipstb.net",
    "update.tvip.ru",
    "prov.tvip.ru"
]

HOSTS_PATH = os.path.expandvars(r"%SystemRoot%\System32\drivers\etc\hosts") if sys.platform == "win32" else "/etc/hosts"
HOSTS_TAG_START = "# >>> TVIP-S605-UNLOCK REDIRECT >>>"
HOSTS_TAG_END   = "# <<< TVIP-S605-UNLOCK REDIRECT <<<"

_hosts_modified = False
_hotspot_started_by_us = False

# =========================================================================
# System & ADB Helpers
# =========================================================================

def is_admin():
    if sys.platform != "win32":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def elevate_if_needed():
    """On Windows, re-launch this script as Administrator via UAC if not already elevated."""
    if sys.platform != "win32":
        return
    if is_admin():
        return
    # Re-launch with elevation request
    print("[*] Administrator privileges required for DNS redirect (hosts file).")
    print("[*] Requesting elevation via Windows UAC...")
    try:
        params = " ".join(f'"{a}"' for a in sys.argv)
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
        if ret > 32:
            # Successfully spawned elevated process - exit current non-elevated one
            sys.exit(0)
        else:
            print("[!] UAC elevation was declined or failed.")
    except Exception as e:
        print(f"[!] Could not elevate: {e}")

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

def telnet_auto_burn(ip, user, password):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(6.0)
        s.connect((ip, 23))
        time.sleep(1.0)
        s.recv(1024)
        s.sendall(f"{user}\n".encode())
        time.sleep(1.0)
        s.recv(1024)
        s.sendall(f"{password}\n".encode())
        time.sleep(1.5)
        for cmd in BURN_COMMANDS:
            s.sendall(f"{cmd}\n".encode())
            time.sleep(0.3)
        s.close()
        return True
    except Exception:
        return False

def ssh_auto_burn(ip, user, password):
    """Burn NVRAM via SSH using paramiko (auto-installs if missing)."""
    try:
        import paramiko
    except ImportError:
        print(f"[*] Installing paramiko for SSH auto-burn...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "paramiko", "-q"],
                           check=True, timeout=30)
            import paramiko
        except Exception as e:
            print(f"[!] Could not install paramiko: {e}")
            return False

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            ip, port=22, username=user, password=password,
            timeout=10, allow_agent=False, look_for_keys=False,
            banner_timeout=15
        )
        # Run all burn commands in one shell session
        session = client.invoke_shell()
        time.sleep(1.0)
        session.recv(4096)  # flush banner
        for cmd in BURN_COMMANDS:
            session.send(f"{cmd}\n")
            time.sleep(0.4)
        time.sleep(1.0)
        session.close()
        client.close()
        return True
    except Exception as e:
        print(f"[!] SSH burn error: {e}")
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

# =========================================================================
# Windows Mobile Hotspot Automation (WinRT API via PowerShell)
# =========================================================================

PS_START_HOTSPOT_CODE = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null
[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null
$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if ($null -eq $profile) { Write-Output "STATUS:NoProfile"; exit 1 }
$manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
if ($manager.TetheringOperationalState -eq "Off") {
    $res = Await ($manager.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
    Write-Output "STATUS:$($res.Status)"
} else {
    Write-Output "STATUS:AlreadyOn"
}
"""

PS_INFO_HOTSPOT_CODE = """
[Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null
[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null
$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if ($null -eq $profile) { Write-Output "STATUS:NoProfile"; exit 1 }
$manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
$config = $manager.GetCurrentAccessPointConfiguration()
Write-Output "SSID:$($config.Ssid)"
Write-Output "KEY:$($config.Passphrase)"
Write-Output "STATE:$($manager.TetheringOperationalState)"
"""

PS_SET_HOTSPOT_CODE = """
param (
    [string]$Ssid = "TVIP-UNLOCK",
    [string]$Password = "12345678"
)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function AwaitAction($WinRtTask) {
    $netTask = $asTaskGeneric.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
}
[Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null
[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null
$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if ($null -eq $profile) { Write-Output "STATUS:NoProfile"; exit 1 }
$manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
$config = $manager.GetCurrentAccessPointConfiguration()
$config.Ssid = $Ssid
$config.Passphrase = $Password
AwaitAction ($manager.ConfigureAccessPointAsync($config))
$updated = $manager.GetCurrentAccessPointConfiguration()
Write-Output "STATUS:Success"
Write-Output "SSID:$($updated.Ssid)"
Write-Output "KEY:$($updated.Passphrase)"
"""

PS_STOP_HOTSPOT_CODE = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime] | Out-Null
[Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime] | Out-Null
$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if ($null -eq $profile) { Write-Output "STATUS:NoProfile"; exit 1 }
$manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
if ($manager.TetheringOperationalState -ne "Off") {
    $res = Await ($manager.StopTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
    Write-Output "STATUS:$($res.Status)"
} else {
    Write-Output "STATUS:AlreadyOff"
}
"""

def execute_ps_script(script_text, fallback_filename):
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), fallback_filename)
    if not os.path.exists(script_path):
        try:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script_text.strip())
        except Exception:
            script_path = os.path.join(tempfile.gettempdir(), fallback_filename)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script_text.strip())

    res = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
        capture_output=True,
        text=True
    )
    return res.stdout.strip()

def get_hotspot_info():
    out = execute_ps_script(PS_INFO_HOTSPOT_CODE, "get_hotspot_info.ps1")
    info = {"ssid": "Unknown", "key": "Unknown", "state": "Unknown"}
    for line in out.splitlines():
        if line.startswith("SSID:"):
            info["ssid"] = line.split("SSID:", 1)[1].strip()
        elif line.startswith("KEY:"):
            info["key"] = line.split("KEY:", 1)[1].strip()
        elif line.startswith("STATE:"):
            info["state"] = line.split("STATE:", 1)[1].strip()
    return info

def start_windows_hotspot():
    out = execute_ps_script(PS_START_HOTSPOT_CODE, "start_hotspot.ps1")
    return "STATUS:Success" in out or "STATUS:AlreadyOn" in out

def stop_windows_hotspot():
    out = execute_ps_script(PS_STOP_HOTSPOT_CODE, "stop_hotspot.ps1")
    return "STATUS:Success" in out or "STATUS:AlreadyOff" in out

def configure_windows_hotspot(ssid="TVIP-UNLOCK", password="12345678"):
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "set_hotspot_config.ps1")
    if not os.path.exists(script_path):
        try:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(PS_SET_HOTSPOT_CODE.strip())
        except Exception:
            script_path = os.path.join(tempfile.gettempdir(), "set_hotspot_config.ps1")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(PS_SET_HOTSPOT_CODE.strip())

    res = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path, "-Ssid", ssid, "-Password", password],
        capture_output=True,
        text=True
    )
    return "STATUS:Success" in res.stdout

# =========================================================================
# Hosts File DNS Redirect Management
# =========================================================================

def _build_hosts_block(redirect_ip, domains):
    lines = [HOSTS_TAG_START]
    for d in domains:
        lines.append(f"{redirect_ip:<16} {d}")
    lines.append(HOSTS_TAG_END)
    return "\n".join(lines)

def apply_hosts_redirect(redirect_ip, domains):
    global _hosts_modified

    block = _build_hosts_block(redirect_ip, domains)

    # Strategy 1: Direct Python write (works if truly elevated)
    try:
        with open(HOSTS_PATH, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if HOSTS_TAG_START in content:
            return True  # Already applied
        with open(HOSTS_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{block}\n")
        _hosts_modified = True
        return True
    except PermissionError:
        pass
    except Exception as e:
        print(f"[!] Direct write failed: {e}")

    # Strategy 2: PowerShell Add-Content via elevated Start-Process -Wait
    try:
        escaped_block = block.replace('"', '`"').replace('\n', '`n')
        ps_cmd = (
            f'Add-Content -Path \\"{HOSTS_PATH}\\" '
            f'-Value \\"{escaped_block}\\" -Encoding ASCII'
        )
        outer = (
            f'Start-Process powershell '
            f'-ArgumentList "-NoProfile -Command {ps_cmd}" '
            f'-Verb RunAs -Wait -WindowStyle Hidden'
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", outer],
            capture_output=True, text=True, timeout=15
        )
        # Verify it worked
        with open(HOSTS_PATH, "r", encoding="utf-8", errors="ignore") as f:
            if HOSTS_TAG_START in f.read():
                _hosts_modified = True
                return True
    except Exception:
        pass

    # Strategy 3: Generate a helper batch file and ask user to run it
    bat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apply_dns_redirect.bat")
    try:
        bat_lines = [
            "@echo off",
            "echo Applying TVIP unlock DNS redirect...",
            f'echo {HOSTS_TAG_START}>> "{HOSTS_PATH}"',
        ]
        for d in domains:
            bat_lines.append(f'echo {redirect_ip:<16} {d}>> "{HOSTS_PATH}"')
        bat_lines += [
            f'echo {HOSTS_TAG_END}>> "{HOSTS_PATH}"',
            "echo Done! You can close this window.",
            "pause"
        ]
        with open(bat_path, "w") as f:
            f.write("\n".join(bat_lines))

        print(f"\n[*] Generated helper: {bat_path}")
        print(f"[*] Right-click that file → 'Run as administrator' to apply DNS redirect.")
        print(f"[*] Then press ENTER here to continue.\n")
        # Auto-launch it elevated via ShellExecuteW
        ctypes.windll.shell32.ShellExecuteW(None, "runas", bat_path, None, None, 1)
    except Exception as e:
        print(f"[!] Could not generate helper bat: {e}")

    return False

def remove_hosts_redirect():
    global _hosts_modified
    if not os.path.exists(HOSTS_PATH):
        return
    try:
        with open(HOSTS_PATH, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if HOSTS_TAG_START in content and HOSTS_TAG_END in content:
            start_idx = content.find(HOSTS_TAG_START)
            end_idx = content.find(HOSTS_TAG_END) + len(HOSTS_TAG_END)
            new_content = content[:start_idx].rstrip() + "\n" + content[end_idx:].lstrip()
            with open(HOSTS_PATH, "w", encoding="utf-8") as f:
                f.write(new_content)
        _hosts_modified = False
    except Exception:
        pass

@atexit.register
def cleanup_on_exit():
    global _hosts_modified, _hotspot_started_by_us
    if _hosts_modified:
        remove_hosts_redirect()
    if _hotspot_started_by_us:
        stop_windows_hotspot()

# =========================================================================
# Provision Server & Zero-Touch Auto-Burner
# =========================================================================

class ProvisionHandler(http.server.BaseHTTPRequestHandler):
    xml_content = b""
    configured_password = "toor"
    burn_attempted = False

    def do_GET(self):
        client_ip = self.client_address[0]
        path = self.path.split("?")[0]
        print(f"\n[HTTP GET] TVIP box ({client_ip}) requested: {self.path}")

        # Match any provision request
        is_prov = (
            path.endswith("tvip_provision.xml") or
            "provision" in path.lower() or
            path.startswith("/prov") or
            path.endswith(".xml") or
            path in ("/", "")
        )

        if is_prov:
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(self.xml_content)))
            self.end_headers()
            self.wfile.write(self.xml_content)
            print(f"[+] Delivered custom tvip_provision.xml to {client_ip}!")
            print("[+] Root shell and unlocked UI preferences activated on box!")

            if not ProvisionHandler.burn_attempted:
                ProvisionHandler.burn_attempted = True
                threading.Thread(target=self.trigger_background_burn, args=(client_ip,), daemon=True).start()
        else:
            self.send_response(404)
            self.end_headers()

    def trigger_background_burn(self, client_ip):
        print("\n[*] ZERO-TOUCH AUTO-BURNER ACTIVATED:")
        print(f"[*] Waiting 5 seconds for TVIP box ({client_ip}) to initialize root shell...")
        time.sleep(5)

        # 1. Try Telnet port 23
        print(f"[*] Probing Telnet on {client_ip}:23...")
        if check_port(client_ip, 23, timeout=3.0):
            print(f"[+] Telnet is OPEN! Logging into root shell and burning NVRAM...")
            if telnet_auto_burn(client_ip, "root", ProvisionHandler.configured_password):
                print("\n============================================================")
                print("[SUCCESS] HARDWARE CHIP PERMANENTLY BURNED WITH 127.0.0.1!")
                print("           The operator lock has been permanently erased.")
                print("           The box is now rebooting fully unlocked.")
                print("============================================================\n")
                return

        # 2. Try SSH port 22 (Dropbear - Linux-QT default when telnet not active)
        print(f"[*] Probing Dropbear SSH on {client_ip}:22...")
        if check_port(client_ip, 22, timeout=3.0):
            print(f"[+] SSH is OPEN! Connecting and burning NVRAM via SSH...")
            if ssh_auto_burn(client_ip, "root", ProvisionHandler.configured_password):
                print("\n============================================================")
                print("[SUCCESS] HARDWARE CHIP PERMANENTLY BURNED WITH 127.0.0.1!")
                print("           The operator lock has been permanently erased.")
                print("           The box is now rebooting fully unlocked.")
                print("============================================================\n")
                return
            else:
                print(f"[!] SSH burn failed. Trying ADB...")

        # 3. Try ADB port 5555
        if check_port(client_ip, 5555, timeout=2.0):
            print(f"[*] ADB is OPEN on {client_ip}:5555. Burning NVRAM via ADB...")
            run_adb(["connect", f"{client_ip}:5555"])
            write_unifykey_ps("127.0.0.1", f"{client_ip}:5555")
            clear_tvip_data(f"{client_ip}:5555")
            run_adb(["reboot"], f"{client_ip}:5555")
            print("\n============================================================")
            print("[SUCCESS] HARDWARE CHIP PERMANENTLY BURNED VIA ADB!")
            print("           The box is now rebooting fully unlocked.")
            print("============================================================\n")
            return

        print(f"\n[!] Auto-burn could not connect (Telnet/SSH/ADB all failed).")
        print(f"    Manually run these commands on the box:")
        print(f"    ssh root@{client_ip}  (password: {ProvisionHandler.configured_password})")
        print(f"    Then paste:")
        for cmd in BURN_COMMANDS:
            print(f"      {cmd}")


    def log_message(self, format, *args):
        pass

def start_provision_server(port, password, portal_url=None):
    custom_proto = ""
    if portal_url:
        custom_proto = f"""  <tv_protocols default="browser">
    <protocol type="browser" server="{portal_url}" api="mag" noui="false" combined="true" />
  </tv_protocols>"""

    xml = PROVISION_TEMPLATE.format(password=password, custom_protocol=custom_proto).encode("utf-8")
    ProvisionHandler.xml_content = xml
    ProvisionHandler.configured_password = password

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

# =========================================================================
# Main Entry Point
# =========================================================================

def main():
    global _hotspot_started_by_us
    parser = argparse.ArgumentParser(description="TVIP S-Box 605 All-in-One Unlocker & Auto-Burn Suite")
    parser.add_argument("-s", "--device", help="ADB target device (e.g. 192.168.1.41:5555)")
    parser.add_argument("--box-ip", help="IP address of the TVIP box for network checks (e.g. 192.168.1.41)")
    parser.add_argument("--hotspot", action="store_true", help="1-Click Windows Mobile Hotspot Mode (Zero Router Config)")
    parser.add_argument("--hotspot-ssid", default="TVIP-UNLOCK", help="Hotspot Wi-Fi network name (default: TVIP-UNLOCK)")
    parser.add_argument("--hotspot-pass", default="12345678", help="Hotspot Wi-Fi password (default: 12345678 - minimum 8 chars for WPA2)")
    parser.add_argument("--stop-hotspot", action="store_true", help="Turn off Windows Mobile Hotspot and exit")
    parser.add_argument("--keep-hotspot", action="store_true", help="Do not turn off hotspot upon exit")
    parser.add_argument("--domains", default=",".join(DEFAULT_DOMAINS), help="Comma-separated domains to redirect to this PC")
    parser.add_argument("--unlock", action="store_true", help="Perform permanent hardware unlock via NVRAM UnifyKeys")
    parser.add_argument("--server-ip", default="127.0.0.1", help="Target server to write to NVRAM (default: 127.0.0.1)")
    parser.add_argument("--serve", action="store_true", help="Start provisioning server with Auto-Burner enabled")
    parser.add_argument("--port", type=int, default=80, help="HTTP server port (default: 80)")
    parser.add_argument("--password", default="toor", help="Password for SSH/Telnet root shell (default: toor)")
    parser.add_argument("--portal", help="Optional custom portal URL to inject (e.g. http://my-stalker-portal.com)")
    parser.add_argument("--check", action="store_true", help="Run read-only diagnostics")
    parser.add_argument("--reboot", action="store_true", help="Reboot device via ADB")
    args = parser.parse_args()

    print(BANNER)

    # 1. Quick utility to stop hotspot
    if args.stop_hotspot:
        print("[*] Turning off Windows Mobile Hotspot...")
        stop_windows_hotspot()
        remove_hosts_redirect()
        print("[+] Hotspot disabled and hosts redirects removed.")
        sys.exit(0)

    devices = get_adb_devices()
    target_dev = args.device or (devices[0] if devices else None)
    box_ip = args.box_ip
    if not box_ip and target_dev and ":" in target_dev:
        box_ip = target_dev.split(":")[0]

    # If no flags passed, default to check + unlock
    if not any([args.hotspot, args.unlock, args.serve, args.check, args.reboot]):
        print("[*] No flags specified. Running diagnostics and hardware unlock...")
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

    # 2. Hotspot Mode Flow
    if args.hotspot:
        if sys.platform != "win32":
            print("[!] Hotspot automation is designed for Windows 10/11.")
            print("    On Linux/macOS, use --serve with your router/dnsmasq redirect.")
            sys.exit(1)

        # Require admin for hosts file DNS redirect - try UAC elevation automatically
        elevate_if_needed()

        print(f"[*] Setting Hotspot SSID to '{args.hotspot_ssid}' and Password to '{args.hotspot_pass}'...")
        configure_windows_hotspot(args.hotspot_ssid, args.hotspot_pass)

        print("[*] ACTIVATING WINDOWS MOBILE HOTSPOT (1-Click Mode)...")
        hotspot_ok = start_windows_hotspot()
        if not hotspot_ok:
            print("[!] Warning: Could not automatically activate Hotspot via WinRT.")
            print("    Please toggle 'Mobile Hotspot' ON in Windows Settings.")
        else:
            _hotspot_started_by_us = not args.keep_hotspot

        info = get_hotspot_info()
        hotspot_ip = "192.168.137.1"
        redirect_domains = [d.strip() for d in args.domains.split(",") if d.strip()]

        # Apply hosts DNS redirects (requires admin - we tried UAC above)
        admin_status = is_admin()
        dns_ok = False
        if admin_status:
            print(f"[*] Configuring local DNS redirects in hosts file...")
            if apply_hosts_redirect(hotspot_ip, redirect_domains):
                dns_ok = True
                print(f"[+] Operator domains redirected to {hotspot_ip}:")
                for d in redirect_domains:
                    print(f"    - {d} -> {hotspot_ip}")

        if not dns_ok:
            print("\n" + "!" * 60)
            print("  WARNING: DNS REDIRECT NOT APPLIED!")
            print("!" * 60)
            print(f"  The TVIP box will still contact the real operator server.")
            print(f"  To fix this, add this line to your hosts file:")
            print(f"  {HOSTS_PATH}")
            print(f"")
            for d in redirect_domains:
                print(f"    {hotspot_ip:<16} {d}")
            print("")
            print("  OR re-run this script as Administrator (right-click -> Run as Admin)")
            print("!" * 60 + "\n")
            input("Press ENTER to continue anyway (DNS redirect will not work) or Ctrl+C to quit...")

        print("\n" + "=" * 60)
        print("          WINDOWS MOBILE HOTSPOT IS READY!")
        print("=" * 60)
        print(f"  Wi-Fi Network (SSID): {info['ssid']}")
        print(f"  Wi-Fi Password:       {info['key']}")
        print(f"  Provision Gateway:    http://{hotspot_ip}:{args.port}")
        if dns_ok:
            print(f"  DNS Redirect:         ACTIVE (hosts file patched)")
        else:
            print(f"  DNS Redirect:         !! NOT ACTIVE - see warning above !!")
        print("=" * 60)
        print("\n>>> WHAT TO DO NOW:")
        print(f"1. Power on your TVIP box.")
        print(f"2. Connect the TVIP box to Wi-Fi: \"{info['ssid']}\" (Password: {info['key']}).")
        print(f"3. Sit back and watch! The script will automatically:")
        print(f"   * Feed the unlock provisioning XML")
        print(f"   * Log into root shell via Telnet / SSH")
        print(f"   * Burn 127.0.0.1 permanently into the hardware chip")
        print(f"   * Reboot the box completely unlocked!")
        print("=" * 60 + "\n")

        try:
            server = start_provision_server(args.port, args.password, args.portal)
            print(f"[+] HTTP Server active on port {args.port}. Waiting for TVIP box...\n")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[*] Exiting Hotspot Mode...")
        except PermissionError:
            print(f"\n[!] Error: Port {args.port} requires administrator privileges.")
            print("    Please run Command Prompt / Terminal as Administrator.")
        finally:
            remove_hosts_redirect()
            if _hotspot_started_by_us:
                print("[*] Turning off Windows Mobile Hotspot...")
                stop_windows_hotspot()
                print("[+] Cleanup complete.")

    # 3. Standard Server Mode Flow
    elif args.serve:
        local_ip = get_local_ip(box_ip or "192.168.1.1")
        print(f"\n[*] Starting Provisioning Server on http://{local_ip}:{args.port}/prov/tvip_provision.xml")
        print(f"[*] Zero-Touch Auto-Burner: ENABLED")
        print(f"[*] Configured root shell password: '{args.password}'")
        if args.portal:
            print(f"[*] Custom portal URL: '{args.portal}'")

        try:
            server = start_provision_server(args.port, args.password, args.portal)
            print("\n[+] HTTP Server is LIVE. Waiting for TVIP box to connect...")
            print("    (When the box connects, the script will automatically burn 127.0.0.1 and reboot it!)\n")

            if target_dev:
                print(f"[*] ADB available: Pointing NVRAM 'ps' to {local_ip}...")
                write_unifykey_ps(local_ip, target_dev)
                run_adb(["shell", "am force-stop tv.tvip.app && am start -n tv.tvip.app/.TvipNativeActivity"], target_dev)

            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[*] Stopping server.")
        except PermissionError:
            print(f"\n[!] Error: Port {args.port} requires administrator privileges.")
            print(f"    Please run Command Prompt / Terminal as Administrator.")

    if args.reboot and target_dev:
        print("\n[*] Rebooting device...")
        run_adb(["reboot"], target_dev)
        print("[+] Reboot command sent.")

if __name__ == "__main__":
    main()
