--!nonstrict
-- Shared helpers: bridge HTTP calls, snapshot decoding, formatting.

local M = {}

M.PLUGIN = "dtd/napple-tv"
M.REMOTE_PANEL = M.PLUGIN .. ":pad"
M.KEYBOARD_PANEL = M.PLUGIN .. ":keyboard"

local DEFAULT_ENDPOINT = "http://127.0.0.1:7655"
local lastErrorAt = -1e12

function M.url(path: string): string
  local ep = noctalia.getConfig("endpoint")
  if type(ep) ~= "string" or ep == "" then
    ep = DEFAULT_ENDPOINT
  end
  return (string.gsub(ep, "/+$", "")) .. path
end

-- Rate-limited so a dead bridge + a held arrow key doesn't spam toasts.
local function report(body: string)
  local now = noctalia.nowMs()
  if now - lastErrorAt > 10000 then
    lastErrorAt = now
    noctalia.notifyError("Apple TV", body)
  end
end

function M.request(method: string, path: string, body: any?, cb: ((any) -> ())?)
  local req = {
    url = M.url(path),
    method = method,
    headers = { "X-Napple: 1", "Content-Type: application/json" },
  }
  if body ~= nil then
    req.body = noctalia.json.encode(body)
  end
  return noctalia.http(req, function(res)
    if not res.ok then
      report("napple-tvd is not reachable at " .. M.url(""))
    elseif res.status >= 400 then
      local v = noctalia.json.decode(res.body)
      report((type(v) == "table" and v.error) or ("HTTP " .. res.status))
    end
    if cb then
      cb(res)
    end
  end)
end

function M.key(name: string, action: string?)
  M.request("POST", "/key/" .. name .. (action and ("?action=" .. action) or ""))
end

function M.post(path: string, body: any?, cb: ((any) -> ())?)
  M.request("POST", path, body, cb)
end

function M.get(path: string, cb: (any) -> ())
  M.request("GET", path, nil, function(res)
    if res.ok and res.status == 200 then
      cb(noctalia.json.decode(res.body))
    end
  end)
end

-- The bridge service publishes the raw SSE JSON under "snapshot"; "" = bridge down.
function M.snapshot(raw: any)
  if type(raw) ~= "string" or raw == "" then
    return { daemon = false, connected = false, features = {} }
  end
  local v = noctalia.json.decode(raw)
  if type(v) ~= "table" then
    return { daemon = false, connected = false, features = {} }
  end
  v.daemon = true
  v.features = v.features or {}
  return v
end

-- Position extrapolated from the last push while playing.
function M.position(s): number?
  if type(s.position) ~= "number" then
    return nil
  end
  local pos = s.position
  if s.state == "playing" and type(s.positionAt) == "number" then
    pos += (noctalia.nowMs() - s.positionAt) / 1000
  end
  if type(s.total) == "number" and s.total > 0 then
    pos = math.min(pos, s.total)
  end
  return math.max(0, pos)
end

function M.fmtTime(sec: number?): string
  if sec == nil then
    return "--:--"
  end
  sec = math.floor(sec)
  local h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
  if h > 0 then
    return string.format("%d:%02d:%02d", h, m, s)
  end
  return string.format("%d:%02d", m, s)
end

function M.subtitle(s): string
  local parts = {}
  if s.series then
    local ep = ""
    if s.season and s.episode then
      ep = string.format(" S%dE%d", s.season, s.episode)
    end
    table.insert(parts, s.series .. ep)
  elseif s.artist then
    table.insert(parts, s.artist)
  end
  if s.app then
    table.insert(parts, s.app)
  end
  return table.concat(parts, " · ")
end

function M.statusText(s): string
  if not s.daemon then
    return "Bridge not running"
  elseif not s.connected then
    return s.error or "Connecting…"
  elseif s.power == "off" then
    return "Asleep"
  end
  return s.state or "idle"
end

function M.truncate(text: string, n: number): string
  local len = utf8.len(text)
  if len == nil or len <= n then
    return text
  end
  return string.sub(text, 1, utf8.offset(text, n) - 1) .. "…"
end

return M
