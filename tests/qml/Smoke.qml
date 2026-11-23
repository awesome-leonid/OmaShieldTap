import QtQuick
import Quickshell
import qs.Commons as Commons

ShellRoot {
  id: test
  property var widget: null
  property int phase: Quickshell.env('REMOTE_BUTTONS_INITIAL_MISSING') === '1' ? -1 : 0
  property int ticks: 0
  property var oldRows: null
  property var content: null
  property var dismissalModels: []
  property real scrollPosition: 0
  function check(ok, message) {
    if (!ok) { console.error("UI_ASSERT: " + message); Qt.exit(1) }
  }
  function checkSetupNotice(text) {
    check(text.includes('README') && text.includes('Install') && text.includes('audit') &&
          text.includes('one non-modifier key') && text.includes('setup') &&
          !text.includes('omarchy-remote-buttons setup'), "missing config points to documented audit and setup")
  }
  function checkHidden() {
    check(!anchorWindow.backingWindowVisible && !widget.panelWindow.backingWindowVisible,
          "neither fixture window has a visible backing surface")
    check(dismissalModels.length > 0, "native dismissal models were found before opening")
    dismissalModels.forEach(function(variants) {
      check(variants.instances.length === 0, "no secondary dismissal surface is instantiated")
    })
  }
  QtObject {
    id: shield
    property string deviceName: "NVIDIA SHIELD Remote"
    property bool paired: true
    property bool connected: true
    property bool batteryAvailable: true
    property real battery: 0.73
  }
  QtObject {
    id: otherDevice
    property string deviceName: "Headphones"
    property bool paired: true
    property bool connected: true
    property bool batteryAvailable: true
    property real battery: 0.49
  }
  QtObject {
    id: fakeBar
    property color foreground: "#eeeeee"
    property color barForeground: foreground
    property color urgent: "#ff7777"
    property string fontFamily: "sans-serif"
    property bool vertical: false
    property bool foregroundAnimationEnabled: false
    property int barSize: 32
    property string position: "top"
    property var activePopout: null
    property var clickTargets: []
    function hideTooltip(owner) {}
    function showTooltip(owner, text) { test.check(text.indexOf("<") === -1 && text.indexOf(">") === -1, "bar tooltip is neutralized") }
    function registerClickTarget(target) {}
    function unregisterClickTarget(target) {}
    function requestPopout(owner) { activePopout = owner }
    function releasePopout(owner) { if (activePopout === owner) activePopout = null }
    function switchPanelFrom(owner, direction) { return false }
  }
  PanelWindow {
    id: anchorWindow
    visible: false
    implicitWidth: 800
    implicitHeight: 40
    Item { id: anchor; width: 32; height: 32 }
  }
  Component.onCompleted: {
    var component = Qt.createComponent("plugin/Panel.qml")
    check(component.status === Component.Ready, component.errorString())
    widget = component.createObject(anchor, {bar: fakeBar, manageIpc: false})
    check(widget !== null, "native panel created")
    if (!("bluetoothDevices" in widget)) { check(false, "panel has no Shield battery source"); return }
    widget.bluetoothDevices = [otherDevice, shield]
    // Break the main visibility binding AND disarm every per-screen Variants
    // factory before logical opening. Hidden main popups alone are insufficient
    // on multi-monitor desktops: their dismissal twins have separate visibility.
    widget.panelWindow.visible = false
    var objects = widget.panelWindow.data
    for (var i = 0; i < objects.length; ++i) {
      var variants = objects[i]
      if (variants instanceof Variants) {
        variants.model = []
        dismissalModels.push(variants)
      }
    }
    if (dismissalModels.length === 0) { check(false, "cannot isolate native dismissal factories"); return }
    checkHidden()
    widget.open()
    widget.ensurePanelContent()
    checkHidden()
  }
  Timer {
    interval: 30
    repeat: true
    running: true
    onTriggered: {
      if (++ticks > 300) { test.check(false, "timeout phase " + test.phase); return }
      if (!widget || !widget.panelContent) return
      checkHidden()
      var panel = widget.panelContent
      // Hidden windows do not receive frame-driven positioner polish.
      function layout(item) {
        for (var i = 0; i < item.children.length; ++i) layout(item.children[i])
        if (typeof item.forceLayout === 'function') item.forceLayout()
      }
      layout(panel)
      if (phase === -1 && widget.errorCode === 'missing') {
        test.check(widget.config === null && widget.buttons.length === 0, "missing startup has no fake assignments")
        test.checkSetupNotice(panel.notice.text)
        phase = 0
        console.log('UI_INITIAL_MISSING')
      } else if (phase === 0 && widget.config && widget.buttons.length === 16) {
        test.check(widget.implicitWidth > 0 && widget.implicitHeight > 0, "bar dimensions")
        test.check(widget.opened && !widget.panelWindow.visible, "logical open stays hidden")
        test.check(panel.rows.count === 16, "all physical buttons, including native/disabled, are rows")
        var firstRow = panel.rows.itemAt(0)
        test.check(firstRow.icon !== undefined, "button names are replaced by compact icons")
        if (firstRow.icon === undefined) return
        test.check(firstRow.icon.buttonId === 'center', "physical center uses its own icon")
        test.check(firstRow.label === undefined, "button name is not a visible text block")
        test.check(firstRow.hint.text.indexOf('‹img') === 0, "button names remain safe hover hints")
        test.check(firstRow.Accessible.name.indexOf('<img') === 0, "physical names remain accessible")
        test.check(firstRow.assignment.textFormat === Text.PlainText, "plain-text assignment sink")
        test.check(firstRow.assignment.text === 'Native', "native behavior has a short label")
        test.check(firstRow.height <= Commons.Style.space(30), "single compact row per button")
        for (var row = 0; row < panel.rows.count; ++row) {
          var item = panel.rows.itemAt(row)
          test.check(item.icon.buttonId === widget.buttons[row].id, "every button has its physical icon")
          test.check(item.icon.width > 0 && item.icon.height > 0, "icon has visible dimensions")
        }
        var multiline = panel.rows.itemAt(2)
        test.check(multiline.assignment.text === 'First second third last next end', "multiline assignments become one visible line")
        test.check(multiline.assignment.lineCount === 1 && multiline.height === firstRow.height,
                   "multiline assignment does not grow the row")
        test.check(multiline.hint.text === 'Button 2\nFirst\r\n  second\tthird\nlast\u2028next\u2029end\nSource key: XF86Select',
                   "hover retains the complete original multiline action")
        var maximum = panel.rows.itemAt(4)
        test.check(maximum.hint.text === '‹' + '🚀'.repeat(158) + '›\n‹' + 'S'.repeat(510) + '🚀\nSource key: ' + 'K'.repeat(128),
                   "maximum-length Unicode name and action survive safe hover composition with the full source key")
        test.check(panel.rows.itemAt(1).assignment.text === 'Disabled', "disabled handling is explicit")
        test.check(panel.title.text === 'OmaShieldTap' && Commons.I18n.language === 'de', "English fallback")
        var battery = panel.batteryLabel
        if (!battery) { test.check(false, "missing battery label"); return }
        var batteryIcon = panel.batteryIcon
        if (!batteryIcon) { test.check(false, "missing battery icon"); return }
        test.check(battery.text === '73%', "header shows the Shield battery, not the headphones")
        test.check(batteryIcon.text === '󰂁', "73% uses the same glyph as Omarchy's laptop battery")
        test.check(battery.x >= panel.title.x + panel.title.width &&
                   Math.abs(battery.y + battery.baselineOffset - panel.title.y - panel.title.baselineOffset) < 1 &&
                   battery.x + battery.width < batteryIcon.x && batteryIcon.width > 0 &&
                   Math.abs(batteryIcon.x + batteryIcon.width - battery.parent.width) < 1,
                   "percentage and battery icon are at the top-right, with the icon after the number")
        shield.battery = 0
        test.check(battery.text === '0%', "zero is valid and the reading updates live")
        test.check(batteryIcon.text === '󰁺', "low battery changes the glyph live")
        shield.connected = false
        test.check(battery.text === '' && batteryIcon.width === 0, "a disconnected Shield has no battery badge")
        shield.connected = true
        shield.batteryAvailable = false
        test.check(battery.text === '', "an unavailable reading is hidden")
        shield.batteryAvailable = true
        shield.battery = 1.1
        test.check(battery.text === '', "out-of-range readings are hidden")
        shield.battery = 1
        test.check(battery.text === '100%', "valid reading returns without reopening")
        test.check(batteryIcon.text === '󰁹', "full battery uses Omarchy's full glyph")
        test.check(panel.agent.text === 'Ask your agent to change a button', "agent-agnostic footer")
        // Force an overflow viewport after checking the compact layout, so the
        // existing navigation/scroll-preservation checks remain nontrivial.
        widget.panelWindow.contentHeight = Commons.Style.space(180)
        layout(panel)
        panel.moveRequested(0, 1)
        test.check(panel.scroller.contentY > 0, "keyboard navigation scrolls")
        panel.activateRequested()
        content = panel
        scrollPosition = panel.scroller.contentY
        phase = 1
        console.log('UI_READY')
      } else if (phase === 1 && widget.config.revision === 2) {
        test.check(widget.buttons[0].summary === 'Changed by agent', "atomic replacement displayed")
        test.check(widget.panelContent === content, "view remains loaded across updates")
        test.check(panel.scroller.contentY === scrollPosition, "assignment update preserves scroll")
        oldRows = widget.buttons
        phase = 2
        console.log('UI_UPDATED')
      } else if (phase === 2 && widget.config.revision === 3 && Commons.I18n.language === 'da') {
        test.check(widget.buttons === oldRows, "unchanged normalized rows are not replaced")
        test.check(panel.title.text === 'OmaShieldTap', "live language switch keeps English fallback")
        phase = 3
        console.log('UI_UNCHANGED')
      } else if (phase === 3 && widget.errorCode === 'invalid') {
        test.check(widget.buttons === oldRows, "invalid config keeps last valid view without flashes")
        test.check(panel.notice.text.indexOf('invalid') !== -1, "invalid config has a visible warning")
        phase = 4
        console.log('UI_INVALID')
      } else if (phase === 4 && widget.errorCode === 'missing') {
        test.checkSetupNotice(panel.notice.text)
        phase = 5
        console.log('UI_MISSING')
      } else if (phase === 5 && widget.errorCode === '') {
        test.check(widget.buttons === oldRows, "recreation recovers without rebuilding unchanged rows")
        panel.closeRequested()
        test.check(!widget.opened, "Escape semantic path closes the panel")
        console.log('UI_RECOVERED')
        Qt.quit()
      }
    }
  }
}
