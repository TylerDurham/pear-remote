--!nonstrict
-- Headless bridge: keeps one SSE stream to napple-tvd open (reconnecting with
-- backoff) and republishes each snapshot to the plugin's shared state, where
-- the bar widget and panels watch it. Also the IPC entry point for keybinds:
--
--   noctalia msg plugin dtd/napple-tv:bridge all key up          (any /key name)
--   noctalia msg plugin dtd/napple-tv:bridge all key-hold select
--   noctalia msg plugin dtd/napple-tv:bridge all power toggle
--   noctalia msg plugin dtd/napple-tv:bridge all launch com.netflix.Netflix

local api = require("./lib/api.luau")

local stream = nil
local nextAttempt = 0
local backoff = 1000

local function publish(raw: string)
  noctalia.state.set("snapshot", raw)
end

local function scheduleRetry()
  stream = nil
  publish("")
  nextAttempt = noctalia.nowMs() + backoff
  backoff = math.min(backoff * 2, 30000)
end

local function connect()
  stream = noctalia.httpStream({ url = api.url("/events") }, function(line)
    if string.sub(line, 1, 5) == "data:" then
      backoff = 1000
      publish(noctalia.string.trim(string.sub(line, 6)))
    end
  end, function(_result)
    scheduleRetry()
  end)
  if stream == nil then
    scheduleRetry()
  end
end

local function disconnect()
  if stream ~= nil then
    stream.stop()
    stream = nil
  end
end

noctalia.setUpdateInterval(1000)

function update()
  if stream == nil and noctalia.nowMs() >= nextAttempt then
    connect()
  end
end

function onConfigChanged()
  disconnect()
  backoff = 1000
  nextAttempt = 0
end

function onExit(_signal, _reason)
  disconnect()
end

function onIpc(event, payload)
  payload = payload and noctalia.string.trim(payload) or ""
  if event == "key" and payload ~= "" then
    api.key(payload)
  elseif event == "key-hold" and payload ~= "" then
    api.key(payload, "hold")
  elseif event == "power" then
    api.post("/power/" .. (payload ~= "" and payload or "toggle"))
  elseif event == "launch" and payload ~= "" then
    api.post("/launch", { id = payload })
  else
    noctalia.log("napple-tv: unknown ipc event " .. tostring(event))
  end
end
