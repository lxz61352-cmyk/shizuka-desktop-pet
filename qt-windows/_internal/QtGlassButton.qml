import QtQuick
import QtQuick.Controls
Button {
    id: control
    property bool primary: false
    padding: 9
    font.bold: true
    contentItem: Text {text:control.text;font:control.font;color:control.enabled?"#f0f5fc":"#8b99ab";horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter}
    background: Rectangle {
        radius: 5;color:control.down?"#a044617b":control.hovered?"#80526a80":control.primary?"#70416684":"#48202d40"
        border.color:control.activeFocus?"#79d8fa":"#708197";opacity:control.enabled?1:.55
    }
}
