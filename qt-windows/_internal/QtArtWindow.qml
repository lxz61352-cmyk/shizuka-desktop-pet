import QtQuick
import QtQuick.Controls
import QtQuick.Effects

ApplicationWindow {
    id: shell
    property string windowKind
    property bool requestedVisible: false
    property bool externalClose: false
    property real localBlur: controller.blur/64
    property real localDarkness: controller.darkness
    property bool backgroundPrimed: false
    readonly property size backgroundTextureSize: Qt.size(scene.width,scene.height)
    readonly property int backgroundStatus: artwork.status
    visible: requestedVisible && (backgroundPrimed || artwork.source.toString()==="")
    flags: Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
           | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint
           | Qt.WindowStaysOnTopHint
    color: "#101824"
    font.family: "Microsoft YaHei UI"; font.pointSize: 10; font.bold: true
    onClosing: function(close) {if(externalClose) close.accepted=false;else controller.close(windowKind)}
    onVisibleChanged: if (visible) requestActivate()
    background: Rectangle {
        color: "#101824"; clip: true
        Item {
            id: scene; anchors.centerIn: parent
            width: Math.max(1,artwork.implicitWidth); height: Math.max(1,artwork.implicitHeight)
            scale: Math.max(shell.width/width,shell.height/height)
            Image {
                id: artwork; anchors.fill: parent; visible: false; asynchronous: true; retainWhileLoading: true
                onStatusChanged: if(status===Image.Ready || status===Image.Error) shell.backgroundPrimed=true
                sourceSize.width: 1600; sourceSize.height: 1600
                source: controller.background(shell.windowKind)
            }
            MultiEffect {
                anchors.fill: artwork; source: artwork
                blurEnabled: true; blurMax: 64; blur: Math.max(0,Math.min(1,shell.localBlur))
                autoPaddingEnabled: false
            }
        }
        Rectangle {anchors.fill: parent;color:"#101824";opacity:shell.localDarkness}
    }
    Connections {
        target: controller
        function onStyleChanged() {artwork.source=controller.background(shell.windowKind)}
    }
    Shortcut {sequence:"Escape";enabled:shell.visible;onActivated:controller.close(shell.windowKind)}
}
