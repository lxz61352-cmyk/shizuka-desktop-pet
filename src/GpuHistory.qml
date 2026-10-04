import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects

ApplicationWindow {
    id: root
    width: 980; height: 740; minimumWidth: 600; minimumHeight: 420
    visible: artwork.status===Image.Ready || artwork.status===Image.Error
    title: fixtureMode ? "Shizuka · 5000 条消息 GPU 试验" : "Shizuka · 聊天记录 GPU 试验"
    color: "#101824"
    font.family: "Microsoft YaHei UI"; font.pointSize: 10; font.bold: true
    property real blurAmount: Math.max(0, Math.min(1, initialBlur/64))
    property real darknessAmount: initialDarkness
    property real scrollFraction: 1
    property int liveDelegates: 0
    property int maxDelegates: 0
    readonly property int backgroundStatus: artwork.status
    readonly property size backgroundTextureSize: Qt.size(backgroundScene.width,backgroundScene.height)
    onScrollFractionChanged: history.contentY = Math.max(0, (history.contentHeight-history.height)*scrollFraction)
    Item {
        anchors.fill: parent; clip: true
        Item {
            id: backgroundScene
            anchors.centerIn: parent
            width: Math.max(1,artwork.implicitWidth); height: Math.max(1,artwork.implicitHeight)
            scale: Math.max(root.width/width,root.height/height)
            Image {
                id: artwork; anchors.fill: parent; source: backgroundUrl
                asynchronous: true; visible: false
                sourceSize.width: 1600; sourceSize.height: 1600
            }
            MultiEffect {
                anchors.fill: artwork; source: artwork
                blurEnabled: true; blurMax: 64; blur: root.blurAmount
                autoPaddingEnabled: false
            }
        }
    }
    Rectangle { anchors.fill: parent; color: "#101824"; opacity: root.darknessAmount }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 22; spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Label { text: "对话记录"; color: "#f0f5fc"; font.pointSize: 16 }
            Item { Layout.fillWidth: true }
            Label { text: historyController.count + " 条"; color: "#cad6e6" }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: "#79d8fa"; opacity: .7 }
        TextField {
            id: search; Layout.fillWidth: true; placeholderText: "搜索消息"
            color: "#f0f5fc"; selectionColor: "#365b7a"; selectedTextColor: "#f0f5fc"
            placeholderTextColor: "#cad6e6"; onTextChanged: searchDelay.restart()
            background: Rectangle { color: "#40202d40"; radius: 5; border.color: "#52667e" }
        }
        Timer { id: searchDelay; interval: 140; onTriggered: historyController.search(search.text) }
        ListView {
            id: history; Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; model: messageModel; reuseItems: true; cacheBuffer: 240
            boundsBehavior: Flickable.StopAtBounds; spacing: 24
            ScrollBar.vertical: ScrollBar { }
            Component.onCompleted: positionViewAtEnd()
            delegate: Column {
                id: entry
                required property string message
                required property string heading
                required property string stamp
                required property string rowId
                width: history.width-14; spacing: 12
                Component.onCompleted: { root.liveDelegates++; root.maxDelegates=Math.max(root.maxDelegates,root.liveDelegates) }
                Component.onDestruction: root.liveDelegates--
                ListView.onReused: { messageText.deselect(); context.close() }
                Row {
                    width: parent.width
                    Text { width: parent.width*.5; text: entry.heading; color: entry.heading==="你" ? "#79d8fa" : "#f0f5fc"; font: root.font }
                    Text { width: parent.width*.5; horizontalAlignment: Text.AlignRight; text: entry.stamp; color: "#cad6e6"; font: root.font }
                }
                TextEdit {
                    id: messageText; width: parent.width
                    text: entry.message; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap
                    readOnly: true; selectByMouse: true; color: "#f0f5fc"; font: root.font
                    selectionColor: "#365b7a"; selectedTextColor: "#f0f5fc"
                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.RightButton; onClicked: context.popup() }
                    Menu {
                        id: context; font.bold: false
                        MenuItem { text: "复制所选"; enabled: messageText.selectedText.length>0; onTriggered: messageText.copy() }
                        MenuItem { text: "复制整条"; onTriggered: historyController.copy(entry.message) }
                        MenuItem { text: "复制全部"; onTriggered: historyController.copyAll() }
                    }
                }
                Rectangle { width: parent.width; height: 1; color: "#52667e"; opacity: .7 }
            }
            Label { anchors.centerIn: parent; visible: historyController.count===0; text: "没有符合条件的消息"; color: "#cad6e6" }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "模糊"; color: "#cad6e6" }
            Slider {
                id: blurSlider; Layout.fillWidth: true; from: 0; to: 1; value: root.blurAmount; onMoved: root.blurAmount=value
                handle: Rectangle { x: blurSlider.leftPadding+blurSlider.visualPosition*(blurSlider.availableWidth-width);y:blurSlider.topPadding+(blurSlider.availableHeight-height)/2;width:16;height:16;radius:8;color:"#79d8fa" }
            }
            Label { text: "亮度"; color: "#cad6e6" }
            Slider {
                id: lightSlider; Layout.fillWidth: true; from: .1; to: 1; value: 1-root.darknessAmount; onMoved: root.darknessAmount=1-value
                handle: Rectangle { x:lightSlider.leftPadding+lightSlider.visualPosition*(lightSlider.availableWidth-width);y:lightSlider.topPadding+(lightSlider.availableHeight-height)/2;width:16;height:16;radius:8;color:"#79d8fa" }
            }
        }
    }
}
