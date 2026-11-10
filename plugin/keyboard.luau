--!nonstrict
-- Type into whatever text field has focus on the Apple TV (search, login...).
-- Text is mirrored live as you type; Enter sends and closes.

local api = require("./lib/api.luau")

local snap = api.snapshot(noctalia.state.get("snapshot"))
local generation = 0 -- bump to recreate the input (clears + refocuses it)
local isOpen = false

local function send(text)
  api.post("/keyboard/set", { text = text })
end

local function render()
  local focused = snap.keyboard == "focused"
  local hint
  if not snap.connected then
    hint = "Not connected to the Apple TV"
  elseif focused then
    hint = "Text field active on the TV"
  else
    hint = "No text field is focused on the TV yet"
  end

  panel.render(ui.column({ gap = 12, flexGrow = 1 }, {
    ui.row({ gap = 8, align = "center" }, {
      ui.glyph({ name = "keyboard", size = 18, color = focused and "primary" or "on_surface_variant" }),
      ui.label({ text = "Type on Apple TV", fontWeight = "bold", flexGrow = 1, color = "on_surface" }),
    }),
    ui.input({
      key = "kb-" .. generation,
      focus = true,
      placeholder = "Search…",
      enabled = snap.connected,
      submitOnEnter = true,
      onChange = send,
      onSubmit = function(text)
        send(text)
        panel.close()
      end,
    }),
    ui.label({ text = hint, fontSize = 11, color = "on_surface_variant" }),
    ui.row({ gap = 8, justify = "end" }, {
      ui.button({
        text = "Clear",
        variant = "ghost",
        enabled = snap.connected,
        onClick = function()
          api.post("/keyboard/clear")
          generation += 1
          render()
        end,
      }),
      ui.button({
        text = "Remote",
        glyph = "device-tv",
        variant = "secondary",
        onClick = function()
          noctalia.togglePanel(api.REMOTE_PANEL)
        end,
      }),
      ui.button({
        text = "Done",
        variant = "primary",
        onClick = function()
          panel.close()
        end,
      }),
    }),
  }))
end

noctalia.state.watch("snapshot", function(raw)
  snap = api.snapshot(raw)
  if isOpen then
    render()
  end
end)

function onOpen(_context)
  isOpen = true
  snap = api.snapshot(noctalia.state.get("snapshot"))
  generation += 1
  render()
end

function onClose()
  isOpen = false
end
