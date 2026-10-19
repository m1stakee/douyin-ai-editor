import json, os, shutil, threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import downloader_service, media, asr, ai, rename_service
from batch_service import run_batch
from app_config import henghengmao_key, groq_key, save_credentials
from downloader import extract_share_urls

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title("VideoFlow · 短视频智能工作台"); self.geometry("1120x900"); self.minsize(960,760); self.configure(bg="#F3F6FA"); self.project=None; self.ffmpeg=tk.StringVar(value=shutil.which("ffmpeg") or "")
        self.download_key=tk.StringVar(value=henghengmao_key()); self.groq_key=tk.StringVar(value=groq_key()); self.download_quality=tk.StringVar(value="推荐"); self.workers=tk.StringVar(value="2"); self.source_lang=tk.StringVar(value="中文"); self.llm_url=tk.StringVar(); self.llm_key=tk.StringVar(); self.llm_model=tk.StringVar(value="gemini-2.5-flash"); self.lang=tk.StringVar(value="英语")
        self.style=tk.StringVar(value="自然口播"); self.length=tk.StringVar(value="保持原时长")
        self.status=tk.StringVar(value="就绪")
        self.project_text=tk.StringVar(value="尚未选择输出目录")
        self._setup_style()
        self.build()
    def _setup_style(self):
        style=ttk.Style(self); style.theme_use("clam")
        style.configure("TFrame",background="#F3F6FA"); style.configure("Card.TFrame",background="#FFFFFF")
        style.configure("TLabel",background="#F3F6FA",foreground="#25324B",font=("Microsoft YaHei UI",9))
        style.configure("Card.TLabel",background="#FFFFFF",foreground="#25324B",font=("Microsoft YaHei UI",9))
        style.configure("Title.TLabel",background="#17233D",foreground="#FFFFFF",font=("Microsoft YaHei UI",20,"bold"))
        style.configure("Subtitle.TLabel",background="#17233D",foreground="#AFC1E5",font=("Microsoft YaHei UI",9))
        style.configure("Section.TLabel",background="#FFFFFF",foreground="#17233D",font=("Microsoft YaHei UI",11,"bold"))
        style.configure("Muted.TLabel",background="#FFFFFF",foreground="#758198",font=("Microsoft YaHei UI",8))
        style.configure("Status.TLabel",background="#E8F1FF",foreground="#185ADB",font=("Microsoft YaHei UI",9,"bold"),padding=(10,6))
        style.configure("TButton",font=("Microsoft YaHei UI",9),padding=(11,7),background="#E8EDF5",foreground="#25324B",borderwidth=0)
        style.map("TButton",background=[("active","#DCE4F0")])
        style.configure("Primary.TButton",font=("Microsoft YaHei UI",9,"bold"),padding=(14,8),background="#2563EB",foreground="#FFFFFF")
        style.map("Primary.TButton",background=[("active","#1D4ED8")])
        style.configure("Step.TButton",font=("Microsoft YaHei UI",9,"bold"),padding=(14,9),background="#FFFFFF",foreground="#23395D")
        style.map("Step.TButton",background=[("active","#EDF3FF")])
        style.configure("TEntry",padding=7,fieldbackground="#F7F9FC",bordercolor="#D9E1EC"); style.configure("TCombobox",padding=6,fieldbackground="#F7F9FC")
    def build(self):
        header=tk.Frame(self,bg="#17233D",height=104); header.pack(fill="x"); header.pack_propagate(False)
        title=tk.Frame(header,bg="#17233D"); title.pack(fill="both",expand=True,padx=28,pady=(16,14))
        ttk.Label(title,text="VideoFlow",style="Title.TLabel").pack(anchor="w"); ttk.Label(title,text="下载、转写、改写与剪辑，在一个工作台完成",style="Subtitle.TLabel").pack(anchor="w",pady=(7,0),ipady=2)
        body=ttk.Frame(self,padding=(22,18)); body.pack(fill="both",expand=True); body.columnconfigure(0,weight=3); body.columnconfigure(1,weight=2); body.rowconfigure(1,weight=1)
        top=ttk.Frame(body,style="Card.TFrame",padding=16); top.grid(row=0,column=0,sticky="nsew",padx=(0,8),pady=(0,10)); top.columnconfigure(0,weight=1)
        ttk.Label(top,text="1  添加视频",style="Section.TLabel").grid(row=0,column=0,sticky="w"); ttk.Label(top,text="支持整段分享文案，每行可放一条或多条链接",style="Muted.TLabel").grid(row=1,column=0,sticky="w",pady=(2,8))
        self.url_text=tk.Text(top,height=7,wrap="word",font=("Microsoft YaHei UI",10),bg="#F7F9FC",fg="#25324B",insertbackground="#2563EB",relief="flat",padx=10,pady=9,highlightthickness=1,highlightbackground="#D9E1EC",highlightcolor="#2563EB"); self.url_text.grid(row=2,column=0,columnspan=2,sticky="nsew")
        ttk.Label(top,textvariable=self.project_text,style="Muted.TLabel").grid(row=3,column=0,sticky="w",pady=(10,0)); source_actions=ttk.Frame(top,style="Card.TFrame"); source_actions.grid(row=3,column=1,sticky="e",pady=(10,0)); ttk.Button(source_actions,text="选择输出目录",command=self.choose_project).pack(side="left",padx=(0,6)); ttk.Button(source_actions,text="打开输出目录",command=self.open_project).pack(side="left",padx=(0,6)); ttk.Button(source_actions,text="开始批量下载",style="Primary.TButton",command=self.start_download).pack(side="left")
        settings=ttk.Frame(body,style="Card.TFrame",padding=16); settings.grid(row=0,column=1,sticky="nsew",padx=(8,0),pady=(0,10)); settings.columnconfigure(0,weight=1); settings.columnconfigure(1,weight=1)
        ttk.Label(settings,text="2  处理设置",style="Section.TLabel").grid(row=0,column=0,columnspan=2,sticky="w")
        ttk.Label(settings,text="下载：哼哼猫 API   ·   转写：Groq Whisper",style="Muted.TLabel").grid(row=1,column=0,columnspan=2,sticky="w",pady=(2,8))
        self._combo(settings, "视频清晰度", self.download_quality, ["推荐", "最高", "1080P", "720P"], row=2, col=0)
        self._combo(settings, "并发任务数", self.workers, ["1", "2", "3", "4"], row=3, col=0)
        self._field(settings, "FFmpeg", self.ffmpeg, browse=True, row=4, col=0)
        self._combo(settings, "原声语言", self.source_lang, ["中文", "英语", "日语", "韩语", "西班牙语", "法语", "德语"], row=5, col=0)
        self._field(settings, "哼哼猫 Key", self.download_key, secret=True, row=6, col=0)
        self._field(settings, "Groq Key", self.groq_key, secret=True, row=7, col=0)
        ttk.Button(settings,text="保存密钥到本机",command=self.save_api_keys).grid(row=8,column=0,columnspan=2,sticky="e",pady=(3,7))
        self._field(settings, "LLM URL", self.llm_url, row=9, col=0)
        self._field(settings, "LLM Key", self.llm_key, secret=True, row=10, col=0)
        self._combo(settings, "LLM Model", self.llm_model, ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gpt-4o-mini", "qwen-plus", "自定义模型"], row=11, col=0, editable=True)
        self._combo(settings, "目标语言", self.lang, ["英语", "日语", "韩语", "西班牙语", "法语", "德语"], row=12, col=0)
        self._combo(settings, "文案风格", self.style, ["自然口播", "新闻讲解", "产品介绍", "故事叙述", "短视频营销"], row=13, col=0)
        self._combo(settings, "文案长度", self.length, ["保持原时长", "缩短文案", "适当扩展"], row=14, col=0)
        workspace=ttk.Frame(body,style="Card.TFrame",padding=16); workspace.grid(row=1,column=0,columnspan=2,sticky="nsew"); workspace.columnconfigure(0,weight=1); workspace.rowconfigure(2,weight=1)
        ttk.Label(workspace,text="3  执行任务",style="Section.TLabel").grid(row=0,column=0,sticky="w"); actions=ttk.Frame(workspace,style="Card.TFrame"); actions.grid(row=1,column=0,sticky="ew",pady=(9,10)); ttk.Button(actions,text="生成 SRT + TXT",style="Step.TButton",command=self.start_transcribe).pack(side="left",padx=(0,7)); ttk.Button(actions,text="AI 改写",style="Step.TButton",command=self.start_rewrite).pack(side="left",padx=7); ttk.Button(actions,text="生成并执行剪辑",style="Step.TButton",command=self.start_edit).pack(side="left",padx=7); ttk.Button(actions,text="批量重命名",command=self.open_rename_window).pack(side="left",padx=7); ttk.Label(actions,textvariable=self.status,style="Status.TLabel").pack(side="right")
        log_frame=tk.Frame(workspace,bg="#111827"); log_frame.grid(row=2,column=0,sticky="nsew"); self.text=tk.Text(log_frame,height=14,wrap="word",font=("Consolas",9),bg="#111827",fg="#D5DCE8",insertbackground="#FFFFFF",relief="flat",padx=12,pady=10); log_scroll=ttk.Scrollbar(log_frame,orient="vertical",command=self.text.yview); self.text.configure(yscrollcommand=log_scroll.set); self.text.pack(side="left",fill="both",expand=True); log_scroll.pack(side="right",fill="y")
    def _field(self, parent, label, var, row, col, secret=False, browse=False):
        box=ttk.Frame(parent,style="Card.TFrame"); box.grid(row=row,column=col,columnspan=2,sticky="ew",padx=0,pady=3); parent.columnconfigure(col,weight=1)
        ttk.Label(box,text=label,width=11,style="Card.TLabel").pack(side="left"); ttk.Entry(box,textvariable=var,show="*" if secret else "").pack(side="left",fill="x",expand=True)
        if browse: ttk.Button(box,text="选择",command=self.choose_ffmpeg,width=6).pack(side="left",padx=(4,0))
    def _combo(self, parent, label, var, values, row, col, editable=False):
        box=ttk.Frame(parent,style="Card.TFrame"); box.grid(row=row,column=col,columnspan=2,sticky="ew",padx=0,pady=3); parent.columnconfigure(col,weight=1)
        ttk.Label(box,text=label,width=11,style="Card.TLabel").pack(side="left"); ttk.Combobox(box,textvariable=var,values=values,state="normal" if editable else "readonly").pack(side="left",fill="x",expand=True)
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
    def save_api_keys(self):
        if not self.download_key.get().strip() or not self.groq_key.get().strip(): messagebox.showwarning("保存密钥","请完整填写哼哼猫 Key 和 Groq Key"); return
        path=save_credentials(self.download_key.get(),self.groq_key.get()); self.status.set("密钥已保存到本机"); messagebox.showinfo("保存密钥",f"密钥已保存：{path.name}")
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
    def set_status(self,value): self.after(0,lambda: self.status.set(value))
    def log(self,x): self.after(0,lambda: (self.text.insert("end",x+"\n"),self.text.see("end")))
    def run(self,fn): threading.Thread(target=fn,daemon=True).start()
    def start_download(self):
        values=(self.url_text.get("1.0","end"),self.project,self.download_quality.get(),self.ffmpeg.get(),int(self.workers.get()),self.download_key.get()); self.run(lambda: self.download(*values))
    def download(self,input_text,project,quality,ffmpeg,workers,api_key):
        try:
            if not project: raise ValueError("请先选择项目目录")
            urls=extract_share_urls(input_text);
            if not urls: raise ValueError("请至少输入一条抖音分享链接")
            completed=0
            def operation(url): return downloader_service.download_video(url,str(project),api_key=api_key,quality=quality,ffmpeg=ffmpeg)
            def done(index,url,path,error):
                nonlocal completed; completed+=1; self.set_status(f"下载进度 {completed}/{len(urls)}")
                self.log(f"[{index+1}/{len(urls)}] 下载失败：{error}" if error else f"[{index+1}/{len(urls)}] 视频已保存：{path}")
            results=run_batch(urls,operation,workers,done); ok=sum(1 for _,_,error in results if error is None); self.set_status(f"批量下载完成：成功 {ok}/{len(urls)}")
        except Exception as e: self.set_status("失败"); self.log("下载失败："+str(e))
    def start_transcribe(self):
        values=(self.project,self.ffmpeg.get(),self.source_lang.get(),int(self.workers.get()),self.groq_key.get()); self.run(lambda: self.transcribe(*values))
    def transcribe(self,project,ffmpeg,source_lang,workers,api_key):
        try:
            if not project: raise ValueError("请先下载视频")
            videos=rename_service.list_videos(project)
            if not videos: raise ValueError("输出目录中没有视频")
            completed=0
            def operation(video):
                wav=str(project/f".{video.stem}.audio.wav")
                try:
                    media.extract_audio(ffmpeg,str(video),wav); seg=asr.transcribe(wav,key=api_key,language=source_lang); json.dump(seg,open(video.with_suffix(".json"),"w",encoding="utf-8"),ensure_ascii=False,indent=2); srt_path=video.with_suffix(".srt"); txt_path=video.with_suffix(".txt"); srt_path.write_text(asr.segments_to_srt(seg),encoding="utf-8-sig"); txt_path.write_text(asr.segments_to_text(seg),encoding="utf-8-sig"); return (srt_path.name,txt_path.name)
                finally: Path(wav).unlink(missing_ok=True)
            def done(index,video,result,error):
                nonlocal completed; completed+=1; self.set_status(f"转写进度 {completed}/{len(videos)}")
                self.log(f"[{index+1}/{len(videos)}] 转写失败 {video.name}：{error}" if error else f"[{index+1}/{len(videos)}] 已生成：{result[0]}、{result[1]}")
            results=run_batch(videos,operation,workers,done); ok=sum(1 for _,_,error in results if error is None); self.set_status(f"批量转写完成：成功 {ok}/{len(videos)}")
        except Exception as e: self.set_status("失败"); self.log("识别失败："+str(e))
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
