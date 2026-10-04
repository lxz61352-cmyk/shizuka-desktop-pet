import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

QtObject {
    property list<QtObject> tools: [
    QtArtWindow {
        id:historyWindow;objectName:"history";windowKind:"history"
        title:"Shizuka · 对话记录";width:900;height:720;minimumWidth:620;minimumHeight:460
        requestedVisible:controller.historyVisible
        ColumnLayout {
            anchors.fill:parent;anchors.margins:22;spacing:12
            RowLayout {
                Layout.fillWidth:true
                Text {text:"对话记录";color:"#f0f5fc";font.pointSize:16;font.bold:true}
                Item {Layout.fillWidth:true}
                QtGlassButton {text:"换张背景";onClicked:controller.request("background",{window:"history"})}
                QtGlassButton {text:"反馈记录";onClicked:controller.request("feedback",{})}
                QtGlassButton {text:"继续聊";primary:true;onClicked:controller.request("chat",{})}
            }
            Rectangle {Layout.fillWidth:true;height:1;color:"#79d8fa";opacity:.7}
            RowLayout {
                Layout.fillWidth:true
                QtGlassField {id:historyQuery;objectName:"historyQuery";Layout.fillWidth:true;placeholderText:"搜索消息";onTextChanged:historySearch.restart();onAccepted:historySearch.triggered()}
                QtGlassCombo {
                    id:historyMode;Layout.preferredWidth:145;model:["对话","通知","全部记录"]
                    currentIndex:model.indexOf(controller.historyMode)
                    onActivated:controller.filterHistory(historyQuery.text,currentText)
                }
                QtGlassButton {text:"刷新";onClicked:controller.request("refresh",{})}
            }
            Timer {id:historySearch;interval:140;onTriggered:{historyList.following=historyQuery.text.trim()==="";controller.filterHistory(historyQuery.text,historyMode.currentText);if(historyQuery.text)historyList.positionViewAtBeginning()}}
            QtMessageList {id:historyList;objectName:"historyList";Layout.fillWidth:true;Layout.fillHeight:true;model:historyModel}
            RowLayout {
                Layout.fillWidth:true
                Text {text:controller.historyCount+" 条记录 · 前后文按钮展开同渠道内容";color:"#cad6e6";font.bold:true;Layout.fillWidth:true;elide:Text.ElideRight}
                QtGlassButton {text:"复制全部";onClicked:controller.copyHistory()}
            }
            Text {text:controller.statusText;color:"#cad6e6";visible:text!=="";Layout.fillWidth:true;wrapMode:Text.Wrap}
        }
    },
    QtArtWindow {
        id:todoWindow;objectName:"todos";windowKind:"todos"
        title:"Shizuka · 待办";width:950;height:740;minimumWidth:680;minimumHeight:500
        requestedVisible:controller.todosVisible
        ColumnLayout {
            anchors.fill:parent;anchors.margins:22;spacing:12
            RowLayout {
                Layout.fillWidth:true
                Text {text:"一起安排好";color:"#f0f5fc";font.pointSize:16;font.bold:true}
                Item {Layout.fillWidth:true}
                QtGlassButton {text:"＋ 新建待办";primary:true;onClicked:controller.request("edit",{})}
                QtGlassButton {text:"编辑 / 时间";enabled:controller.selectedId!=="";onClicked:controller.request("edit",{id:controller.selectedId})}
                QtGlassButton {text:"刷新";onClicked:controller.request("refresh",{})}
            }
            Rectangle {Layout.fillWidth:true;height:1;color:"#79d8fa";opacity:.7}
            RowLayout {
                Layout.fillWidth:true
                Repeater {
                    model:["生活","研究","已完成"]
                    QtGlassButton {required property string modelData;text:modelData;primary:controller.todoCategory===modelData;onClicked:controller.filterTodos(todoQuery.text,modelData)}
                }
                QtGlassField {id:todoQuery;objectName:"todoQuery";Layout.fillWidth:true;placeholderText:"搜索标题、备注";onTextChanged:todoSearch.restart()}
            }
            Timer {id:todoSearch;interval:140;onTriggered:controller.filterTodos(todoQuery.text,controller.todoCategory)}
            ListView {
                id:todoList;objectName:"todoList";Layout.fillWidth:true;Layout.fillHeight:true
                model:todoModel;clip:true;reuseItems:true;cacheBuffer:180;spacing:8
                property int liveDelegates:0
                property int maxDelegates:0
                ScrollBar.vertical:ScrollBar {}
                delegate:Rectangle {
                    id:task
                    required property string rowId
                    required property string message
                    required property string schedule
                    required property string channels
                    required property string status
                    width:todoList.width-14;height:Math.max(78,taskLines.implicitHeight+24);radius:7
                    color:controller.selectedId===rowId?"#60456c96":"#16202d40"
                    border.color:controller.selectedId===rowId?"#79d8fa":"#52667e"
                    Component.onCompleted:{todoList.liveDelegates++;todoList.maxDelegates=Math.max(todoList.maxDelegates,todoList.liveDelegates)}
                    Component.onDestruction:todoList.liveDelegates--
                    Column {
                        id:taskLines;anchors.left:parent.left;anchors.right:parent.right;anchors.margins:12;anchors.verticalCenter:parent.verticalCenter;spacing:7
                        Text {width:parent.width;text:task.message;color:"#f0f5fc";font.bold:true;elide:Text.ElideRight}
                        Text {width:parent.width;text:task.schedule+" · "+task.channels;color:"#cad6e6";font.bold:true;elide:Text.ElideRight}
                        Text {width:parent.width;text:task.status;color:"#79d8fa";font.bold:true;elide:Text.ElideRight}
                    }
                    MouseArea {anchors.fill:parent;onClicked:controller.selectTodo(task.rowId);onDoubleClicked:controller.request("edit",{id:task.rowId})}
                }
                Text {anchors.centerIn:parent;visible:controller.todoCount===0;text:"这里还没有待办";color:"#cad6e6";font.bold:true}
            }
            ScrollView {
                Layout.fillWidth:true;Layout.preferredHeight:110;clip:true
                TextArea {
                    text:controller.selectedTodo.id?(controller.selectedTodo.title+"\n"+controller.selectedTodo.schedule+(controller.selectedTodo.note?"\n\n备注："+controller.selectedTodo.note:"")+(controller.selectedTodo.notes?"\n\n对话中的补充：\n"+controller.selectedTodo.notes:"")):"选中事项查看备注"
                    readOnly:true;selectByMouse:true;wrapMode:TextEdit.Wrap;color:"#f0f5fc";font.bold:true
                    background:Rectangle {color:"#10202d40";radius:5;border.color:"#52667e"}
                }
            }
            Flow {
                Layout.fillWidth:true;Layout.preferredHeight:childrenRect.height;spacing:8
                QtGlassButton {text:controller.selectedTodo.done?"恢复":controller.selectedTodo.recurring?"完成本次":"完成";enabled:controller.selectedId!=="";onClicked:controller.request("done",{id:controller.selectedId})}
                QtGlassButton {text:"结束循环";visible:controller.selectedTodo.recurring&&!controller.selectedTodo.done;onClicked:endConfirm.open()}
                QtGlassButton {text:"稍后 / 专注";enabled:controller.selectedId!==""&&!controller.selectedTodo.done;onClicked:quickPopup.open()}
                QtGlassButton {text:"删除";enabled:controller.selectedId!=="";onClicked:deleteConfirm.open()}
                QtGlassButton {text:"重试微信提醒";enabled:["failed","uncertain","waiting"].indexOf(controller.selectedTodo.retry_state)>=0;onClicked:controller.selectedTodo.retry_state==="uncertain"?retryConfirm.open():controller.request("retry",{id:controller.selectedId})}
            }
            Text {Layout.fillWidth:true;text:controller.todoCount+" 件 · "+controller.statusText;color:"#cad6e6";wrapMode:Text.Wrap}
        }
        Dialog {id:deleteConfirm;title:"删除待办";modal:true;font.bold:false;standardButtons:Dialog.Yes|Dialog.No;anchors.centerIn:parent;onAccepted:controller.request("delete",{id:controller.selectedId});Label {text:"删除选中的待办及其提醒？";font.bold:false}}
        Dialog {id:endConfirm;title:"结束循环";modal:true;font.bold:false;standardButtons:Dialog.Yes|Dialog.No;anchors.centerIn:parent;onAccepted:controller.request("end_series",{id:controller.selectedId});Label {text:"结束此事项的后续循环？";font.bold:false}}
        Dialog {id:retryConfirm;title:"核对微信";modal:true;font.bold:false;standardButtons:Dialog.Yes|Dialog.No;anchors.centerIn:parent;onAccepted:controller.request("retry",{id:controller.selectedId,confirmed:true});Label {width:320;text:"上次发送结果不确定，请先核对微信。再次发送可能收到重复提醒，仍要重试吗？";wrapMode:Text.Wrap;font.bold:false}}
        Popup {
            id:quickPopup;anchors.centerIn:parent;padding:16
            background:Rectangle {color:"#e0142c46";radius:7;border.color:"#52667e"}
            Column {
                spacing:10
                QtGlassButton {text:"10分钟后提醒";onClicked:{controller.request("snooze",{id:controller.selectedId,minutes:10});quickPopup.close()}}
                QtGlassButton {text:"30分钟后提醒";onClicked:{controller.request("snooze",{id:controller.selectedId,minutes:30});quickPopup.close()}}
                QtGlassButton {text:"开始专注";onClicked:{controller.request("focus",{id:controller.selectedId});quickPopup.close()}}
                QtGlassButton {text:"其他快捷处理";onClicked:{controller.request("quick",{id:controller.selectedId});quickPopup.close()}}
            }
        }
    },
    QtArtWindow {
        id:editor;objectName:"editor";windowKind:"editor"
        title:controller.editingId?"编辑待办":"新建待办";width:660;height:Math.min(780,Screen.desktopAvailableHeight-70);minimumWidth:580;minimumHeight:530
        requestedVisible:controller.editorVisible
        property var repeats:["不重复","每天","每周","每月","工作日","每天直到完成"]
        property var modes:["未安排时间","指定时间","下次启动"]
        function quick(minutes) {var d=new Date(Date.now()+minutes*60000);modeBox.currentIndex=1;dateBox.text=Qt.formatDate(d,"yyyy-MM-dd");hourBox.text=Qt.formatTime(d,"HH");minuteBox.text=Qt.formatTime(d,"mm");leadBox.text="0"}
        function values() {return {title:titleBox.text,note:noteBox.text,category:categoryBox.currentText,repeat:repeatBox.currentText,mode:modeBox.currentText,date:dateBox.text,hour:hourBox.text,minute:minuteBox.text,lead:leadBox.text,interval:intervalBox.text,desktop:desktopBox.checked,weixin:weixinBox.checked}}
        Connections {
            target:controller
            function onEditorOpened() {
                var v=controller.editorInitial
                titleBox.text=v.title;noteBox.text=v.note;categoryBox.currentIndex=["生活","研究"].indexOf(v.category)
                repeatBox.currentIndex=editor.repeats.indexOf(v.repeat);modeBox.currentIndex=editor.modes.indexOf(v.mode)
                dateBox.text=v.date;hourBox.text=v.hour;minuteBox.text=v.minute;leadBox.text=v.lead;intervalBox.text=v.interval
                desktopBox.checked=v.desktop;weixinBox.checked=v.weixin
                titleBox.forceActiveFocus()
            }
        }
        ColumnLayout {
            anchors.fill:parent;anchors.margins:22;spacing:12
            Text {text:editor.title;color:"#f0f5fc";font.pointSize:16;font.bold:true}
            Rectangle {Layout.fillWidth:true;height:1;color:"#79d8fa";opacity:.7}
            ScrollView {
                Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth
                ColumnLayout {
                    width:parent.width;spacing:10
                    Text {text:"标题";color:"#cad6e6";font.bold:true}
                    TextArea {id:titleBox;objectName:"todoTitle";Layout.fillWidth:true;Layout.preferredHeight:72;wrapMode:TextEdit.Wrap;selectByMouse:true;color:"#f0f5fc";font.bold:true;background:Rectangle {color:"#18202d40";radius:5;border.color:"#52667e"}}
                    Text {text:"备注";color:"#cad6e6";font.bold:true}
                    TextArea {id:noteBox;objectName:"todoNote";Layout.fillWidth:true;Layout.preferredHeight:115;wrapMode:TextEdit.Wrap;selectByMouse:true;color:"#f0f5fc";font.bold:true;background:Rectangle {color:"#18202d40";radius:5;border.color:"#52667e"}}
                    RowLayout {
                        Layout.fillWidth:true
                        Text {text:"用途";color:"#cad6e6";font.bold:true}
                        QtGlassCombo {id:categoryBox;model:["生活","研究"];Layout.preferredWidth:110}
                        Text {text:"重复";color:"#cad6e6";font.bold:true}
                        QtGlassCombo {id:repeatBox;model:editor.repeats;Layout.fillWidth:true;onActivated:{if(currentIndex>0)modeBox.currentIndex=1;if(currentText==="每天直到完成"){hourBox.text="09";minuteBox.text="00";leadBox.text="0";intervalBox.text="1"}}}
                    }
                    RowLayout {Layout.fillWidth:true;Text {text:"事项时间";color:"#cad6e6";font.bold:true}QtGlassCombo {id:modeBox;model:editor.modes;Layout.fillWidth:true}}
                    RowLayout {
                        Layout.fillWidth:true;enabled:modeBox.currentIndex===1
                        QtGlassField {id:dateBox;Layout.fillWidth:true;placeholderText:"YYYY-MM-DD"}
                        QtGlassButton {text:"选日期";onClicked:calendarPopup.open()}
                        QtGlassField {id:hourBox;Layout.preferredWidth:52;validator:IntValidator {bottom:0;top:23}}
                        Text {text:":";color:"#cad6e6"}
                        QtGlassField {id:minuteBox;Layout.preferredWidth:52;validator:IntValidator {bottom:0;top:59}}
                    }
                    RowLayout {
                        Layout.fillWidth:true
                        Text {text:"提前";color:"#cad6e6";font.bold:true}
                        QtGlassField {id:leadBox;enabled:modeBox.currentIndex===1;Layout.preferredWidth:72;validator:IntValidator {bottom:0;top:43200}}
                        Text {text:"分钟提醒";color:"#cad6e6";font.bold:true}
                        Item {Layout.fillWidth:true}
                        Text {text:"周期间隔";color:"#cad6e6";font.bold:true}
                        QtGlassField {id:intervalBox;enabled:[1,2,3].indexOf(repeatBox.currentIndex)>=0;Layout.preferredWidth:62;validator:IntValidator {bottom:1;top:366}}
                    }
                    RowLayout {QtGlassButton {text:"30分钟后";onClicked:editor.quick(30)}QtGlassButton {text:"1小时后";onClicked:editor.quick(60)}}
                    RowLayout {CheckBox {id:desktopBox;text:"桌面提醒";font.bold:true;palette.windowText:"#f0f5fc"}CheckBox {id:weixinBox;text:"微信提醒";font.bold:true;palette.windowText:"#f0f5fc"}}
                }
            }
            Text {Layout.fillWidth:true;text:controller.statusText;color:"#cad6e6";wrapMode:Text.Wrap}
            RowLayout {
                Layout.fillWidth:true;Item {Layout.fillWidth:true}
                QtGlassButton {text:"取消";enabled:!controller.isSaving;onClicked:controller.close("editor")}
                QtGlassButton {objectName:"todoSave";text:controller.isSaving?"保存中…":"保存";primary:true;enabled:!controller.isSaving;onClicked:controller.save(editor.values())}
            }
        }
        Popup {
            id:calendarPopup;anchors.centerIn:parent;padding:14
            property int year:new Date().getFullYear()
            property int month:new Date().getMonth()
            readonly property int first:(new Date(year,month,1).getDay()+6)%7
            readonly property int days:new Date(year,month+1,0).getDate()
            onOpened:{var d=new Date(dateBox.text+"T12:00:00");if(!isNaN(d.getTime())){year=d.getFullYear();month=d.getMonth()}}
            function shift(n) {var d=new Date(year,month+n,1);year=d.getFullYear();month=d.getMonth()}
            background:Rectangle {color:"#f0142c46";radius:8;border.color:"#52667e"}
            Column {
                spacing:10
                Row {spacing:16;QtGlassButton {text:"‹";onClicked:calendarPopup.shift(-1)}Text {text:calendarPopup.year+"年 "+(calendarPopup.month+1)+"月";color:"#f0f5fc";height:38;verticalAlignment:Text.AlignVCenter}QtGlassButton {text:"›";onClicked:calendarPopup.shift(1)}}
                GridLayout {
                    columns:7;rowSpacing:4;columnSpacing:4
                    Repeater {model:["一","二","三","四","五","六","日"];Text {required property string modelData;text:modelData;Layout.preferredWidth:36;color:"#cad6e6";horizontalAlignment:Text.AlignHCenter}}
                    Repeater {
                        model:42
                        QtGlassButton {
                            required property int index
                            property int day:index-calendarPopup.first+1
                            Layout.preferredWidth:36;Layout.preferredHeight:32;padding:3
                            text:day>0&&day<=calendarPopup.days?String(day):"";enabled:text!==""
                            onClicked:{dateBox.text=Qt.formatDate(new Date(calendarPopup.year,calendarPopup.month,day),"yyyy-MM-dd");calendarPopup.close()}
                        }
                    }
                }
            }
        }
    },
    QtArtWindow {
        id:contextWindow;objectName:"context";windowKind:"context"
        title:"Shizuka · 对话前后文";width:880;height:680;minimumWidth:620;minimumHeight:460
        requestedVisible:controller.contextVisible
        ColumnLayout {
            anchors.fill:parent;anchors.margins:22;spacing:12
            Text {text:"对话前后文";color:"#f0f5fc";font.pointSize:16;font.bold:true}
            Text {text:"已定位选中消息，仅展开同一渠道的记录。";color:"#cad6e6";Layout.fillWidth:true;wrapMode:Text.Wrap}
            QtMessageList {id:contextList;objectName:"contextList";Layout.fillWidth:true;Layout.fillHeight:true;model:contextModel;following:false;currentIndex:controller.contextFocusIndex;highlight:Rectangle {color:"#20456c96";radius:5;border.color:"#79d8fa"}}
            RowLayout {
                Layout.fillWidth:true
                QtGlassButton {text:"更早的20条";enabled:controller.hasOlder;onClicked:controller.moreContext(-1)}
                QtGlassButton {text:"后面的20条";enabled:controller.hasNewer;onClicked:controller.moreContext(1)}
                Item {Layout.fillWidth:true}
                QtGlassButton {text:"关闭";onClicked:controller.close("context")}
            }
        }
        Connections {target:controller;function onContextOpened(){Qt.callLater(function(){contextList.positionViewAtIndex(controller.contextFocusIndex,ListView.Center)})}}
    }
    ]
}
