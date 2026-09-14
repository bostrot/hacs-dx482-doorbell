# 2easy / V-Tec DX482 Video Doorbell — local Home Assistant integration

A **fully local, cloud-free** integration for the 2easy (Video-Tech / V-Tec) **DX482**
Wi-Fi video doorbell. Home Assistant takes the place of the vendor's cloud, so
ring detection, live video, snapshots and door unlock all work on your LAN with no
internet and no VDP Connect app.

- **Ring** — `event` entity and a momentary `binary_sensor`, fired the instant the button is pressed.
- **Live video & snapshots** — `camera` entity (H.264 from the doorbell, on demand).
- **Door unlock** — `button` entities for relay 1 (and 2), plus light and hang-up.
- **Diagnostics** — doorbell connected, call active, session state, last ring.

> Tested on DX482 firmware with Linphone 3.6.1. Requires Home Assistant 2024.12+.

---

## How it works (and why)

The DX482 is not a standard SIP doorbell. It only accepts control commands and only
streams video through the **vendor media proxy** it dials into during a call, and
it finds that proxy at its configured SIP server address. So this integration
impersonates the vendor cloud on your LAN:

| Doorbell expects | Home Assistant provides |
|---|---|
| SIP registrar at `[server]` udp/5068 | a minimal registrar (answers REGISTER) |
| media proxy at `[server]` tcp/8850 during calls | a proxy that logs the doorbell in and sends its control frames |
| somewhere to push H.264 RTP | a UDP video port, fanned out to ffmpeg for MJPEG live view and JPEG stills |

A ring is simply the doorbell calling the phone account through "the cloud" (us).
Video/unlock sessions are started by Home Assistant calling the doorbell directly.
The wire protocol was reverse-engineered from the VDP Connect app and verified against
a captured real cloud session; details are in `vdp.py`.

## Supported devices

| Status | Device |
|---|---|
| Confirmed | 2easy / V-Tec **DX482** Wi-Fi monitor |

### Possibly working, not confirmed

The integration does not depend on anything DX482-specific: it impersonates the
**VDP Connect** cloud (SIP registrar on udp/5068, media proxy on tcp/8850) and reads
`sipcfg.cfg` over root FTP. Any Video-Tech unit that uses the VDP Connect app and
points at the same vendor server should behave the same. None of these have been
tested; reports (firmware version plus a sanitised `sipcfg.cfg`) are very welcome.

| Device | Notes |
|---|---|
| CDVI **CDV-47DX**, **CDV-470DX** | CDVI's UK rebrand of the 2easy Wi-Fi monitors. Manual names VDP Connect, a SIP config section and call divert. Most likely to work as-is. |
| 2easy **DX471**, **DX470**, **DX47**, **DX439** | Previous-generation 2-wire Wi-Fi monitors. Firmware V1.8+ switched to VDP Connect with the "new media transmit protocol", which is what this integration speaks. Older firmware may still use plain SIP and will not work. |
| 2easy **DH473** (VDP Connect variant) | 2025 hybrid 2-wire + IP monitor. Creates two SIP accounts (monitor and app), matching the `[account]` / `[divert]` setup fields. The Tuya variant will not work. |
| 2easy-IX **IX471S**, **IX482** | Ethernet IP monitors supported by VDP Connect from firmware V1.8.1. The IX system runs its own LAN SIP server, so the server address, ports and config path may differ. |
| Same units sold by Intelligent Home Online, DVC, 2easy.com.gr and other resellers | Different model numbers, identical hardware and firmware. |

Quick check for an untested unit: root FTP login with an empty password works,
`/mnt/nand1-2/Settings/sipcfg.cfg` exists with `[server]` pointing at `47.91.88.33:5068`,
and the vendor app is VDP Connect. Jeatone, Anjielosmart and other Tuya-based
intercoms are a different platform and are not candidates.

## Installation

1. HACS → Integrations → ⋮ → **Custom repositories** → add this repo, category *Integration*.
2. Install **2easy DX482 Video Doorbell**, restart Home Assistant.
3. Settings → Devices & services → **Add integration** → *2easy / V-Tec DX482*.

### Setup fields

| Field | Where to find it |
|---|---|
| Doorbell IP address | your router / DHCP reservation |
| This Home Assistant host's LAN IP | pre-filled; must be reachable by the doorbell |
| Doorbell SIP account | `[account]` in the doorbell's `sipcfg.cfg`, e.g. `64000002db48` |
| Phone/divert SIP account | `[divert]` in `sipcfg.cfg`, e.g. `6e000002db48` |
| Monitor code | the door station's *moncode* from the VDP Connect QR/account (commonly `0x34`) |

`sipcfg.cfg` lives at `/mnt/nand1-2/Settings/sipcfg.cfg` on the doorbell (FTP or telnet, user `root`, empty password).

### Point the doorbell at Home Assistant (one-time)

Edit `/mnt/nand1-2/Settings/sipcfg.cfg` on the doorbell and replace the vendor
server address (`47.91.88.33`) with your Home Assistant IP in these lines, then reboot it:

```
[server]     = <HA-IP>:5068
[serverIp]   = <HA-IP>:5068
[VTK_AUTO_REG_SERVER_IPADD2] = <HA-IP>
[VTK_AUTO_REG_SERVER_IP2]    = <HA-IP>:5068
```

Keep a copy of the original file. Restoring it (and rebooting) returns the doorbell
to the vendor cloud and the VDP Connect app. While pointed at Home Assistant the
phone app does not work; use Home Assistant notifications and the camera instead.

The "Doorbell connected" sensor turns on once the doorbell has registered.

## Entities

| Entity | Notes |
|---|---|
| `camera` | On demand: opening the view or taking a snapshot starts a call, logs the doorbell into the proxy and starts video. The call ends after the idle timeout (default 30 s) once nobody is watching. |
| `button` Open door / Open door 2 | Relay pulse. Starts a short call if none is active. |
| `button` Light | Door-station light (if fitted). Disabled by default. |
| `button` Hang up | Ends the current call. Disabled by default. |
| `event` Doorbell | `ring` |
| `binary_sensor` Ringing | On for 5 s after a press |
| `binary_sensor` Call / Doorbell connected | Session and registration state |
| `sensor` Session / Last ring | `idle`, `in_call`, `streaming`; timestamp of last ring |

### Doorbell settings from Home Assistant

The doorbell stores its own settings in `/mnt/nand1-2/Settings/io_data_value.json`
and only reads them at boot. The integration edits that file over the doorbell's
FTP service (`root`, empty password) and can reboot it over telnet, so these show up
as **number** entities under the device's Configuration section:

| Entity | Firmware parameter | Default |
|---|---|---|
| Unlock time / Unlock 2 time | `UNLOCK1_TIMING` / `UNLOCK2_TIMING` | 5 s |
| Monitor time limit | `MONITOR_TIME_LIMIT` (max length of a video call) | 30 s |
| Divert delay | `DivertTime` (how long the indoor monitor rings before the doorbell calls Home Assistant) | 30 s |
| Day / night call volume, Talk volume, Microphone / Speaker volume | `*_VOLUME*` | |
| Doorbell tune, Ring duration | `DOORBELL_TUNE_SELECT`, `CALL_TUNE_TIME_LIMIT` | |
| **Auto unlock** (switch) + start/end hour | `AutoUnlockIo`, `AutoUnlockStartTime`, `AutoUnlockEndTime` (doorbell opens the door by itself during those hours) | off |
| Auto close after unlock (switch) | `AutoCloseAfterUnlock` | off |

Changing a value writes it immediately; the **Reboot required** sensor turns on and the
**Reboot doorbell** button applies it (the doorbell is offline for about two minutes).
Values are re-read when the doorbell registers again. Set **Divert delay** low (e.g. 5 s)
if you want ring events to reach Home Assistant quickly.

Two more buttons (disabled by default) automate the one-time server change described
above: **Point doorbell at Home Assistant** rewrites `sipcfg.cfg` to this host (keeping a
backup) and **Restore vendor cloud** puts the original back. Press **Reboot doorbell**
after either.

### Call mode (divert) from Home Assistant

The doorbell's call-handling mode is a **Call mode** select entity (firmware
`CallScene_SET`): Normal, Do-not-disturb 8h, Do-not-disturb always, Divert if no
answer, **Divert always**. Set it to **Divert always** so a button press is
forwarded to Home Assistant over SIP the instant it happens (real push, no polling).
This applies live, without a reboot. It is the same setting as the doorbell's on-screen
*Anrufeinstellungen → "Anruf immer weiterleiten"*.

### Ring detection without divert (call-log polling)

The doorbell only sends a SIP call to Home Assistant when its **divert** mode is on,
and that mode is buried in the installer menu. If you can't or don't want to enable it,
turn on **Ring detection via call log** in the integration's options. Home Assistant
then watches the doorbell's own call-record table over FTP and fires the ring event
(and your notification) whenever the door station is pressed. It needs no device-menu
change and no cloud. Trade-off: a few seconds of latency (the poll interval, default 3 s)
and light extra load on the doorbell. Live video and unlock still work on demand.

If you later enable divert on the doorbell, the instant SIP path takes over and you can
switch this off.

### Auto-answer on ring

Off by default. When enabled (Configure → options), a ring is answered immediately so
the camera and unlock are usable during the ring. The doorbell then behaves as if a
phone picked up.

### Ring chime on speakers

The integration ships a small set of chime sounds and, on startup, copies them into
`<config>/www/dx482/` so Home Assistant serves them at `/local/dx482/<name>.mp3`
(`ding_dong`, `doorbell`, `bright`, `chord`, `marimba`, `glockenspiel`, `bells`).
Each chime is one to three seconds long, which is easy to miss. Every chime also ships
as a `<name>_ring.mp3` variant that repeats the chime with a short pause for just over
30 seconds, so one `play_media` call rings the speakers for the whole time a visitor
would keep pressing the button. Use `ding_dong_ring`, `marimba_ring`, and so on.
Google Cast speakers only play audio from a URL they can reach, which on an isolated
IoT network means Home Assistant's own IP, so play the chime by absolute URL:

```yaml
- action: media_player.play_media
  target:
    entity_id: media_player.google_home
  data:
    media_content_id: "http://<HA-IP>:8123/local/dx482/ding_dong_ring.mp3"
    media_content_type: music
```

## Example automation

```yaml
automation:
  - alias: "Doorbell ring — notify with snapshot"
    triggers:
      - trigger: state
        entity_id: event.dx482_doorbell
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "Someone is at the door"
          data:
            image: /api/camera_proxy/camera.dx482_camera
            actions:
              - action: OPEN_DOOR
                title: Open door
```

## Ports

Home Assistant must be able to bind UDP 5068, TCP 8850 and UDP 30000/30002 (all
configurable in options). The doorbell must be able to reach them (same LAN or routed).

## Credits

Reverse engineering of the DX482 firmware and the VDP Connect app; no vendor code is included.
For interoperability with hardware you own.
