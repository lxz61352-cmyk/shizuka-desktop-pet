import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    objectName:"node-"+n.id
    required property var specification
    required property var tableModel
    required property var state
    readonly property var n: specification
    x:Math.max(n.x,n.clip[0]);y:Math.max(n.y,n.clip[1])
    width:Math.max(0,Math.min(n.x+n.width,n.clip[2])-x);height:Math.max(0,Math.min(n.y+n.height,n.clip[3])-y)
    enabled:n.enabled
    clip:true
    property int editSequence:n.ackSequence || 0
    function action(kind,extra) {
        var p=extra || {};p.action=kind;p.widget=n.id
        if(kind==="edit")p.sequence=++editSequence
        state.action(p)
    }
    Loader {
        x:root.n.x-root.x;y:root.n.y-root.y;width:root.n.width;height:root.n.height
        sourceComponent: {
            switch(root.n.kind) {
            case "label":return labelPart
            case "button":return buttonPart
            case "check":return checkPart
            case "radio":return radioPart
            case "field":return fieldPart
            case "combo":return comboPart
            case "slider":return sliderPart
            case "progress":return progressPart
            case "text":return textPart
            case "list":return listPart
            case "canvas":return canvasPart
            case "tabs":return tabsPart
            case "group":return groupPart
            default:return null
            }
        }
    }
    Component {
        id: labelPart
        Item {
            Text {
                anchors.fill:parent;text:root.n.text || "";color:"#f0f5fc";font.family:"Microsoft YaHei UI"
                font.pointSize:root.n.title?16:10;font.bold:true;wrapMode:Text.Wrap;textFormat:Text.PlainText
                verticalAlignment:Text.AlignVCenter
                horizontalAlignment:root.n.align==="center"?Text.AlignHCenter:root.n.align==="e"?Text.AlignRight:Text.AlignLeft
                visible:!root.n.image
            }
            Image {anchors.fill:parent;source:root.n.image || "";fillMode:Image.PreserveAspectFit;asynchronous:true;visible:!!root.n.image}
            MouseArea {anchors.fill:parent;enabled:!!root.n.clickable;cursorShape:Qt.PointingHandCursor;onClicked:function(mouse){var global=mapToGlobal(mouse.x,mouse.y);root.action("event",{sequence:"<Button-1>",x:mouse.x,y:mouse.y,globalX:global.x,globalY:global.y})}}
        }
    }
    Component {id:buttonPart;QtGlassButton {objectName:"button-"+root.n.id;text:root.n.text || "";onClicked:root.action("invoke")}}
    Component {id:checkPart;CheckBox {text:root.n.text || "";checked:!!root.n.checked;font.bold:true;palette.windowText:"#f0f5fc";onClicked:root.action("invoke")}}
    Component {id:radioPart;RadioButton {text:root.n.text || "";checked:!!root.n.checked;autoExclusive:false;font.bold:true;palette.windowText:"#f0f5fc";onClicked:root.action("invoke")}}
    Component {
        id:fieldPart
        QtGlassField {
            id:field;objectName:"field-"+root.n.id;readOnly:!!root.n.readonly
            Component.onCompleted:text=root.n.value || ""
            echoMode:root.n.secret?TextInput.Password:TextInput.Normal
            placeholderText:root.n.hasValue?"已设置，输入可替换":""
            onTextEdited:root.action("edit",{value:text})
            onAccepted:root.action("event",{sequence:"<Return>"})
            onActiveFocusChanged:if(!activeFocus)root.action("event",{sequence:"<FocusOut>"})
            Connections {target:root;function onSpecificationChanged(){if(!root.n.secret && (!field.activeFocus || root.n.ackSequence>=root.editSequence) && field.text!==(root.n.value || ""))field.text=root.n.value || ""}}
            Connections {target:root.state;function onChanged(){if(root.state.meta.focus===root.n.id)field.forceActiveFocus()}}
        }
    }
    Component {
        id:comboPart
        QtGlassCombo {
            id:combo;objectName:"combo-"+root.n.id;model:root.n.choices || [];editable:!!root.n.editable
            currentIndex:model.indexOf(root.n.value);editText:root.n.value || ""
            contentItem:TextField {
                text:combo.editable?combo.editText:combo.displayText;readOnly:!combo.editable
                color:"#f0f5fc";font.bold:true;padding:0;selectByMouse:combo.editable;background:null
                onTextEdited:root.action("edit",{value:text})
                onAccepted:root.action("event",{sequence:"<Return>"})
            }
            onActivated:root.action("edit",{value:currentText})
            onAccepted:root.action("edit",{value:editText})
        }
    }
    Component {id:sliderPart;Slider {from:root.n.low;to:root.n.high;value:root.n.value;onMoved:root.action("edit",{value:value.toString()})}}
    Component {id:progressPart;ProgressBar {from:0;to:root.n.maximum;value:root.n.value;indeterminate:!!root.n.indeterminate}}
    Component {
        id:textPart
        ScrollView {
            id:textScroll
            clip:true
            TextArea {
                id:area;objectName:"text-"+root.n.id;width:parent.width;readOnly:!!root.n.readonly;selectByMouse:true
                Component.onCompleted:text=root.n.value || ""
                color:"#f0f5fc";font.bold:true;wrapMode:TextEdit.Wrap;textFormat:TextEdit.PlainText;leftPadding:10;rightPadding:10
                background:Rectangle {color:"#16203355";border.color:"#667e93";radius:3}
                property bool syncing:false
                property int endSerial:0
                onTextChanged:if(activeFocus && !readOnly && !syncing)root.action("edit",{value:text})
                onSelectedTextChanged:root.action("textSelection",{start:selectionStart,end:selectionEnd})
                Connections {
                    target:root
                    function onSpecificationChanged(){
                        if((!area.activeFocus || root.n.ackSequence>=root.editSequence) && area.text!==(root.n.value || "")){area.syncing=true;area.text=root.n.value || "";area.syncing=false}
                        if(root.n.scrollToEnd>area.endSerial){area.endSerial=root.n.scrollToEnd;Qt.callLater(function(){textScroll.contentItem.contentY=Math.max(0,textScroll.contentItem.contentHeight-textScroll.contentItem.height)})}
                    }
                }
                TapHandler {acceptedButtons:Qt.RightButton;onTapped:textMenu.popup()}
                Menu {
                    id:textMenu
                    font.bold:false
                    MenuItem {text:"复制所选";font.bold:false;enabled:area.selectedText.length>0;onTriggered:controller.copy(area.selectedText)}
                    MenuItem {text:"全选";font.bold:false;onTriggered:area.selectAll()}
                    MenuItem {text:"复制全部";font.bold:false;onTriggered:controller.copy(area.text)}
                }
            }
        }
    }
    Component {
        id:listPart
        Item {
            id:listContainer
            property var selected:root.n.selection || []
            property int anchorIndex:0
            Row {
                id:head;width:parent.width;height:(root.n.headings || []).length?34:0
                Repeater {model:root.n.headings || [];delegate:Text {required property string modelData;width:head.width/Math.max(1,root.n.headings.length);height:head.height;text:modelData;color:"#79d8fa";font.bold:true;elide:Text.ElideRight;textFormat:Text.PlainText;verticalAlignment:Text.AlignVCenter}}
            }
            ListView {
                id:table;anchors.top:head.bottom;anchors.left:parent.left;anchors.right:parent.right;anchors.bottom:parent.bottom
                objectName:"table-"+root.n.id
                clip:true;model:root.tableModel;reuseItems:true;cacheBuffer:80
                ScrollBar.vertical:ScrollBar {}
                delegate:Rectangle {
                    objectName:"row-"+node.id
                    required property var node
                    required property int index
                    width:table.width;height:36;color:root.n.selection.indexOf(node.id)>=0?"#80456886":"#19162433"
                    Row {
                        anchors.fill:parent
                        Repeater {model:node.cells;delegate:Text {required property string modelData;width:table.width/Math.max(1,node.cells.length);height:36;text:modelData;color:"#f0f5fc";font.bold:true;elide:Text.ElideRight;textFormat:Text.PlainText;verticalAlignment:Text.AlignVCenter;leftPadding:6}}
                    }
                    MouseArea {
                        anchors.fill:parent
                        onClicked:function(mouse){var ids=[node.id];if(root.n.multiple && (mouse.modifiers & Qt.ShiftModifier)){ids=root.tableModel.selectionRange(listContainer.anchorIndex,index)}else if(root.n.multiple && (mouse.modifiers & Qt.ControlModifier)){ids=root.n.selection.slice();var i=ids.indexOf(node.id);if(i>=0)ids.splice(i,1);else ids.push(node.id)}else listContainer.anchorIndex=index;root.action("select",{rows:ids})}
                        onDoubleClicked:root.action("double",{row:node.id})
                    }
                }
            }
        }
    }
    Component {
        id:tabsPart
        TabBar {
            currentIndex:root.n.index
            Repeater {model:root.n.choices || [];delegate:TabButton {required property string modelData;required property int index;text:modelData;onClicked:root.action("tab",{index:index});background:Rectangle {color:parent.checked?"#80344860":"#18182433"}}}
        }
    }
    Component {id:groupPart;Rectangle {color:"transparent";border.color:"#52667e";radius:3;Text {x:8;y:0;text:root.n.text;color:"#cad6e6";font.bold:true}}}
    Component {
        id:canvasPart
        Item {
            Repeater {
                model:root.n.items || []
                delegate:Item {
                    id:primitive;required property var modelData
                    x:modelData.x;y:modelData.y;width:modelData.width;height:modelData.height
                    Rectangle {anchors.fill:parent;visible:modelData.kind==="rectangle" || modelData.kind==="oval";radius:modelData.kind==="oval"?Math.min(width,height)/2:0;color:modelData.fill || "transparent";border.color:modelData.outline || "transparent"}
                    Text {anchors.fill:parent;visible:modelData.kind==="text";text:modelData.text || "";color:modelData.fill || "#f0f5fc";font.family:"Microsoft YaHei UI";font.pointSize:10;font.bold:true;wrapMode:Text.Wrap;textFormat:Text.PlainText}
                    Image {anchors.fill:parent;visible:modelData.kind==="image";source:modelData.image || "";asynchronous:true;fillMode:Image.PreserveAspectFit}
                    Rectangle {anchors.centerIn:parent;width:parent.width;height:1;visible:modelData.kind==="line";color:modelData.fill || "#52667e"}
                    MouseArea {
                        anchors.fill:parent;acceptedButtons:Qt.LeftButton|Qt.RightButton
                        onClicked:function(mouse){var global=mapToGlobal(mouse.x,mouse.y);root.action("canvas",{item:modelData.id,right:mouse.button===Qt.RightButton,x:mouse.x+primitive.x,y:mouse.y+primitive.y,globalX:global.x,globalY:global.y})}
                        onDoubleClicked:root.action("canvas",{item:modelData.id,double:true,x:mouseX+primitive.x,y:mouseY+primitive.y})
                    }
                }
            }
            WheelHandler {onWheel:function(event){root.action("scroll",{delta:event.angleDelta.y>0?-3:3});event.accepted=true}}
            ScrollBar {
                anchors.right:parent.right;anchors.top:parent.top;anchors.bottom:parent.bottom
                orientation:Qt.Vertical;visible:!!root.n.scrollable;size:root.n.scrollSize;position:root.n.scrollPosition
                onPositionChanged:if(pressed)root.action("scrollTo",{position:position})
            }
        }
    }
}
