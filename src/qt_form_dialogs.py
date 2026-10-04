"""Native Qt file/confirmation dialogs, centred on the primary monitor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog,QMessageBox

class Dialogs:
    def __init__(self,app,emit):self.app=app;self.emit=emit;self.active={}
    def show(self,message,parent=None):
        ident=message['dialog'];kind=message['kind'];options=message.get('options',{})
        try:
            if kind=='Message':
                dialog=QMessageBox();dialog.setText(str(options.get('message','')));dialog.setInformativeText(str(options.get('detail','')))
                icon={'info':QMessageBox.Information,'warning':QMessageBox.Warning,'error':QMessageBox.Critical,'question':QMessageBox.Question}.get(options.get('icon'),QMessageBox.Information)
                dialog.setIcon(icon)
                names={'ok':['ok'],'okcancel':['ok','cancel'],'yesno':['yes','no'],'yesnocancel':['yes','no','cancel'],'retrycancel':['retry','cancel'],'abortretryignore':['abort','retry','ignore']}.get(options.get('type','ok'),['ok'])
                buttons={'ok':QMessageBox.Ok,'cancel':QMessageBox.Cancel,'yes':QMessageBox.Yes,'no':QMessageBox.No,'retry':QMessageBox.Retry,'abort':QMessageBox.Abort,'ignore':QMessageBox.Ignore}
                flags=QMessageBox.NoButton
                for name in names:flags|=buttons[name]
                dialog.setStandardButtons(flags)
                dialog.setDefaultButton(buttons['no' if 'no' in names else 'cancel' if 'cancel' in names else names[0]])
                def value(result):return next((name for name,button in buttons.items() if int(button)==result),'cancel')
            else:
                dialog=QFileDialog();dialog.setOption(QFileDialog.DontUseNativeDialog,True);dialog.setDirectory(str(options.get('initialdir','')))
                if options.get('initialfile'):dialog.selectFile(str(options['initialfile']))
                if options.get('filetypes'):dialog.setNameFilters([str(label)+' ('+(' '.join(pattern) if isinstance(pattern,(tuple,list)) else str(pattern)) +')' for label,pattern in options['filetypes']])
                if kind=='SaveAs':
                    dialog.setAcceptMode(QFileDialog.AcceptSave);dialog.setFileMode(QFileDialog.AnyFile)
                    dialog.setDefaultSuffix(str(options.get('defaultextension','')).lstrip('.'))
                elif kind=='Directory':dialog.setFileMode(QFileDialog.Directory)
                else:dialog.setFileMode(QFileDialog.ExistingFiles if options.get('multiple') else QFileDialog.ExistingFile)
                def value(result):
                    files=dialog.selectedFiles() if result else []
                    return files if options.get('multiple') else files[0] if files else ''
            dialog.setWindowTitle(str(options.get('title','Shizuka')));dialog.setWindowModality(Qt.ApplicationModal)
            dialog.setWindowFlag(Qt.WindowStaysOnTopHint,True)
            dialog.setWindowIcon(self.app.windowIcon())
            self.active[ident]=dialog
            def finished(result):
                self.emit(dict(type='form_dialog_result',dialog=ident,ok=True,value=value(result)))
                self.active.pop(ident,None);dialog.deleteLater()
            dialog.finished.connect(finished)
            dialog.ensurePolished();dialog.adjustSize()
            dialog.winId();dialog.windowHandle().setScreen(self.app.primaryScreen())
            if parent:dialog.windowHandle().setTransientParent(parent)
            area=self.app.primaryScreen().availableGeometry()
            dialog.move(area.x()+max(0,(area.width()-dialog.width())//2),area.y()+max(0,(area.height()-dialog.height())//2))
            dialog.open()
        except Exception as error:self.emit(dict(type='form_dialog_result',dialog=ident,ok=False,error=str(error)))
