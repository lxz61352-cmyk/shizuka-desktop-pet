import QtQuick
import QtQuick.Controls
ListView {
    id:list
    property bool following: true
    property real savedY: 0
    property int liveDelegates: 0
    property int maxDelegates: 0
    clip:true;reuseItems:true;cacheBuffer:240;spacing:22
    boundsBehavior:Flickable.StopAtBounds
    ScrollBar.vertical:ScrollBar {}
    onMovementEnded: following=contentY>=contentHeight-height-30
    Connections {
        target:list.model
        function onModelAboutToBeReset() {list.savedY=list.contentY}
        function onModelReset() {Qt.callLater(function(){if(list.following)list.positionViewAtEnd();else list.contentY=Math.min(list.savedY,Math.max(0,list.contentHeight-list.height))})}
    }
    delegate:Column {
        id:entry
        required property string rowId
        required property string message
        required property string heading
        required property string stamp
        required property string kind
        width:list.width-14;spacing:9
        Component.onCompleted:{list.liveDelegates++;list.maxDelegates=Math.max(list.maxDelegates,list.liveDelegates)}
        Component.onDestruction:list.liveDelegates--
        ListView.onReused:{body.deselect();context.close()}
        Row {
            width:parent.width
            Text {width:parent.width*.45;text:entry.heading;color:entry.heading==="你"?"#79d8fa":"#f0f5fc";font.bold:true}
            Text {width:parent.width*.55;text:entry.stamp;color:"#cad6e6";horizontalAlignment:Text.AlignRight;font.bold:true}
        }
        TextEdit {
            id:body;width:parent.width;text:entry.message;textFormat:TextEdit.PlainText
            readOnly:true;selectByMouse:true;wrapMode:TextEdit.Wrap;color:"#f0f5fc"
            font.family:"Microsoft YaHei UI";font.pointSize:10;font.bold:true
            selectionColor:"#365b7a";selectedTextColor:"#f0f5fc"
            MouseArea {anchors.fill:parent;acceptedButtons:Qt.RightButton;onClicked:context.popup()}
            Menu {
                id:context;font.bold:false
                MenuItem {text:"复制所选";enabled:body.selectedText.length>0;onTriggered:body.copy()}
                MenuItem {text:"复制整条";onTriggered:controller.copy(entry.message)}
                MenuItem {text:entry.kind==="notification"?"查看通知":"展开前后文";onTriggered:entry.kind==="notification"?controller.request("notice",{id:entry.rowId}):controller.openContext(entry.rowId)}
                MenuItem {text:"反馈这条回复";visible:entry.heading==="静香";onTriggered:controller.request("feedback",{id:entry.rowId})}
            }
        }
        Row {
            spacing:8
            QtGlassButton {text:entry.kind==="notification"?"查看通知":"前后文";padding:5;onClicked:entry.kind==="notification"?controller.request("notice",{id:entry.rowId}):controller.openContext(entry.rowId)}
            QtGlassButton {text:"反馈";padding:5;visible:entry.heading==="静香";onClicked:controller.request("feedback",{id:entry.rowId})}
        }
        Rectangle {width:parent.width;height:1;color:"#52667e";opacity:.7}
    }
}
