#!/usr/bin/env bash
# Install napple-tvd (editable, via uv tool), link the Noctalia plugin, and
# enable the systemd user service. Safe to re-run after pulling changes.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
plugins="${XDG_DATA_HOME:-$HOME/.local/share}/noctalia/plugins"
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

uv tool install --force --editable "$here/daemon"

mkdir -p "$plugins" "$units"
ln -sfn "$here/plugin" "$plugins/napple-tv"
ln -sfn "$here/daemon/napple-tvd.service" "$units/napple-tvd.service"

systemctl --user daemon-reload
systemctl --user enable napple-tvd.service
systemctl --user restart napple-tvd.service

if pgrep -x noctalia >/dev/null; then
  noctalia msg plugins enable dtd/napple-tv || true
fi

cat <<'MSG'

Installed. Next:
  1. napple-tvd pair      # pick your Apple TV, enter the PIN(s) it shows
                          # (the running service picks the device up automatically)
  2. Add the widget to a bar in ~/.config/noctalia/config.toml:
       end = [ ..., "appletv", ... ]
       [widget.appletv]
       type = "dtd/napple-tv:remote"
MSG
