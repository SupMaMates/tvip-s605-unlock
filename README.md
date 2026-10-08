# TVIP S-Box 605 — Provider Portal Lock Investigation & Permanent Neutralization Guide

A comprehensive technical guide and reference on how the operator portal lock is enforced on the **TVIP S-Box v.605** (Amlogic S905X running official TVIP Android 8.0 firmware), and how to permanently remove it via the Amlogic NVRAM UnifyKeys subsystem without rooting or reflashing.

---

## 1. Overview & Problem Statement

The **TVIP S-Box 605** is a hybrid IPTV/OTT set-top box built on the **Amlogic S905X** SoC. Many units are shipped pre-configured by IPTV operators running customized Linux-QT or Android firmware.

When running the official TVIP Android 8.0 firmware:
* The system boots into the TVIP home launcher.
* The original provider's portal (e.g. `IPTV-2026`) remains locked into the firmware.
* In **Settings -> TV**, the **"Content source"** dropdown and the **"Setup"** buttons are completely hidden from the user interface.
* Editing local application XML files or restoring backups via `adb restore` temporarily changes settings, but **reverts automatically upon reboot or internet connection**.

---

## 2. Reverse Engineering Findings

By extracting and disassembling the core TVIP application binaries (`/system/app/Tvip/Tvip.apk`, `/system/lib/libtvip.so`, and `/system/lib/libtvipstb.so`), the exact locking mechanism was traced:

### A. Hardware Key Storage: Amlogic UnifyKeys
Inside `libtvipstb.so`, the native class method `STBKeyValueStorage::get("ps")` communicates directly with the Linux sysfs interface for Amlogic NVRAM hardware key storage:
```text
/sys/class/unifykeys/
```
In the normal eMMC key partition:
* **Key Index 14 (`ps`)** stands for **Provision Server**.
* On locked operator devices, this key contains the operator's provisioning hostname (e.g., `dreambox.for-better.biz`).

### B. Remote Provisioning Loop
On every startup and network reconnection of `tv.tvip.app`:
1. The app reads key `ps` from the Amlogic NVRAM chip.
2. It sends an HTTP GET request to:
   ```text
   http://<ps>/prov/tvip_provision.xml
   ```
3. The downloaded provisioning XML instructs the TVIP native engine to lock down the device:
   ```xml
   <tv_protocols default="browser"> 
     <protocol type="browser" server="http://[OPERATOR_PORTAL_URL]" api="mag" noui="false" combined="true" />
   </tv_protocols> 

   <preferences>
     <pref_tv>
       <pref_tv_middleware visible="false" />
       <pref_tv_button_midd_setup visible="false" />
       <pref_tv_streamtype visible="false" />
       <pref_tv_udpxyaddress visible="false" />
       <pref_tv_dvr_deviceid visible="false" />
       <pref_tv_timeshift_deviceid visible="false" />
       <pref_tv_autotimeshift visible="false" />
     </pref_tv>
   </preferences>
   ```
4. **Why local file modifications failed previously:** Any local edits to `/data/data/tv.tvip.app/` were overwritten immediately because the app phoned home to `ps` on every startup and re-applied the operator restrictions.

---

## 3. Why Root Access Is Not Required

On standard Android mobile devices, writing to `/sys/` is strictly blocked by Linux permissions (`0600`) and SELinux enforcement (`avc: denied`).

On TVIP's official Android 8.0 firmware for the S-Box 605:
1. **World-Writable Kernel Driver:** The Amlogic unifykey sysfs interface has world-writable permissions (`-rw-rw-rw-` / `0666`), allowing any user—including the standard ADB `shell` user (`uid=2000`)—to write to the keys.
2. **SELinux in Permissive Mode:** `getenforce` returns `Permissive`. SELinux does not enforce Mandatory Access Control restrictions against the ADB shell.
3. **Design Intent:** The TVIP app itself runs as an unprivileged user (`u0_a23`). TVIP left sysfs accessible so their application and factory flashing tools could read and write device identifiers (MAC address, serial number, provision URL) without needing root privileges.

---

## 4. Permanent Unlock Procedure

### Method A: Automated All-in-One Python Suite (Recommended)

Run the included all-in-one suite directly from this repository:

```bash
# 1. Run read-only diagnostics (checks ADB, UnifyKeys, and network ports):
python tvip_s605_unlock.py --check

# 2. Permanent Hardware Unlock (neutralizes NVRAM lock & wipes app cache):
python tvip_s605_unlock.py --unlock --reboot

# 3. Linux-QT & Android Provision Server Mode (serves XML, unlocks UI, enables SSH/Telnet root shell):
python tvip_s605_unlock.py --serve --password toor

# 4. Optional: inject your custom Stalker / MAG portal directly into the provisioning feed:
python tvip_s605_unlock.py --serve --portal "http://your-stalker-portal.com"
```

---

## 5. Linux-QT Firmware: Root Shell Activation

Inside `system.img` of the TVIP Linux-QT firmware, **Dropbear (SSH)** and **Telnet** are pre-installed. The startup scripts (`/etc/init.d/S50dropbear` and `/etc/init.d/S50telnetd`) activate automatically when `/var/tvip/password` exists.

This file is created automatically when `tvip_provision.xml` contains the `<shell>` tag:
```xml
<system_locks>
  <shell password="YOUR_ROOT_PASSWORD" />
</system_locks>
```

Running `python tvip_s605_unlock.py --serve --password toor` generates this configuration and hosts it on port 80. Once the box boots and checks in:
1. It downloads the XML and generates the password.
2. Dropbear SSH (Port 22) and Telnet (Port 23) launch automatically.
3. You can log into a root Linux shell immediately:
   ```bash
   ssh root@<TVIP_IP>
   # or
   telnet <TVIP_IP>
   # Password: toor
   ```


### Method B: Manual ADB Commands

If you prefer executing the raw ADB shell commands:

#### Step 1: Reprogram Amlogic NVRAM UnifyKey `ps`
Write loopback `127.0.0.1` to key `ps`:
```bash
adb shell "echo 1 > /sys/class/unifykeys/attach && echo 1 > /sys/class/unifykeys/lock && echo ps > /sys/class/unifykeys/name && echo 127.0.0.1 > /sys/class/unifykeys/write && echo 0 > /sys/class/unifykeys/lock"
```

Verify that the key updated:
```bash
adb shell "echo 1 > /sys/class/unifykeys/attach && echo ps > /sys/class/unifykeys/name && cat /sys/class/unifykeys/read"
# Expected output: 127.0.0.1
```

#### Step 2: Clear Application Data & Cached Operator Config
```bash
adb shell pm clear tv.tvip.app
```

#### Step 3: Complete Factory Wizard (Once)
On the TV screen with the remote control:
1. Select language (e.g. English).
2. Network setup: (Already connected / Skip).
3. Software update: Skip.
4. Timezone: Select your timezone.
5. Display overscan: Confirm.

---

## 5. Configuring Your Custom IPTV / Stalker / MAG Portal

Once unlocked, the TVIP app runs in its unrestricted factory mode:
1. From the TVIP home screen, navigate down to the **Settings** row and select **TV**.
2. Navigate down to **Content source:** (press Left/Right on your remote control to cycle through options):
   * **IPTV-portal:** Enter Login, Password, and Server URL.
   * **Middleware API:** Enter custom TVIP JSON API server URL.
   * **M3U-playlist:** Enter custom M3U playlist URL and XMLTV EPG URL.
   * **Android app:** Select an external installed player (e.g. TiviMate, OTT Navigator).
3. Select **Setup [chosen source]** and enter your credentials.

---

## 6. Verification & Persistence

This modification is **permanent** and survives:
* Cold reboots and power disconnections.
* Internet reconnections across Ethernet and Wi-Fi.
* Clearing application cache or reinstalling apps.
* Android factory resets (Amlogic UnifyKeys resides in a separate raw NVRAM/eMMC partition unaffected by user data wipes).

### Rollback / Restoring Operator Configuration
If you ever need to restore the original operator configuration:
```bash
adb shell "echo 1 > /sys/class/unifykeys/attach && echo 1 > /sys/class/unifykeys/lock && echo ps > /sys/class/unifykeys/name && echo dreambox.for-better.biz > /sys/class/unifykeys/write && echo 0 > /sys/class/unifykeys/lock"
adb shell pm clear tv.tvip.app
```
