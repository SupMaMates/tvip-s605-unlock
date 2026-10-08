#!/usr/bin/env python3
"""
TVIP S-Box 605 — Hardware Provisioning & Portal Unlock Tool
Neutralizes operator locks permanently via Amlogic NVRAM UnifyKeys.
"""

import argparse
import subprocess
import sys
import time

def run_adb(cmd_list, device=None):
    base = ["adb"]
    if device:
        base.extend(["-s", device])
    full_cmd = base + cmd_list
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def get_devices():
    code, out, _ = run_adb(["devices", "-l"])
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices

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

def main():
    parser = argparse.ArgumentParser(description="TVIP S-Box 605 Hardware UnifyKeys Portal Unlocker")
    parser.add_argument("-s", "--device", help="ADB target device (e.g. 192.168.1.41:5555)")
    parser.add_argument("--server", default="127.0.0.1", help="Target provision server (default: 127.0.0.1 to disable remote lock)")
    parser.add_argument("--check", action="store_true", help="Perform read-only diagnostic check without changes")
    parser.add_argument("--reboot", action="store_true", help="Reboot device after applying changes")
    args = parser.parse_args()

    devices = get_devices()
    if not devices:
        print("[!] Error: No ADB devices found. Ensure device is connected and ADB is running.")
        sys.exit(1)

    target_dev = args.device or devices[0]
    print(f"[*] Target device: {target_dev}")

    info = check_device_info(target_dev)
    print(f"[*] Model: {info.get('ro.product.model')} | Board: {info.get('ro.product.board')}")
    print(f"[*] Android Version: {info.get('ro.build.version.release')} | Build: {info.get('ro.build.display.id')}")
    print(f"[*] SELinux: {info.get('selinux')}")

    current_ps, err = read_unifykey_ps(target_dev)
    if current_ps is None:
        print(f"[!] Failed to read unifykeys: {err}")
        sys.exit(1)

    print(f"[*] Current NVRAM UnifyKey 'ps': '{current_ps}'")

    if args.check:
        if current_ps in ("127.0.0.1", "localhost"):
            print("[+] STATUS: Device is already UNLOCKED (provisioning disabled).")
        else:
            print(f"[!] STATUS: Device is LOCKED to operator server: {current_ps}")
        return

    if current_ps == args.server:
        print(f"[+] NVRAM 'ps' is already set to '{args.server}'.")
    else:
        print(f"[*] Writing '{args.server}' to Amlogic NVRAM UnifyKeys key 14 ('ps')...")
        ok, err = write_unifykey_ps(args.server, target_dev)
        if not ok:
            print(f"[!] Failed to write key: {err}")
            sys.exit(1)

        readback, _ = read_unifykey_ps(target_dev)
        if readback != args.server:
            print(f"[!] Verification failed: Expected '{args.server}', read '{readback}'")
            sys.exit(1)
        print(f"[+] Success: Hardware key verified as '{readback}'.")

    print("[*] Resetting tv.tvip.app application state to factory defaults...")
    if clear_tvip_data(target_dev):
        print("[+] tv.tvip.app data cleared successfully.")
    else:
        print("[!] Warning: Could not clear app data. You may need to clear it manually in Android Settings.")

    if args.reboot:
        print("[*] Rebooting device...")
        run_adb(["reboot"], target_dev)
        print("[+] Reboot command sent.")

    print("\n[+] UNLOCK COMPLETE: The operator lock has been neutralized.")
    print("    You can now navigate on the TV screen to Settings -> TV -> Content source")
    print("    and configure your custom IPTV / MAG / Stalker / M3U portal.")

if __name__ == "__main__":
    main()
