--!nonstrict
-- Remote panel: now playing, d-pad, transport, volume, app launcher.
-- Keys while open: arrows = d-pad, Return = select, BackSpace = menu,
-- space = play/pause, h = home. Escape closes the panel.

local api = require("./lib/api.luau")

local snap = api.snapshot(noctalia.state.get("snapshot"))
local apps = nil -- { { name, id } } once fetched
local volDraft = nil -- slider value while dragging
local isOpen = false

local KEYMAP = {
  Up = "up",
  Down = "down",
  Left = "left",
  Right = "right",
  Return = "select",
  BackSpace = "menu",
  space = "play_pause",
  h = "home",
}

local function press(name, action)
  return function()
    api.key(name, action)
  end
end

local function btn(props)
  props.variant = props.variant or "secondary"
  props.enabled = snap.connected and (props.enabled ~= false)
  return ui.button(props)
end

local function padButton(glyph, name, tip, extra)
  local p = { glyph = glyph, glyphSize = 20, width = 64, height = 48, tooltip = tip, onClick = press(name) }
  for k, v in extra or {} do
    p[k] = v
  end
  return btn(p)
end

local function iconButton(glyph, onClick, tip, extra)
  local p = { glyph = glyph, glyphSize = 18, controlSize = "md", variant = "ghost", tooltip = tip, onClick = onClick }
  for k, v in extra or {} do
    p[k] = v
  end
  return btn(p)
end

local function artwork(s)
  if s.artwork then
    return ui.image({ path = s.artwork, width = 72, height = 72, radius = 10, fit = "cover" })
  end
  return ui.column({ width = 72, height = 72, radius = 10, fill = "surface_variant", align = "center", justify = "center" }, {
    ui.glyph({ name = "device-tv", size = 30, color = "on_surface_variant" }),
  })
end

local function header(s)
  local title
  if not s.daemon then
    title = "Bridge not running"
  elseif not s.connected then
    title = "Not connected"
  else
    title = s.title or s.app or (s.power == "off" and "Asleep" or "Nothing playing")
  end
  local sub = api.subtitle(s)
  local status = (s.device or "Apple TV") .. " · " .. api.statusText(s)

  return ui.row({ gap = 12, align = "center" }, {
    artwork(s),
    ui.column({ gap = 2, flexGrow = 1 }, {
      ui.label({ text = title, fontWeight = "bold", fontSize = 15, maxLines = 2, color = "on_surface" }),
      ui.label({ text = sub, maxLines = 1, color = "on_surface_variant", visible = sub ~= "" }),
      ui.label({ text = status, maxLines = 2, fontSize = 11, color = "on_surface_variant" }),
    }),
  })
end

local function progress(s)
  local total = s.total
  if type(total) ~= "number" or total <= 0 then
    return nil
  end
  local pos = api.position(s) or 0
  return ui.column({ gap = 4 }, {
    ui.progress({ progress = pos / total, height = 4, radius = 2 }),
    ui.row({ justify = "space_between" }, {
      ui.label({ text = api.fmtTime(pos), fontSize = 11, color = "on_surface_variant" }),
      ui.label({ text = "-" .. api.fmtTime(total - pos), fontSize = 11, color = "on_surface_variant" }),
    }),
  })
end

local function dpad()
  local function centered(children)
    return ui.row({ gap = 8, justify = "center", align = "center" }, children)
  end
  return ui.column({ gap = 8 }, {
    centered({ padButton("chevron-up", "up", "Up") }),
    centered({
      padButton("chevron-left", "left", "Left"),
      padButton("circle-dot", "select", "Select (right-click: hold)", { variant = "primary", onRightClick = press("select", "hold") }),
      padButton("chevron-right", "right", "Right"),
    }),
    centered({ padButton("chevron-down", "down", "Down") }),
  })
end

local function navRow(s)
  return ui.row({ gap = 8, justify = "center" }, {
    iconButton("arrow-back-up", press("menu"), "Back / Menu"),
    iconButton("home", press("home"), "Home (right-click: app switcher)", { onRightClick = press("home", "double") }),
    iconButton("layout-sidebar-right", press("control_center"), "Control Center"),
    iconButton("keyboard", function()
      noctalia.togglePanel(api.KEYBOARD_PANEL)
    end, "Type on TV", {
      enabled = s.features.keyboard ~= false,
      variant = s.keyboard == "focused" and "primary" or "ghost",
    }),
    iconButton("power", function()
      api.post("/power/toggle")
    end, s.power == "on" and "Sleep" or "Wake", { enabled = s.features.power ~= false }),
  })
end

local function transport(s)
  return ui.row({ gap = 4, justify = "center", align = "center" }, {
    iconButton("player-skip-back-filled", press("previous"), "Previous"),
    iconButton("rewind-backward-10", press("skip_backward"), "Skip back"),
    iconButton(s.state == "playing" and "player-pause-filled" or "player-play-filled", press("play_pause"), "Play / Pause", {
      variant = "primary",
      controlSize = "lg",
    }),
    iconButton("rewind-forward-10", press("skip_forward"), "Skip forward"),
    iconButton("player-skip-forward-filled", press("next"), "Next"),
  })
end

local function volumeRow(s)
  if not s.features.volume then
    return nil
  end
  local middle
  if s.features.setVolume and type(s.volume) == "number" then
    middle = ui.slider({
      min = 0,
      max = 100,
      step = 1,
      value = volDraft or s.volume,
      flexGrow = 1,
      enabled = s.connected,
      onChange = function(v)
        volDraft = tonumber(v)
      end,
      onDragEnd = function()
        if volDraft then
          api.post("/volume", { level = volDraft })
        end
        volDraft = nil
      end,
    })
  else
    middle = ui.label({ text = "Volume", flexGrow = 1, textAlign = "center", color = "on_surface_variant" })
  end
  return ui.row({ gap = 8, align = "center" }, {
    iconButton("volume-2", press("volume_down"), "Volume down"),
    middle,
    iconButton("volume", press("volume_up"), "Volume up"),
  })
end

local function appsRow(s)
  if not s.features.apps then
    return nil
  end
  local names = {}
  for _, a in apps or {} do
    table.insert(names, a.name)
  end
  return ui.row({ gap = 8, align = "center" }, {
    ui.select({
      options = names,
      placeholder = apps and "Launch app…" or "Loading apps…",
      flexGrow = 1,
      enabled = s.connected and apps ~= nil,
      onChange = function(index, _text)
        local a = apps and apps[(tonumber(index) or -1) + 1]
        if a then
          api.post("/launch", { id = a.id })
        end
      end,
    }),
    iconButton("refresh", function()
      apps = nil
      render()
      fetchApps(true)
    end, "Refresh app list"),
  })
end

function fetchApps(refresh)
  if not snap.connected or not snap.features.apps then
    return
  end
  api.get(refresh and "/apps?refresh=1" or "/apps", function(list)
    if type(list) == "table" then
      apps = list
      if isOpen then
        render()
      end
    end
  end)
end

function render()
  local s = snap
  local children = { header(s) }
  local function add(node)
    if node then
      table.insert(children, node)
    end
  end
  add(progress(s))
  add(ui.separator({}))
  add(dpad())
  add(navRow(s))
  add(transport(s))
  add(volumeRow(s))
  add(appsRow(s))
  if not s.daemon then
    add(ui.label({
      text = "Start it with: systemctl --user start napple-tvd",
      fontSize = 11,
      color = "error",
      maxLines = 2,
    }))
  end
  panel.render(ui.column({ gap = 14, flexGrow = 1 }, children))
end

noctalia.state.watch("snapshot", function(raw)
  local wasConnected = snap.connected
  snap = api.snapshot(raw)
  if not snap.connected then
    apps = nil
  elseif not wasConnected or apps == nil then
    fetchApps(false)
  end
  if isOpen then
    render()
  end
end)

function onOpen(_context)
  isOpen = true
  snap = api.snapshot(noctalia.state.get("snapshot"))
  panel.setWantsSecondTicks(true)
  if apps == nil then
    fetchApps(false)
  end
  render()
end

function onClose()
  isOpen = false
  volDraft = nil
  panel.setWantsSecondTicks(false)
end

-- Second ticks: advance the progress bar while playing.
function update()
  if isOpen and snap.state == "playing" then
    render()
  end
end

function onKey(chord, pressed)
  if not pressed then
    return
  end
  local name = KEYMAP[chord]
  if name and snap.connected then
    api.key(name)
  end
end
