#!/usr/bin/env python3
"""
TVIP S-Box 605 — Hardware Provisioning & Portal Unlock Tool
Permanent operator lockout neutralization via Amlogic NVRAM UnifyKeys.
Author: SupMaMates
Repository: https://github.com/SupMaMates/tvip-s605-unlock
"""

import argparse
import subprocess
import sys
import time


def run_adb(cmd_list, device=None):
    """Execute an ADB command and return (returncode, stdout, stderr)."""
    base = ["adb"]
    if device:
        base.extend(["-s", device])
    full_cmd = base + cmd_list
    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=15)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -2, "", "adb executable not found in PATH"


def get_connected_devices():
    """Return a list of connected and authorized ADB device IDs."""
    code, out, _ = run_adb(["devices", "-l"])
    if code != 0:
        return []
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def get_device_info(device=None):
    """Query core device properties via getprop."""
    props_to_query = [
        ("Model", "ro.product.model"),
        ("Board", "ro.product.board"),
        ("Android Version", "ro.build.version.release"),
        ("Firmware Build", "ro.build.display.id"),
        ("Build Fingerprint", "ro.build.fingerprint"),
        ("SELinux Status", "None"),
    ]
    info = {}
    for label, prop in props_to_query:
        if prop == "None":
            _, out, _ = run_adb(["shell", "getenforce"], device)
            info[label] = out
        else:
            _, out, _ = run_adb(["shell", f"getprop {prop}"], device)
            info[label] = out
    return info


def read_unifykey_ps(device=None):
    """Read the current value of the Amlogic NVRAM UnifyKey 'ps' (Provision Server)."""
    shell_cmd = (
        "echo 1 > /sys/class/unifykeys/attach && "
        "echo ps > /sys/class/unifykeys/name && "
        "cat /sys/class/unifykeys/read"
    )
    code, out, err = run_adb(["shell", shell_cmd], device)
    if code != 0 or not out:
        return None, err
    return out.strip(), None


def write_unifykey_ps(new_value, device=None):
    """Write a new value to the Amlogic NVRAM UnifyKey 'ps' with mutex locking."""
    shell_cmd = (
        "echo 1 > /sys/class/unifykeys/attach && "
        "echo 1 > /sys/class/unifykeys/lock && "
        "echo ps > /sys/class/unifykeys/name && "
        f"echo {new_value} > /sys/class/unifykeys/write && "
        "echo 0 > /sys/class/unifykeys/lock"
    )
    code, _, err = run_adb(["shell", shell_cmd], device)
    if code != 0:
        return False, err
    # Verify the write
    verified_val, _ = read_unifykey_ps(device)
    if verified_val != new_value:
        return False, f"Verification failed: expected '{new_value}', got '{verified_val}'"
    return True, None


def clear_tvip_app_data(device=None):
    """Purge cached operator configuration and private files."""
    code, out, err = run_adb(["shell", "pm clear tv.tvip.app"], device)
    return code == 0 and "Success" in out


def restart_device(device=None):
    """Reboot the target device."""
    run_adb(["reboot"], device)


def main():
    parser = argparse.ArgumentParser(
        description="TVIP S-Box 605 — Permanent Hardware Provisioning & Portal Unlock Tool"
    )
    parser.add_argument(
        "-s", "--device",
        help="Target ADB device serial or IP:port (e.g. 192.168.1.41:5555)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Inspect device state and check current NVRAM Provision Server key"
    )
    parser.add_argument(
        "--server",
        default="127.0.0.1",
        help="Provision server to write into NVRAM (default: 127.0.0.1 for complete neutralization)"
    )
    parser.add_argument(
        "--restore",
        metavar="ORIGINAL_HOST",
        help="Restore a specific operator provision hostname (e.g. dreambox.for-better.biz)"
    )
    parser.add_argument(
        "--reboot",
        action="store_true",
        help="Reboot the set-top box after completing the operation"
    )

    args = parser.parse_args()

    # Detect devices
    devices = get_connected_devices()
    if not devices:
        print("[!] Error: No connected ADB devices found. Ensure ADB is connected and authorized.")
        sys.exit(1)

    target_device = args.device or devices[0]
    print(f"[*] Target Device: {target_device}")

    # Read hardware state
    info = get_device_info(target_device)
    current_ps, err = read_unifykey_ps(target_device)

    print("\n--- Device Identification ---")
    for k, v in info.items():
        print(f"  {k:18}: {v}")
    print(f"  {'Current NVRAM ps':18}: {current_ps or f'Error reading key ({err})'}")

    is_locked = current_ps and current_ps not in ("127.0.0.1", "0.0.0.0", "localhost")
    if is_locked:
        print(f"\n[!] Status: LOCKED to operator provisioning server [{current_ps}]")
    else:
        print(f"\n[+] Status: UNLOCKED / NEUTRALIZED (ps = {current_ps})")

    # If only checking, exit cleanly
    if args.check and not args.restore and args.server == "127.0.0.1" and not args.reboot:
        print("\n[*] Inspection complete. No modifications applied.")
        sys.exit(0)

    # Determine desired action
    new_server = args.restore if args.restore else args.server
    action_desc = "Restoring operator key" if args.restore else "Neutralizing operator lock"

    print(f"\n[*] {action_desc} -> Writing '{new_server}' to Amlogic NVRAM UnifyKey 'ps'...")
    success, write_err = write_unifykey_ps(new_server, target_device)
    if not success:
        print(f"[!] Error writing NVRAM key: {write_err}")
        sys.exit(1)
    print(f"[+] NVRAM Key 'ps' successfully written and verified: {new_server}")

    # Clear application data
    print("[*] Clearing cached operator configuration (pm clear tv.tvip.app)...")
    if clear_tvip_app_data(target_device):
        print("[+] Cached application data and operator overrides purged successfully.")
    else:
        print("[!] Warning: 'pm clear' returned an unexpected status, but NVRAM key is updated.")

    if args.reboot:
        print("[*] Rebooting TVIP set-top box...")
        restart_device(target_device)
        print("[+] Reboot signal sent.")
    else:
        print("\n[+] Done! You can now launch TVIP on your TV screen.")
        print("[+] First-time wizard will run once, after which all portal and setup menus are unlocked.")


if __name__ == "__main__":
    main()
