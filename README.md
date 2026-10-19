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
2. 在“处理设置”中填写“哼哼猫 Key”和“Groq Key”。
3. 点击“保存密钥到本机”。下次启动时会自动加载。
4. 填写大模型的 URL、Key 和模型名称后即可使用 AI 改写与剪辑。

密钥保存在程序同目录的 `credentials.local.json`。该文件已加入 `.gitignore`，不会提交到 Git。也可以复制 `credentials.example.json` 并改名为 `credentials.local.json` 后手动填写。

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
