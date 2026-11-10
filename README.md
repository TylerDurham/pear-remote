# pear-remote

*An Apple TV remote you pair with — so, a pear remote.*

An Apple TV remote for the [Noctalia](https://noctalia.dev) v5 bar, built on
[pyatv](https://pyatv.dev).

```
┌──────── Noctalia plugin (Luau) ────────┐            ┌──────────── peard (Python) ─────────┐
│ service.luau  ── GET /events (SSE) ────┼──────────▶ │ aiohttp on 127.0.0.1:7655           │
│   └─ noctalia.state "snapshot"         │            │ one persistent pyatv connection     │
│ widget.luau / panel.luau / keyboard    │            │ push listeners → snapshots          │
│   ── POST /key/up, /volume, ... ───────┼──────────▶ │ artwork → ~/.cache/pear-remote/       │
└────────────────────────────────────────┘            └─────── systemd --user unit ─────────┘
```

The daemon keeps a single connection open, so button presses don't pay the
discovery/connect cost that per-call `atvremote` would.

## Install

```sh
./install.sh          # uv tool install, link plugin, enable systemd user unit
peard pair            # choose the Apple TV, enter the PIN(s) shown on screen
```

Then add the widget to a bar in `~/.config/noctalia/config.toml`:

```toml
[bar.default]
end = [ "battery", "appletv", "media", ... ]

[widget.appletv]
type = "dtd/pear-remote:remote"
```

If `pair`/`scan` find nothing, multicast replies are probably being dropped.
A firewall such as ufw will do this, because pyatv's mDNS replies come back to a
random UDP port. Point it at the TV directly instead:
`peard pair --host 192.168.1.x`. The IP is saved, and `serve` connects by
unicast first. It falls back to multicast discovery only if that IP stops answering.
To make multicast discovery work too, allow mDNS replies from the LAN:
`sudo ufw allow proto udp from 192.168.1.0/24 port 5353`.

### Multiple TVs

Pair each TV once. They all show up in the remote panel's TV picker:

```sh
peard pair --host 192.168.1.127   # Office
peard pair --host 192.168.1.105   # Living Room (2)
peard devices                     # * marks the active TV
peard use office                  # switch from the shell (name prefix or id)
```

Switching takes effect right away and is remembered. The bridge drops the
current TV and connects to the new one. Pairing another TV doesn't change
which TV is active.

Pairing covers **Companion** (apps, keyboard, power, remote keys) and
**AirPlay** (now-playing metadata and artwork). Credentials live in pyatv's
storage (`~/.pyatv.conf`); the chosen device is in
`~/.config/pear-remote/config.toml`, together with the active one.

Only run one bridge per TV. The TV allows one connection per pairing, so two
bridges keep kicking each other off. The log shows this as
"connection dropped after 2s; is another peard connected to this TV?".

## Using it

| Where | Input | Action |
|---|---|---|
| Bar | left click | open remote panel |
| Bar | right click | play / pause |
| Bar | scroll | volume |
| Panel | arrows / Return / BackSpace | d-pad / select / menu |
| Panel | space / h | play-pause / home |
| Panel | right-click Select | long press (context menus) |
| Panel | right-click Home | app switcher |
| Panel | TV picker (top) | switch between paired Apple TVs |
| Panel | ⌨ button | type into the TV's focused text field (highlighted when one is focused) |

Keybinds (e.g. Hyprland) go through the bridge service via IPC:

```
bind = SUPER ALT, up,    exec, noctalia msg plugin dtd/pear-remote:bridge all key up
bind = SUPER ALT, space, exec, noctalia msg plugin dtd/pear-remote:bridge all key play_pause
bind = SUPER ALT, t,     exec, noctalia msg panel-toggle dtd/pear-remote:pad
```

IPC events: `key <name>`, `key-hold <name>`, `power [on|off|toggle]`, `launch <bundle-id>`,
`device <name|id>`.

## Bridge API

Loopback only. POSTs need `X-Pear: 1`, and the `Host` header must be loopback.
Together these stop web pages and DNS-rebinding tricks from driving the TV.

```
GET  /health | /state | /events (SSE) | /apps[?refresh=1]
POST /key/<name>[?action=tap|double|hold]
POST /volume {"level": 0-100}     POST /position {"seconds": n}
POST /power/<on|off|toggle>       POST /launch {"id": "<bundle id>"}
POST /keyboard/<set|append|clear> {"text": "..."}
GET  /devices                     POST /device {"id": "<identifier or name>"}
```

Key names: `up down left right select menu home home_hold top_menu control_center
play_pause play pause stop next previous skip_forward skip_backward screensaver
channel_up channel_down guide volume_up volume_down`.

```sh
curl -X POST -H 'X-Pear: 1' http://127.0.0.1:7655/key/home
```

## Notes

- Volume controls only appear when the TV exposes volume, which needs HDMI-CEC
  or an AirPlay audio output.
- If `shell.offline_mode` is on, Noctalia blocks plugin HTTP, including this
  localhost bridge.
- Logs: `journalctl --user -u peard -f`; `peard -v serve` for pyatv debug output.
- Dev: `.luau` edits hot-reload; `noctalia plugins lint plugin/` checks the manifest.
