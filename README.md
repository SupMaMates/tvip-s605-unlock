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
1. Configure your Windows Hotspot network to **`TVIP-UNLOCK`** with the simplest possible password: **`12345678`** (typed easily with remote number keys 1–8).
2. Turn on Windows Mobile Hotspot.
3. Automatically redirect operator domains (`dreambox.for-better.biz`, `tvipstb.net`, `update.tvip.ru`) to your PC.
4. Launch the custom provisioning server on Port 80 with the **Zero-Touch Auto-Burner** active.

```text
============================================================
          WINDOWS MOBILE HOTSPOT IS READY!
============================================================
  Wi-Fi Network (SSID): TVIP-UNLOCK
  Wi-Fi Password:       12345678
  Provision Gateway:    http://192.168.137.1:80
============================================================
```

### Step 2: Connect the TVIP Box
1. Power on your TVIP box.
2. In the Wi-Fi settings on the TV screen, select **`TVIP-UNLOCK`**.
3. Enter password: **`12345678`** (using the numeric keypad on your TV remote).

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

## 4. Configuring Custom MAG / Stalker Middleware

On Android 8.0 Oreo (build 20221028), TVIP does **not** use an HTML/Web browser or WebView for Stalker portals. Instead, TVIP includes a native C++ client (`15StalkerProtocol`) that connects directly to the portal's REST API endpoint (`/server/load.php`) and renders channels, EPG, and player UI via native hardware-accelerated OpenGL ES.

### A. Step 1: Get Your Device MAC Address
Stalker / Ministra portals authenticate subscriptions by MAC address:
```bash
# Query MAC addresses directly via the suite:
python tvip_s605_unlock.py --get-mac
```
Output:
```text
  Ethernet MAC (eth0):  10:27:BE:24:09:6E
  Wi-Fi MAC (wlan0):     A0:67:20:6C:8E:4C
```
Provide the active MAC address (Ethernet or Wi-Fi, depending on how your box connects) to your IPTV provider to activate your subscription line.

### B. Step 2: Configure the Stalker Portal

#### Option 1: Automatic Injection via Provisioning Feed (`--stalker` / `--mag`)
You can pre-configure your Stalker portal when launching `--hotspot` or `--serve`:
```bash
python tvip_s605_unlock.py --hotspot --stalker "http://YOUR_PORTAL_HOST/c/"
```
The suite automatically builds the native Stalker XML:
```xml
<tv_protocols force="true" default="stalker">
  <protocol type="stalker" url="http://YOUR_PORTAL_HOST/c/" server="http://YOUR_PORTAL_HOST/c/" />
</tv_protocols>
<preferences>
  <pref_tv>
    <stalker_server value="http://YOUR_PORTAL_HOST/c/" />
    <pref_tv_middleware value="stalker" visible="true" />
    <pref_tv_button_midd_setup visible="true" />
  </pref_tv>
</preferences>
```

#### Option 2: Configure via TV Remote Control (On-Screen UI)
1. In the TVIP main screen, go to **Settings** (gear icon) -> **TV**.
2. Set **Content source** to **Stalker** (or *Stalker middleware*).
3. Click the button directly underneath: **Setup Stalker Middleware**.
4. In the dialog, set:
   * **Portal URL:** `http://YOUR_PORTAL_HOST/c/` (or `http://YOUR_PORTAL_HOST/stalker_portal/c/`)
5. Click **Apply**.
6. Return to the home screen and click **Watch TV**.

### C. Step 3: Monitor Connection Handshake (Optional)
To verify the native Stalker handshake in real time:
```bash
python tvip_s605_unlock.py --monitor-stalker
```
Expected log flow on successful connection:
1. `Adding "http://" to portal address...`
2. `JS API version: 331; STB API version: 141; Player Engine version: 0x572`
3. `Constructor. Portal url: http://YOUR_PORTAL_HOST/c/`
4. `GET /server/load.php?type=stb&action=handshake`
5. `GET /server/load.php?type=stb&action=get_profile`
6. `GET /server/load.php?type=itv&action=get_genres`
7. `GET /server/load.php?type=itv&action=get_ordered_list`

### Troubleshooting Stalker Portals
* **"LoadProfile: STB is blocked OR 'enable_mac_format_validation' is enabled on server"**: Provider has not registered your MAC address in their panel, or the subscription has expired. Confirm the exact MAC address from `--get-mac` with your provider.
* **"Stalker portal URL is empty. Can't run protocol"**: Ensure the URL is entered and ends with `/c/`.
* **"Protocol was not created!"**: The protocol type was set to "browser" instead of "stalker". TVIP on Android does not have a browser protocol; use native `stalker`.

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
                           [--hotspot-ssid HOTSPOT_SSID]
                           [--hotspot-pass HOTSPOT_PASS] [--stop-hotspot]
                           [--keep-hotspot] [--domains DOMAINS] [--unlock]
                           [--server-ip SERVER_IP] [--serve] [--port PORT]
                           [--password PASSWORD] [--portal PORTAL]
                           [--stalker STALKER] [--mag MAG] [--get-mac]
                           [--monitor-stalker] [--check] [--reboot]

options:
  --hotspot             1-Click Windows Mobile Hotspot Mode (Zero Router Config)
  --hotspot-ssid        Custom SSID for hotspot (default: TVIP-UNLOCK)
  --hotspot-pass        Custom password for hotspot (default: 12345678)
  --stop-hotspot        Turn off Windows Mobile Hotspot and exit
  --serve               Start provisioning server with Auto-Burner enabled
  --unlock              Perform permanent hardware unlock via NVRAM UnifyKeys
  --stalker, --mag      Inject custom Stalker / MAG portal (e.g. http://my-portal/c/)
  --get-mac             Display Ethernet and Wi-Fi MAC addresses for line activation
  --monitor-stalker     Tail real-time Stalker handshake logs via ADB logcat
  --check               Run read-only diagnostics
  --reboot              Reboot device via ADB
```

---

## License

MIT License. For educational, research, and device ownership / right-to-repair purposes.
