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

   <!-- Operator forced OS switch -->
   <update_types>
     <device id="s605" force_type="release" force_os="linux-qt" />
   </update_types>
   ```
4. **Why local file modifications failed previously:** Any local edits to `/data/data/tv.tvip.app/` were overwritten immediately because the app phoned home to `ps` on every startup and re-applied the operator restrictions.

---

## 3. Why Root Access Is Not Required

On standard Android mobile devices, writing to `/sys/` is strictly blocked by Linux permissions (`0600`) and SELinux enforcement (`avc: denied`).

On TVIP's official Android 8.0 firmware for the S-Box 605:
1. **World-Writable Kernel Driver:** The Amlogic unifykey sysfs interface has world-writable permissions (`-rw-rw-rw-` / `0666`), allowing any user—including the standard ADB `shell` user (`uid=2000`)—to write to the keys.
2. **SELinux in Permissive Mode:** `getenforce` returns `Permissive`. SELinux does not enforce Mandatory Access Control restrictions against the ADB shell.
3. **Design Intent:** The TVIP app itself runs as an unprivileged user (`u0_a37`). TVIP left sysfs accessible so their application and factory flashing tools could read and write device identifiers (MAC address, serial number, provision URL) without needing root privileges.

---

## 4. Permanent Unlock Procedure

### Prerequisites
* Enable USB Debugging or Network ADB on your TVIP box.
* Connect via ADB:
  ```powershell
  adb connect 192.168.1.41:5555  # Replace with your TVIP IP address
  ```

---

### Method A: Automated Python Tool (Recommended)

Run the included unlock script:
```bash
# Check device state without making changes:
python tvip_s605_unlock.py --check

# Permanently neutralize the operator lock and reboot:
python tvip_s605_unlock.py --server 127.0.0.1 --reboot
```

---

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

> **Note on Mutex Locking:** Always ensure `echo 0 > /sys/class/unifykeys/lock` is executed to release the kernel mutex lock after writing.

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
* **Android factory resets:** Amlogic UnifyKeys resides in a separate raw NVRAM/eMMC key partition (`/dev/block/param` / `cri_data`) unaffected by `/data` user data wipes.

### Additional Safeguard: Preventing Forced Linux-QT Updates
Because the operator provisioning server is neutralized to `127.0.0.1`, the device will **never** receive the instruction `<device id="s605" force_os="linux-qt" />`. Your Android 8.0 OS installation is completely protected from unwanted provider firmware changes.

---

## 7. Rollback / Emergency Recovery

### Software Rollback (Restore Original Operator)
If you ever need to restore the original operator configuration:
```bash
adb shell "echo 1 > /sys/class/unifykeys/attach && echo 1 > /sys/class/unifykeys/lock && echo ps > /sys/class/unifykeys/name && echo dreambox.for-better.biz > /sys/class/unifykeys/write && echo 0 > /sys/class/unifykeys/lock"
adb shell pm clear tv.tvip.app
```

### Hardware Recovery (AV Jack Toothpick Method)
If the device ever fails to boot or becomes unresponsive:
1. Disconnect the power cable.
2. Insert a toothpick or non-conductive pin into the **AV jack** on the rear panel until you feel the physical reset switch depress.
3. Hold the switch down while reconnecting power.
4. Continue holding for 8–10 seconds until the Android Recovery screen appears.
5. Select **Wipe data / factory reset** to return to clean factory defaults.
