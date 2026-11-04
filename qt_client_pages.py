"""Qt workflow pages; all network and media work runs outside the UI thread."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QPushButton, QLabel, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QProgressBar, QSplitter, QMessageBox,
    QScrollArea, QAbstractItemView, QDialog, QDialogButtonBox,
)

import ai
import downloader_service
import rename_service
import asr
from qt_voice_preview import card, label
from qt_workflow_service import Workflow, STEPS, DEFAULT_URL, DEFAULT_MODEL, copy_library
from rewrite_batch_service import immediate_retry
from text_io import read_text, write_text


def button(text, callback, primary=False):
    result = QPushButton(text)
    if primary:
        result.setObjectName('primary')
    result.clicked.connect(callback)
    return result


def folder_row(initial='', callback=None):
    layout = QHBoxLayout()
    edit = QLineEdit(str(initial))
    layout.addWidget(edit,1)
    def choose():
        path = QFileDialog.getExistingDirectory(edit, '选择目录', edit.text())
        if path:
            edit.setText(path)
            if callback: callback()
    layout.addWidget(button('选择',choose))
    layout.addWidget(button('打开',lambda:open_folder(edit.text())))
    return edit,layout


def open_folder(value):
    if value.strip():
        folder = Path(value).expanduser().resolve()
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def table(headers):
    result = QTableWidget(0,len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.verticalHeader().hide()
    result.verticalHeader().setDefaultSectionSize(48)
    result.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    result.setAlternatingRowColors(True)
    result.setWordWrap(False)
    return result


class ProcessPage(QWidget):
    def __init__(self, host, kind):
        super().__init__()
        self.host,self.kind = host,kind
        self.busy = False
        self.sources=[]
        self.outputs={}
        self.failures=set()
        self.controls={}
        self.prompt_widgets=[]
        self.states={}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(16)
        top,top_layout = card()
        layout.addWidget(top)
        if kind=='download':
            top_layout.addWidget(label('抖音分享链接','section'))
            self.links = QPlainTextEdit()
            self.links.setPlaceholderText('粘贴抖音分享文本或链接，支持多条。')
            self.links.setMinimumHeight(140)
            top_layout.addWidget(self.links)
            self.quality=QComboBox(); self.quality.addItems(['推荐','最高','1080P','720P'])
            self.quality.setCurrentText(host.settings.get('download_quality','推荐'))
            row=QHBoxLayout(); row.addWidget(label('下载清晰度')); row.addWidget(self.quality); row.addStretch()
            row.addWidget(button('识别链接',self.recognize_links)); top_layout.addLayout(row)
        else:
            row=QHBoxLayout()
            row.addWidget(label({'transcribe':'视频文件','answers':'SRT 与同名视频','rewrite':'待改写文案'}[kind],'section'))
            row.addStretch()
            row.addWidget(button('识别目录',self.import_directory))
            row.addWidget(button('导入文件',self.import_files))
            row.addWidget(button('全选',self.select_all))
            row.addWidget(button('清空',self.clear))
            top_layout.addLayout(row)
            if kind=='transcribe':
                language_row=QHBoxLayout(); language_row.addWidget(label('原声语言'))
                self.language=QComboBox(); self.language.addItems(list(asr.LANGUAGE_CODES))
                self.language.setCurrentText(host.settings.get('source_lang','中文'))
                language_row.addWidget(self.language); language_row.addStretch(); top_layout.addLayout(language_row)
                top_layout.addWidget(label('固定使用 paraformer-v2；API 地址和密钥读取统一配置。','muted'))
            if kind in ('answers','rewrite'):
                prompt_row=QHBoxLayout(); self.prompt_combo=QComboBox()
                key='rewrite_prompts' if kind=='rewrite' else 'cut_prompts'
                default=[{'name':'自然口播','text':'将文案改写成自然、流畅的口播表达。保留原文事实，只返回正文。'}] if kind=='rewrite' else [{'name':'默认剪辑方案','text':ai.SRT_DELETION_PROMPT}]
                self.prompts=host.settings.get(key) or default
                self.prompt_combo.addItems([p.get('name','未命名') for p in self.prompts])
                prompt_row.addWidget(label('提示词')); prompt_row.addWidget(self.prompt_combo,1)
                prompt_row.addWidget(button('提示词管理',self.manage_prompts))
                if kind=='rewrite':
                    self.provider=QComboBox(); self.provider.addItem('New API','newapi'); self.provider.addItem('豆包 / 火山方舟','doubao'); prompt_row.addWidget(self.provider)
                top_layout.addLayout(prompt_row)
                self.prompt=QPlainTextEdit(); self.prompt.setMaximumHeight(110)
                self.prompt.setPlainText(self.prompts[0].get('text',''))
                self.prompt_combo.currentIndexChanged.connect(lambda index:self.prompt.setPlainText(self.prompts[index].get('text','')) if index>=0 else None)
                top_layout.addWidget(self.prompt)
        middle,middle_layout = card()
        layout.addWidget(middle,1)
        self.table=table(['文件 / 链接','状态','进度','操作'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.open_result)
        middle_layout.addWidget(self.table,1)
        if kind=='rewrite':
            self.preview=QPlainTextEdit(); self.preview.setReadOnly(True); self.preview.setPlaceholderText('双击条目查看原文或改写结果'); self.preview.setMaximumHeight(135)
            middle_layout.addWidget(self.preview)
        output_card,out_layout=card(); layout.addWidget(output_card)
        initial = host.settings.get('qt_'+kind+'_output','')
        if not initial and host.settings.get('output_directory'):
            initial=str(Path(host.settings['output_directory'])/STEPS[kind])
        self.output,output_row=folder_row(initial)
        out_layout.addWidget(label('保存目录','muted')); out_layout.addLayout(output_row)
        footer=QHBoxLayout(); self.status=label('准备就绪','muted'); self.status.setWordWrap(True); footer.addWidget(self.status,1)
        self.retry_button=button('批量重试失败项',lambda:self.begin(retry=True)); self.retry_button.setEnabled(False); footer.addWidget(self.retry_button)
        self.start=button({'download':'下载视频','transcribe':'生成文案与 SRT','answers':'生成答案','rewrite':'批量改写'}[kind],self.begin,True); footer.addWidget(self.start); out_layout.addLayout(footer)
        self.progress=QProgressBar(); self.progress.setValue(0); self.progress.setTextVisible(False); self.progress.setFixedHeight(7); out_layout.addWidget(self.progress)

    def add_paths(self,paths):
        if self.busy:return
        existing={str(p).casefold() for p in self.sources}
        for value in paths:
            path=Path(value).resolve()
            if str(path).casefold() not in existing:
                self.sources.append(path); existing.add(str(path).casefold())
        self.render()

    def render(self):
        self.table.setRowCount(len(self.sources))
        for index,source in enumerate(self.sources):
            item=QTableWidgetItem(str(source) if self.kind=='download' else source.name)
            item.setToolTip(str(source)); item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(index,0,item)
            self.table.setItem(index,1,QTableWidgetItem(self.states.get(index,'等待中')))
            self.table.setItem(index,2,QTableWidgetItem('0%'))
            actions=QWidget(); row=QHBoxLayout(actions); row.setContentsMargins(2,2,2,2)
            row.addWidget(button('重试',lambda checked=False,i=index:self.begin(rows=[i])))
            if self.kind=='download':
                row.addWidget(button('暂停/继续',lambda checked=False,i=index:self.pause_download(i)))
            self.table.setCellWidget(index,3,actions)
        self.status.setText(f'共 {len(self.sources)} 个条目')

    def recognize_links(self):
        if self.busy:return
        self.sources=downloader_service.extract_share_urls(self.links.toPlainText())
        self.failures.clear(); self.outputs.clear(); self.states.clear(); self.render()

    def select_all(self):
        for index in range(self.table.rowCount()):self.table.item(index,0).setCheckState(Qt.CheckState.Checked)

    def clear(self):
        if not self.busy:self.sources.clear(); self.outputs.clear(); self.failures.clear(); self.states.clear(); self.render()

    def import_files(self):
        filters={'transcribe':'视频 (*.mp4 *.mov *.m4v *.webm *.mkv)','answers':'SRT 字幕 (*.srt)','rewrite':'文案 (*.txt *.srt)'}
        paths,_=QFileDialog.getOpenFileNames(self,'导入文件','',filters[self.kind]); self.add_paths(paths)

    def import_directory(self):
        initial=self.host.project_path()
        if initial:
            initial=str(Path(initial)/STEPS['download' if self.kind=='transcribe' else 'transcribe' if self.kind=='answers' else 'answers'])
        folder=QFileDialog.getExistingDirectory(self,'选择输入目录',initial or '')
        if folder:
            extensions={'transcribe':{'.mp4','.mov','.m4v','.webm','.mkv'},'answers':{'.srt'},'rewrite':{'.txt','.srt'}}[self.kind]
            self.add_paths(sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in extensions))

    def failed_rows(self):return sorted(self.failures)

    def open_result(self,item):
        index=item.row(); source=self.outputs.get(index) or self.sources[index]
        if self.kind=='rewrite':
            try:self.preview.setPlainText(read_text(source))
            except Exception as exc:self.status.setText(str(exc))
        elif Path(source).is_file():QDesktopServices.openUrl(QUrl.fromLocalFile(str(source)))

    def pause_download(self,index):
        control=self.controls.get(index)
        if control:
            paused=getattr(control,'_qt_paused',False)
            control.resume() if paused else control.pause()
            control._qt_paused=not paused
            self.table.item(index,1).setText('继续下载' if paused else '已暂停')

    def begin(self,checked=False,*,retry=False,rows=None):
        if self.busy:return
        if self.kind=='download' and rows is None and not retry:self.recognize_links()
        targets=rows if rows is not None else self.failed_rows() if retry else [i for i in range(len(self.sources)) if self.table.item(i,0).checkState()==Qt.CheckState.Checked]
        if not targets:self.status.setText('请先导入并选择条目');return
        try:
            self.host.save_configuration()
            config=dict(self.host.settings)
            if not self.output.text().strip():raise ValueError('请选择保存目录')
            output=Path(self.output.text()).expanduser().resolve(); output.mkdir(parents=True,exist_ok=True)
            if self.kind=='download':
                if not config.get('henghengmao_api_key','').strip():raise ValueError('请先填写哼哼猫 API Key')
                config['download_quality']=self.quality.currentText()
            if self.kind=='transcribe':config['source_lang']=self.language.currentText()
            prompt=self.prompt.toPlainText() if hasattr(self,'prompt') else ''
            provider=self.provider.currentData() if hasattr(self,'provider') else 'newapi'
            workflow=Workflow(config)
            sources={i:self.sources[i] for i in targets}
            ffmpeg=asr.resolve_ffmpeg() if self.kind=='download' else None
            self.busy=True; self.start.setEnabled(False); self.retry_button.setEnabled(False)
            for index in targets:
                self.failures.discard(index); self.table.item(index,1).setText('排队中')
            history=self.host.history.create(self.kind,self.start.text(),str(output),[{'source':str(sources[i])} for i in targets])
            self.host.history.update_task(history['id'],status='运行中')
            self.status.setText('处理中，最多五个并发…'); self.progress.setValue(0)
            self.controls={i:downloader_service.DownloadControl() for i in targets} if self.kind=='download' else {}
        except Exception as exc:
            self.busy=False; self.start.setEnabled(True); self.status.setText(str(exc)); return

        def work(emit):
            completed=0; results=[]
            def operation(index):
                source=sources[index]
                emit(('state',index,'处理中',0))
                report=lambda text:emit(('state',index,text,None))
                if self.kind=='download':
                    def download():
                        spec=downloader_service.resolve_video(source,api_key=config['henghengmao_api_key'],quality=config.get('download_quality','推荐'))
                        return downloader_service.download_resolved(spec,str(output),ffmpeg,on_progress=lambda value:emit(('state',index,'下载中',round(value*100))),refresh=lambda:downloader_service.resolve_video(source,api_key=config['henghengmao_api_key'],quality=config.get('download_quality','推荐')),control=self.controls[index],concurrent_downloads=min(5,len(targets)))
                    return immediate_retry(download,max_attempts=3)
                invoke=lambda:workflow.process(self.kind,source,prompt=prompt,status=report,output=output,provider=provider)
                return invoke() if self.kind=='rewrite' else immediate_retry(invoke,max_attempts=3,on_retry=lambda attempt,total:report(f'重试中 {attempt}/{total}'))
            with ThreadPoolExecutor(max_workers=min(5,len(targets)),thread_name_prefix='qt-'+self.kind) as pool:
                futures={pool.submit(operation,index):index for index in targets}
                for future in as_completed(futures):
                    index=futures[future]
                    try:result,error=future.result(),None
                    except Exception as exc:result,error=None,str(exc)
                    results.append((index,result,error)); completed+=1
                    self.host.history.update_item(history['id'],targets.index(index),status='失败' if error else '完成',output=str(result or ''),error=error or '',progress=0 if error else 100)
                    emit(('done',index,result,error,round(completed/len(targets)*100)))
            self.host.history.update_task(history['id'],status='部分失败' if any(v[2] for v in results) else '完成')
            return results
        self.host.start_job(work,self.finished,self.failed,self.updated)

    def updated(self,event):
        kind,index=event[:2]
        if kind=='state':
            self.table.item(index,1).setText(event[2])
            if event[3] is not None:self.table.item(index,2).setText(f'{event[3]}%')
        else:
            _,index,result,error,percent=event
            self.progress.setValue(percent)
            self.table.item(index,1).setText('失败' if error else '完成')
            self.table.item(index,1).setToolTip(error or str(result))
            self.table.item(index,2).setText('0%' if error else '100%')
            if error:self.failures.add(index)
            else:self.outputs[index]=str(result)
            self.status.setText(error or str(result))

    def finished(self,results):
        self.busy=False; self.start.setEnabled(True); self.retry_button.setEnabled(bool(self.failures))
        good=sum(not error for _,_,error in results); self.status.setText(f'处理完成 · 成功 {good}，失败 {len(results)-good}（失败原因悬停状态栏查看）')
        self.host.refresh_history()

    def failed(self,error):
        self.busy=False; self.start.setEnabled(True); self.retry_button.setEnabled(bool(self.failures)); self.status.setText(error)

    def manage_prompts(self):
        dialog=QDialog(self); dialog.setWindowTitle('提示词管理'); dialog.resize(650,450)
        layout=QVBoxLayout(dialog); select=QComboBox(); select.addItems([p.get('name','') for p in self.prompts]); layout.addWidget(select)
        name=QLineEdit(); text=QPlainTextEdit(); layout.addWidget(name); layout.addWidget(text)
        def show(index):
            if index>=0:name.setText(self.prompts[index].get('name',''));text.setPlainText(self.prompts[index].get('text',''))
        select.currentIndexChanged.connect(show);show(0)
        controls=QHBoxLayout()
        def store():
            if not name.text().strip() or not text.toPlainText().strip():return
            index=select.currentIndex();self.prompts[index]={'name':name.text(),'text':text.toPlainText()};select.setItemText(index,name.text())
        def add():
            self.prompts.append({'name':'新提示词','text':''});select.addItem('新提示词');select.setCurrentIndex(select.count()-1)
        def remove():
            if len(self.prompts)>1:
                index=select.currentIndex();self.prompts.pop(index);select.removeItem(index);show(select.currentIndex())
        controls.addWidget(button('新增',add));controls.addWidget(button('保存当前',store));controls.addWidget(button('删除',remove));layout.addLayout(controls)
        controls.addWidget(button('完成',dialog.accept));dialog.exec()
        key='rewrite_prompts' if self.kind=='rewrite' else 'cut_prompts';self.host.settings[key]=self.prompts
        self.prompt_combo.blockSignals(True);self.prompt_combo.clear();self.prompt_combo.addItems([p['name'] for p in self.prompts]);self.prompt_combo.blockSignals(False);self.prompt.setPlainText(self.prompts[0]['text']);self.host.save_configuration()


class SettingsPage(QWidget):
    def __init__(self,host):
        super().__init__(); self.host=host; self.fields={}; layout=QVBoxLayout(self)
        box,body=card();layout.addWidget(box);body.addWidget(label('接口配置','section'))
        form=QFormLayout();form.setVerticalSpacing(16);body.addLayout(form)
        for key,title,default,secret in [('henghengmao_api_key','哼哼猫 API Key','',True),('llm_base_url','New API 地址',DEFAULT_URL,False),('llm_key','New API Key','',True),('dashscope_api_key','临时 OSS 上传 Key','',True),('ark_api_key','火山方舟 Key','',True),('qt_doubao_model','豆包模型','doubao-seed-2-1-pro-260915',False)]:
            edit=QLineEdit(str(host.settings.get(key) or default)); self.fields[key]=edit
            if secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
                row=QHBoxLayout();row.addWidget(edit,1)
                show=QPushButton('显示');show.setCheckable(True);show.toggled.connect(lambda checked,e=edit:e.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password));row.addWidget(show);form.addRow(title,row)
            else:form.addRow(title,edit)
        model_row=QHBoxLayout();self.model=QComboBox();self.model.setEditable(True);self.model.addItem(host.settings.get('llm_model') or DEFAULT_MODEL);model_row.addWidget(self.model,1)
        self.fetch=button('获取模型列表',self.fetch_models);model_row.addWidget(self.fetch);form.addRow('文本模型',model_row)
        body.addWidget(label('转写固定使用 paraformer-v2，上传 Key 仅用于临时 OSS。','muted'))
        body.addWidget(button('保存配置',host.save_configuration,True))
        self.status=label('配置保存在本机 VideoFlow 数据目录。','muted');body.addWidget(self.status);layout.addStretch()

    def values(self):return {**{key:edit.text().strip() for key,edit in self.fields.items()},'llm_model':self.model.currentText().strip()}
    def fetch_models(self):
        self.fetch.setEnabled(False);url=self.fields['llm_base_url'].text();key=self.fields['llm_key'].text()
        def done(models):
            current=self.model.currentText();self.model.clear();self.model.addItems(models);self.model.setCurrentText(current);self.fetch.setEnabled(True);self.status.setText(f'已获取 {len(models)} 个模型')
        def error(text):self.fetch.setEnabled(True);self.status.setText(text)
        self.host.start_job(lambda _:ai.list_models(url,key),done,error)


class LibraryPage(QWidget):
    def __init__(self,host):
        super().__init__();self.host=host;layout=QVBoxLayout(self);box,body=card();layout.addWidget(box)
        body.addWidget(label('按同名文件整理资源','section'));self.fields=[]
        root=Path(host.project_path() or Path.home()/'Desktop')
        defaults=[host.settings.get('anti_flash_directory') or root/STEPS['download'],root/STEPS['rewrite'],root/STEPS['voice'],host.settings.get('library_directory') or root/STEPS['library']]
        for title,value in zip(['视频目录','SRT 目录','语音目录','资源库目录'],defaults):
            body.addWidget(label(title,'muted'));edit,row=folder_row(value);self.fields.append(edit);body.addLayout(row)
        body.addWidget(label('仅复制视频、字幕和语音三者同名的完整组。','muted'))
        self.start=button('复制到资源库',self.copy,True);body.addWidget(self.start);self.status=label('准备就绪','muted');self.status.setWordWrap(True);body.addWidget(self.status);layout.addStretch()
    def copy(self):
        values=[edit.text() for edit in self.fields];self.start.setEnabled(False)
        def done(result):
            count,missing=result;self.start.setEnabled(True);self.status.setText(f'已复制 {count} 组'+('；缺少对应资源：'+', '.join(missing[:15]) if missing else ''))
            self.host.settings.update(anti_flash_directory=values[0],library_directory=values[3]);self.host.save_configuration()
        def error(text):self.start.setEnabled(True);self.status.setText(text)
        self.host.start_job(lambda _:copy_library(*values),done,error)


class RenamePage(QWidget):
    def __init__(self,host):
        super().__init__();self.host=host;self.videos=[];layout=QVBoxLayout(self);box,body=card();layout.addWidget(box)
        initial=str(Path(host.project_path())/STEPS['download']) if host.project_path() else ''
        self.folder,row=folder_row(initial);body.addWidget(label('同名文件同步重命名','section'));body.addLayout(row);body.addWidget(button('扫描视频文件',self.scan))
        self.table=table(['当前文件名','新文件名']);layout.addWidget(self.table,1)
        bottom=QHBoxLayout();self.status=label('同一目录内同名的 TXT、SRT 和其他扩展名会一起修改。','muted');bottom.addWidget(self.status,1);bottom.addWidget(button('执行重命名',self.rename,True));layout.addLayout(bottom)
    def scan(self):
        try:self.videos=rename_service.list_videos(self.folder.text());self.table.setRowCount(len(self.videos))
        except Exception as exc:self.status.setText(str(exc));return
        for index,path in enumerate(self.videos):
            original=QTableWidgetItem(path.name);original.setFlags(original.flags() & ~Qt.ItemFlag.ItemIsEditable);self.table.setItem(index,0,original);self.table.setItem(index,1,QTableWidgetItem(path.stem))
    def rename(self):
        try:
            changed=0
            for index,path in enumerate(self.videos):
                name=self.table.item(index,1).text().strip()
                if name!=path.stem:rename_service.rename_media_bundle(path,name);changed+=1
            self.scan();self.status.setText(f'已修改 {changed} 组同名文件')
        except Exception as exc:self.status.setText(f'部分操作未完成：{exc}');self.scan()
