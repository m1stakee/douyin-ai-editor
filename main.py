import json, os, shutil, threading, time, webbrowser
from datetime import datetime
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import downloader_service, media, asr, ai, rename_service, voicevox_service
from batch_service import run_batch, transcribe_worker_count
from app_config import ark_key, dashscope_key, henghengmao_key, load_settings, save_settings
from task_store import TaskStore
from license_client import require_license, verify_saved_license

DEFAULT_REWRITE_PROMPTS={"自然口播":"请将文案改写成自然、流畅、适合口播的表达。保留原文事实和核心信息，不添加未经证实的内容。只返回改写后的正文。","卖点浓缩":"请提炼并改写文案，突出最重要的卖点，表达简洁有力。保留原文事实，不添加新信息。只返回改写后的正文。","故事叙述":"请将文案改写成有起承转合、易于听懂的故事化表达。保留原文事实和核心信息，不虚构情节。只返回改写后的正文。","新闻讲解":"请将文案改写成清晰、客观、适合短视频讲解的表达。保留原文事实，不夸大、不添加未经证实的信息。只返回改写后的正文。","轻度去重":"请对文案进行轻度改写，调整措辞和句式以降低重复度，同时完整保留原意、事实和信息顺序。只返回改写后的正文。","悬念开场":"请为文案设计一个简短、有吸引力的悬念式开场，再自然衔接正文。保留原文事实，不夸大、不虚构。只返回改写后的完整文案。"}
OPENAI_COMPAT_URL="https://new-api.aicarb.com/v1"
OPENAI_COMPAT_MODEL="gpt-6.1-sol"
OPENAI_COMPAT_REASONING_EFFORT="low"
DOUBAO_API_URL="https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_MODEL="doubao-seed-2-1-pro-260915"
STEP_DOWNLOAD_DIR="1_下载视频"
STEP_TRANSCRIBE_DIR="2_文案与SRT"
STEP_CUT_DIR="3_字幕剪辑"
STEP_REWRITE_DIR="4_AI改写"
STEP_VOICE_DIR="5_语音转出"

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title("VideoFlow · 短视频智能工作台"); self.geometry("1180x820"); self.minsize(1000,720); self.configure(bg="#EEF1F5")
        saved=load_settings(); output=saved.get("output_directory",""); self.project=Path(output) if output else None
        stored_prompts=saved.get("rewrite_prompts")
        defaults=[{"name":name,"text":text} for name,text in DEFAULT_REWRITE_PROMPTS.items()]
        self.rewrite_prompts=stored_prompts if isinstance(stored_prompts,list) else defaults
        if len(self.rewrite_prompts)==5 and all(item.get("name") in DEFAULT_REWRITE_PROMPTS for item in self.rewrite_prompts):
            missing=[item for item in defaults if item["name"] not in {saved_item.get("name") for saved_item in self.rewrite_prompts}]
            self.rewrite_prompts.extend(missing)
        # FFmpeg is bundled with the application; ignore any legacy user path.
        self.ffmpeg=tk.StringVar(value=asr.resolve_ffmpeg())
        self.download_key=tk.StringVar(value=saved.get("henghengmao_api_key", "")); self.asr_key=tk.StringVar(value=saved.get("dashscope_api_key") or dashscope_key())
        self.download_quality=tk.StringVar(value=saved.get("download_quality","推荐")); self.download_workers=tk.StringVar(value=saved.get("download_workers","8")); self.source_lang=tk.StringVar(value=saved.get("source_lang","中文"))
        self.llm_key=tk.StringVar(value=saved.get("llm_key","")); self.ark_key=tk.StringVar(value=saved.get("ark_api_key") or ark_key()); self.lang=tk.StringVar(value=saved.get("target_lang","英语"))
        self.style=tk.StringVar(value=saved.get("writing_style","自然口播")); self.length=tk.StringVar(value=saved.get("writing_length","保持原时长"))
        self.license_key=tk.StringVar(value=saved.get("license_key", ""))
        self.voicevox_path=tk.StringVar(value=saved.get("voicevox_path", "")); self.voicevox_voice=tk.StringVar(value=saved.get("voicevox_voice", "")); self.voicevox_speed=tk.StringVar(value=saved.get("voicevox_speed", "1.0")); self.voicevox_pitch=tk.StringVar(value=saved.get("voicevox_pitch", "0.0")); self.voicevox_volume=tk.StringVar(value=saved.get("voicevox_volume", "1.0")); self.voicevox_pause=tk.StringVar(value=saved.get("voicevox_pause", "0.3")); self.voicevox_output_directory=tk.StringVar(value=saved.get("voicevox_output_directory", "")); self.voicevox_output_format=tk.StringVar(value=str(saved.get("voicevox_output_format", "WAV")).upper()); self.voicevox_use_gpu=tk.BooleanVar(value=saved.get("voicevox_use_gpu", False)); self.voicevox_process=None; self.voicevox_process_gpu=None; self.voicevox_window=None
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
        style.configure("Selected.TButton",font=("Microsoft YaHei UI",9,"bold"),padding=(9,5),background="#2C7A65",foreground="#FFFFFF")
        style.map("Selected.TButton",background=[("active","#236452")])
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
        ttk.Button(flow,text="1  下载视频",style="Primary.TButton",command=self.start_download).pack(side="left",padx=(0,7)); ttk.Button(flow,text="2  生成文案与 SRT",style="Flow.TButton",command=self.start_transcribe).pack(side="left",padx=7); ttk.Button(flow,text="3  字幕剪辑",style="Flow.TButton",command=self.start_cutting).pack(side="left",padx=7); ttk.Button(flow,text="4  AI 改写",style="Flow.TButton",command=self.open_rewrite_window).pack(side="left",padx=7); ttk.Button(flow,text="5  语音转出",style="Flow.TButton",command=self.open_voicevox_window).pack(side="left",padx=7)
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
        self.advanced=ttk.Frame(settings,style="Panel.TFrame"); self._field(self.advanced,"软件卡密",self.license_key,0,0,secret=True); self._field(self.advanced,"哼哼猫 Key",self.download_key,1,0,secret=True); self._field(self.advanced,"阿里百炼 Key",self.asr_key,2,0,secret=True); self._field(self.advanced,"ChatGPT 接口 Key",self.llm_key,3,0,secret=True); self._field(self.advanced,"豆包 Ark Key",self.ark_key,4,0,secret=True)
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
        return {"output_directory":str(self.project or ""),"download_quality":self.download_quality.get(),"download_workers":self.download_workers.get(),"source_lang":self.source_lang.get(),"henghengmao_api_key":self.download_key.get(),"dashscope_api_key":self.asr_key.get(),"llm_key":self.llm_key.get(),"ark_api_key":self.ark_key.get(),"target_lang":self.lang.get(),"writing_style":self.style.get(),"writing_length":self.length.get(),"license_key":self.license_key.get(),"voicevox_path":self.voicevox_path.get(),"voicevox_voice":self.voicevox_voice.get(),"voicevox_speed":self.voicevox_speed.get(),"voicevox_pitch":self.voicevox_pitch.get(),"voicevox_volume":self.voicevox_volume.get(),"voicevox_pause":self.voicevox_pause.get(),"voicevox_output_directory":self.voicevox_output_directory.get(),"voicevox_output_format":self.voicevox_output_format.get(),"voicevox_use_gpu":self.voicevox_use_gpu.get(),"rewrite_prompts":self.rewrite_prompts}
    def save_all_settings(self,notify=True):
        path=save_settings(self.settings_values()); self.status.set("配置已保存")
        if notify: messagebox.showinfo("保存配置",f"全部配置已保存到本机：{path.name}")
    def close_app(self):
        self.save_all_settings(False)
        for group in (self.batch_controls,self.transcribe_controls):
            for controls in group.values():
                for control in controls: control.cancel()
        voicevox_service.stop_owned_process(self.voicevox_process)
        self.exit_process()
    def exit_process(self):
        self.destroy(); os._exit(0)
    def choose_project(self):
        p=filedialog.askdirectory();
        if p: self.project=Path(p); self.project_text.set(f"输出到：{p}"); self.status.set("输出目录已选择")
    def step_directory(self,name):
        if not self.project: raise ValueError("请先选择项目目录")
        folder=self.project/name; folder.mkdir(parents=True,exist_ok=True); return folder
    def open_project(self):
        if not self.project: messagebox.showinfo("打开输出目录","请先选择输出目录"); return
        if not self.project.exists(): messagebox.showerror("打开输出目录","输出目录不存在"); return
        os.startfile(str(self.project))
    def open_voicevox_window(self):
        if self.voicevox_window and self.voicevox_window.winfo_exists():
            self.voicevox_window.deiconify(); self.voicevox_window.lift(); return
        win=tk.Toplevel(self); win.title("VOICEVOX 本地语音"); win.geometry("800x880"); win.minsize(700,880); win.resizable(True,False); self.voicevox_window=win
        outer=ttk.Frame(win,padding=16); outer.pack(fill="both",expand=True); outer.columnconfigure(0,weight=1)
        ttk.Label(outer,text="VOICEVOX 本地语音",style="Section.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(outer,text="用户从官方渠道安装；本软件只连接本机 127.0.0.1，不会把引擎开放到公网。",style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(3,9))
        install_box=ttk.Frame(outer,style="Panel.TFrame",padding=12,height=158); install_box.grid(row=2,column=0,sticky="ew"); install_box.grid_propagate(False); install_box.columnconfigure(1,weight=1)
        status_var=tk.StringVar(value="未连接"); operation_var=tk.StringVar(value="正在检测本机引擎……")
        ttk.Label(install_box,text="引擎状态",style="Panel.TLabel",width=11).grid(row=0,column=0,sticky="w"); ttk.Label(install_box,textvariable=status_var,style="Panel.TLabel").grid(row=0,column=1,sticky="w")
        ttk.Label(install_box,text="安装位置",style="Panel.TLabel",width=11).grid(row=1,column=0,sticky="w",pady=(7,0)); path_entry=ttk.Entry(install_box,textvariable=self.voicevox_path); path_entry.grid(row=1,column=1,sticky="ew",pady=(7,0))
        install_actions=ttk.Frame(install_box,style="Panel.TFrame"); install_actions.grid(row=2,column=0,columnspan=2,sticky="ew",pady=(9,0))
        ttk.Button(install_actions,text="打开官方安装页",command=lambda:webbrowser.open(voicevox_service.OFFICIAL_DOWNLOAD_URL)).pack(side="left")
        def choose_installation():
            selected=filedialog.askopenfilename(parent=win,title="选择 VOICEVOX.exe 或 vv-engine/run.exe",filetypes=[("VOICEVOX", "*.exe"),("所有文件", "*.*")])
            if selected: self.voicevox_path.set(selected); self.save_all_settings(False); inspect(False)
        ttk.Button(install_actions,text="选择安装位置",command=choose_installation).pack(side="left",padx=6)
        connect_button=ttk.Button(install_actions,text="启动并连接"); connect_button.pack(side="left")
        exit_engine_button=ttk.Button(install_actions,text="退出引擎"); exit_engine_button.pack(side="left",padx=(6,0))
        ttk.Label(install_box,text="操作提示",style="Panel.TLabel",width=11).grid(row=3,column=0,sticky="nw",pady=(8,0)); ttk.Label(install_box,textvariable=operation_var,style="Muted.TLabel",wraplength=610).grid(row=3,column=1,sticky="w",pady=(8,0))

        settings_box=ttk.Frame(outer,style="Panel.TFrame",padding=12,height=137); settings_box.grid(row=3,column=0,sticky="ew",pady=10); settings_box.grid_propagate(False); settings_box.columnconfigure(1,weight=1)
        voice_var=self.voicevox_voice; voice_combo=ttk.Combobox(settings_box,textvariable=voice_var,state="readonly"); voice_combo.grid(row=0,column=1,columnspan=3,sticky="ew")
        ttk.Label(settings_box,text="音色",style="Panel.TLabel",width=11).grid(row=0,column=0,sticky="w")
        speed_var=self.voicevox_speed; pitch_var=self.voicevox_pitch; volume_var=self.voicevox_volume
        for column,(label,var) in enumerate((("语速",speed_var),("音高",pitch_var),("音量",volume_var))):
            box=ttk.Frame(settings_box,style="Panel.TFrame"); box.grid(row=1,column=column+1,sticky="ew",padx=(0 if column==0 else 7,0),pady=(8,0)); settings_box.columnconfigure(column+1,weight=1)
            ttk.Label(box,text=label,style="Panel.TLabel").pack(side="left"); ttk.Entry(box,textvariable=var,width=8).pack(side="left",fill="x",expand=True,padx=(5,0))
        ttk.Label(settings_box,text="参数",style="Panel.TLabel",width=11).grid(row=1,column=0,sticky="w",pady=(8,0))
        compute_box=ttk.Frame(settings_box,style="Panel.TFrame"); compute_box.grid(row=2,column=0,columnspan=4,sticky="ew",pady=(8,0))
        ttk.Label(compute_box,text="计算模式",style="Panel.TLabel",width=11).pack(side="left")
        gpu_mode_text=tk.StringVar(); gpu_button=ttk.Button(compute_box,textvariable=gpu_mode_text,width=14); gpu_button.pack(side="left")
        ttk.Label(compute_box,text="GPU 推理，CPU 仍负责文本和音频处理",style="Muted.TLabel").pack(side="left",padx=(8,0))

        file_box=ttk.Frame(outer,style="Panel.TFrame",padding=12,height=340); file_box.grid(row=4,column=0,sticky="ew"); file_box.grid_propagate(False); file_box.columnconfigure(0,weight=1); file_box.rowconfigure(2,weight=1)
        ttk.Label(file_box,text="导入文案文件（支持一次选择多个 TXT）",style="Panel.TLabel").grid(row=0,column=0,sticky="w")
        file_actions=ttk.Frame(file_box,style="Panel.TFrame"); file_actions.grid(row=1,column=0,sticky="ew",pady=(7,7))
        file_rows=[]
        file_canvas=tk.Canvas(file_box,bg="#F8FAFC",relief="flat",highlightthickness=1,highlightbackground="#D5DCE5")
        file_scroll=ttk.Scrollbar(file_box,orient="vertical",command=file_canvas.yview); file_canvas.configure(yscrollcommand=file_scroll.set)
        file_canvas.grid(row=2,column=0,sticky="nsew"); file_scroll.grid(row=2,column=1,sticky="ns")
        file_rows_frame=ttk.Frame(file_canvas,style="Panel.TFrame"); file_rows_window=file_canvas.create_window((0,0),window=file_rows_frame,anchor="nw")
        file_rows_frame.bind("<Configure>",lambda _event:file_canvas.configure(scrollregion=file_canvas.bbox("all")))
        file_canvas.bind("<Configure>",lambda event:file_canvas.itemconfigure(file_rows_window,width=event.width))
        file_count=tk.StringVar(value="尚未导入文案")
        def refresh_file_count():
            selected=sum(1 for row in file_rows if row["selected"].get()); file_count.set(f"已选择 {selected} / {len(file_rows)} 个文件")
        def refresh_script_selection(row):
            is_selected=row["selected"].get(); row["selection_text"].set("已选择" if is_selected else "未选择")
            row["selection_button"].configure(style="Selected.TButton" if is_selected else "TButton")
        def toggle_script_selection(row):
            row["selected"].set(not row["selected"].get()); refresh_script_selection(row); refresh_file_count()
        def delete_script_row(row):
            if row not in file_rows: return
            file_rows.remove(row); row["frame"].destroy(); refresh_file_count(); operation_var.set(f"已删除：{row['path'].name}")
        def add_script_row(path):
            selected_var=tk.BooleanVar(value=True); row_frame=ttk.Frame(file_rows_frame,style="Panel.TFrame",padding=(5,4)); row_frame.pack(fill="x")
            selection_text=tk.StringVar(); selection_button=ttk.Button(row_frame,textvariable=selection_text,width=8); selection_button.pack(side="left")
            delete_button=ttk.Button(row_frame,text="删除",width=6); delete_button.pack(side="right")
            item_progress_text=tk.StringVar(value="0%")
            ttk.Label(row_frame,textvariable=item_progress_text,style="Muted.TLabel",width=5,anchor="e").pack(side="right",padx=(5,4))
            item_progress=ttk.Progressbar(row_frame,orient="horizontal",mode="determinate",maximum=100,length=105); item_progress.pack(side="right",padx=(5,0))
            ttk.Label(row_frame,text=str(path),style="Panel.TLabel").pack(side="left",fill="x",expand=True,padx=(4,8))
            row={"path":path,"selected":selected_var,"selection_text":selection_text,"selection_button":selection_button,"progress":item_progress,"progress_text":item_progress_text,"frame":row_frame}; file_rows.append(row)
            selection_button.configure(command=lambda item=row:toggle_script_selection(item)); refresh_script_selection(row)
            delete_button.configure(command=lambda item=row:delete_script_row(item))
        def import_scripts():
            selected=filedialog.askopenfilenames(parent=win,title="导入一个或多个文案",filetypes=[("TXT 文案", "*.txt"),("所有文件", "*.*")])
            existing={str(row["path"]).casefold() for row in file_rows}; added=0
            for item in selected:
                path=Path(item).resolve()
                if path.suffix.lower()!=".txt" or str(path).casefold() in existing: continue
                add_script_row(path); existing.add(str(path).casefold()); added+=1
            if added: refresh_file_count(); operation_var.set(f"已导入 {len(file_rows)} 个文案")
        def select_all_scripts():
            for row in file_rows: row["selected"].set(True); refresh_script_selection(row)
            refresh_file_count()
        def clear_scripts():
            for row in list(file_rows): row["frame"].destroy()
            file_rows.clear(); refresh_file_count(); operation_var.set("文案列表已清除")
        ttk.Button(file_actions,text="导入文件",command=import_scripts).pack(side="left")
        ttk.Button(file_actions,text="全选",command=select_all_scripts).pack(side="left",padx=6)
        ttk.Button(file_actions,text="清除",command=clear_scripts).pack(side="left")
        ttk.Label(file_actions,textvariable=file_count,style="Muted.TLabel").pack(side="right")

        output_box=ttk.Frame(file_box,style="Panel.TFrame"); output_box.grid(row=3,column=0,columnspan=2,sticky="ew",pady=(9,0)); output_box.columnconfigure(1,weight=1)
        output_directory_var=self.voicevox_output_directory; output_directory_var.set(str(self.step_directory(STEP_VOICE_DIR) if self.project else Path.cwd()/STEP_VOICE_DIR)); pause_var=self.voicevox_pause
        ttk.Label(output_box,text="保存目录",style="Panel.TLabel",width=11).grid(row=0,column=0,sticky="w"); ttk.Entry(output_box,textvariable=output_directory_var).grid(row=0,column=1,sticky="ew")
        def choose_output_directory():
            selected=filedialog.askdirectory(parent=win,title="选择语音和字幕保存目录")
            if selected: output_directory_var.set(selected); self.save_all_settings(False)
        ttk.Button(output_box,text="选择",command=choose_output_directory).grid(row=0,column=2,padx=(6,0))
        def open_output_directory():
            try:
                directory=Path(output_directory_var.get()).expanduser().resolve(); directory.mkdir(parents=True,exist_ok=True); os.startfile(str(directory))
            except Exception as exc: messagebox.showerror("打开目录失败",str(exc),parent=win)
        ttk.Button(output_box,text="打开目录",command=open_output_directory).grid(row=0,column=3,padx=(6,0))
        ttk.Label(output_box,text="文件格式",style="Panel.TLabel",width=11).grid(row=1,column=0,sticky="w",pady=(7,0)); format_combo=ttk.Combobox(output_box,textvariable=self.voicevox_output_format,values=("WAV","MP3","M4A","FLAC"),state="readonly",width=10); format_combo.grid(row=1,column=1,sticky="w",pady=(7,0)); format_combo.bind("<<ComboboxSelected>>",lambda _event:self.save_all_settings(False))
        ttk.Label(output_box,text="句间停顿",style="Panel.TLabel",width=11).grid(row=2,column=0,sticky="w",pady=(7,0)); ttk.Entry(output_box,textvariable=pause_var,width=12).grid(row=2,column=1,sticky="w",pady=(7,0)); ttk.Label(output_box,text="秒（会计入语音时间轴）",style="Muted.TLabel").grid(row=2,column=1,sticky="w",padx=(95,0),pady=(7,0))

        progress_box=ttk.Frame(outer,style="Panel.TFrame",padding=(12,9),height=64); progress_box.grid(row=5,column=0,sticky="ew",pady=(10,0)); progress_box.grid_propagate(False); progress_box.columnconfigure(0,weight=1)
        progress_text=tk.StringVar(value="等待生成"); progress_percent=tk.StringVar(value="0%")
        progress_header=ttk.Frame(progress_box,style="Panel.TFrame"); progress_header.grid(row=0,column=0,sticky="ew"); progress_header.columnconfigure(0,weight=1)
        ttk.Label(progress_header,textvariable=progress_text,style="Panel.TLabel").grid(row=0,column=0,sticky="w"); ttk.Label(progress_header,textvariable=progress_percent,style="Panel.TLabel").grid(row=0,column=1,sticky="e")
        voicevox_progress=ttk.Progressbar(progress_box,orient="horizontal",mode="determinate",maximum=100); voicevox_progress.grid(row=1,column=0,sticky="ew",pady=(6,0))
        footer=ttk.Frame(outer,height=55); footer.grid(row=6,column=0,sticky="ew",pady=(10,0)); footer.pack_propagate(False); attribution=tk.StringVar(value="发布内容时请按角色条款标注，例如：VOICEVOX: 青山龍星")
        ttk.Label(footer,textvariable=attribution,style="Muted.TLabel").pack(side="left"); batch_button=ttk.Button(footer,text="批量生成语音和 SRT",style="Primary.TButton"); batch_button.pack(side="right")
        voices={}
        def refresh_gpu_button():
            enabled=self.voicevox_use_gpu.get(); gpu_mode_text.set("GPU 加速：开" if enabled else "GPU 加速：关")
            gpu_button.configure(style="Selected.TButton" if enabled else "TButton")
        def compute_mode_changed():
            self.save_all_settings(False); voices.clear()
            if self.voicevox_process is not None:
                voicevox_service.stop_owned_process(self.voicevox_process); self.voicevox_process=None; self.voicevox_process_gpu=None
                status_var.set("未连接"); operation_var.set("计算模式已切换，请点击“启动并连接”重启引擎")
            else:
                operation_var.set("计算模式已保存；外部引擎需退出后再由本软件启动才能切换")
        def toggle_gpu_mode():
            self.voicevox_use_gpu.set(not self.voicevox_use_gpu.get()); refresh_gpu_button(); compute_mode_changed()
        gpu_button.configure(command=toggle_gpu_mode); refresh_gpu_button()
        def finish_error(title,exc):
            operation_var.set(str(exc)); connect_button.configure(state="normal"); batch_button.configure(state="normal"); messagebox.showerror(title,str(exc),parent=win)
        def exit_engine():
            process=self.voicevox_process
            owned=process is not None and process.poll() is None
            if not owned:
                self.voicevox_process=None; self.voicevox_process_gpu=None
                try: external_pid=voicevox_service.find_running_engine_pid()
                except Exception as exc: finish_error("检测 VOICEVOX 引擎失败",exc); return
                if external_pid is None:
                    status_var.set("未连接"); operation_var.set("没有检测到正在运行的 VOICEVOX 引擎"); return
                if not messagebox.askyesno("退出外部 VOICEVOX 引擎","当前引擎由外部 VOICEVOX 启动。\n\n继续将同时关闭 VOICEVOX 桌面程序及其引擎，未保存的 VOICEVOX 编辑内容可能丢失。\n\n确定继续吗？",parent=win): return
            connect_button.configure(state="disabled"); exit_engine_button.configure(state="disabled"); batch_button.configure(state="disabled"); operation_var.set("正在退出 VOICEVOX 引擎……")
            def work():
                try:
                    stopped=voicevox_service.stop_engine(process)
                    if not stopped: raise voicevox_service.VoicevoxError("没有检测到正在运行的 VOICEVOX 引擎")
                    def finished():
                        self.voicevox_process=None; self.voicevox_process_gpu=None; voices.clear(); voice_combo.configure(values=())
                        status_var.set("未连接"); operation_var.set("VOICEVOX 引擎已退出"); connect_button.configure(state="normal"); exit_engine_button.configure(state="normal"); batch_button.configure(state="normal")
                    self.after(0,finished)
                except Exception as exc:
                    self.after(0,lambda e=exc:(exit_engine_button.configure(state="normal"),finish_error("退出 VOICEVOX 引擎失败",e)))
            self.run(work)
        exit_engine_button.configure(command=exit_engine)
        def inspect(start_engine=False):
            connect_button.configure(state="disabled"); operation_var.set("正在检测本机引擎……")
            def work():
                try:
                    version=voicevox_service.engine_version()
                    executable=voicevox_service.find_installation(self.voicevox_path.get())
                    if executable and not self.voicevox_path.get(): self.after(0,lambda:self.voicevox_path.set(str(executable)))
                    if not version and start_engine:
                        if not executable: raise voicevox_service.VoicevoxError("尚未检测到 VOICEVOX，请先安装或选择安装位置")
                        use_gpu=self.voicevox_use_gpu.get()
                        process=voicevox_service.launch_engine(executable,use_gpu=use_gpu); self.voicevox_process=process; self.voicevox_process_gpu=use_gpu; version=voicevox_service.wait_until_ready()
                    if not version:
                        detail="已检测到安装，尚未启动" if executable else "未安装或未检测到安装位置"
                        self.after(0,lambda:(status_var.set("未连接"),operation_var.set(detail),connect_button.configure(state="normal"))); return
                    options=voicevox_service.available_voices(); labels=[item.label for item in options]
                    def connected():
                        voices.clear(); voices.update({item.label:item for item in options}); voice_combo.configure(values=labels)
                        preferred=voice_var.get() if voice_var.get() in labels else next((label for label in labels if label.startswith("青山龍星 /")),labels[0]); voice_var.set(preferred)
                        if self.voicevox_process is not None:
                            mode="GPU" if self.voicevox_process_gpu else "CPU"
                            detail=f"{mode} 模式"
                        else:
                            detail="外部引擎，实际模式由其启动参数决定"
                        status_var.set("已连接"); operation_var.set(f"版本 {version}，{detail}，共 {len(options)} 个音色"); connect_button.configure(state="normal")
                    self.after(0,connected)
                except Exception as exc: self.after(0,lambda e=exc:(status_var.set("未连接"),finish_error("VOICEVOX 连接失败",e)))
            self.run(work)
        connect_button.configure(command=lambda:inspect(True))
        def generate_batch():
            option=voices.get(voice_var.get())
            if not option: messagebox.showinfo("VOICEVOX","请先启动并连接引擎",parent=win); return
            selected_files=[row["path"] for row in file_rows if row["selected"].get()]
            if not selected_files: messagebox.showinfo("VOICEVOX","请导入文案并勾选需要生成的文件",parent=win); return
            progress_rows={str(row["path"]):row for row in file_rows if row["selected"].get()}
            for row in progress_rows.values(): row["progress"].configure(value=0); row["progress_text"].set("0%")
            self.save_all_settings(False); batch_button.configure(state="disabled"); operation_var.set("正在准备批量生成……"); voicevox_progress.configure(value=0); progress_percent.set("0%"); progress_text.set(f"准备处理 {len(selected_files)} 个文件")
            def progress(file_index,file_total,source,sentence_index,sentence_total):
                value=((file_index-1)+(sentence_index/max(1,sentence_total)))/max(1,file_total)*100
                item_value=sentence_index/max(1,sentence_total)*100; item_row=progress_rows.get(str(source))
                def update_progress(v=value,iv=item_value,row=item_row,fi=file_index,ft=file_total,name=source.name,si=sentence_index,st=sentence_total):
                    voicevox_progress.configure(value=v); progress_percent.set(f"{v:.0f}%"); progress_text.set(f"文件 {fi}/{ft} · {name} · 句子 {si}/{st}"); operation_var.set(f"文件 {fi}/{ft} · {name} · 句子 {si}/{st}")
                    if row is not None: row["progress"].configure(value=iv); row["progress_text"].set(f"{iv:.0f}%")
                self.after(0,update_progress)
            def work():
                try:
                    results=voicevox_service.synthesize_script_files(selected_files,output_directory_var.get(),style_id=option.style_id,speed=float(speed_var.get()),pitch=float(pitch_var.get()),volume=float(volume_var.get()),pause_seconds=float(pause_var.get()),output_format=self.voicevox_output_format.get(),ffmpeg_path=asr.resolve_ffmpeg(),on_progress=progress)
                    success=sum(1 for item in results if item["error"] is None); failed=len(results)-success
                    def finished():
                        for item in results:
                            row=progress_rows.get(str(item["source"]))
                            if row is not None:
                                if item["error"] is None: row["progress"].configure(value=100); row["progress_text"].set("100%")
                                else: row["progress"].configure(value=0); row["progress_text"].set("失败")
                        voicevox_progress.configure(value=100); progress_percent.set("100%"); progress_text.set(f"生成完成 · 成功 {success}，失败 {failed}"); operation_var.set(f"批量完成：成功 {success}，失败 {failed}"); batch_button.configure(state="normal")
                        details="\n".join(f"失败：{item['source'].name} · {item['error']}" for item in results if item["error"] is not None)
                        messagebox.showinfo("VOICEVOX 批量生成",f"共 {len(results)} 个文案\n成功：{success}\n失败：{failed}\n每个文案已生成同名 {self.voicevox_output_format.get()}、SRT 和分段目录。\n输出目录：\n{Path(output_directory_var.get()).resolve()}"+(f"\n\n{details}" if details else "")+f"\n\n使用音频时请标注：VOICEVOX: {option.name}",parent=win)
                    self.after(0,finished)
                except Exception as exc: self.after(0,lambda e=exc:finish_error("VOICEVOX 批量生成失败",e))
            self.run(work)
        batch_button.configure(command=generate_batch)
        win.protocol("WM_DELETE_WINDOW",lambda:(self.save_all_settings(False),setattr(self,"voicevox_window",None),win.destroy()))
        inspect(False)
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
        if output:
            project=Path(output)
            if project.name.startswith("改写批次_"): project=project.parent
            if project.name in {STEP_DOWNLOAD_DIR,STEP_TRANSCRIBE_DIR,STEP_CUT_DIR,STEP_REWRITE_DIR,STEP_VOICE_DIR}: project=project.parent
            self.project=project; self.project_text.set(f"输出到：{project}")
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
        download_dir=self.step_directory(STEP_DOWNLOAD_DIR)
        saved_task=self.task_store.create("download",f"下载批次 {batch_id}",str(download_dir),[{"url":url} for url in urls]); self.batch_task_ids[batch_id]=saved_task["id"]; self.task_store.update_task(saved_task["id"],status="运行中")
        self.batch_contexts[batch_id]={"urls":urls,"controls":controls,"output_dir":str(download_dir),"quality":self.download_quality.get(),"ffmpeg":self.ffmpeg.get(),"api_key":self.download_key.get(),"api_url":downloader_service.DEFAULT_API_URL}
        self.prepare_download_rows(batch_id,urls); self.open_download_window(batch_id,urls,controls)
        values=(batch_id,input_text,download_dir,self.download_quality.get(),self.ffmpeg.get(),int(self.download_workers.get()),self.download_key.get(),controls); self.run(lambda: self.download(*values))
    def download(self,batch_id,input_text,project,quality,ffmpeg,download_workers,api_key,controls):
        try:
            if not project: raise ValueError("请先选择项目目录")
            urls=downloader_service.extract_share_urls(input_text);
            if not urls: raise ValueError("请至少输入一条抖音分享链接")
            api_threads=downloader_service.api_worker_count(len(urls)); download_threads=downloader_service.worker_count(len(urls),download_workers)
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
            output_dir=Path(context["output_directory"]); output_dir.mkdir(parents=True,exist_ok=True)
            json_path=output_dir/f"{video.stem}.json"; srt_path=output_dir/f"{video.stem}.srt"; txt_path=output_dir/f"{video.stem}.txt"
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
    def start_cutting(self):
        if not self.project:
            messagebox.showinfo("字幕剪辑","请先选择项目目录",parent=self); return
        source_dir=self.step_directory(STEP_DOWNLOAD_DIR); srt_dir=self.step_directory(STEP_TRANSCRIBE_DIR); output_dir=self.step_directory(STEP_CUT_DIR)
        videos=[]
        for video in rename_service.list_videos(source_dir):
            srt=srt_dir/f"{video.stem}.srt"
            if srt.is_file(): videos.append((video,srt))
        if not videos:
            messagebox.showinfo("字幕剪辑","步骤 1 和步骤 2 中没有可匹配的视频与 SRT",parent=self); return
        win=tk.Toplevel(self); win.title("3  字幕剪辑"); win.geometry("1120x700"); win.minsize(900,560)
        outer=ttk.Frame(win,padding=16); outer.pack(fill="both",expand=True); outer.columnconfigure(0,weight=1); outer.rowconfigure(3,weight=1)
        ttk.Label(outer,text="字幕剪辑",style="Section.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(outer,text="读取步骤文件或手动导入视频；程序按同名 SRT 匹配并输出到 3_字幕剪辑。",style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(3,10))
        rows=[]; list_frame=ttk.Frame(outer); list_frame.grid(row=3,column=0,sticky="nsew"); list_frame.columnconfigure(0,weight=1); list_frame.rowconfigure(0,weight=1)
        canvas=tk.Canvas(list_frame,bg="#F8FAFC",highlightthickness=1,highlightbackground="#D5DCE5"); canvas.grid(row=0,column=0,sticky="nsew"); scroll=ttk.Scrollbar(list_frame,orient="vertical",command=canvas.yview); scroll.grid(row=0,column=1,sticky="ns"); canvas.configure(yscrollcommand=scroll.set)
        frame=ttk.Frame(canvas); window_id=canvas.create_window((0,0),window=frame,anchor="nw"); frame.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all"))); canvas.bind("<Configure>",lambda e:canvas.itemconfigure(window_id,width=e.width))
        count=tk.StringVar(value="尚未载入视频"); status=tk.StringVar(value="就绪")
        def short_name(path,limit=58):
            name=Path(path).name
            if len(name)<=limit:return name
            suffix=Path(name).suffix; keep=max(12,limit-len(suffix)-4); return name[:keep]+"..."+suffix
        def show_detail(item):
            messagebox.showinfo("字幕剪辑详情",f"视频：\n{item['video']}\n\nSRT：\n{item['srt']}\n\n状态：\n{item.get('detail') or item['label'].get()}",parent=win)
        def add_video(video,srt):
            if any(str(item["video"]).casefold()==str(video).casefold() for item in rows): return
            selected=tk.BooleanVar(value=True); item_frame=ttk.Frame(frame,padding=(8,7)); item_frame.pack(fill="x",pady=(0,1)); item_frame.columnconfigure(1,weight=1); item_frame.columnconfigure(2,weight=1)
            button=ttk.Button(item_frame,text="已选择",width=8,style="Selected.TButton",command=lambda:toggle(item)); button.grid(row=0,column=0,rowspan=2,padx=(0,10),sticky="ns")
            ttk.Label(item_frame,text="视频：",style="Muted.TLabel").grid(row=0,column=1,sticky="w"); ttk.Label(item_frame,text=short_name(video),style="Panel.TLabel").grid(row=0,column=1,sticky="w",padx=(45,8))
            ttk.Label(item_frame,text="SRT：",style="Muted.TLabel").grid(row=1,column=1,sticky="w"); ttk.Label(item_frame,text=short_name(srt),style="Panel.TLabel").grid(row=1,column=1,sticky="w",padx=(45,8))
            progress=ttk.Progressbar(item_frame,maximum=100,length=180); progress.grid(row=0,column=2,sticky="e",padx=(8,4)); label=tk.StringVar(value="等待"); ttk.Label(item_frame,textvariable=label,width=20,anchor="e",style="Muted.TLabel").grid(row=1,column=2,sticky="e",padx=(8,4)); detail_button=ttk.Button(item_frame,text="详情",width=6); detail_button.grid(row=0,column=3,rowspan=2,padx=(6,0))
            item={"video":video,"srt":srt,"selected":selected,"button":button,"frame":item_frame,"progress":progress,"label":label,"detail":"等待处理"}; detail_button.configure(command=lambda i=item:show_detail(i)); rows.append(item)
        def toggle(item):
            value=not item["selected"].get(); item["selected"].set(value); item["button"].configure(text="已选择" if value else "未选择",style="Selected.TButton" if value else "TButton"); count.set(f"已选择 {sum(x['selected'].get() for x in rows)} / {len(rows)} 个视频")
        def refresh(): count.set(f"已选择 {sum(x['selected'].get() for x in rows)} / {len(rows)} 个视频")
        def load_step():
            for video,srt in videos: add_video(video,srt)
            refresh()
        def import_video():
            for value in filedialog.askopenfilenames(parent=win,title="导入视频",filetypes=[("视频","*.mp4;*.mov;*.m4v;*.webm"),("所有文件","*.*")]):
                video=Path(value).resolve(); srt=video.with_suffix(".srt")
                if not srt.is_file(): srt=srt_dir/f"{video.stem}.srt"
                if not srt.is_file():
                    selected=filedialog.askopenfilename(parent=win,title=f"为 {video.name} 选择对应 SRT",filetypes=[("SRT 字幕","*.srt"),("所有文件","*.*")])
                    if selected: srt=Path(selected).resolve()
                if srt.is_file(): add_video(video,srt)
            refresh()
        def select_all():
            for item in rows: item["selected"].set(True); item["button"].configure(text="已选择",style="Selected.TButton")
            refresh()
        actions=ttk.Frame(outer); actions.grid(row=2,column=0,sticky="ew",pady=(0,8)); ttk.Button(actions,text="读取步骤文件",command=load_step).pack(side="left"); ttk.Button(actions,text="手动导入视频",command=import_video).pack(side="left",padx=7); ttk.Button(actions,text="全选",command=select_all).pack(side="left"); ttk.Label(actions,textvariable=count,style="Muted.TLabel").pack(side="right")
        footer=ttk.Frame(outer); footer.grid(row=4,column=0,sticky="ew",pady=(10,0)); ttk.Label(footer,textvariable=status,style="Muted.TLabel").pack(side="left")
        def begin():
            chosen=[x for x in rows if x["selected"].get()]
            if not chosen: messagebox.showinfo("字幕剪辑","请至少选择一个视频",parent=win); return
            if not self.llm_key.get().strip(): messagebox.showerror("字幕剪辑","请先在接口配置中填写 ChatGPT 接口 Key",parent=win); return
            button.configure(state="disabled"); status.set("正在剪辑……")
            def work():
                good=0
                for item in chosen:
                    try:
                        self.after(0,lambda i=item:(i["progress"].configure(value=10),i["label"].set("分析字幕")))
                        duration=media.probe_duration(asr.resolve_ffmpeg(),str(item["video"])); cues=voicevox_service.parse_srt(item["srt"].read_text(encoding="utf-8-sig")); ranges=ai.srt_deletion_plan(cues,duration,OPENAI_COMPAT_URL,self.llm_key.get(),OPENAI_COMPAT_MODEL,OPENAI_COMPAT_REASONING_EFFORT)
                        try: plan=media.build_srt_cut_plan(cues,duration,ranges)
                        except ValueError as first_error:
                            ranges=ai.srt_deletion_plan(cues,duration,OPENAI_COMPAT_URL,self.llm_key.get(),OPENAI_COMPAT_MODEL,OPENAI_COMPAT_REASONING_EFFORT,str(first_error)); plan=media.build_srt_cut_plan(cues,duration,ranges)
                        out=output_dir/f"{item['video'].stem}_剪辑.mp4"; media.execute_srt_cut(asr.resolve_ffmpeg(),str(item["video"]),plan,str(out)); media.write_cut_subtitles(cues,plan,str(output_dir/f"{item['video'].stem}_剪辑.srt"),str(output_dir/f"{item['video'].stem}_剪辑.txt")); item["detail"]=f"完成\n输出视频：{out}"; good+=1; self.after(0,lambda i=item:(i["progress"].configure(value=100),i["label"].set("完成")))
                    except Exception as exc:
                        item["detail"]=f"失败：{exc}"; self.after(0,lambda i=item:(i["progress"].configure(value=0),i["label"].set("失败（查看详情）")))
                self.after(0,lambda: (button.configure(state="normal"),status.set(f"完成：{good}/{len(chosen)}")))
            self.run(work)
        button=ttk.Button(footer,text="开始字幕剪辑",style="Primary.TButton",command=begin); button.pack(side="right"); load_step()
    def transcribed_videos(self):
        if not self.project or not self.project.is_dir(): return []
        source=self.step_directory(STEP_DOWNLOAD_DIR); transcripts=self.step_directory(STEP_TRANSCRIBE_DIR)
        return [video for video in rename_service.list_videos(source) if (transcripts/f"{video.stem}.txt").is_file() and (transcripts/f"{video.stem}.srt").is_file()]
    def open_rewrite_window(self):
        if not self.project:
            messagebox.showinfo("AI 改写","请先选择项目目录",parent=self); return
        win=tk.Toplevel(self); win.title("AI 文案改写"); win.geometry("900x880"); win.minsize(760,760)
        outer=ttk.Frame(win,padding=16); outer.pack(fill="both",expand=True); outer.columnconfigure(0,weight=1); outer.rowconfigure(1,minsize=118); outer.rowconfigure(5,minsize=220,weight=3); outer.rowconfigure(6,minsize=120,weight=1); outer.rowconfigure(8,minsize=120,weight=1)
        entries=[]; current=[0]; loading=[False]
        prompt_header=ttk.Frame(outer); prompt_header.grid(row=0,column=0,sticky="ew",pady=(0,4)); ttk.Label(prompt_header,text="改写提示词",style="Section.TLabel").pack(side="left")
        ttk.Button(prompt_header,text="提示词管理",command=lambda:self.manage_rewrite_prompts(win,prompt,refresh_prompt_buttons)).pack(side="right")
        prompt=tk.Text(outer,height=5,wrap="word",font=("Microsoft YaHei UI",9),bg="#F8FAFC",fg="#203047",relief="flat",padx=9,pady=8); prompt.grid(row=1,column=0,sticky="nsew",pady=(0,3))
        prompt_buttons=ttk.Frame(outer); prompt_buttons.grid(row=2,column=0,sticky="ew",pady=(6,8))
        def use_prompt(item):
            prompt.delete("1.0","end"); prompt.insert("1.0",item["text"])
        def refresh_prompt_buttons():
            for button in prompt_buttons.winfo_children(): button.destroy()
            for index,item in enumerate(self.rewrite_prompts):
                button=ttk.Button(prompt_buttons,text=item["name"],command=lambda value=item:use_prompt(value))
                button.grid(row=index//6,column=index%6,sticky="ew",padx=(0,5),pady=(0,4))
                prompt_buttons.columnconfigure(index%6,weight=1,uniform="prompt")
        refresh_prompt_buttons()
        if self.rewrite_prompts: use_prompt(self.rewrite_prompts[0])
        source_bar=ttk.Frame(outer); source_bar.grid(row=3,column=0,sticky="ew",pady=(0,8)); source_bar.columnconfigure(3,weight=1)
        ttk.Button(source_bar,text="读取目录 TXT",command=lambda:load_directory()).grid(row=0,column=0,sticky="w")
        ttk.Button(source_bar,text="导入 TXT（可多选）",command=lambda:import_files()).grid(row=0,column=1,sticky="w",padx=(7,0))
        clear_all_button=ttk.Button(source_bar,text="一键清空",command=lambda:clear_all()); clear_all_button.grid(row=0,column=2,sticky="w",padx=(7,0))
        count=tk.StringVar(value="尚未载入文案"); ttk.Label(source_bar,textvariable=count,style="Muted.TLabel").grid(row=0,column=3,sticky="e")
        title_row=ttk.Frame(outer); title_row.grid(row=4,column=0,sticky="ew",pady=(0,7)); ttk.Label(title_row,text="标题",style="Section.TLabel").pack(side="left")
        title=tk.StringVar(); title_entry=ttk.Entry(title_row,textvariable=title); title_entry.pack(side="left",fill="x",expand=True,padx=(10,0))
        editor=ttk.Frame(outer); editor.grid(row=5,column=0,sticky="nsew"); editor.columnconfigure(0,weight=1); editor.rowconfigure(1,weight=1)
        ttk.Label(editor,text="内容",style="Section.TLabel").grid(row=0,column=0,sticky="w",pady=(0,5))
        content_box=ttk.Frame(editor); content_box.grid(row=1,column=0,sticky="nsew"); content_box.columnconfigure(0,weight=1); content_box.rowconfigure(0,weight=1)
        content=tk.Text(content_box,wrap="word",font=("Microsoft YaHei UI",10),bg="#F8FAFC",fg="#203047",relief="flat",padx=10,pady=9); content.grid(row=0,column=0,sticky="nsew")
        content_scroll=ttk.Scrollbar(content_box,orient="vertical",command=content.yview); content_scroll.grid(row=0,column=1,sticky="ns"); content.configure(yscrollcommand=content_scroll.set)
        nav=ttk.Frame(content_box); nav.grid(row=0,column=2,sticky="ns",padx=(9,0)); previous_button=ttk.Button(nav,text="上一个",state="disabled",command=lambda:show_entry(current[0]-1)); previous_button.pack(fill="x",pady=(0,5)); next_button=ttk.Button(nav,text="下一个",state="disabled",command=lambda:show_entry(current[0]+1)); next_button.pack(fill="x")
        output_box=ttk.Frame(outer); output_box.grid(row=6,column=0,sticky="nsew",pady=(10,0)); output_box.columnconfigure(0,weight=1); output_box.rowconfigure(1,weight=1)
        ttk.Label(output_box,text="改写结果",style="Section.TLabel").grid(row=0,column=0,sticky="w",pady=(0,5))
        output_text=tk.Text(output_box,wrap="word",font=("Microsoft YaHei UI",10),bg="#F1F5F9",fg="#203047",relief="flat",padx=10,pady=9,state="disabled"); output_text.grid(row=1,column=0,sticky="nsew")
        output_scroll=ttk.Scrollbar(output_box,orient="vertical",command=output_text.yview); output_scroll.grid(row=1,column=1,sticky="ns"); output_text.configure(yscrollcommand=output_scroll.set)
        result_nav=ttk.Frame(output_box); result_nav.grid(row=1,column=2,sticky="ns",padx=(8,0)); previous_result=ttk.Button(result_nav,text="上一个",state="disabled"); previous_result.pack(fill="x",pady=(0,5)); next_result=ttk.Button(result_nav,text="下一个",state="disabled"); next_result.pack(fill="x")
        def save_current():
            text=content.get("1.0","end-1c")
            if entries and not loading[0] and text.strip(): entries[current[0]].update(title=title.get(),text=text)
        def show_entry(index):
            save_current()
            if not entries: return
            current[0]=index % len(entries); item=entries[current[0]]; loading[0]=True
            title.set(item["title"]); content.delete("1.0","end"); content.insert("1.0",item["text"]); loading[0]=False
            count.set(f"{current[0]+1} / {len(entries)} 篇")
        def add_files(paths):
            existing={str(item["path"].resolve()).casefold() for item in entries if item.get("path")}
            added=[]
            for path in paths:
                path=Path(path)
                if path.suffix.lower()!=".txt" or not path.is_file() or str(path.resolve()).casefold() in existing: continue
                try: text=path.read_text(encoding="utf-8-sig").strip()
                except (OSError,UnicodeError) as exc:
                    messagebox.showwarning("导入 TXT",f"无法读取 {path.name}：{exc}",parent=win); continue
                if not text: continue
                entries.append({"path":path,"title":path.stem,"text":text}); existing.add(str(path.resolve()).casefold()); added.append(len(entries)-1)
            if added: show_entry(added[0])
            elif not entries: count.set("没有可用的 TXT 文案")
            if entries: previous_button.configure(state="normal"); next_button.configure(state="normal")
        def clear_all():
            save_current(); entries.clear(); current[0]=0; loading[0]=True
            title.set(""); content.delete("1.0","end"); loading[0]=False
            count.set("已清空，请重新导入 TXT"); previous_button.configure(state="disabled"); next_button.configure(state="disabled")
        def load_directory():
            directory=filedialog.askdirectory(title="选择包含 TXT 文案的目录",initialdir=str(self.project),parent=win)
            if directory: add_files(sorted(Path(directory).glob("*.txt"),key=lambda path:path.name.casefold()))
        def import_files():
            paths=filedialog.askopenfilenames(title="导入 TXT 文案",initialdir=str(self.project),filetypes=[("TXT 文案","*.txt")],parent=win)
            if paths: add_files(paths)
        title_entry.bind("<FocusOut>",lambda _event:save_current()); content.bind("<FocusOut>",lambda _event:save_current())
        options=ttk.Frame(outer); options.grid(row=7,column=0,sticky="ew",pady=(10,0)); provider=tk.StringVar(value="阿里云百炼"); model=tk.StringVar(value="qwen3.7-plus")
        ttk.Label(options,text="AI 服务",style="Panel.TLabel").pack(side="left"); provider_picker=ttk.Combobox(options,textvariable=provider,state="readonly",values=["阿里云百炼","豆包","OpenAI 兼容接口"],width=18); provider_picker.pack(side="left",padx=(7,12))
        model_label=tk.StringVar(value="模型"); ttk.Label(options,textvariable=model_label,style="Panel.TLabel").pack(side="left"); model_picker=ttk.Combobox(options,textvariable=model,state="readonly",values=["qwen3.7-plus","qwen-plus","qwen-turbo","qwen-max","qwen-long"],width=22); model_picker.pack(side="left",padx=7)
        def change_provider(_event=None):
            compatible=provider.get()=="OpenAI 兼容接口"
            doubao=provider.get()=="豆包"
            model.set(OPENAI_COMPAT_MODEL if compatible else (DOUBAO_MODEL if doubao else "qwen3.7-plus")); model_label.set("兼容模型" if compatible else ("豆包模型" if doubao else "百炼模型"))
            model_picker.configure(values=[OPENAI_COMPAT_MODEL] if compatible else ([DOUBAO_MODEL] if doubao else ["qwen3.7-plus","qwen-plus","qwen-turbo","qwen-max","qwen-long"]))
        provider_picker.bind("<<ComboboxSelected>>",change_provider)
        status=tk.StringVar(value="就绪"); ttk.Label(options,textvariable=status,style="Muted.TLabel").pack(side="right")
        result_box=ttk.Frame(outer); result_box.grid(row=8,column=0,sticky="nsew",pady=(9,0)); result_box.columnconfigure(0,weight=1); result_box.rowconfigure(0,weight=1)
        result_tree=ttk.Treeview(result_box,columns=("status","duration","output"),show="tree headings",height=4); result_tree.heading("#0",text="标题"); result_tree.heading("status",text="状态"); result_tree.heading("duration",text="改写时间"); result_tree.heading("output",text="输出文件"); result_tree.column("#0",width=220); result_tree.column("status",width=90,anchor="center"); result_tree.column("duration",width=100,anchor="center"); result_tree.column("output",width=330); result_tree.grid(row=0,column=0,sticky="nsew")
        result_scroll=ttk.Scrollbar(result_box,orient="vertical",command=result_tree.yview); result_scroll.grid(row=0,column=1,sticky="ns"); result_tree.configure(yscrollcommand=result_scroll.set)
        result_state={}
        def display_result(index):
            rows=result_tree.get_children()
            if not rows:return
            index%=len(rows)
            item=result_state.get("results",{}).get(index)
            if item:self._set_rewrite_output(output_text,item["title"],item["text"])
        def show_result(index):
            rows=result_tree.get_children()
            if not rows:return
            current=int(result_tree.focus() or 0); direction=1 if index>current else -1
            iid=None
            for offset in range(1,len(rows)+1):
                candidate=rows[(current+direction*offset)%len(rows)]
                state=result_tree.item(candidate,"values")[0]
                if not state.startswith(("改写中","重试中")):
                    iid=candidate; break
            if iid is None:return
            if result_tree.selection()!=(iid,): result_tree.selection_set(iid)
            result_tree.focus(iid); result_tree.see(iid); display_result(int(iid))
        previous_result.configure(command=lambda:show_result(int(result_tree.focus() or 0)-1)); next_result.configure(command=lambda:show_result(int(result_tree.focus() or 0)+1))
        result_tree.bind("<<TreeviewSelect>>",lambda _event:display_result(int(result_tree.selection()[0])) if result_tree.selection() else None)
        footer=ttk.Frame(outer); footer.grid(row=9,column=0,sticky="ew",pady=(10,0)); footer.columnconfigure(0,weight=1)
        progress_value=tk.DoubleVar(value=0); progress=ttk.Progressbar(footer,variable=progress_value,maximum=1,mode="determinate"); progress.grid(row=0,column=0,sticky="ew",padx=(0,12))
        progress_text=tk.StringVar(value="就绪"); ttk.Label(footer,textvariable=progress_text,style="Muted.TLabel",width=14,anchor="e").grid(row=0,column=1,sticky="e",padx=(0,12))
        def begin():
            save_current(); chosen=[dict(item) for item in entries]; instruction=prompt.get("1.0","end").strip(); selected_provider=provider.get(); compatible=selected_provider=="OpenAI 兼容接口"; doubao=selected_provider=="豆包"
            key=(self.llm_key.get() if compatible else (self.ark_key.get() if doubao else self.asr_key.get())).strip(); selected_model=OPENAI_COMPAT_MODEL if compatible else (DOUBAO_MODEL if doubao else model.get().strip()); base_url=OPENAI_COMPAT_URL if compatible else (DOUBAO_API_URL if doubao else None)
            if not chosen: messagebox.showinfo("AI 改写","请先从目录读取或导入 TXT 文案",parent=win); return
            if not instruction: messagebox.showinfo("AI 改写","请填写改写提示词",parent=win); return
            if not key: messagebox.showerror("AI 改写","请先在接口与工具配置中填写所选服务的 API Key",parent=win); return
            output_names=[re.sub(r'[<>:"/\\|?*\x00-\x1f]',"_",item["title"]).strip(" .") for item in chosen]
            if any(not name for name in output_names):
                messagebox.showinfo("AI 改写","标题不能为空",parent=win); return
            batch_time=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            output_dir=self.step_directory(STEP_REWRITE_DIR)/f"改写批次_{batch_time}"
            output_dir.mkdir(parents=True,exist_ok=True)
            for row in result_tree.get_children(): result_tree.delete(row)
            for index,item in enumerate(chosen): result_tree.insert("","end",iid=str(index),text=item["title"],values=("等待中","-",""))
            result_state["results"]={}; result_tree.selection_set("0"); result_tree.focus("0"); self._set_rewrite_output(output_text,chosen[0]["title"],"等待改写...")
            previous_result.configure(state="disabled"); next_result.configure(state="normal" if len(chosen)>1 else "disabled")
            task=self.task_store.create("rewrite",f"AI 改写批次 · {selected_provider} · {selected_model}",str(output_dir),[{"path":str(item["path"]),"name":item["title"]} for item in chosen]); self.task_store.update_task(task["id"],status="运行中")
            result_state.update(task_id=task["id"],completed=0,success=0,total=len(chosen),progress_lock=threading.Lock(),results={})
            progress.configure(maximum=len(chosen)); progress_value.set(0); progress_text.set(f"0 / {len(chosen)}")
            start_button.configure(state="disabled"); status.set(f"处理中 0/{len(chosen)}")
            reasoning_effort=OPENAI_COMPAT_REASONING_EFFORT if compatible else None
            self.run(lambda:self.rewrite_batch(chosen,instruction,key,selected_model,base_url,reasoning_effort,output_dir,batch_time,result_tree,status,start_button,result_state,output_text,progress,progress_value,progress_text))
        start_button=ttk.Button(footer,text="开始生成",style="Primary.TButton",command=begin); start_button.grid(row=0,column=2,sticky="e")
        cut_dir=self.step_directory(STEP_CUT_DIR)
        add_files(sorted(cut_dir.glob("*.txt"),key=lambda path:path.name.casefold()))
    def manage_rewrite_prompts(self,parent,prompt,refresh_buttons):
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
            if not selection and len(self.rewrite_prompts)>=10: messagebox.showinfo("提示词管理","最多保存 10 个提示词",parent=win); return
            duplicate=next((i for i,item in enumerate(self.rewrite_prompts) if item["name"]==label and item["name"]!=old),None)
            if duplicate is not None: messagebox.showinfo("提示词管理","提示词名称已存在",parent=win); return
            replacement={"name":label,"text":text}
            if selection:self.rewrite_prompts[selection[0]]=replacement; index=selection[0]
            else:self.rewrite_prompts.append(replacement); index=len(self.rewrite_prompts)-1
            self.save_all_settings(False); refresh(index); refresh_buttons()
        def delete_prompt():
            selection=listing.curselection()
            if not selection:return
            del self.rewrite_prompts[selection[0]]; self.save_all_settings(False); refresh(min(selection[0],len(self.rewrite_prompts)-1) if self.rewrite_prompts else None); refresh_buttons()
        def apply_prompt():
            text=content.get("1.0","end").strip()
            if not text: messagebox.showinfo("提示词管理","请先选择或填写提示词",parent=win); return
            prompt.delete("1.0","end"); prompt.insert("1.0",text)
            win.destroy()
        actions=ttk.Frame(outer); actions.grid(row=2,column=0,columnspan=2,sticky="ew",pady=(12,0))
        ttk.Button(actions,text="新建",command=lambda:(listing.selection_clear(0,"end"),name.set("新提示词"),content.delete("1.0","end"))).pack(side="left")
        ttk.Button(actions,text="保存",command=save_prompt).pack(side="left",padx=5); ttk.Button(actions,text="删除",command=delete_prompt).pack(side="left")
        ttk.Button(actions,text="应用到编辑框",style="Primary.TButton",command=apply_prompt).pack(side="right"); refresh(0 if self.rewrite_prompts else None)
    def rewrite_batch(self,items,prompt,key,model,base_url,reasoning_effort,output_dir,batch_time,result_tree,status,start_button,result_state,output_text,progress,progress_value,progress_text):
        max_attempts=3
        def operation(item):
            index,entry=item; label=entry["title"]; started=time.monotonic(); self.task_store.update_item(result_state["task_id"],index,status="改写中")
            self.after(0,lambda:self._set_rewrite_row(result_tree,index,"改写中"))
            try:
                text=entry["text"].strip()
                if not text: raise ValueError("转录 TXT 内容为空")
                rewritten=None
                for attempt in range(1,max_attempts+1):
                    try:
                        rewritten=ai.rewrite_text(text,prompt,key,model,base_url,reasoning_effort)
                        break
                    except Exception:
                        if attempt==max_attempts: raise
                        retry_status=f"重试中 ({attempt+1}/{max_attempts})"
                        self.task_store.update_item(result_state["task_id"],index,status=retry_status)
                        self.after(0,lambda state=retry_status:self._set_rewrite_row(result_tree,index,state))
                        time.sleep(min(2**attempt,8))
                safe_title=re.sub(r'[<>:"/\\|?*\x00-\x1f]',"_",label).strip(" .")
                if not safe_title: raise ValueError("标题不能作为文件名")
                output=output_dir/f"{safe_title}_{batch_time}_{index+1:02d}.txt"; output.write_text(rewritten+"\n",encoding="utf-8-sig")
                elapsed=time.monotonic()-started; result_state["results"][index]={"title":label,"text":rewritten}
                self.task_store.update_item(result_state["task_id"],index,status="完成",progress=100,output=str(output),error="",duration_seconds=elapsed)
                self.after(0,lambda:self._set_rewrite_row(result_tree,index,"完成",str(output),elapsed))
                self.after(0,lambda:self._show_rewrite_result(result_tree,index,output_text,label,rewritten))
                return output
            except Exception as exc:
                error=str(exc); elapsed=time.monotonic()-started; result_state["results"][index]={"title":label,"text":f"改写失败\n\n{error}"}; self.task_store.update_item(result_state["task_id"],index,status="失败",error=error,duration_seconds=elapsed)
                self.after(0,lambda:self._set_rewrite_row(result_tree,index,f"失败：{error}","",elapsed))
                raise
            finally:
                with result_state["progress_lock"]:
                    result_state["completed"]+=1; completed=result_state["completed"]
                self.after(0,lambda:self._update_rewrite_progress(progress,progress_value,progress_text,completed,len(items)))
        results=run_batch(list(enumerate(items)),operation,workers=min(len(items),8),retries=0)
        ok=sum(1 for _,_,error in results if error is None)
        self.task_store.update_task(result_state["task_id"],status="完成" if ok==len(items) else "部分失败")
        self.after(0,lambda:(start_button.configure(state="normal") if start_button.winfo_exists() else None,status.set(f"批次完成：成功 {ok}/{len(items)}") if status.winfo_exists() else None))
    def _update_rewrite_progress(self,bar,value,label,completed,total):
        if bar.winfo_exists(): value.set(completed); label.set(f"{completed} / {total}")
    def _set_rewrite_row(self,tree,index,state,output="",duration=None):
        if tree.winfo_exists(): tree.item(str(index),values=(state,f"{duration:.1f} 秒" if duration is not None else "-",output))
    def _show_rewrite_result(self,tree,index,widget,title,text):
        if tree.winfo_exists() and tree.focus()==str(index): self._set_rewrite_output(widget,title,text)
    def _set_rewrite_output(self,widget,title,text):
        if widget.winfo_exists(): widget.configure(state="normal"); widget.delete("1.0","end"); widget.insert("1.0",f"{title}\n\n{text}"); widget.configure(state="disabled")
    def start_transcribe(self):
        if not self.project: self.log("转写失败：请先选择输出目录"); return
        download_dir=self.step_directory(STEP_DOWNLOAD_DIR)
        videos=rename_service.list_videos(download_dir)
        if not videos: self.log("转写失败：输出目录中没有视频"); return
        transcribe_dir=self.step_directory(STEP_TRANSCRIBE_DIR)
        self.transcribe_counter+=1; batch_id=self.transcribe_counter; self.latest_transcribe_id=batch_id; controls=[downloader_service.DownloadControl() for _ in videos]; context={"project":transcribe_dir,"videos":videos,"output_directory":transcribe_dir,"controls":controls,"source_lang":self.source_lang.get(),"ffmpeg":self.ffmpeg.get(),"api_key":self.asr_key.get()}; self.transcribe_controls[batch_id]=controls; self.transcribe_contexts[batch_id]=context
        saved_task=self.task_store.create("transcribe",f"文案与 SRT 批次 {batch_id}",str(transcribe_dir),[{"path":str(video),"name":video.name} for video in videos]); self.transcribe_task_ids[batch_id]=saved_task["id"]; self.task_store.update_task(saved_task["id"],status="运行中")
        self.open_transcribe_window(batch_id,videos,controls); self.run(lambda:self.transcribe(batch_id,context))
    def transcribe(self,batch_id,context):
        videos=context["videos"]; completed=0
        effective_workers=transcribe_worker_count(len(videos))
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
            seg=json.load(open(self.project/"transcript.json",encoding="utf-8")); result=ai.rewrite(seg,self.lang.get(),OPENAI_COMPAT_URL,self.llm_key.get(),OPENAI_COMPAT_MODEL,self.style.get(),self.length.get(),OPENAI_COMPAT_REASONING_EFFORT); json.dump(result,open(self.project/"rewrite.json","w",encoding="utf-8"),ensure_ascii=False,indent=2); self.log(json.dumps(result,ensure_ascii=False,indent=2)); self.status.set("改写完成")
        except Exception as e: self.status.set("失败"); self.log("改写失败："+str(e))
    def start_edit(self): self.run(self.edit)
    def edit(self):
        try:
            video=str(next((p for p in self.project.glob("*.mp4") if p.name != "edited.mp4"), self.project/"source.mp4")); duration=media.probe_duration(self.ffmpeg.get(),video); scenes=media.fixed_scenes(duration); seg=json.load(open(self.project/"transcript.json",encoding="utf-8")); rewrite=json.load(open(self.project/"rewrite.json",encoding="utf-8")); raw=ai.edit_plan(seg,scenes,rewrite,OPENAI_COMPAT_URL,self.llm_key.get(),OPENAI_COMPAT_MODEL,OPENAI_COMPAT_REASONING_EFFORT); plan=ai.validate_plan(raw,scenes,rewrite,duration); json.dump(plan,open(self.project/"edit-plan.json","w",encoding="utf-8"),ensure_ascii=False,indent=2); out=str(self.project/"edited.mp4"); media.execute_plan(self.ffmpeg.get(),video,plan,out); self.log(json.dumps(plan,ensure_ascii=False,indent=2)); self.log("成片已导出："+out); self.status.set("剪辑完成")
        except Exception as e: self.status.set("失败"); self.log("剪辑失败："+str(e))

if __name__ == "__main__": App().mainloop()
