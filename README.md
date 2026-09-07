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

### Auto-answer on ring

Off by default. When enabled (Configure → options), a ring is answered immediately so
the camera and unlock are usable during the ring. The doorbell then behaves as if a
phone picked up.

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
