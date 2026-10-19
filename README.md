# VideoFlow 短视频智能工作台

轻量 Windows 桌面工具，用于处理已获授权的抖音视频。支持批量下载、原声转写、AI 改写，以及生成并自动执行 FFmpeg 剪辑计划。

## 主要功能

- 输入多条抖音分享内容，通过哼哼猫 API 批量下载视频
- 使用 Groq Whisper 生成同名 SRT 字幕和 TXT 纯文案
- 调用 OpenAI 兼容接口改写文案并生成剪辑计划
- 校验并自动执行 FFmpeg 命令
- 批量重命名视频及所有同名 SRT、TXT、JSON 文件
- 支持 1–4 个任务并发执行

## 首次使用

1. 安装 FFmpeg，并在界面选择 `ffmpeg.exe`；如果 FFmpeg 已加入 PATH，软件会自动识别。
2. 展开“接口与工具配置”，填写哼哼猫、Groq 和大模型接口配置。
3. 点击“保存全部配置”。输出目录、处理选项、FFmpeg 和接口配置会在下次启动时自动恢复。
4. 软件正常关闭时也会自动保存当前配置。

全部设置保存在程序同目录的 `settings.local.json`。该文件已加入 `.gitignore`，不会提交到 Git。旧版 `credentials.local.json` 仍可读取，保存新配置后会统一迁移到新配置文件。

## 本地运行

```powershell
python -m pip install -r requirements.txt
python main.py
```

## 构建 Windows EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建结果位于 `dist\DouyinAIEditor.exe`。
