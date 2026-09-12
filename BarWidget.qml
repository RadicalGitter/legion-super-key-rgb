import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui as Ui

Ui.BarWidget {
    id: root
    moduleName: "io.github.radicalgitter.legion-super-key-rgb"
    property bool lightingOn: false
    property bool failed: false
    readonly property string entry: decodeURIComponent(Qt.resolvedUrl("src/entry.py").toString().replace(/^file:\/\//, ""))
    readonly property var processEnvironment: ({
        PATH: "/usr/bin", LANG: "C.UTF-8",
        HYPRLAND_INSTANCE_SIGNATURE: Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE")
    })
    function boundedCommand(action, seconds) {
        return ["/usr/bin/timeout", "--signal=TERM", "--kill-after=1s", seconds,
                "/usr/bin/python3", "-I", root.entry, action, "--quiet"]
    }
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    Process {
        id: status
        command: root.boundedCommand("status-exit", "5s")
        clearEnvironment: true
        environment: root.processEnvironment
        workingDirectory: "/"
        // No output parsers: Quickshell closes both channels, retaining no output.
        onExited: function(exitCode) { root.lightingOn = exitCode === 0 }
    }
    Process {
        id: toggleProcess
        command: root.boundedCommand("toggle", "18s")
        clearEnvironment: true
        environment: root.processEnvironment
        workingDirectory: "/"
        onExited: function(exitCode) {
            if (!status.running) status.running = true
            root.failed = exitCode !== 0
        }
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
        tooltipText: root.failed ? "Toggle failed: check README setup and the user service log" : "Toggle Super-key lighting · Legion Spectrum keyboard required"
        onPressed: function(buttonCode) {
            if (buttonCode === Qt.LeftButton && !toggleProcess.running)
                toggleProcess.running = true
        }
    }
}
