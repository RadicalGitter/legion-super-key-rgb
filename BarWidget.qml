import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui as Ui

Ui.BarWidget {
    id: root
    moduleName: "io.github.radicalgitter.legion-super-key-rgb"
    property bool lightingOn: false
    property string helper: Quickshell.env("HOME") + "/.local/bin/legion-shortcut-lights"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    Process {
        id: status
        command: ["systemctl", "--user", "is-active", "--quiet", "legion-shortcut-lights.service"]
        onExited: function(exitCode) { root.lightingOn = exitCode === 0 }
    }
    Process {
        id: toggleProcess
        command: [root.helper, "toggle"]
        onExited: function(exitCode) {
            if (!status.running) status.running = true
            if (exitCode !== 0) failure.running = true
        }
    }
    Process {
        id: failure
        command: ["notify-send", "Legion RGB", "Could not toggle lighting. Complete the README setup and check the user service log."]
    }
    Timer {
        interval: 2000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: { if (!status.running) status.running = true }
    }
    Ui.WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: root.lightingOn ? "RGB on" : "RGB off"
        active: root.lightingOn
        tooltipText: "Toggle Super-key lighting · Legion Spectrum keyboard required"
        onPressed: function(buttonCode) {
            if (buttonCode === Qt.LeftButton && !toggleProcess.running)
                toggleProcess.running = true
        }
    }
}
