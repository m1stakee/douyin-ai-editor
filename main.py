import json, os, shutil, threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import downloader_service, media, asr, ai, rename_service
from batch_service import run_batch
from app_config import dashscope_key, henghengmao_key, load_settings, save_settings
from task_store import TaskStore
from license_client import require_license, verify_saved_license

DEFAULT_REWRITE_PROMPTS={"自然口播":"请将文案改写成自然、流畅、适合口播的表达。保留原文事实和核心信息，不添加未经证实的内容。只返回改写后的正文。","卖点浓缩":"请提炼并改写文案，突出最重要的卖点，表达简洁有力。保留原文事实，不添加新信息。只返回改写后的正文。","故事叙述":"请将文案改写成有起承转合、易于听懂的故事化表达。保留原文事实和核心信息，不虚构情节。只返回改写后的正文。","新闻讲解":"请将文案改写成清晰、客观、适合短视频讲解的表达。保留原文事实，不夸大、不添加未经证实的信息。只返回改写后的正文。","轻度去重":"请对文案进行轻度改写，调整措辞和句式以降低重复度，同时完整保留原意、事实和信息顺序。只返回改写后的正文。"}

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title("VideoFlow · 短视频智能工作台"); self.geometry("1180x820"); self.minsize(1000,720); self.configure(bg="#EEF1F5")
        saved=load_settings(); output=saved.get("output_directory",""); self.project=Path(output) if output else None
        stored_prompts=saved.get("rewrite_prompts",[])
        self.rewrite_prompts=stored_prompts if isinstance(stored_prompts,list) and stored_prompts else [{"name":name,"text":text} for name,text in DEFAULT_REWRITE_PROMPTS.items()]
        # FFmpeg is bundled with the application; ignore any legacy user path.
        self.ffmpeg=tk.StringVar(value=asr.resolve_ffmpeg())
        self.download_key=tk.StringVar(value=saved.get("henghengmao_api_key", "")); self.asr_key=tk.StringVar(value=saved.get("dashscope_api_key") or dashscope_key())
        self.download_quality=tk.StringVar(value=saved.get("download_quality","推荐")); self.download_workers=tk.StringVar(value=saved.get("download_workers","8")); self.source_lang=tk.StringVar(value=saved.get("source_lang","中文"))
        self.llm_url=tk.StringVar(value=saved.get("llm_url","")); self.llm_key=tk.StringVar(value=saved.get("llm_key","")); self.llm_model=tk.StringVar(value=saved.get("llm_model","gemini-2.5-flash")); self.lang=tk.StringVar(value=saved.get("target_lang","英语"))
        self.style=tk.StringVar(value=saved.get("writing_style","自然口播")); self.length=tk.StringVar(value=saved.get("writing_length","保持原时长"))
        self.license_key=tk.StringVar(value=saved.get("license_key", ""))
        self.status=tk.StringVar(value="就绪"); self.task_store=TaskStore(); self.task_center_window=None; self.task_center_tree=None; self.batch_task_ids={}; self.transcribe_task_ids={}
        self.project_text=tk.StringVar(value=f"输出到：{self.project}" if self.project else "尚未选择输出目录")
        self._setup_style()
        self.withdraw(); self.build()
        self.after(50, self._authorize_startup)
        self.protocol("WM_DELETE_WINDOW",self.close_app)
    def _authorize_startup(self):
        result=verify_saved_license(self.license_key.get())
        if not result:
            result=require_license(self, self.license_key.get())
        if not result: self.exit_process(); return
        self.license_key.set(result); self.save_all_settings(False); self.deiconify(); self.lift()
    def _setup_style(self):
        style=ttk.Style(self); style.theme_use("clam")
        style.configure("TFrame",background="#EEF1F5"); style.configure("Panel.TFrame",background="#FFFFFF")
        style.configure("TLabel",background="#EEF1F5",foreground="#203047",font=("Microsoft YaHei UI",9))
        style.configure("Panel.TLabel",background="#FFFFFF",foreground="#203047",font=("Microsoft YaHei UI",9))
        style.configure("Brand.TLabel",background="#152238",foreground="#FFFFFF",font=("Microsoft YaHei UI",19,"bold"))
        style.configure("BrandSub.TLabel",background="#152238",foreground="#A8B7CC",font=("Microsoft YaHei UI",9))
        style.configure("Section.TLabel",background="#FFFFFF",foreground="#152238",font=("Microsoft YaHei UI",12,"bold"))
        style.configure("Muted.TLabel",background="#FFFFFF",foreground="#718096",font=("Microsoft YaHei UI",8))
        style.configure("Status.TLabel",background="#E9F5F0",foreground="#167356",font=("Microsoft YaHei UI",9,"bold"),padding=(11,6))
        style.configure("TButton",font=("Microsoft YaHei UI",9),padding=(11,7),background="#E7EBF0",foreground="#203047",borderwidth=0)
        style.map("TButton",background=[("active","#D8DEE7")])
        style.configure("Primary.TButton",font=("Microsoft YaHei UI",9,"bold"),padding=(14,9),background="#F06449",foreground="#FFFFFF")
        style.map("Primary.TButton",background=[("active","#D95239")])
        style.configure("Flow.TButton",font=("Microsoft YaHei UI",9,"bold"),padding=(13,10),background="#F2F5F8",foreground="#203047")
        style.map("Flow.TButton",background=[("active","#E4EAF1")])
        style.configure("TEntry",padding=7,fieldbackground="#F8FAFC",bordercolor="#D5DCE5"); style.configure("TCombobox",padding=6,fieldbackground="#F8FAFC")
    def build(self):
        header=tk.Frame(self,bg="#152238",height=76); header.pack(fill="x"); header.pack_propagate(False)
        brand=tk.Frame(header,bg="#152238"); brand.pack(fill="both",expand=True,padx=26,pady=12)
        ttk.Label(brand,text="VideoFlow",style="Brand.TLabel").pack(side="left"); ttk.Label(brand,text="把分享链接变成可编辑的视频素材",style="BrandSub.TLabel").pack(side="left",padx=18,pady=(7,0)); ttk.Label(brand,textvariable=self.status,style="Status.TLabel").pack(side="right",pady=7); ttk.Button(brand,text="任务中心",command=self.open_task_center).pack(side="right",padx=10,pady=7)
        viewport=ttk.Frame(self); viewport.pack(fill="both",expand=True); viewport.rowconfigure(0,weight=1); viewport.columnconfigure(0,weight=1)
        self.main_canvas=tk.Canvas(viewport,bg="#EEF1F5",highlightthickness=0); self.main_canvas.grid(row=0,column=0,sticky="nsew")
        main_scroll=ttk.Scrollbar(viewport,orient="vertical",command=self.main_canvas.yview); main_scroll.grid(row=0,column=1,sticky="ns"); self.main_canvas.configure(yscrollcommand=main_scroll.set)
        body=ttk.Frame(self.main_canvas,padding=18); self.main_body_window=self.main_canvas.create_window((0,0),window=body,anchor="nw")
        body.bind("<Configure>",lambda _event:self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all")))
        self.main_canvas.bind("<Configure>",lambda event:self.main_canvas.itemconfigure(self.main_body_window,width=event.width))
        self.bind_all("<MouseWheel>",self._scroll_main_window,add="+")
        body.columnconfigure(0,weight=7); body.columnconfigure(1,weight=4); body.rowconfigure(1,weight=1)
        source=ttk.Frame(body,style="Panel.TFrame",padding=18); source.grid(row=0,column=0,sticky="nsew",padx=(0,9),pady=(0,10)); source.columnconfigure(0,weight=1)
        ttk.Label(source,text="视频来源",style="Section.TLabel").grid(row=0,column=0,sticky="w"); ttk.Label(source,text="粘贴多个独立视频地址，每条链接分别解析并并发下载",style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(3,10))
        self.url_text=tk.Text(source,height=8,wrap="word",font=("Microsoft YaHei UI",10),bg="#F8FAFC",fg="#203047",insertbackground="#F06449",relief="flat",padx=11,pady=10,highlightthickness=1,highlightbackground="#D5DCE5",highlightcolor="#F06449"); self.url_text.grid(row=2,column=0,sticky="nsew")
        directory=ttk.Frame(source,style="Panel.TFrame"); directory.grid(row=3,column=0,sticky="ew",pady=(11,0)); ttk.Label(directory,textvariable=self.project_text,style="Muted.TLabel").pack(side="left",fill="x",expand=True); ttk.Button(directory,text="选择目录",command=self.choose_project).pack(side="left",padx=5); ttk.Button(directory,text="打开目录",command=self.open_project).pack(side="left")
        flow=ttk.Frame(source,style="Panel.TFrame"); flow.grid(row=4,column=0,sticky="ew",pady=(14,0))
        ttk.Button(flow,text="1  下载视频",style="Primary.TButton",command=self.start_download).pack(side="left",padx=(0,7)); ttk.Button(flow,text="2  生成文案与 SRT",style="Flow.TButton",command=self.start_transcribe).pack(side="left",padx=7); ttk.Button(flow,text="3  AI 改写",style="Flow.TButton",command=self.open_rewrite_window).pack(side="left",padx=7)
        self.progress=ttk.Progressbar(source,orient="horizontal",mode="determinate",maximum=100); self.progress.grid(row=5,column=0,sticky="ew",pady=(10,0))
        task_box=ttk.Frame(source,style="Panel.TFrame"); task_box.grid(row=6,column=0,sticky="ew",pady=(9,0)); task_box.columnconfigure(0,weight=1)
        ttk.Label(task_box,text="各视频下载进度",style="Muted.TLabel").grid(row=0,column=0,sticky="w",pady=(0,5))
        self.task_canvas=tk.Canvas(task_box,height=132,bg="#FFFFFF",highlightthickness=1,highlightbackground="#E1E6ED"); self.task_canvas.grid(row=1,column=0,sticky="ew")
        task_scroll=ttk.Scrollbar(task_box,orient="vertical",command=self.task_canvas.yview); task_scroll.grid(row=1,column=1,sticky="ns"); self.task_canvas.configure(yscrollcommand=task_scroll.set)
        self.task_rows_frame=ttk.Frame(self.task_canvas,style="Panel.TFrame"); self.task_rows_window=self.task_canvas.create_window((0,0),window=self.task_rows_frame,anchor="nw")
        self.task_rows_frame.bind("<Configure>",lambda event: self.task_canvas.configure(scrollregion=self.task_canvas.bbox("all")))
        self.task_canvas.bind("<Configure>",lambda event: self.task_canvas.itemconfigure(self.task_rows_window,width=event.width))
        self.task_rows={}; self.task_windows={}; self.batch_controls={}; self.batch_contexts={}; self.batch_counter=0; self.latest_batch_id=0
        self.transcribe_rows={}; self.transcribe_windows={}; self.transcribe_controls={}; self.transcribe_contexts={}; self.transcribe_counter=0; self.latest_transcribe_id=0
        settings=ttk.Frame(body,style="Panel.TFrame",padding=18); settings.grid(row=0,column=1,sticky="nsew",padx=(9,0),pady=(0,10)); settings.columnconfigure(0,weight=1)
        ttk.Label(settings,text="处理设置",style="Section.TLabel").grid(row=0,column=0,sticky="w"); ttk.Label(settings,text="保存后下次启动自动恢复",style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(3,9))
        self._combo(settings,"视频清晰度",self.download_quality,["推荐","最高","1080P","720P"],2,0); self._combo(settings,"原声语言",self.source_lang,["中文","英语","日语","韩语","西班牙语","法语","德语"],3,0)
        self.advanced_button=ttk.Button(settings,text="展开接口与工具配置",command=self.toggle_advanced); self.advanced_button.grid(row=4,column=0,sticky="ew",pady=(9,5))
        self.advanced=ttk.Frame(settings,style="Panel.TFrame"); self._field(self.advanced,"软件卡密",self.license_key,0,0,secret=True); self._field(self.advanced,"哼哼猫 Key",self.download_key,1,0,secret=True); self._field(self.advanced,"阿里百炼 Key",self.asr_key,2,0,secret=True)
        controls=ttk.Frame(settings,style="Panel.TFrame"); controls.grid(row=6,column=0,sticky="ew",pady=(9,0)); ttk.Button(controls,text="批量重命名",command=self.open_rename_window).pack(side="left"); ttk.Button(controls,text="保存全部配置",style="Primary.TButton",command=self.save_all_settings).pack(side="right")
        logs=ttk.Frame(body,style="Panel.TFrame",padding=16); logs.grid(row=1,column=0,columnspan=2,sticky="nsew"); logs.columnconfigure(0,weight=1); logs.rowconfigure(1,weight=1); ttk.Label(logs,text="任务记录",style="Section.TLabel").grid(row=0,column=0,sticky="w",pady=(0,8))
        log_frame=tk.Frame(logs,bg="#182333"); log_frame.grid(row=1,column=0,sticky="nsew"); self.text=tk.Text(log_frame,height=10,wrap="word",font=("Consolas",9),bg="#182333",fg="#D8E0EA",insertbackground="#FFFFFF",relief="flat",padx=12,pady=10); log_scroll=ttk.Scrollbar(log_frame,orient="vertical",command=self.text.yview); self.text.configure(yscrollcommand=log_scroll.set); self.text.pack(side="left",fill="both",expand=True); log_scroll.pack(side="right",fill="y")
    def _scroll_main_window(self,event):
        if event.widget.winfo_toplevel() is self and not isinstance(event.widget,tk.Text) and self.main_canvas.winfo_exists():
            units=-1 if event.delta>0 else 1
            self.main_canvas.yview_scroll(units*3,"units")
    def _field(self, parent, label, var, row, col, secret=False, browse=False):
        box=ttk.Frame(parent,style="Panel.TFrame"); box.grid(row=row,column=col,columnspan=2,sticky="ew",padx=0,pady=3); parent.columnconfigure(col,weight=1)
        ttk.Label(box,text=label,width=11,style="Panel.TLabel").pack(side="left"); ttk.Entry(box,textvariable=var,show="*" if secret else "").pack(side="left",fill="x",expand=True)
        if browse: ttk.Button(box,text="选择",command=self.choose_ffmpeg,width=6).pack(side="left",padx=(4,0))
    def _combo(self, parent, label, var, values, row, col, editable=False):
        box=ttk.Frame(parent,style="Panel.TFrame"); box.grid(row=row,column=col,columnspan=2,sticky="ew",padx=0,pady=3); parent.columnconfigure(col,weight=1)
        ttk.Label(box,text=label,width=11,style="Panel.TLabel").pack(side="left"); ttk.Combobox(box,textvariable=var,values=values,state="normal" if editable else "readonly").pack(side="left",fill="x",expand=True)
    def toggle_advanced(self):
        if self.advanced.winfo_manager(): self.advanced.grid_remove(); self.advanced_button.configure(text="展开接口与工具配置")
        else: self.advanced.grid(row=5,column=0,sticky="ew"); self.advanced_button.configure(text="收起接口与工具配置")
    def settings_values(self):
        return {"output_directory":str(self.project or ""),"download_quality":self.download_quality.get(),"download_workers":self.download_workers.get(),"source_lang":self.source_lang.get(),"henghengmao_api_key":self.download_key.get(),"dashscope_api_key":self.asr_key.get(),"llm_url":self.llm_url.get(),"llm_key":self.llm_key.get(),"llm_model":self.llm_model.get(),"target_lang":self.lang.get(),"writing_style":self.style.get(),"writing_length":self.length.get(),"license_key":self.license_key.get(),"rewrite_prompts":self.rewrite_prompts}
    def save_all_settings(self,notify=True):
        path=save_settings(self.settings_values()); self.status.set("配置已保存")
        if notify: messagebox.showinfo("保存配置",f"全部配置已保存到本机：{path.name}")
    def close_app(self):
        self.save_all_settings(False)
        for group in (self.batch_controls,self.transcribe_controls):
            for controls in group.values():
                for control in controls: control.cancel()
        self.exit_process()
    def exit_process(self):
        self.destroy(); os._exit(0)
    def choose_project(self):
        p=filedialog.askdirectory();
        if p: self.project=Path(p); self.project_text.set(f"输出到：{p}"); self.status.set("输出目录已选择")
    def open_project(self):
        if not self.project: messagebox.showinfo("打开输出目录","请先选择输出目录"); return
        if not self.project.exists(): messagebox.showerror("打开输出目录","输出目录不存在"); return
        os.startfile(str(self.project))
    def choose_ffmpeg(self):
        p=filedialog.askopenfilename(title="选择 ffmpeg.exe",filetypes=[("FFmpeg", "ffmpeg.exe"), ("所有文件", "*.*")])
        if p: self.ffmpeg.set(p)
    def open_rename_window(self):
        if not self.project: messagebox.showinfo("批量重命名","请先选择输出目录"); return
        folder=str(self.project)
        videos=rename_service.list_videos(folder)
        if not videos: messagebox.showinfo("批量重命名","该文件夹下没有支持的视频文件"); return
        win=tk.Toplevel(self); win.title("批量重命名视频、SRT 和 TXT"); win.geometry("860x600")
        outer=ttk.Frame(win,padding=10); outer.pack(fill="both",expand=True)
        ttk.Label(outer,text=f"文件夹：{folder}").pack(anchor="w",pady=(0,8))
        canvas=tk.Canvas(outer,highlightthickness=0); scroll=ttk.Scrollbar(outer,orient="vertical",command=canvas.yview); rows=ttk.Frame(canvas)
        rows.bind("<Configure>",lambda e: canvas.configure(scrollregion=canvas.bbox("all"))); canvas.create_window((0,0),window=rows,anchor="nw"); canvas.configure(yscrollcommand=scroll.set); canvas.pack(side="left",fill="both",expand=True); scroll.pack(side="right",fill="y")
        ttk.Label(rows,text="当前视频文件名",width=52).grid(row=0,column=0,sticky="w",padx=4,pady=4); ttk.Label(rows,text="修改后的文件名",width=45).grid(row=0,column=1,sticky="w",padx=4,pady=4)
        items=[]
        for index,video in enumerate(videos,1):
            value=tk.StringVar(value=video.stem); ttk.Label(rows,text=video.name,width=52).grid(row=index,column=0,sticky="w",padx=4,pady=3); ttk.Entry(rows,textvariable=value,width=48).grid(row=index,column=1,sticky="ew",padx=4,pady=3); items.append((video,value))
        def apply_renames():
            try:
                changed=0
                for video,value in items:
                    if value.get().strip()!=video.stem: rename_service.rename_media_bundle(video,value.get()); changed+=1
                messagebox.showinfo("批量重命名",f"完成，共修改 {changed} 组文件；所有同名文件已同步修改",parent=win); win.destroy()
            except Exception as exc: messagebox.showerror("重命名失败",str(exc),parent=win)
        ttk.Button(win,text="执行批量重命名",command=apply_renames).pack(pady=10)
    def refresh_task_center(self):
        tree=self.task_center_tree
        if not tree or not tree.winfo_exists(): return
        selected=tree.selection(); selected_id=selected[0] if selected else None
        for row in tree.get_children(): tree.delete(row)
        for task in self.task_store.list():
            items=task.get("items",[]); progress=round(sum(item.get("progress",0) for item in items)/len(items)) if items else 0
            created=str(task.get("created_at","")).replace("T"," ")[:19]
            kind={"download":"下载视频","transcribe":"文案与 SRT","rewrite":"AI 改写"}.get(task.get("kind"),task.get("kind",""))
            tree.insert("", "end", iid=task["id"], values=(created,kind,task.get("title",""),len(items),task.get("status",""),f"{progress}%"))
        if selected_id and tree.exists(selected_id): tree.selection_set(selected_id)
    def open_task_center(self):
        if self.task_center_window and self.task_center_window.winfo_exists(): self.task_center_window.deiconify(); self.task_center_window.lift(); self.refresh_task_center(); return
        win=tk.Toplevel(self); win.title("任务中心"); win.geometry("1050x560"); win.minsize(820,380); self.task_center_window=win
        outer=ttk.Frame(win,padding=14); outer.pack(fill="both",expand=True); outer.columnconfigure(0,weight=1); outer.rowconfigure(2,weight=1)
        ttk.Label(outer,text="任务中心",style="Section.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(outer,text=f"任务历史自动保存在 {self.task_store.path.name}；重启后未完成任务显示为已中断",style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(3,10))
        columns=("created","kind","title","count","status","progress"); tree=ttk.Treeview(outer,columns=columns,show="headings",selectmode="browse"); self.task_center_tree=tree
        headings=(("created","创建时间",155),("kind","类型",110),("title","任务",330),("count","数量",60),("status","状态",100),("progress","总进度",80))
        for key,label,width in headings: tree.heading(key,text=label); tree.column(key,width=width,anchor="center" if key in {"count","status","progress"} else "w")
        tree.grid(row=2,column=0,sticky="nsew"); scroll=ttk.Scrollbar(outer,orient="vertical",command=tree.yview); scroll.grid(row=2,column=1,sticky="ns"); tree.configure(yscrollcommand=scroll.set)
        buttons=ttk.Frame(outer); buttons.grid(row=3,column=0,sticky="ew",pady=(10,0)); ttk.Button(buttons,text="查看详情",command=self.open_selected_task).pack(side="left"); ttk.Button(buttons,text="重新执行",command=self.rerun_selected_task).pack(side="left",padx=8); ttk.Button(buttons,text="打开输出目录",command=self.open_selected_task_folder).pack(side="left"); ttk.Button(buttons,text="刷新",command=self.refresh_task_center).pack(side="right")
        tree.bind("<Double-1>",lambda _event:self.open_selected_task()); win.protocol("WM_DELETE_WINDOW",lambda:(setattr(self,"task_center_tree",None),setattr(self,"task_center_window",None),win.destroy())); self.refresh_task_center()
    def selected_task(self):
        tree=self.task_center_tree
        if not tree or not tree.selection(): return None
        return self.task_store.get(tree.selection()[0])
    def open_selected_task(self):
        task=self.selected_task()
        if not task: return
        for batch_id,task_id in self.batch_task_ids.items():
            if task_id==task["id"]:
                live=self.task_windows.get(batch_id)
                if live and live["window"].winfo_exists(): live["window"].deiconify(); live["window"].lift(); return
        for batch_id,task_id in self.transcribe_task_ids.items():
            if task_id==task["id"]:
                live=self.transcribe_windows.get(batch_id)
                if live and live.winfo_exists(): live.deiconify(); live.lift(); return
        self.open_history_detail(task)
    def open_history_detail(self,task):
        win=tk.Toplevel(self); win.title(task.get("title","任务详情")); win.geometry("920x480"); win.minsize(720,320)
        outer=ttk.Frame(win,padding=12); outer.pack(fill="both",expand=True); outer.columnconfigure(0,weight=1); outer.rowconfigure(2,weight=1)
        ttk.Label(outer,text=task.get("title","任务详情"),style="Section.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(outer,text=f"状态：{task.get('status','')}    输出目录：{task.get('output_dir','')}",style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(4,9))
        columns=("name","status","progress","error"); tree=ttk.Treeview(outer,columns=columns,show="headings");
        for key,label,width in (("name","链接 / 文件",430),("status","状态",100),("progress","进度",70),("error","错误信息",280)): tree.heading(key,text=label); tree.column(key,width=width,anchor="center" if key in {"status","progress"} else "w")
        for item in task.get("items",[]): tree.insert("","end",values=(item.get("url") or item.get("output") or item.get("path") or item.get("name",""),item.get("status",""),f"{item.get('progress',0)}%",item.get("error","")))
        tree.grid(row=2,column=0,sticky="nsew"); scroll=ttk.Scrollbar(outer,orient="vertical",command=tree.yview); scroll.grid(row=2,column=1,sticky="ns"); tree.configure(yscrollcommand=scroll.set)
        ttk.Button(outer,text="重新执行此任务",command=lambda:(win.destroy(),self.rerun_task(task))).grid(row=3,column=0,sticky="w",pady=(10,0))
    def rerun_selected_task(self):
        task=self.selected_task()
        if task: self.rerun_task(task)
    def rerun_task(self,task):
        output=task.get("output_dir","")
        if output: self.project=Path(output); self.project_text.set(f"输出到：{output}")
        if task.get("kind")=="download":
            urls=[item.get("url","") for item in task.get("items",[]) if item.get("url")]
            self.url_text.delete("1.0","end"); self.url_text.insert("1.0","\n".join(urls)); self.start_download()
        else: self.start_transcribe()
    def open_selected_task_folder(self):
        task=self.selected_task()
        if not task:return
        folder=Path(task.get("output_dir", ""))
        if folder.exists(): os.startfile(str(folder))
        else: messagebox.showerror("打开输出目录","任务的输出目录不存在")
    def set_status(self,value): self.after(0,lambda: self.status.set(value))
    def set_progress(self,value): self.after(0,lambda: self.progress.configure(value=max(0,min(100,value))))
    def prepare_download_rows(self,batch_id,urls):
        ttk.Label(self.task_rows_frame,text=f"批次 {batch_id} · {len(urls)} 个视频",style="Section.TLabel").pack(fill="x",padx=5,pady=(8,2))
        for index,url in enumerate(urls):
            row=ttk.Frame(self.task_rows_frame,style="Panel.TFrame",padding=(5,4)); row.pack(fill="x"); row.columnconfigure(1,weight=1)
            ttk.Label(row,text=f"{index+1}.",width=3,style="Panel.TLabel").grid(row=0,column=0,sticky="w")
            ttk.Label(row,text=url,style="Panel.TLabel").grid(row=0,column=1,sticky="w",padx=(0,8))
            bar=ttk.Progressbar(row,orient="horizontal",mode="determinate",maximum=100,length=180); bar.grid(row=0,column=2,sticky="ew",padx=(4,8))
            state=tk.StringVar(value="等待解析"); ttk.Label(row,textvariable=state,width=14,style="Muted.TLabel").grid(row=0,column=3,sticky="e")
            self.task_rows[(batch_id,index)]=(bar,state)
        self.after_idle(lambda: self.task_canvas.yview_moveto(1.0))
    def set_task_progress(self,batch_id,index,value,status=None):
        task_id=self.batch_task_ids.get(batch_id)
        if task_id:
            values={"progress":value}
            if status: values["status"]=status
            self.task_store.update_item(task_id,index,**values)
        def update():
            row=self.task_rows.get((batch_id,index))
            if row:
                bar,state=row; percent=max(0,min(100,value)); bar.configure(value=percent); state.set(status or f"下载中 {percent:.0f}%")
            task=row and self.task_windows.get(batch_id)
            if task:
                task_row=task["rows"].get(index)
                if task_row:
                    bar,state,retry=task_row; percent=max(0,min(100,value)); bar.configure(value=percent); state.set(status or f"下载中 {percent:.0f}%"); retry.configure(state="normal" if status=="失败" else "disabled")
            self.refresh_task_center()
        self.after(0,update)
    def control_download(self,batch_id,index,resume):
        controls=self.batch_controls.get(batch_id,[])
        if not (0<=index<len(controls)): return
        controls[index].resume() if resume else controls[index].pause()
        row=self.task_rows.get((batch_id,index)); value=float(row[0]["value"]) if row else 0
        self.set_task_progress(batch_id,index,value,"续传中" if resume else "已停止")
    def retry_parse(self,batch_id,index):
        context=self.batch_contexts.get(batch_id)
        if not context or not (0<=index<len(context["urls"])): return
        url=context["urls"][index]; control=context["controls"][index]; control.resume(); self.set_task_progress(batch_id,index,0,"重新解析中")
        def retry():
            try:
                spec=downloader_service.resolve_video(url,context["api_key"],context["api_url"],context["quality"])
                refresh=lambda: downloader_service.resolve_video(url,context["api_key"],context["api_url"],context["quality"])
                path=downloader_service.download_resolved(spec,context["output_dir"],context["ffmpeg"],lambda value:self.set_task_progress(batch_id,index,value*100),refresh,control)
                self.set_task_progress(batch_id,index,100,"完成"); self.log(f"[批次 {batch_id} · {index+1}] 重新解析成功，视频已保存：{path}")
            except Exception as exc:
                self.set_task_progress(batch_id,index,0,"失败"); self.log(f"[批次 {batch_id} · {index+1}] 重新解析失败：{exc}")
        self.run(retry)
    def log(self,x): self.after(0,lambda: (self.text.insert("end",x+"\n"),self.text.see("end")))
    def run(self,fn): threading.Thread(target=fn,daemon=True).start()
    def open_download_window(self,batch_id,urls,controls):
        win=tk.Toplevel(self); win.title(f"下载任务 · 批次 {batch_id}"); win.geometry("980x430"); win.minsize(760,300)
        outer=ttk.Frame(win,padding=12); outer.pack(fill="both",expand=True); outer.columnconfigure(0,weight=1); outer.rowconfigure(1,weight=1)
        ttk.Label(outer,text=f"批次 {batch_id} · {len(urls)} 个视频（可调整窗口大小）",style="Section.TLabel").grid(row=0,column=0,sticky="w",pady=(0,8))
        canvas=tk.Canvas(outer,bg="#FFFFFF",highlightthickness=1,highlightbackground="#E1E6ED"); canvas.grid(row=1,column=0,sticky="nsew"); scroll=ttk.Scrollbar(outer,orient="vertical",command=canvas.yview); scroll.grid(row=1,column=1,sticky="ns"); canvas.configure(yscrollcommand=scroll.set)
        frame=ttk.Frame(canvas,style="Panel.TFrame"); window_id=canvas.create_window((0,0),window=frame,anchor="nw"); frame.bind("<Configure>",lambda e: canvas.configure(scrollregion=canvas.bbox("all"))); canvas.bind("<Configure>",lambda e: canvas.itemconfigure(window_id,width=e.width))
        task={"window":win,"rows":{}}; self.task_windows[batch_id]=task
        for index,url in enumerate(urls):
            row=ttk.Frame(frame,style="Panel.TFrame",padding=7); row.pack(fill="x"); row.columnconfigure(1,weight=1); ttk.Label(row,text=f"{index+1}.",width=4,style="Panel.TLabel").grid(row=0,column=0,sticky="w"); ttk.Label(row,text=url,style="Panel.TLabel").grid(row=0,column=1,sticky="w",padx=5); bar=ttk.Progressbar(row,maximum=100); bar.grid(row=0,column=2,sticky="ew",padx=8); state=tk.StringVar(value="等待解析"); ttk.Label(row,textvariable=state,width=12,style="Muted.TLabel").grid(row=0,column=3); ttk.Button(row,text="停止",command=lambda i=index:self.control_download(batch_id,i,False)).grid(row=0,column=4,padx=(8,2)); ttk.Button(row,text="续传",command=lambda i=index:self.control_download(batch_id,i,True)).grid(row=0,column=5,padx=2); retry=ttk.Button(row,text="重新解析",state="disabled",command=lambda i=index:self.retry_parse(batch_id,i)); retry.grid(row=0,column=6,padx=(2,0)); task["rows"][index]=(bar,state,retry)
        def close():
            self.task_windows.pop(batch_id,None); win.destroy()
        win.protocol("WM_DELETE_WINDOW",close)
    def start_download(self):
        input_text=self.url_text.get("1.0","end"); urls=downloader_service.extract_share_urls(input_text)
        if not urls: self.log("下载失败：请至少输入一条抖音分享链接"); return
        if not self.project: self.log("下载失败：请先选择项目目录"); return
        self.batch_counter+=1; batch_id=self.batch_counter; self.latest_batch_id=batch_id; controls=[downloader_service.DownloadControl() for _ in urls]; self.batch_controls[batch_id]=controls
        saved_task=self.task_store.create("download",f"下载批次 {batch_id}",str(self.project),[{"url":url} for url in urls]); self.batch_task_ids[batch_id]=saved_task["id"]; self.task_store.update_task(saved_task["id"],status="运行中")
        self.batch_contexts[batch_id]={"urls":urls,"controls":controls,"output_dir":str(self.project or ""),"quality":self.download_quality.get(),"ffmpeg":self.ffmpeg.get(),"api_key":self.download_key.get(),"api_url":downloader_service.DEFAULT_API_URL}
        self.prepare_download_rows(batch_id,urls); self.open_download_window(batch_id,urls,controls)
        values=(batch_id,input_text,self.project,self.download_quality.get(),self.ffmpeg.get(),int(self.download_workers.get()),self.download_key.get(),controls); self.run(lambda: self.download(*values))
    def download(self,batch_id,input_text,project,quality,ffmpeg,download_workers,api_key,controls):
        try:
            if not project: raise ValueError("请先选择项目目录")
            urls=downloader_service.extract_share_urls(input_text);
            if not urls: raise ValueError("请至少输入一条抖音分享链接")
            api_threads=len(urls); download_threads=downloader_service.worker_count(len(urls),download_workers)
            self.log(f"[批次 {batch_id}] 识别到 {len(urls)} 个独立视频 URL，自动分配 {api_threads} 个 API 解析线程、{download_threads} 个下载线程")
            if batch_id==self.latest_batch_id: self.set_status(f"批次 {batch_id}：已识别 {len(urls)} 条链接")
            completed=0
            progress_values=[0.0]*len(urls)
            if batch_id==self.latest_batch_id: self.set_progress(0)
            def done(index,url,path,error):
                nonlocal completed; completed+=1; progress_values[index]=1.0
                if batch_id==self.latest_batch_id: self.set_progress(sum(progress_values)/len(progress_values)*100); self.set_status(f"批次 {batch_id}：{completed}/{len(urls)}")
                self.set_task_progress(batch_id,index,100 if not error else 0,"失败" if error else "完成")
                self.task_store.update_item(self.batch_task_ids[batch_id],index,path=str(path or ""),error=str(error or ""))
                self.log(f"[批次 {batch_id} · {index+1}/{len(urls)}] 下载失败：{error}" if error else f"[批次 {batch_id} · {index+1}/{len(urls)}] 视频已保存：{path}")
            def progress(index,url,value):
                progress_values[index]=value
                if batch_id==self.latest_batch_id: self.set_progress(sum(progress_values)/len(progress_values)*100)
                self.set_task_progress(batch_id,index,value*100)
            results=downloader_service.download_videos(input_text,str(project),api_key=api_key,quality=quality,ffmpeg=ffmpeg,download_workers=download_workers,on_done=done,on_progress=progress,controls=controls); ok=sum(1 for _,_,error in results if error is None)
            self.task_store.update_task(self.batch_task_ids[batch_id],status="完成" if ok==len(urls) else "部分失败")
            if batch_id==self.latest_batch_id: self.set_progress(100); self.set_status(f"批次 {batch_id} 完成：成功 {ok}/{len(urls)}")
        except Exception as e:
            task_id=self.batch_task_ids.get(batch_id)
            if task_id:self.task_store.update_task(task_id,status="失败",error=str(e))
            if batch_id==self.latest_batch_id: self.set_status(f"批次 {batch_id} 失败")
            self.log(f"[批次 {batch_id}] 下载失败：{e}")
    def set_transcribe_progress(self,batch_id,index,value,status):
        task_id=self.transcribe_task_ids.get(batch_id)
        if task_id:self.task_store.update_item(task_id,index,progress=value,status=status)
        def update():
            row=self.transcribe_rows.get((batch_id,index)); percent=max(0,min(100,value))
            if row:
                bar,state,retry=row; bar.configure(value=percent); state.set(status); retry.configure(state="normal" if status=="失败" else "disabled")
            self.refresh_task_center()
        self.after(0,update)
    def control_transcribe(self,batch_id,index,resume):
        controls=self.transcribe_controls.get(batch_id,[])
        if not (0<=index<len(controls)): return
        controls[index].resume() if resume else controls[index].pause(); row=self.transcribe_rows.get((batch_id,index)); value=float(row[0]["value"]) if row else 0; self.set_transcribe_progress(batch_id,index,value,"续传中" if resume else "已停止")
    def open_transcribe_window(self,batch_id,videos,controls):
        win=tk.Toplevel(self); win.title(f"文案与 SRT 任务 · 批次 {batch_id}"); win.geometry("980x430"); win.minsize(760,300)
        outer=ttk.Frame(win,padding=12); outer.pack(fill="both",expand=True); outer.columnconfigure(0,weight=1); outer.rowconfigure(1,weight=1); ttk.Label(outer,text=f"转写批次 {batch_id} · {len(videos)} 个视频",style="Section.TLabel").grid(row=0,column=0,sticky="w",pady=(0,8))
        canvas=tk.Canvas(outer,bg="#FFFFFF",highlightthickness=1,highlightbackground="#E1E6ED"); canvas.grid(row=1,column=0,sticky="nsew"); scroll=ttk.Scrollbar(outer,orient="vertical",command=canvas.yview); scroll.grid(row=1,column=1,sticky="ns"); canvas.configure(yscrollcommand=scroll.set); frame=ttk.Frame(canvas,style="Panel.TFrame"); window_id=canvas.create_window((0,0),window=frame,anchor="nw"); frame.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all"))); canvas.bind("<Configure>",lambda e:canvas.itemconfigure(window_id,width=e.width)); self.transcribe_windows[batch_id]=win
        for index,video in enumerate(videos):
            row=ttk.Frame(frame,style="Panel.TFrame",padding=7); row.pack(fill="x"); row.columnconfigure(1,weight=1); ttk.Label(row,text=f"{index+1}.",width=4,style="Panel.TLabel").grid(row=0,column=0); ttk.Label(row,text=video.name,style="Panel.TLabel").grid(row=0,column=1,sticky="w"); bar=ttk.Progressbar(row,maximum=100); bar.grid(row=0,column=2,sticky="ew",padx=8); state=tk.StringVar(value="等待处理"); ttk.Label(row,textvariable=state,width=13,style="Muted.TLabel").grid(row=0,column=3); retry=ttk.Button(row,text="重试",state="disabled",command=lambda i=index:self.retry_transcribe(batch_id,i)); retry.grid(row=0,column=4,padx=2); self.transcribe_rows[(batch_id,index)]=(bar,state,retry)
        def close():
            self.transcribe_windows.pop(batch_id,None)
            for key in [key for key in self.transcribe_rows if key[0]==batch_id]: self.transcribe_rows.pop(key,None)
            win.destroy()
        win.protocol("WM_DELETE_WINDOW",close)
    def transcribe_one(self,batch_id,index,video,context):
        control=context["controls"][index]
        try:
            control.checkpoint(); self.set_transcribe_progress(batch_id,index,5,"准备音频")
            status=lambda value:self.set_transcribe_progress(batch_id,index,45 if "识别" in value else (12 if "提取" in value else 20),value)
            with asr.prepared_asr_audio(str(video),context["ffmpeg"],status) as audio_path:
                control.checkpoint(); seg=asr.transcribe(audio_path,key=context["api_key"],language=context["source_lang"],on_status=status)
            control.checkpoint(); self.set_transcribe_progress(batch_id,index,85,"生成文案/SRT")
            json_path=video.with_suffix(".json"); srt_path=video.with_suffix(".srt"); txt_path=video.with_suffix(".txt")
            json_path.write_text(json.dumps(seg,ensure_ascii=False,indent=2),encoding="utf-8")
            srt_path.write_text(asr.segments_to_srt(seg),encoding="utf-8-sig")
            txt_path.write_text(asr.segments_to_text(seg),encoding="utf-8-sig")
            self.set_transcribe_progress(batch_id,index,100,"完成"); return (srt_path.name,txt_path.name)
        except Exception:
            self.set_transcribe_progress(batch_id,index,0,"失败"); raise
    def retry_transcribe(self,batch_id,index):
        context=self.transcribe_contexts.get(batch_id)
        if not context:return
        context["controls"][index].resume(); self.set_transcribe_progress(batch_id,index,0,"重试中"); video=context["videos"][index]
        def retry():
            try: result=self.transcribe_one(batch_id,index,video,context); self.log(f"[转写批次 {batch_id} · {index+1}] 重试成功：{result[0]}、{result[1]}")
            except Exception as exc: self.log(f"[转写批次 {batch_id} · {index+1}] 重试失败：{exc}")
        self.run(retry)
    def transcribed_videos(self):
        if not self.project or not self.project.is_dir(): return []
        return [video for video in rename_service.list_videos(self.project) if video.with_suffix(".txt").is_file() and video.with_suffix(".srt").is_file()]
    def open_rewrite_window(self):
        if not self.project:
            messagebox.showinfo("AI 改写","请先选择项目目录",parent=self); return
        videos=self.transcribed_videos()
        if not videos:
            messagebox.showinfo("AI 改写","当前目录没有同时包含同名 TXT 和 SRT 的已转写视频",parent=self); return
        win=tk.Toplevel(self); win.title("AI 文案改写"); win.geometry("820x700"); win.minsize(680,560)
        outer=ttk.Frame(win,padding=16); outer.pack(fill="both",expand=True); outer.columnconfigure(0,weight=1); outer.rowconfigure(1,weight=1); outer.rowconfigure(4,weight=1); outer.rowconfigure(7,weight=1)
        ttk.Label(outer,text="选择已转写视频",style="Section.TLabel").grid(row=0,column=0,sticky="w")
        list_box=ttk.Frame(outer); list_box.grid(row=1,column=0,sticky="nsew",pady=(7,8)); list_box.columnconfigure(0,weight=1); list_box.rowconfigure(0,weight=1)
        canvas=tk.Canvas(list_box,height=180,highlightthickness=1,highlightbackground="#D5DCE5",background="#FFFFFF"); canvas.grid(row=0,column=0,sticky="nsew")
        scroll=ttk.Scrollbar(list_box,orient="vertical",command=canvas.yview); scroll.grid(row=0,column=1,sticky="ns"); canvas.configure(yscrollcommand=scroll.set)
        rows=ttk.Frame(canvas); window_id=canvas.create_window((0,0),window=rows,anchor="nw")
        rows.bind("<Configure>",lambda _event:canvas.configure(scrollregion=canvas.bbox("all"))); canvas.bind("<Configure>",lambda event:canvas.itemconfigure(window_id,width=event.width))
        checks=[]
        for video in videos:
            selected=tk.BooleanVar(value=True); ttk.Checkbutton(rows,text=video.name,variable=selected).pack(fill="x",anchor="w",padx=8,pady=3); checks.append((video,selected))
        select_bar=ttk.Frame(outer); select_bar.grid(row=2,column=0,sticky="ew"); ttk.Button(select_bar,text="全选",command=lambda:[value.set(True) for _,value in checks]).pack(side="left"); ttk.Button(select_bar,text="清空",command=lambda:[value.set(False) for _,value in checks]).pack(side="left",padx=5)
        prompt_header=ttk.Frame(outer); prompt_header.grid(row=3,column=0,sticky="ew",pady=(12,4)); ttk.Label(prompt_header,text="改写提示词",style="Section.TLabel").pack(side="left")
        prompt_name=tk.StringVar(value=self.rewrite_prompts[0]["name"] if self.rewrite_prompts else "")
        prompt_picker=ttk.Combobox(prompt_header,textvariable=prompt_name,state="readonly",values=[item["name"] for item in self.rewrite_prompts],width=22); prompt_picker.pack(side="right",padx=(6,0))
        ttk.Button(prompt_header,text="提示词管理",command=lambda:self.manage_rewrite_prompts(win,prompt,prompt_name,prompt_picker)).pack(side="right")
        prompt=tk.Text(outer,height=7,wrap="word",font=("Microsoft YaHei UI",9),bg="#F8FAFC",fg="#203047",relief="flat",padx=9,pady=8); prompt.grid(row=4,column=0,sticky="nsew")
        def use_prompt(name):
            item=next((item for item in self.rewrite_prompts if item["name"]==name),None)
            if item: prompt.delete("1.0","end"); prompt.insert("1.0",item["text"])
        prompt_picker.bind("<<ComboboxSelected>>",lambda _event:use_prompt(prompt_name.get()))
        if self.rewrite_prompts: use_prompt(prompt_name.get())
        preset_bar=ttk.Frame(outer); preset_bar.grid(row=5,column=0,sticky="ew",pady=(6,0))
        for name,value in DEFAULT_REWRITE_PROMPTS.items(): ttk.Button(preset_bar,text=name,command=lambda text=value:(prompt.delete("1.0","end"),prompt.insert("1.0",text))).pack(side="left",padx=(0,4))
        options=ttk.Frame(outer); options.grid(row=6,column=0,sticky="ew",pady=(10,0)); model=tk.StringVar(value="qwen-plus")
        ttk.Label(options,text="百炼模型",style="Panel.TLabel").pack(side="left"); ttk.Combobox(options,textvariable=model,state="readonly",values=["qwen-plus","qwen-turbo","qwen-max","qwen-long"],width=22).pack(side="left",padx=7)
        status=tk.StringVar(value="就绪"); ttk.Label(options,textvariable=status,style="Muted.TLabel").pack(side="right")
        result_box=ttk.Frame(outer); result_box.grid(row=7,column=0,sticky="nsew",pady=(9,0)); result_box.columnconfigure(0,weight=1); result_box.rowconfigure(0,weight=1)
        result_tree=ttk.Treeview(result_box,columns=("status","output"),show="tree headings",height=5); result_tree.heading("#0",text="视频"); result_tree.heading("status",text="状态"); result_tree.heading("output",text="输出文件"); result_tree.column("#0",width=280); result_tree.column("status",width=120,anchor="center"); result_tree.column("output",width=300); result_tree.grid(row=0,column=0,sticky="nsew")
        result_scroll=ttk.Scrollbar(result_box,orient="vertical",command=result_tree.yview); result_scroll.grid(row=0,column=1,sticky="ns"); result_tree.configure(yscrollcommand=result_scroll.set)
        result_state={}
        def begin():
            chosen=[video for video,value in checks if value.get()]; instruction=prompt.get("1.0","end").strip(); key=self.asr_key.get().strip(); selected_model=model.get()
            if not chosen: messagebox.showinfo("AI 改写","请至少勾选一个视频",parent=win); return
            if not instruction: messagebox.showinfo("AI 改写","请填写改写提示词",parent=win); return
            if not key: messagebox.showerror("AI 改写","请先在接口设置中填写阿里云百炼 API Key",parent=win); return
            for video in chosen: result_tree.insert("","end",iid=str(video),text=video.name,values=("等待中",""))
            task=self.task_store.create("rewrite",f"AI 改写批次 · {selected_model}",str(self.project),[{"path":str(video),"name":video.name} for video in chosen]); self.task_store.update_task(task["id"],status="运行中")
            result_state.update(task_id=task["id"],completed=0,success=0,total=len(chosen))
            start_button.configure(state="disabled"); status.set(f"处理中 0/{len(chosen)}")
            self.run(lambda:self.rewrite_batch(chosen,instruction,key,selected_model,self.project,result_tree,status,start_button,result_state))
        start_button=ttk.Button(outer,text="开始生成",style="Primary.TButton",command=begin); start_button.grid(row=8,column=0,sticky="e",pady=(10,0))
    def manage_rewrite_prompts(self,parent,prompt,prompt_name,prompt_picker):
        win=tk.Toplevel(parent); win.title("改写提示词管理"); win.geometry("760x520"); win.minsize(620,420)
        outer=ttk.Frame(win,padding=14); outer.pack(fill="both",expand=True); outer.columnconfigure(0,weight=1); outer.columnconfigure(1,weight=2); outer.rowconfigure(1,weight=1)
        ttk.Label(outer,text="已保存提示词",style="Section.TLabel").grid(row=0,column=0,sticky="w",pady=(0,7)); ttk.Label(outer,text="提示词内容",style="Section.TLabel").grid(row=0,column=1,sticky="w",padx=(12,0),pady=(0,7))
        listing=tk.Listbox(outer,exportselection=False); listing.grid(row=1,column=0,sticky="nsew")
        name=tk.StringVar(); name_entry=ttk.Entry(outer,textvariable=name); name_entry.grid(row=1,column=1,sticky="new",padx=(12,0))
        content=tk.Text(outer,wrap="word",font=("Microsoft YaHei UI",9),bg="#F8FAFC",fg="#203047",relief="flat",padx=9,pady=8); content.grid(row=1,column=1,sticky="nsew",padx=(12,0),pady=(34,0))
        def refresh(select=None):
            listing.delete(0,"end")
            for item in self.rewrite_prompts: listing.insert("end",item["name"])
            if select is not None and self.rewrite_prompts: listing.selection_set(select); listing.activate(select); load_selected()
        def load_selected(_event=None):
            selection=listing.curselection()
            if not selection:return
            item=self.rewrite_prompts[selection[0]]; name.set(item["name"]); content.delete("1.0","end"); content.insert("1.0",item["text"])
        listing.bind("<<ListboxSelect>>",load_selected)
        def save_prompt():
            label=name.get().strip(); text=content.get("1.0","end").strip()
            if not label or not text: messagebox.showinfo("提示词管理","名称和提示词内容都不能为空",parent=win); return
            selection=listing.curselection(); old=self.rewrite_prompts[selection[0]]["name"] if selection else None
            duplicate=next((i for i,item in enumerate(self.rewrite_prompts) if item["name"]==label and item["name"]!=old),None)
            if duplicate is not None: messagebox.showinfo("提示词管理","提示词名称已存在",parent=win); return
            replacement={"name":label,"text":text}
            if selection:self.rewrite_prompts[selection[0]]=replacement; index=selection[0]
            else:self.rewrite_prompts.append(replacement); index=len(self.rewrite_prompts)-1
            self.save_all_settings(False); refresh(index); prompt_picker.configure(values=[item["name"] for item in self.rewrite_prompts]); prompt_name.set(label)
        def delete_prompt():
            selection=listing.curselection()
            if not selection:return
            del self.rewrite_prompts[selection[0]]; self.save_all_settings(False); refresh(min(selection[0],len(self.rewrite_prompts)-1) if self.rewrite_prompts else None)
            prompt_picker.configure(values=[item["name"] for item in self.rewrite_prompts]); prompt_name.set(self.rewrite_prompts[0]["name"] if self.rewrite_prompts else "")
        def apply_prompt():
            text=content.get("1.0","end").strip()
            if not text: messagebox.showinfo("提示词管理","请先选择或填写提示词",parent=win); return
            prompt.delete("1.0","end"); prompt.insert("1.0",text)
            if name.get().strip():prompt_name.set(name.get().strip())
            win.destroy()
        actions=ttk.Frame(outer); actions.grid(row=2,column=0,columnspan=2,sticky="ew",pady=(12,0))
        ttk.Button(actions,text="新建",command=lambda:(listing.selection_clear(0,"end"),name.set("新提示词"),content.delete("1.0","end"))).pack(side="left")
        ttk.Button(actions,text="保存",command=save_prompt).pack(side="left",padx=5); ttk.Button(actions,text="删除",command=delete_prompt).pack(side="left")
        ttk.Button(actions,text="应用到编辑框",style="Primary.TButton",command=apply_prompt).pack(side="right"); refresh(0 if self.rewrite_prompts else None)
    def rewrite_batch(self,videos,prompt,key,model,project,result_tree,status,start_button,result_state):
        def operation(item):
            index,video=item; self.task_store.update_item(result_state["task_id"],index,status="改写中")
            self.after(0,lambda:self._set_rewrite_row(result_tree,video,"改写中"))
            try:
                text=video.with_suffix(".txt").read_text(encoding="utf-8-sig").strip()
                if not text: raise ValueError("转录 TXT 内容为空")
                rewritten=ai.rewrite_text(text,prompt,key,model)
                output_dir=project/video.stem; output_dir.mkdir(parents=True,exist_ok=True)
                output=output_dir/(video.stem+".txt"); output.write_text(rewritten+"\n",encoding="utf-8-sig")
                self.task_store.update_item(result_state["task_id"],index,status="完成",progress=100,output=str(output),error="")
                self.after(0,lambda:self._set_rewrite_row(result_tree,video,"完成",str(output)))
                return output
            except Exception as exc:
                error=str(exc); self.task_store.update_item(result_state["task_id"],index,status="失败",error=error)
                self.after(0,lambda:self._set_rewrite_row(result_tree,video,f"失败：{error}"))
                raise
        results=run_batch(list(enumerate(videos)),operation,workers=min(len(videos),8),retries=0)
        ok=sum(1 for _,_,error in results if error is None)
        self.task_store.update_task(result_state["task_id"],status="完成" if ok==len(videos) else "部分失败")
        self.after(0,lambda:(start_button.configure(state="normal") if start_button.winfo_exists() else None,status.set(f"批次完成：成功 {ok}/{len(videos)}") if status.winfo_exists() else None))
    def _set_rewrite_row(self,tree,video,state,output=""):
        if tree.winfo_exists(): tree.item(str(video),values=(state,output))
    def start_transcribe(self):
        if not self.project: self.log("转写失败：请先选择输出目录"); return
        videos=rename_service.list_videos(self.project)
        if not videos: self.log("转写失败：输出目录中没有视频"); return
        self.transcribe_counter+=1; batch_id=self.transcribe_counter; self.latest_transcribe_id=batch_id; controls=[downloader_service.DownloadControl() for _ in videos]; context={"project":self.project,"videos":videos,"controls":controls,"source_lang":self.source_lang.get(),"ffmpeg":self.ffmpeg.get(),"api_key":self.asr_key.get()}; self.transcribe_controls[batch_id]=controls; self.transcribe_contexts[batch_id]=context
        saved_task=self.task_store.create("transcribe",f"文案与 SRT 批次 {batch_id}",str(self.project),[{"path":str(video),"name":video.name} for video in videos]); self.transcribe_task_ids[batch_id]=saved_task["id"]; self.task_store.update_task(saved_task["id"],status="运行中")
        self.open_transcribe_window(batch_id,videos,controls); self.run(lambda:self.transcribe(batch_id,context))
    def transcribe(self,batch_id,context):
        videos=context["videos"]; completed=0
        effective_workers=len(videos)
        self.log(f"[转写批次 {batch_id}] 已按 {len(videos)} 个视频自动分配 {effective_workers} 个任务线程")
        def operation(item): index,video=item; return self.transcribe_one(batch_id,index,video,context)
        def done(position,item,result,error):
            nonlocal completed; index,video=item; completed+=1
            self.task_store.update_item(self.transcribe_task_ids[batch_id],index,error=str(error or ""))
            if batch_id==self.latest_transcribe_id:self.set_status(f"转写批次 {batch_id}：{completed}/{len(videos)}")
            self.log(f"[转写批次 {batch_id} · {index+1}] 失败 {video.name}：{error}" if error else f"[转写批次 {batch_id} · {index+1}] 已生成：{result[0]}、{result[1]}")
        results=run_batch(list(enumerate(videos)),operation,effective_workers,done,retries=3); ok=sum(1 for _,_,error in results if error is None)
        self.task_store.update_task(self.transcribe_task_ids[batch_id],status="完成" if ok==len(videos) else "部分失败")
        if batch_id==self.latest_transcribe_id:self.set_status(f"转写批次 {batch_id} 完成：成功 {ok}/{len(videos)}")
    def start_rewrite(self): self.run(self.rewrite)
    def rewrite(self):
        try:
            seg=json.load(open(self.project/"transcript.json",encoding="utf-8")); result=ai.rewrite(seg,self.lang.get(),self.llm_url.get(),self.llm_key.get(),self.llm_model.get(),self.style.get(),self.length.get()); json.dump(result,open(self.project/"rewrite.json","w",encoding="utf-8"),ensure_ascii=False,indent=2); self.log(json.dumps(result,ensure_ascii=False,indent=2)); self.status.set("改写完成")
        except Exception as e: self.status.set("失败"); self.log("改写失败："+str(e))
    def start_edit(self): self.run(self.edit)
    def edit(self):
        try:
            video=str(next((p for p in self.project.glob("*.mp4") if p.name != "edited.mp4"), self.project/"source.mp4")); duration=media.probe_duration(self.ffmpeg.get(),video); scenes=media.fixed_scenes(duration); seg=json.load(open(self.project/"transcript.json",encoding="utf-8")); rewrite=json.load(open(self.project/"rewrite.json",encoding="utf-8")); raw=ai.edit_plan(seg,scenes,rewrite,self.llm_url.get(),self.llm_key.get(),self.llm_model.get()); plan=ai.validate_plan(raw,scenes,rewrite,duration); json.dump(plan,open(self.project/"edit-plan.json","w",encoding="utf-8"),ensure_ascii=False,indent=2); out=str(self.project/"edited.mp4"); media.execute_plan(self.ffmpeg.get(),video,plan,out); self.log(json.dumps(plan,ensure_ascii=False,indent=2)); self.log("成片已导出："+out); self.status.set("剪辑完成")
        except Exception as e: self.status.set("失败"); self.log("剪辑失败："+str(e))

if __name__ == "__main__": App().mainloop()
