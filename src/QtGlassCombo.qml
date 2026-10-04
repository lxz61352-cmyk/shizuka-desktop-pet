import QtQuick
import QtQuick.Controls
ComboBox {
    id:control;font.bold:true;padding:8;rightPadding:28
    contentItem:Text {text:control.displayText;font:control.font;color:"#f0f5fc";verticalAlignment:Text.AlignVCenter;elide:Text.ElideRight}
    background:Rectangle {color:"#18202d40";radius:5;border.color:"#52667e"}
    indicator:Text {text:"⌄";color:"#cad6e6";anchors.right:parent.right;anchors.rightMargin:9;anchors.verticalCenter:parent.verticalCenter}
    delegate:ItemDelegate {
        id:option;width:control.width;height:36;text:modelData;font.bold:false
        highlighted:control.highlightedIndex===index
        contentItem:Text {
            objectName:"combo-option-text-"+index
            text:option.text;font:option.font;color:option.highlighted?"#ffffff":"#1b2638"
            textFormat:Text.PlainText;verticalAlignment:Text.AlignVCenter;elide:Text.ElideRight
        }
        background:Rectangle {color:option.highlighted?"#304864":"transparent"}
    }
    popup:Popup {
        y:control.height;width:control.width;padding:1
        background:Rectangle {color:"#f6f9fd";border.color:"#92abc7";radius:4}
        contentItem:ListView {
            implicitHeight:Math.min(control.count*36,320)
            model:control.popup.visible?control.delegateModel:null;clip:true;currentIndex:control.highlightedIndex
            ScrollBar.vertical:ScrollBar {}
        }
    }
}
