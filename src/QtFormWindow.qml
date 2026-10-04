import QtQuick
import QtQuick.Controls

QtArtWindow {
    id: form
    required property var formState
    windowKind: formState.formId
    title: formState.meta.title || "Shizuka"
    requestedVisible: !!formState.meta.visible && contents.count>0
    externalClose:true
    property bool initialized: false
    property int modelWidth: formState.meta.width || 800
    property int modelHeight: formState.meta.height || 640
    onClosing: function(close) {close.accepted=false;formState.action({action:"close"})}
    // The scene graph resizes immediately. The private layout model follows on
    // a short debounce without touching the background texture or compositor.
    Timer {
        id: resizeLayout;interval:45
        onTriggered: if(form.visible) formState.action({action:"resize",width:form.width,height:form.height})
    }
    onWidthChanged: if(initialized && width!==modelWidth) resizeLayout.restart()
    onHeightChanged: if(initialized && height!==modelHeight) resizeLayout.restart()
    onVisibleChanged: if(visible) {initialized=true;resizeLayout.restart()}
    Item {
        anchors.fill: parent;clip:true
        Repeater {
            id:contents
            model: formState.nodeModel
            delegate: QtFormNode {
                required property var node
                required property var rowModel
                specification: node;tableModel:rowModel;state:form.formState
            }
        }
    }
}
