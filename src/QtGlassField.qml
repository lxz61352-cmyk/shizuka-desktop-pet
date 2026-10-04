import QtQuick
import QtQuick.Controls
TextField {
    color:"#f0f5fc";placeholderTextColor:"#cad6e6";selectionColor:"#365b7a";selectedTextColor:"#f0f5fc"
    font.bold:true;padding:8;selectByMouse:true
    background:Rectangle {color:"#18202d40";radius:5;border.color:parent.activeFocus?"#79d8fa":"#52667e"}
}
