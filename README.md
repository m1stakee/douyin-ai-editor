# VideoFlow 短视频智能工作台

轻量 Windows 桌面工具，用于处理已获授权的抖音视频。支持批量下载、原声转写、字幕剪辑、AI 改写和 VOICEVOX 语音生成。

项目输出按步骤分目录保存：`1_下载视频`、`2_文案与SRT`、`3_字幕剪辑`、`4_AI改写`、`5_语音转出`。第 3 步支持读取步骤文件，也支持手动导入视频并自动匹配 SRT。

## 主要功能

- 输入多条独立抖音视频地址，每条分别调用哼哼猫单帖接口并并发下载（按 URL 数量自动分配线程，最多 8 个）
- API 解析不设置并发上下限，按 URL 数量自动分配线程；媒体下载使用独立线程池，单条失败不影响其他任务
- 多视频下载显示总体字节进度；网络中断时保留临时文件并使用 HTTP Range 自动续传
- 对支持 HTTP Range 的较大媒体自动智能分片：根据文件大小和批次并发量分配 1–6 个分片，缓解 CDN 单连接限速并避免大批量任务产生过多连接；不支持分片时自动回退普通下载
- 每次点击下载都会创建独立批次和可放大的任务窗口，每个视频可单独停止与续传
- 解析或下载失败后可对单条视频点击“重新解析”，刷新短效链接并从断点继续
- 媒体短效链接过期时自动重新调用哼哼猫解析接口再继续下载
- 默认先用 FFmpeg 将 MP4 提取为 16 kHz、单声道、48 kbps MP3，再直接上传阿里云百炼 Paraformer，生成带时间戳的 SRT、TXT 和 JSON
- 转写完成或失败后都会自动删除临时 MP3；转写接口只保留阿里云百炼
- 文案与 SRT 采用独立批次窗口，逐视频显示阶段进度，失败后可单独重试
- 统一任务中心展示下载和文案/SRT批次；任务明细、进度、状态和错误会持久化，重启后仍可查看和重新执行
- 在“4 AI 改写”窗口批量处理 TXT，可选择阿里云百炼或 OpenAI 兼容接口
- 校验并自动执行 FFmpeg 命令
- 批量重命名视频及所有同名 SRT、TXT、JSON 文件
- 文案/SRT 不设置并发上下限，按当前视频数量自动分配任务线程；Windows 下 FFmpeg 静默运行，不弹出控制台黑框
- 单个任务确认失败后会关闭本轮线程池并重新创建线程，最多自动重试 3 次；连续失败才标记任务失败

## 首次使用

1. 软件启动后输入卡密。客户端固定连接授权服务器，不显示也不允许修改服务器地址；验证成功后进入主界面。
2. 软件已内置 FFmpeg Essentials 精简版，无需另外安装；“FFmpeg”路径选择仅用于手动替换内置版本。
3. 展开“接口与工具配置”，填写哼哼猫、阿里百炼、豆包 Ark 和 ChatGPT 接口 Key。AI 改写可选择豆包，使用火山方舟 Chat API `https://ark.cn-beijing.volces.com/api/v3/chat/completions` 与模型 `doubao-seed-2-1-pro-260915`；豆包 Key 也可通过 `ARK_API_KEY` 环境变量提供。兼容接口固定使用 `https://new-api.aicarb.com/v1` 与 `gpt-6.1-sol`，推理级别为 `low`。
4. 点击“保存全部配置”。输出目录、处理选项和接口配置会在下次启动时自动恢复；FFmpeg 已内置，无需配置。
5. 软件正常关闭时也会自动保存当前配置。

AI 改写只将提示词和 TXT 正文发送到所选模型接口。改写结果按批次保存到 `项目目录/4_AI改写/改写批次_时间戳`。提示词管理支持保存、编辑、删除和应用自定义提示词，数据保存在本机设置中。

全部设置保存在 `%LOCALAPPDATA%\VideoFlow\settings.local.json`，更换或移动 EXE 后仍会继续使用。旧版程序同目录的 `settings.local.json` 和 `credentials.local.json` 仍可读取，保存配置后会迁移到固定目录。

## 本地运行

```powershell
python -m pip install -r requirements.txt
python main.py
```

## Azure 文本转语音模块

协作者可以直接调用独立模块 `azure_tts_service.py`。调用者可显式传入 Key、地域、音色和语速：

```python
from azure_tts_service import available_voices, synthesize_speech

print(available_voices())  # 可用于填充界面音色下拉框

output = synthesize_speech(
    "你好，这是测试语音。",
    "output/test.mp3",
    speech_key="调用者填写的 Key",
    speech_region="canadacentral",
    voice="zh-CN-XiaoxiaoNeural",  # 也可传中文标签“晓晓（女）”
    rate=1.2,
)
print(output)
```

四项参数的含义：

- `speech_key`：调用者填写的 Azure Speech Key
- `speech_region`：调用者填写的 Azure 地域，例如 `canadacentral`
- `voice`：调用者选择的音色名称或本模块提供的中文标签
- `rate`：调用者填写的语速倍率，允许 `0.1`～`3.0`

如果调用者没有传 Key 或地域，模块才会尝试读取 `AZURE_SPEECH_KEY` 和 `AZURE_SPEECH_REGION` 环境变量。批量调用使用 `synthesize_batch()`，每个任务的成功或异常会独立返回，单条失败不会中断整个批次。

## VOICEVOX 本地语音

主界面的“VOICEVOX 本地语音”入口支持用户自行安装后直接使用：

1. 点击“打开官方安装页”，从 VOICEVOX 官方渠道安装。
2. 返回软件点击“启动并连接”；未自动识别时选择 `VOICEVOX.exe` 或 `vv-engine/run.exe`。
3. 可勾选“启用 GPU 加速”，由本软件启动引擎时会使用 `--use_gpu`；GPU 负责语音推理，CPU 仍负责文本和音频处理。
4. 软件从本地引擎动态读取音色，可选择青山龍星等已安装音色并调整语速、音高和音量。
5. 点击“退出引擎”可关闭由本软件启动的引擎；若连接的是外部 VOICEVOX，确认警告后会同时关闭其桌面程序和引擎，避免引擎被自动重新启动。
6. 点击“导入文件”可一次导入多个 UTF-8、UTF-16 或日文 CP932 编码的 TXT 文案，并用“全选”和“清除”管理任务。
7. 选择统一保存目录和 WAV、MP3、M4A 或 FLAC 输出格式后点击“批量生成语音和 SRT”。软件会按换行和句末标点拆句，并根据每句真实语音时长生成同步字幕。
8. 每份文案输出同名完整 WAV、同名 SRT 和同名 `_segments` 分段目录；某个文件失败不会中断其他文件。
9. “句间停顿”默认 0.3 秒，该停顿会同时反映在完整音轨和字幕时间轴中。

第 3 步读取 `1_下载视频` 和 `2_文案与SRT`，也支持手动导入视频并自动匹配同名 SRT；随后将字幕条目和时间轴交给已配置的 ChatGPT 兼容接口，按“只整段删除、每处至少 3 条、至少 3 处、保留 60%~80%”生成删除范围，使用内置 FFmpeg 输出到 `3_字幕剪辑`，同时生成重新计时的 `_剪辑.srt` 和对应 `_剪辑.txt`。原始文件不会被覆盖。
10. 发布时应遵守对应角色条款并标注，例如 `VOICEVOX: 青山龍星`。

VOICEVOX 的安装位置、GPU 模式、音色、语速、音高、音量、句间停顿和保存目录会写入本机设置文件，并在下次打开时恢复；临时导入的文案列表不会保存。文件列表中的每一项都可单独删除，保存目录也可从窗口直接打开。若连接的是外部已经启动的引擎，实际 CPU/GPU 模式由外部引擎的启动参数决定。

本项目不重新分发 VOICEVOX 引擎或音声模型。引擎仅绑定并连接本机 `127.0.0.1:50021`，不会由本软件开放到公网；关闭本软件时只结束由本软件启动的引擎。只有用户主动点击“退出引擎”并确认警告时，软件才会关闭外部 VOICEVOX。

## 构建 Windows EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建结果位于 `dist\DouyinAIEditor.exe`。
