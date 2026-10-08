# TVIP S-Box 605 — Permanent Hardware Unlock & Root Provisioning Suite

A complete technical guide, reverse-engineering reference, and automated unlock suite for the **TVIP S-Box v.605** (Amlogic S905X running TVIP Linux-QT or Android 8.0 firmware).

This tool permanently neutralizes the operator lock by reprogramming the **Amlogic NVRAM UnifyKeys** subsystem, opening Dropbear SSH / Telnet root shells, and unlocking all hidden TV preference menus without requiring soldering or third-party ROM flashing.

---

## 1. Quick Start: 1-Click Windows Hotspot Unlock (Zero Router Config)

The simplest and most elegant way to unlock a brand-new or operator-locked TVIP S-Box 605:

### Step 1: Run the suite on your Windows PC
Open Command Prompt or PowerShell (as Administrator) and run:

```bash
python tvip_s605_unlock.py --hotspot
```

The script will automatically:
1. Turn on Windows Mobile Hotspot.
2. Display your PC's Wi-Fi network name (SSID) and Password.
3. Automatically redirect operator domains (`dreambox.for-better.biz`, `tvipstb.net`, `update.tvip.ru`) to your PC.
4. Launch the custom provisioning server on Port 80 with the **Zero-Touch Auto-Burner** active.

```text
============================================================
          WINDOWS MOBILE HOTSPOT IS READY!
============================================================
  Wi-Fi Network (SSID): DESKTOP-XXXXXX 0915
  Wi-Fi Password:       4<95Tg56
  Provision Gateway:    http://192.168.137.1:80
============================================================
```

### Step 2: Connect the TVIP Box
1. Power on your TVIP box.
2. On the TV screen, connect to the displayed Wi-Fi network.

### Step 3: Done!
As soon as the TVIP box connects:
* Your PC serves the custom `tvip_provision.xml`.
* All hidden GUI menus ("Content source", "Setup", etc.) unlock instantly on your TV screen.
* The **Zero-Touch Auto-Burner** connects via Telnet / SSH, burns `127.0.0.1` permanently into the Amlogic hardware chip (Key `ps`), wipes operator cache, and reboots the box.
* The operator lock is erased forever!

---

## 2. Alternative Methods

### Method B: Home Wi-Fi / Router DNS Redirect (`--serve`)
If you prefer using your existing home router, Pi-hole, or pfSense:
1. Start the provisioning server:
   ```bash
   python tvip_s605_unlock.py --serve --password toor
   ```
2. On your router or DNS server, point the operator domain (e.g. `dreambox.for-better.biz`) to your computer's local IP (e.g. `192.168.1.XX`).
3. Power on the box. The server feeds the unlock configuration, automatically logs in via root Telnet/SSH, burns `127.0.0.1`, and reboots.

### Method C: Direct ADB Unlock (`--unlock`)
If ADB is enabled on the device (Android firmware or Linux-QT with ADB):
```bash
# Connect to box:
adb connect <TVIP_IP>:5555

# Apply permanent hardware unlock:
python tvip_s605_unlock.py --unlock --reboot
```

---

## 3. Reverse Engineering Findings & Technical Architecture

### A. The Lock Mechanism: Amlogic UnifyKeys
Inside `libtvipstb.so` and `tvip_daemon`, the firmware communicates directly with the Amlogic hardware key storage subsystem in the Linux sysfs tree:
```text
/sys/class/unifykeys/
```
* **Key Index 14 (`ps`)**: Stands for **Provision Server**.
* On locked operator devices, this key contains the operator's provisioning hostname (e.g. `dreambox.for-better.biz`).
* On every boot and network reconnection, the TVIP daemon queries `http://<ps>/prov/tvip_provision.xml` and locks down the interface:
  ```xml
  <preferences>
    <pref_tv>
      <pref_tv_middleware visible="false" />
      <pref_tv_button_midd_setup visible="false" />
      <pref_tv_streamtype visible="false" />
    </pref_tv>
  </preferences>
  ```
Because `ps` is stored in the raw eMMC hardware partition, modifying local files on Android/Linux fails because the box re-fetches the operator XML on each reboot.

### B. Linux-QT Root Shell Discovery
Reverse engineering of the official release package (`tvip_firmware.signed.ota.zip`, Linux-QT build `5.0.101`) revealed that:
* **Dropbear SSH** (`/usr/sbin/dropbear`) and **Telnet** (`telnetd`) are pre-installed in `system.img`.
* Both init scripts (`/etc/init.d/S50dropbear` and `/etc/init.d/S50telnetd`) activate when `/var/tvip/password` exists.
* The provision XML parser creates `/var/tvip/password` when `<system_locks><shell password="..." /></system_locks>` is present.
* By serving this XML, root Dropbear SSH (Port 22) and Telnet (Port 23) open instantly with the password of your choice!

### C. The Permanent Neutralization Command
Once inside the root shell, burning `127.0.0.1` into Key `ps` permanently stops the box from ever calling the operator server:
```bash
echo 1 > /sys/class/unifykeys/attach && \
echo 1 > /sys/class/unifykeys/lock && \
echo ps > /sys/class/unifykeys/name && \
echo 127.0.0.1 > /sys/class/unifykeys/write && \
echo 0 > /sys/class/unifykeys/lock && \
rm -rf /var/tvip/* && \
sync && \
reboot
```

---

## 4. Configuring Your Custom IPTV / Stalker / MAG Portal

Once unlocked, the TVIP box runs in unrestricted factory mode:
1. From the TVIP home screen, navigate to **Settings -> TV**.
2. Under **Content source**, select your desired mode:
   * **IPTV-portal:** Enter Login, Password, and Server URL.
   * **Middleware API:** Enter TVIP JSON API server URL.
   * **M3U-playlist:** Enter custom M3U playlist and XMLTV EPG URL.
   * **Android app:** Launch external players (TiviMate, OTT Navigator, etc.).
3. Click **Setup [source]** to save your credentials.

Optional: You can also pre-inject your portal directly into the provisioning feed:
```bash
python tvip_s605_unlock.py --hotspot --portal "http://your-stalker-portal.com"
```

---

## 5. Verification & Persistence

* **Survives cold reboots & power loss:** NVRAM UnifyKeys is non-volatile hardware storage.
* **Survives factory resets:** Factory reset wipes `/data` and `/cache`, leaving the Amlogic NVRAM key partition intact.
* **Survives firmware updates:** Key `ps` remains `127.0.0.1`.

### Restoring Operator Configuration (Rollback)
If you ever wish to re-lock the box to an operator:
```bash
adb shell "echo 1 > /sys/class/unifykeys/attach && echo 1 > /sys/class/unifykeys/lock && echo ps > /sys/class/unifykeys/name && echo dreambox.for-better.biz > /sys/class/unifykeys/write && echo 0 > /sys/class/unifykeys/lock"
adb shell pm clear tv.tvip.app
```

---

## 6. CLI Reference

```text
usage: tvip_s605_unlock.py [-h] [-s DEVICE] [--box-ip BOX_IP] [--hotspot]
                           [--stop-hotspot] [--keep-hotspot]
                           [--domains DOMAINS] [--unlock]
                           [--server-ip SERVER_IP] [--serve] [--port PORT]
                           [--password PASSWORD] [--portal PORTAL] [--check]
                           [--reboot]

options:
  --hotspot             1-Click Windows Mobile Hotspot Mode (Zero Router Config)
  --stop-hotspot        Turn off Windows Mobile Hotspot and exit
  --keep-hotspot        Do not turn off hotspot upon exit
  --domains DOMAINS     Comma-separated domains to redirect (default: dreambox.for-better.biz,...)
  --serve               Start provisioning server with Auto-Burner enabled
  --unlock              Perform permanent hardware unlock via NVRAM UnifyKeys
  --password PASSWORD   Password for SSH/Telnet root shell (default: toor)
  --portal PORTAL       Optional custom portal URL to inject
  --check               Run read-only diagnostics
  --reboot              Reboot device via ADB
```

---

## License

MIT License. For educational, research, and device ownership / right-to-repair purposes.
