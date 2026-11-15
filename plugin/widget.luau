--!nonstrict
-- Bar widget: state glyph + now-playing title.
--   left click   toggle the remote panel
--   right click  play / pause
--   scroll       volume

local api = require("./lib/api.luau")

local snap = api.snapshot(noctalia.state.get("snapshot"))

local function glyphFor(s): string
  if not s.daemon then
    return "plug-connected-x"
  elseif not s.connected then
    return "device-tv-off"
  elseif s.power == "off" then
    return "zzz"
  elseif s.state == "playing" then
    return "player-play-filled"
  elseif s.state == "paused" then
    return "player-pause-filled"
  end
  return "device-tv"
end

local function tooltip(s)
  local rows = { { key = s.device or "Apple TV", value = api.statusText(s) } }
  if s.title then
    table.insert(rows, { key = "Playing", value = s.title })
  end
  local sub = api.subtitle(s)
  if sub ~= "" then
    table.insert(rows, { key = "From", value = sub })
  end
  if type(s.total) == "number" and s.total > 0 then
    table.insert(rows, { key = "Time", value = api.fmtTime(api.position(s)) .. " / " .. api.fmtTime(s.total) })
  end
  if type(s.volume) == "number" then
    table.insert(rows, { key = "Volume", value = tostring(s.volume) .. "%" })
  end
  return rows
end

local function draw()
  local s = snap
  local asleep = not s.connected or s.power == "off"
  barWidget.setVisible(not (noctalia.getConfig("hide_when_off") and asleep))
  barWidget.setGlyph(glyphFor(s))

  local text = ""
  if noctalia.getConfig("show_title") and s.connected and s.title then
    text = api.truncate(s.title, noctalia.getConfig("max_title") or 24)
  end
  barWidget.setText(text)
  barWidget.setTooltip(tooltip(s))
end

noctalia.state.watch("snapshot", function(raw)
  snap = api.snapshot(raw)
  draw()
end)

function update()
  -- Only the tooltip's elapsed time changes between pushes.
  noctalia.setUpdateInterval(snap.state == "playing" and 1000 or 5000)
  draw()
end

function onClick()
  noctalia.togglePanel(api.REMOTE_PANEL)
end

function onRightClick()
  api.key("play_pause")
end

function onScroll(axis, steps, _startsGesture)
  if axis ~= "vertical" or steps == 0 then
    return
  end
  local name = steps < 0 and "volume_up" or "volume_down"
  for _ = 1, math.min(math.abs(steps), 5) do
    api.key(name)
  end
end
