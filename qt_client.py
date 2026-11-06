"""Independent Qt client using the existing VideoFlow service layer."""
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Slot, QTimer, QUrl
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QStackedWidget, QPushButton, QLabel, QTableWidgetItem,
    QMessageBox, QDialog, QDialogButtonBox,
)

from app_config import load_settings, save_settings, settings_path
import local_logger
from task_store import TaskStore
from license_client import LICENSE_SERVER_URL, verify_license
from qt_voice_preview import QtVoiceWindow, Job, STYLE, card, label
from qt_client_pages import ProcessPage, SettingsPage, LibraryPage, RenamePage, button, folder_row, table
from qt_controls import LineEdit as QLineEdit


from qt_theme import CLIENT_STYLE


class VideoFlowQt(QMainWindow):
    def __init__(self, config_path=None):
        super().__init__()
        self.setWindowTitle('VideoFlow · Qt 智能工作台')
        self.resize(1380,1000)
        self.setMinimumSize(1170,850)
        self.config_path=config_path
        self.settings=load_settings(config_path)
        local_logger.register_secrets(self.settings)
        history_path=(Path(config_path).parent if config_path else settings_path().parent)/'qt-task-history.json'
        self.history=TaskStore(history_path)
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(8)
        self.jobs=[];self.pages={};self.voice_window=None
        self._build()
        self.setStyleSheet(CLIENT_STYLE)

    def _build(self):
        surface=QWidget();surface.setObjectName('surface');self.setCentralWidget(surface)
        layout=QHBoxLayout(surface);layout.setContentsMargins(20,20,20,20);layout.setSpacing(22)
        sidebar=QVBoxLayout();sidebar.setSpacing(16);brand=label('VideoFlow','brand');sidebar.addWidget(brand);sidebar.addWidget(label('视频创作工作台','muted'))
        self.navigation=QListWidget();self.navigation.setObjectName('navigation');self.navigation.setFixedWidth(190)
        self.navigation.addItems(['01   下载视频','02   文案与 SRT','03   生成答案','04   AI 改写','05   语音转出','06   资源库','     同步重命名','     任务记录','     接口与配置'])
        sidebar.addWidget(self.navigation,1);sidebar.addWidget(label('API 模式 · 本地保存配置','muted'));layout.addLayout(sidebar)
        content=QVBoxLayout();content.setSpacing(16);layout.addLayout(content,1)
        header,head=card();content.addWidget(header)
        top=QHBoxLayout();self.heading=label('下载视频','brand');top.addWidget(self.heading);top.addStretch();head.addLayout(top)
        output_row=QHBoxLayout();output_row.addWidget(label('工作目录','muted'))
        self.project,project_row=folder_row(self.settings.get('output_directory',''),self.project_changed)
        self.project.editingFinished.connect(self.project_changed);output_row.addLayout(project_row,1);head.addLayout(output_row)
        self.stack=QStackedWidget();content.addWidget(self.stack,1)
        for kind in ('download','transcribe','answers','rewrite'):
            page=ProcessPage(self,kind);self.pages[kind]=page;self.stack.addWidget(page)
        self.voice_placeholder=QWidget();placeholder_layout=QVBoxLayout(self.voice_placeholder);placeholder_layout.addWidget(label('正在准备语音转出…','muted'));self.stack.addWidget(self.voice_placeholder)
        library=LibraryPage(self);self.pages['library']=library;self.stack.addWidget(library)
        rename=RenamePage(self);self.pages['rename']=rename;self.stack.addWidget(rename)
        history=QWidget();history_layout=QVBoxLayout(history);history_layout.setContentsMargins(0,0,0,0)
        tools=QHBoxLayout();tools.addWidget(button('刷新记录',self.refresh_history));tools.addStretch();tools.addWidget(button('打开任务目录',self.open_history_output));history_layout.addLayout(tools)
        self.history_table=table(['时间','任务','状态','输出目录']);self.history_table.setEditTriggers(self.history_table.EditTrigger.NoEditTriggers);history_layout.addWidget(self.history_table);self.stack.addWidget(history)
        self.settings_page=SettingsPage(self);self.pages['settings']=self.settings_page;self.stack.addWidget(self.settings_page)
        self.footer=label('就绪','muted');content.addWidget(self.footer)
        self.navigation.currentRowChanged.connect(self.navigate)
        initial=self.settings.get('qt_last_page',0)
        self.navigation.setCurrentRow(initial if isinstance(initial,int) and 0<=initial<9 else 0)
        self.refresh_history()

    def project_path(self):return self.project.text().strip()

    def project_changed(self):
        root=self.project_path()
        if root:
            from qt_workflow_service import STEPS
            for kind in ('download','transcribe','answers','rewrite'):
                self.pages[kind].output.setText(str(Path(root)/STEPS[kind]))
            if 'rename' in self.pages:self.pages['rename'].folder.setText(str(Path(root)/STEPS['download']))
        self.save_configuration()

    def navigate(self,index):
        if index==4 and self.voice_window is None:
            self.voice_window=QtVoiceWindow()
            widget=self.voice_window.takeCentralWidget()
            # The workspace already supplies a header and background.
            voice_layout=widget.layout()
            old_header=voice_layout.takeAt(0).layout()
            while old_header.count():
                item=old_header.takeAt(0)
                if item.widget():item.widget().hide()
                if item.layout():
                    while item.layout().count():
                        child=item.layout().takeAt(0)
                        if child.widget():child.widget().hide()
            voice_layout.setContentsMargins(0,0,0,0)
            if self.project_path():self.voice_window.output.setText(str(Path(self.project_path())/'5_语音转出'))
            self.stack.removeWidget(self.voice_placeholder);self.voice_placeholder.deleteLater()
            self.stack.insertWidget(4,widget)
        self.stack.setCurrentIndex(index)
        if index>=0:self.heading.setText(self.navigation.item(index).text().strip())
        if index==7:self.refresh_history()

    def save_configuration(self,*_):
        # Merge with disk first: retain settings owned by the existing client.
        values=load_settings(self.config_path)
        values.update(self.settings)
        values['output_directory']=self.project_path()
        if hasattr(self,'settings_page'):values.update(self.settings_page.values())
        for kind in ('download','transcribe','answers','rewrite'):
            values['qt_'+kind+'_output']=self.pages[kind].output.text()
        values['source_lang']=self.pages['transcribe'].language.currentText()
        values['download_quality']=self.pages['download'].quality.currentText()
        values['qt_last_page']=self.navigation.currentRow()
        save_settings(values,self.config_path);self.settings=values;local_logger.register_secrets(values)
        if hasattr(self,'footer'):self.footer.setText('配置已保存')

    def start_job(self,function,finished,error=None,progress=None):
        job=Job(function);self.jobs.append(job)
        job.signals.done.connect(finished)
        job.signals.error.connect(error or self.show_error)
        if progress:job.signals.progress.connect(progress)
        self.pool.start(job)

    @Slot(str)
    def show_error(self,text):
        self.footer.setText(text);local_logger.error('qt task failed: %s',text)

    def refresh_history(self):
        if not hasattr(self,'history_table'):return
        tasks=self.history.list();self.history_table.setRowCount(len(tasks))
        for row,task in enumerate(tasks):
            for column,value in enumerate([task.get('created_at',''),task.get('title',''),task.get('status',''),task.get('output_dir','')]):
                item=QTableWidgetItem(str(value));item.setToolTip(str(value));self.history_table.setItem(row,column,item)

    def open_history_output(self):
        row=self.history_table.currentRow()
        if row>=0:
            folder=self.history_table.item(row,3).text()
            if Path(folder).is_dir():QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def closeEvent(self,event):
        voice_active=self.voice_window is not None and self.voice_window.pool.activeThreadCount()
        if self.pool.activeThreadCount() or voice_active:
            self.footer.setText('任务正在进行，请等待完成后退出。下载任务如已暂停，请先继续。');event.ignore();return
        try:self.save_configuration()
        except OSError as exc:QMessageBox.warning(self,'配置保存失败',str(exc));event.ignore();return
        if self.voice_window is not None:self.voice_window.close()
        self.history.flush();event.accept()


class LicenseDialog(QDialog):
    def __init__(self,config_path=None):
        super().__init__();self.config_path=config_path;self.saved=load_settings(config_path)
        self.pool=QThreadPool(self);self.job=None;self.validated=False
        self.setWindowTitle('VideoFlow · 授权验证');self.setFixedWidth(440);self.setStyleSheet(CLIENT_STYLE)
        layout=QVBoxLayout(self);layout.setContentsMargins(28,28,28,28);layout.setSpacing(16)
        layout.addWidget(label('启动授权验证','brand'));layout.addWidget(label('验证通过后进入 Qt 客户端。','muted'))
        self.key=QLineEdit(str(self.saved.get('license_key','')));self.key.setPlaceholderText('请输入卡密');self.key.setEchoMode(QLineEdit.EchoMode.Password);layout.addWidget(self.key)
        self.status=label('','muted');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.submit=button('验证并进入',self.verify,True);layout.addWidget(self.submit);self.key.returnPressed.connect(self.verify)

    def verify(self):
        key=self.key.text().strip()
        if not key:self.status.setText('请输入卡密');return
        self.submit.setEnabled(False);self.key.setEnabled(False);self.status.setText('正在验证…')
        self.job=Job(lambda _:verify_license(LICENSE_SERVER_URL,key))
        self.job.signals.done.connect(self.checked);self.job.signals.error.connect(self.failed);self.pool.start(self.job)

    @Slot(object)
    def checked(self,result):
        valid,message=result
        if not valid:self.failed(message);return
        try:
            saved=load_settings(self.config_path);saved['license_key']=self.key.text().strip();save_settings(saved,self.config_path)
        except OSError as exc:self.failed(str(exc));return
        self.validated=True;self.accept()

    @Slot(str)
    def failed(self,text):self.status.setText(text);self.submit.setEnabled(True);self.key.setEnabled(True)

    def reject(self):
        if self.pool.activeThreadCount():self.status.setText('正在验证，请稍候…');return
        super().reject()


def main():
    local_logger.install_exception_hooks()
    app=QApplication(sys.argv);app.setFont(QFont('Microsoft YaHei UI',9));app.setStyle('Fusion')
    # Keep the main window hidden until the existing license service verifies it.
    dialog=LicenseDialog()
    if dialog.key.text().strip():QTimer.singleShot(0,dialog.verify)
    if dialog.exec()!=QDialog.DialogCode.Accepted or not dialog.validated:return 0
    window=VideoFlowQt();window.show();return app.exec()


if __name__=='__main__':sys.exit(main())
