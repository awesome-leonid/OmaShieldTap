// Display data only: action payloads are deliberately discarded after validation.
function object(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}
// Return the UTF-16 offset after at most limit Unicode code points.
function codePointOffset(value, limit) {
  var offset = 0
  for (var count = 0; count < limit && offset < value.length; ++count) {
    var lead = value.charCodeAt(offset++)
    if (lead >= 0xd800 && lead <= 0xdbff) {
      var trail = value.charCodeAt(offset)
      if (trail >= 0xdc00 && trail <= 0xdfff) ++offset
    }
  }
  return offset
}
function text(value, max, empty) {
  return typeof value === "string" && (empty || value.length > 0) &&
    (value.length <= max || codePointOffset(value, max) === value.length) && value.indexOf("\u0000") === -1
}
function token(value, max, pattern) {
  // Negative character classes avoid JavaScript $ accepting a final newline.
  return text(value, max, false) && !pattern.test(value)
}
function validAction(action) {
  if (!object(action)) return false
  if (action.kind === "native" || action.kind === "disabled") return true
  if (action.kind === "key") return token(action.value, 128, /[^A-Za-z0-9_]/)
  if (action.kind === "shortcut") return text(action.mods, 160, false) &&
    !/[^A-Za-z0-9_ +]/.test(action.mods) && token(action.key, 128, /[^A-Za-z0-9_]/)
  return action.kind === "command" && Array.isArray(action.argv) && action.argv.length > 0 &&
    action.argv.length <= 64 && action.argv.every(function(arg) { return text(arg, 4096, true) }) && action.argv[0].length > 0
}
function parseConfig(raw) {
  try {
    if (typeof raw !== "string" || raw.length > 262144) throw "invalid"
    var source = JSON.parse(raw)
    if (!object(source) || source.schema !== 1 || !Number.isSafeInteger(source.revision) || source.revision < 0 ||
        !token(source.keyboard, 128, /[^A-Za-z0-9_.:-]/) || !/^[A-Za-z0-9]/.test(source.keyboard) ||
        !text(source.remote_name, 160, false) || !Array.isArray(source.buttons) || source.buttons.length > 64) throw "invalid"
    var ids = Object.create(null)
    var buttons = source.buttons.map(function(button) {
      if (!object(button) || !token(button.id, 64, /[^a-z0-9_-]/) || !/^[a-z]/.test(button.id) || ids[button.id] ||
          !text(button.label, 160, false) || !token(button.key, 128, /[^A-Za-z0-9_]/) ||
          !text(button.summary, 512, true) || !validAction(button.action)) throw "invalid"
      ids[button.id] = true
      return {id: button.id, label: button.label, key: button.key, summary: button.summary, kind: button.action.kind}
    })
    return {ok: true, value: {schema: 1, revision: source.revision, keyboard: source.keyboard,
      remote_name: source.remote_name, buttons: buttons}}
  } catch (e) { return {ok: false, code: "invalid"} }
}

function tooltip(value) {
  var plain = String(value)
  return plain.slice(0, codePointOffset(plain, 512)).replace(/</g, "‹").replace(/>/g, "›")
}
function singleLine(value) {
  return String(value).replace(/\s+/g, " ").trim()
}
function batteryGlyph(percent) {
  if (!(percent >= 0 && percent <= 100)) return ""
  // Match Omarchy's laptop power panel in its on-battery state.
  var icons = ["󰁺", "󰁻", "󰁼", "󰁽", "󰁾", "󰁿", "󰂀", "󰂁", "󰂂", "󰁹"]
  return icons[Math.min(9, Math.floor(percent / 10))]
}
function detailTooltip(label, summary, sourceText) {
  // Bound and neutralize each field, never truncate the combined details.
  return tooltip(label) + "\n" + tooltip(summary) + "\n" + tooltip(sourceText)
}
