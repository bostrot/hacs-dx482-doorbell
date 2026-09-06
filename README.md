# 2easy DX482 Video Doorbell — Home Assistant (HACS) integration

A **local, cloud-free** custom integration for the 2easy **DX482** video doorbell
(Anyka AK376xD, Linux 4.4). It talks directly to the device on your LAN for door
control and live video, so it keeps working even if the vendor cloud is down.

- **Door control** — momentary "Open door" button and a lockable "Door" entity.
- **Live video** — H.264 RTSP stream, plus a JPEG snapshot fallback.
- **State & diagnostics** — door state, door-open binary sensor, Wi-Fi signal.
- **Ring / motion events** — an `event` entity and a `binary_sensor`, raised
  through a local webhook (see [Ring detection](#ring-detection)).

> Status: 0.1.0, direct-LAN control. Requires the doorbell to be reachable on
> your network at a known IP.

---

## Why direct-to-device instead of SIP / cloud?

The official **vdpconnect** Android app was reverse-engineered to decide the
architecture. It is a **Linphone SIP client** that registers with the vendor
cloud (`sip.vdpconnect.com`, TLS) and controls the doorbell in one of two ways:

1. **DTMF over the SIP call** — e.g. relay 1 = DTMF `1#`, relay 2 = `2#`.
2. A **"MediaServer" TCP protocol on port 8850** — a *cloud RTP relay* the app
   logs into with credentials handed out by the cloud during a call. Its control
   frame is `10 10 01 00` + a little-endian sub-command (`1` = unlock,
   `7` = open light, `5`/`6` = IPC list/switch) + parameters.

Both paths depend on the vendor cloud and a live SIP call. There is also a
**LAN multicast discovery** (`236.6.6.1:25007`, magic `"SWITCH"`) the app uses to
find the doorbell and pull video directly, but the media itself is raw negotiated
RTP — awkward to consume in Home Assistant.

Firmware-side reverse engineering (documented in this repo's parent project)
found **fully local interfaces that need no cloud and no SIP call**:

| Function | Local interface |
|---|---|
| Door trigger / lock / state / snapshot | **TCP port 8765** custom binary protocol |
| Live video | **RTSP** on port 554 (`admin` / `1234abcd`) |

This integration is built on those two. That is the answer to *"should we do it
directly with the device?"* — **yes**.

### Port 8765 binary protocol (used here)

Request is a 4-byte little-endian *dispatcher* id followed by a payload; the
reply is a 10-byte header (`op`, `sid`, `rsp`, `len`, `chk`) followed by data.
`rsp = 0` means a query reply, `rsp = 1` means an action was acknowledged.

| Dispatcher | Function | Payload |
|---|---|---|
| `0x06` | Door trigger (momentary unlock) | `01 00 00 00` |
| `0x08` | Lock (`00…`) / unlock (`01…`) | `NN 00 00 00` |
| `0x0B` | JPEG snapshot | `01 00 00 00` |
| `0x0D` | Query door state | — |
| `0x1B` | Wi-Fi RSSI | — |

The device is single-threaded and fragile: the client opens one TCP connection
per command, reads the reply, closes, and waits briefly before the next one.

---

## Installation (HACS)

1. In HACS → **Integrations** → menu → **Custom repositories**, add this
   repository's URL with category **Integration**.
2. Install **"2easy DX482 Video Doorbell"** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → DX482**.

Manual install: copy `custom_components/dx482_doorbell/` into your HA
`config/custom_components/` directory and restart.

## Configuration

The setup form asks for:

| Field | Default | Notes |
|---|---|---|
| IP address | — | The doorbell's LAN IP (give it a DHCP reservation) |
| Control port | `8765` | Binary protocol port |
| RTSP port | `554` | |
| RTSP username / password | `admin` / `1234abcd` | Change if you customised them |
| RTSP channel | `101` | `101` = main/high-res, `102` = sub/low-res |

Setup verifies connectivity by querying the door state on the control port.
Poll interval and RTSP channel can be changed later under the integration's
**Configure** (options) dialog. Default poll interval is 60 s, deliberately gentle.

## Entities

| Entity | Type | Notes |
|---|---|---|
| Open door | `button` | Momentary relay pulse (dispatcher `0x06`) |
| Door | `lock` | Lock/unlock via `0x08`; optimistic, reconciled from polled state |
| Camera | `camera` | RTSP live view + snapshot |
| Door state | `sensor` | Coarse state label from `0x0D` |
| Door | `binary_sensor` | Door-open contact |
| Ringing | `binary_sensor` | Momentary, via webhook |
| Doorbell | `event` | `ring` / `motion` event types, via webhook |
| Wi-Fi signal | `sensor` | Diagnostic, disabled by default |

## Ring detection

The doorbell announces a ring as a **SIP INVITE from the cloud** — not visible on
the LAN without packet capture. This integration detects rings **locally and
built-in**, with no script on the doorbell and nothing external to run:

- It keeps **one persistent TCP connection** to the control port and polls the
  call-log dispatcher (`0x11`) every **200 ms** by default.
- When the call log changes, it raises a `ring` event (debounced so one ring
  produces one event). After a disconnect it reconnects with backoff and
  re-baselines, so a stale diff is never reported as a ring.
- Enable/disable and the poll interval (50–10000 ms) are in the integration's
  **Configure** dialog. If the device proves unstable under fast polling, raise
  the interval.

As an alternative or supplement, a **local webhook** can also raise ring/motion
events from any external notifier (a router-side SIP watcher, an ONVIF event
bridge, Frigate motion):

```
POST http://<home-assistant>:8123/api/webhook/dx482_doorbell_<entry_id>
# body optional: {"event": "motion"}   (defaults to "ring")
```

## Example automation

```yaml
automation:
  - alias: "Doorbell ring — notify with snapshot"
    trigger:
      - trigger: state
        entity_id: event.dx482_doorbell_doorbell
    action:
      - action: notify.mobile_app_phone
        data:
          message: "Someone is at the door"
          data:
            image: "/api/camera_proxy/camera.dx482_doorbell_camera"
```

## Limitations

- Door **state** from the device is coarse and its byte position varies across
  firmware; the integration scans for a known state code and exposes the raw
  value as an attribute. The lock entity is therefore optimistic.
- ONVIF on this hardware is broken at the firmware level and is not used.
- Built-in ring detection infers a ring from a call-log change, so latency is
  roughly the poll interval and the persistent connection is untested against
  every firmware revision; the webhook remains available as a fallback.

## Credits

Built from reverse engineering of the DX482 firmware and the vdpconnect Android
app. For educational and interoperability use with hardware you own.
