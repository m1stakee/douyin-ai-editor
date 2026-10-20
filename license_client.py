import hashlib, os, platform, uuid
import tkinter as tk
from tkinter import messagebox, ttk
import requests

LICENSE_SERVER_URL = "http://124.220.178.193:10190"

def device_id() -> str:
    raw = f"{platform.node()}|{platform.machine()}|{uuid.getnode()}|{os.environ.get('USERNAME','')}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def verify_license(server_url: str, license_key: str, timeout: int = 12) -> tuple[bool, str]:
    url = server_url.rstrip('/') + '/api/license/verify'
    try:
        response = requests.post(url, json={"license_key": license_key, "device_id": device_id(), "device_name": platform.node(), "app_version": "1.0"}, timeout=timeout)
        payload = response.json()
        return bool(payload.get('valid')), str(payload.get('message') or payload.get('code') or '授权验证失败')
    except requests.RequestException as exc:
        return False, f"授权服务器连接失败：{exc}"
    except (ValueError, TypeError):
        return False, "授权服务器返回格式错误"

def verify_saved_license(license_key: str, verifier=None) -> str | None:
    key = license_key.strip()
    if not key:
        return None
    check = verifier or (lambda value: verify_license(LICENSE_SERVER_URL, value))
    valid, _message = check(key)
    return key if valid else None

def require_license(parent, license_key: str) -> str | None:
    result=[]; win=tk.Toplevel(parent); win.title('VideoFlow 授权验证'); win.geometry('440x285'); win.minsize(440,285); win.resizable(False,False); win.protocol('WM_DELETE_WINDOW',win.destroy)
    frame=ttk.Frame(win,padding=24); frame.pack(fill='both',expand=True); ttk.Label(frame,text='启动授权验证',font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w'); ttk.Label(frame,text='请输入卡密，验证成功后进入软件。').pack(anchor='w',pady=(4,15))
    key_var=tk.StringVar(value=license_key)
    row2=ttk.Frame(frame); row2.pack(fill='x',pady=4); ttk.Label(row2,text='卡密',width=8).pack(side='left'); key_entry=ttk.Entry(row2,textvariable=key_var,show='*'); key_entry.pack(side='left',fill='x',expand=True)
    status=tk.StringVar(value=''); ttk.Label(frame,textvariable=status,foreground='#C2412D').pack(anchor='w',pady=(7,0))
    def submit():
        key=key_var.get().strip()
        if not key: status.set('请输入卡密'); return
        status.set('正在验证…'); win.update_idletasks(); valid,message=verify_license(LICENSE_SERVER_URL,key)
        if valid: result.append(key); win.destroy()
        else: status.set(message)
    ttk.Button(frame,text='验证并进入',command=submit).pack(side='bottom',anchor='e',pady=(12,0)); win.bind('<Return>',lambda _event:submit())
    win.update_idletasks(); x=(win.winfo_screenwidth()-win.winfo_width())//2; y=(win.winfo_screenheight()-win.winfo_height())//2; win.geometry(f'+{x}+{y}')
    win.attributes('-topmost',True); win.after(400,lambda:win.winfo_exists() and win.attributes('-topmost',False)); win.grab_set(); win.lift(); key_entry.focus_force(); parent.wait_window(win)
    return result[0] if result else None
