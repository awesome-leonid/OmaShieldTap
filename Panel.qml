import QtQuick
import QtQuick.Controls as QQC
import Quickshell
import Quickshell.Bluetooth
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui
import "Model.js" as Model

Ui.Panel {
  id: remotePanel
  moduleName: "leo.remote-buttons"
  ipcTarget: "leo.remote-buttons"
  implicitWidth: barButton.implicitWidth
  implicitHeight: barButton.implicitHeight

  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.5)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string configPath: (Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config")) + "/omarchy-remote-buttons/config.json"
  property var config: null
  property var buttons: []
  property var bluetoothDevices: Bluetooth.devices ? Bluetooth.devices.values : []
  readonly property int shieldBatteryPercent: {
    if (!config) return -1
    var shield = null
    for (var i = 0; i < bluetoothDevices.length; ++i) {
      var device = bluetoothDevices[i]
      if (!device || !device.paired || device.deviceName !== "NVIDIA SHIELD Remote") continue
      if (shield) return -1 // Don't guess between identical paired remotes.
      shield = device
    }
    if (!shield || !shield.connected || !shield.batteryAvailable) return -1
    var level = shield.battery
    return level >= 0 && level <= 1 ? Math.round(level * 100) : -1
  }
  property string errorCode: ""
  readonly property var panelContent: popup.loadedContent
  readonly property alias panelWindow: popup
  readonly property string noticeText: errorCode === "" ? "" :
    (errorCode === "missing" ? strings.t("panel.setup") : strings.t("error." + errorCode)) +
    (config ? "\n" + strings.t("panel.stale") : "")

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

  function acceptConfig(raw) {
    var reply = Model.parseConfig(raw)
    if (!reply.ok) { errorCode = "invalid"; return }
    if (JSON.stringify(buttons) !== JSON.stringify(reply.value.buttons)) buttons = reply.value.buttons
    if (JSON.stringify(config) !== JSON.stringify(reply.value)) config = reply.value
    errorCode = ""
  }
  function ensurePanelContent() { return popup.ensureContent() }

  // Local vector icons: independent of icon fonts, files, and network resources.
  component ButtonIcon: Canvas {
    property string buttonId: ""
    property color ink: "white"
    Accessible.ignored: true
    onButtonIdChanged: requestPaint()
    onInkChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onAvailableChanged: if (available) requestPaint()
    onPaint: {
      var c = getContext("2d")
      c.setTransform(1, 0, 0, 1, 0, 0)
      c.clearRect(0, 0, width, height)
      c.scale(width / 24, height / 24)
      c.strokeStyle = ink
      c.fillStyle = ink
      c.lineWidth = 1.8
      c.lineCap = "round"
      c.lineJoin = "round"
      function line(points) {
        c.beginPath(); c.moveTo(points[0][0], points[0][1])
        for (var i = 1; i < points.length; ++i) c.lineTo(points[i][0], points[i][1])
        c.stroke()
      }
      switch (buttonId) {
      case "center":
        c.beginPath(); c.arc(12, 12, 8, 0, Math.PI * 2); c.stroke()
        c.beginPath(); c.arc(12, 12, 2, 0, Math.PI * 2); c.fill(); break
      case "mic":
        c.beginPath(); c.moveTo(9, 5); c.quadraticCurveTo(9, 2, 12, 2)
        c.quadraticCurveTo(15, 2, 15, 5); c.lineTo(15, 11)
        c.quadraticCurveTo(15, 14, 12, 14); c.quadraticCurveTo(9, 14, 9, 11)
        c.closePath(); c.stroke()
        c.beginPath(); c.moveTo(6, 10); c.bezierCurveTo(6, 20, 18, 20, 18, 10); c.stroke()
        line([[12,18],[12,22]]); line([[9,22],[15,22]]); break
      case "up": line([[6,15],[12,9],[18,15]]); break
      case "down": line([[6,9],[12,15],[18,9]]); break
      case "left": line([[15,6],[9,12],[15,18]]); break
      case "right": line([[9,6],[15,12],[9,18]]); break
      case "home":
        line([[3,11],[12,4],[21,11]])
        line([[6,10],[6,20],[10,20],[10,14],[14,14],[14,20],[18,20],[18,10]]); break
      case "back":
        line([[10,5],[4,11],[10,17]]); line([[4,11],[15,11],[19,15],[19,20]]); break
      case "menu":
        line([[5,6],[19,6]]); line([[5,12],[19,12]]); line([[5,18],[19,18]]); break
      case "play_pause":
        line([[4,5],[4,19],[13,12],[4,5]])
        line([[17,5],[17,19]]); line([[21,5],[21,19]]); break
      case "rewind":
        line([[11,6],[3,12],[11,18],[11,6]])
        line([[21,6],[13,12],[21,18],[21,6]]); break
      case "fast_forward":
        line([[3,6],[11,12],[3,18],[3,6]])
        line([[13,6],[21,12],[13,18],[13,6]]); break
      case "volume_up":
      case "volume_down":
        line([[3,10],[7,10],[12,6],[12,18],[7,14],[3,14],[3,10]])
        line([[16,12],[22,12]])
        if (buttonId === "volume_up") line([[19,9],[19,15]])
        break
      case "power":
        c.beginPath(); c.arc(12, 13, 8, -Math.PI / 4, Math.PI * 1.25); c.stroke()
        line([[12,2],[12,12]]); break
      case "netflix": line([[6,19],[6,5],[18,19],[18,5]]); break
      default:
        c.beginPath(); c.rect(5,5,4,4); c.rect(15,5,4,4)
        c.rect(5,15,4,4); c.rect(15,15,4,4); c.stroke()
      }
    }
  }

  FileView {
    id: configFile
    path: remotePanel.configPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: remotePanel.acceptConfig(text())
    onLoadFailed: function(error) { remotePanel.errorCode = error === FileViewError.FileNotFound ? "missing" : "read" }
  }
  // Retry only missing/unreadable files, with no loading UI or status churn.
  Timer {
    interval: 750
    running: remotePanel.errorCode === "missing" || remotePanel.errorCode === "read"
    repeat: true
    onTriggered: configFile.reload()
  }

  Ui.BarIconButton {
    id: barButton
    anchors.fill: parent
    bar: remotePanel.bar
    text: "󰑔"
    tooltipText: Model.tooltip(strings.t("panel.title") + (remotePanel.config ? " — " + remotePanel.config.remote_name : ""))
    Accessible.role: Accessible.Button
    Accessible.name: strings.t("panel.title")
    onPressed: remotePanel.toggle()
  }

  Ui.KeyboardPanel {
    id: popup
    anchorItem: barButton
    owner: remotePanel
    bar: remotePanel.bar
    open: remotePanel.opened
    focusTarget: popup.loadedContent
    contentWidth: popup.fittedContentWidth(Style.space(360))
    contentHeight: popup.fittedContentHeight(popup.loadedContentHeight, Style.space(610))

    content: Ui.PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      implicitHeight: contentColumn.implicitHeight
      property alias rows: rows
      property alias scroller: flick
      property alias title: title
      property alias batteryLabel: battery
      property alias batteryIcon: batteryIcon
      property alias notice: notice
      property alias agent: agent
      function scrollBy(amount) {
        flick.contentY = Math.max(0, Math.min(Math.max(0, flick.contentHeight - flick.height), flick.contentY + amount))
      }
      onMoveRequested: function(dx, dy) { scrollBy((dy || dx) * Style.space(64)) }
      onTabRequested: function(direction) { scrollBy(direction * Style.space(64)) }
      onCloseRequested: remotePanel.close()
      // Enter/Space have no action handler: assignments are not buttons.
      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.implicitHeight
        flickableDirection: Flickable.VerticalFlick
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        QQC.ScrollBar.vertical: QQC.ScrollBar { policy: QQC.ScrollBar.AsNeeded }
        Column {
          id: contentColumn
          width: flick.width
          spacing: Style.space(8)
          Item {
            width: parent.width
            height: Math.max(title.implicitHeight, battery.implicitHeight)
            Text {
              id: title
              anchors.left: parent.left
              anchors.right: battery.left
              anchors.rightMargin: battery.text !== "" ? Style.space(8) : 0
              textFormat: Text.PlainText
              text: strings.t("panel.title")
              color: remotePanel.foreground
              font.family: remotePanel.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              elide: Text.ElideRight
            }
            Text {
              id: battery
              anchors.right: batteryIcon.left
              anchors.rightMargin: text !== "" ? Style.space(5) : 0
              anchors.baseline: title.baseline
              textFormat: Text.PlainText
              text: remotePanel.shieldBatteryPercent < 0 ? "" :
                Commons.I18n.formatNumber(remotePanel.shieldBatteryPercent) + "%"
              visible: text !== ""
              color: remotePanel.foreground
              font.family: remotePanel.fontFamily
              font.pixelSize: Style.font.body
              Accessible.role: Accessible.StaticText
              Accessible.name: visible ? strings.t("panel.battery").arg(text) : ""
            }
            Text {
              id: batteryIcon
              anchors.right: parent.right
              anchors.verticalCenter: title.verticalCenter
              width: text !== "" ? Style.space(18) : 0
              visible: text !== ""
              textFormat: Text.PlainText
              text: Model.batteryGlyph(remotePanel.shieldBatteryPercent)
              horizontalAlignment: Text.AlignHCenter
              color: remotePanel.foreground
              font.family: remotePanel.fontFamily
              font.pixelSize: Style.space(18)
              Accessible.ignored: true
            }
          }
          Text {
            width: parent.width
            visible: remotePanel.config !== null
            textFormat: Text.PlainText
            text: remotePanel.config ? remotePanel.config.remote_name : ""
            color: remotePanel.dim
            font.family: remotePanel.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
          Text {
            id: notice
            width: parent.width
            visible: text !== ""
            textFormat: Text.PlainText
            text: remotePanel.noticeText
            color: remotePanel.foreground
            font.family: remotePanel.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.WordWrap
          }
          Column {
            width: parent.width
            spacing: Style.space(2)
            Repeater {
              id: rows
              model: remotePanel.buttons
              delegate: Item {
                required property var modelData
                width: contentColumn.width
                height: Math.max(Style.space(24), assignment.implicitHeight, buttonIcon.height)
                property alias icon: buttonIcon
                property alias assignment: assignment
                property alias hint: rowHint
                Accessible.role: Accessible.StaticText
                Accessible.name: modelData.label + ": " + assignment.text
                ButtonIcon {
                  id: buttonIcon
                  anchors.left: parent.left
                  anchors.verticalCenter: parent.verticalCenter
                  width: Style.space(18)
                  height: width
                  buttonId: modelData.id
                  ink: remotePanel.foreground
                }
                Text {
                  id: assignment
                  anchors.left: buttonIcon.right
                  anchors.leftMargin: Style.space(14)
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  textFormat: Text.PlainText
                  text: modelData.kind === "native" ? strings.t("panel.nativeShort") :
                    modelData.kind === "disabled" ? strings.t("panel.disabled") : Model.singleLine(modelData.summary)
                  color: modelData.kind === "native" ? remotePanel.dim : remotePanel.foreground
                  font.family: remotePanel.fontFamily
                  font.pixelSize: Style.font.body
                  elide: Text.ElideRight
                }
                HoverHandler { id: rowHover }
                Ui.PanelToolTip {
                  id: rowHint
                  visible: rowHover.hovered
                  width: Math.min(implicitWidth, Style.space(360))
                  text: Model.detailTooltip(modelData.label,
                    modelData.kind === "native" ? strings.t("panel.native") : modelData.summary,
                    strings.t("panel.sourceKey").arg(modelData.key))
                }
              }
            }
          }
          Ui.PanelSeparator { width: parent.width; foreground: remotePanel.foreground }
          Text {
            id: agent
            width: parent.width
            textFormat: Text.PlainText
            text: strings.t("panel.agent")
            color: remotePanel.dim
            font.family: remotePanel.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
            HoverHandler { id: agentHover }
            Ui.PanelToolTip {
              visible: agentHover.hovered
              width: Math.min(implicitWidth, Style.space(360))
              text: Model.tooltip(strings.t("panel.cli"))
            }
          }
        }
      }
    }
  }
}
