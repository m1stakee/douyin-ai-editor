# VideoFlow Qt 客户端

独立入口 `qt_client.py`，现有 Tkinter 入口 `main.py` 保留。

## 模块

- 下载：哼哼猫分享链接解析、五路并发下载、逐条暂停/继续、逐条和批量重试。
- 文案与 SRT：视频导入，复用临时 OSS 上传及 New API paraformer-v2，导出 UTF-8 JSON/SRT/TXT。
- 生成答案：SRT 匹配工作目录下第一步同名视频，复用剪辑方案校验，仅生成答案及复制对应资源。
- AI 改写：TXT/SRT 导入、提示词管理、New API 或火山方舟，五路并发，失败立即最多尝试三次。
- 语音转出：嵌入 Qt 语音工作台，Edge TTS 完整目录、收藏、试听、VOICEVOX 本地连接及共用导出区。
- 资源库：按视频、SRT、音频同名复制完整组。
- 重命名：同一目录下所有同名文件一起修改。
- 任务记录：Qt 任务独立记录，不覆盖旧客户端任务记录。
- 配置：复用 `%LOCALAPPDATA%\VideoFlow\settings.local.json`，保存时保留未知字段。语音偏好继续保存到 `qt-tts-preview.json`。

完整 Qt 客户端通过原有固定授权服务器验证卡密后进入；不提供修改服务器的设置。

## 运行与打包

```powershell
python -m venv .venv-qt
.\.venv-qt\Scripts\python.exe -m pip install -r requirements-qt.txt
.\.venv-qt\Scripts\python.exe qt_client.py
.\build-qt-client.ps1
```

依赖与打包使用独立 Python 环境，固定 PySide6 6.8.3。FFmpeg 沿用 `vendor/ffmpeg`。

产物为 `dist/VideoFlow-Qt.exe`。单独语音预览仍可通过 `qt_voice_preview.py` 运行。

语音转出新增 MiniMax 标签页：在页内填写 Key，选择中国大陆或国际区域、模型和音色；“获取音色”查询账号可用音色，也可手填音色 ID。参数和上次引擎保存在本机 `qt-tts-preview.json`。采用官方 `/v1/t2a_v2` 非流式合成，逐句 PCM 音频生成共享时间轴 SRT，支持句间停顿及 MP3/WAV/M4A/FLAC 导出。每句发起一次合成请求，按 MiniMax 账户计费；自动化测试使用模拟响应。

这是首版 Qt 主流程迁移；旧客户端的部分辅助操作（如任务详情重开、转写任务暂停）尚未逐项迁移。付费 API 的自动化检查采用模拟响应，不表示已对真实账户完成端到端调用。
