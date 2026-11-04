# 听课 Listenote

Windows 10/11 x64 本地课堂录音转写与笔记工具。使用 Whisper large-v3-turbo 在电脑上离线识别，无需账号。

![Listenote 界面预览](界面预览.png)

## 下载安装

前往 [Releases](https://github.com/Snowflake006/Listenote/releases/latest) 下载 `Listenote-Windows-x64.zip`，完整解压后双击 `Listenote/听课.exe`。

软件包包含 Python 运行环境、CPU 推理依赖、模型和 FFmpeg，无需另装 Python。请保留全部文件，不要单独移动 EXE。建议至少 8 GB 内存（推荐 16 GB），约 4 GB 可用空间。

下载包的 SHA-256 校验值见 [SHA256.txt](SHA256.txt)。PowerShell 校验命令：

```powershell
Get-FileHash .\Listenote-Windows-x64.zip -Algorithm SHA256
```

## 功能

- 导入 MP3、M4A、WAV、MP4 等音视频，支持中文、英语和自动识别。
- 麦克风录音、暂停和标记重点。
- 编辑并自动保存转写文字。
- 按时间和关键词提取课堂原文摘录。
- 导出 Word、PDF、TXT、Markdown 和 SRT。

课堂摘录是原文提取，不是大语言模型总结。时间戳约按 25 秒分段，SRT 为片段级时间。识别结果可能出现错漏，重要内容请回听核对。

笔记和录音默认存放在 `%LOCALAPPDATA%\Listenote`。导入的原录音保留在原位置，请不要移动或删除。更多信息见 [使用说明](Listenote/使用说明.txt)。

## 源码结构

```text
Listenote/
  app/main.py        界面与业务逻辑
  app/startup.py     启动入口和错误日志
  app/fonts/         字体及许可证
  Launcher.cs        Windows 启动器源码
  models/whisper/    模型配置与分词器（权重在离线软件包中）
  tools/             FFmpeg 许可证（可执行文件在离线软件包中）
  THIRD-PARTY.txt    第三方组件说明
```

Git 仓库不包含体积较大的 Python 运行环境、模型权重和 FFmpeg 可执行文件；完整离线软件包通过 Releases 分发。

## 从源码运行

需要 Windows x64 与 Python 3.12。最直接的方式是完整解压 Release 软件包，将本仓库中的 `Listenote/app` 源码覆盖到解压目录对应位置，再运行启动器。

也可以自行准备依赖：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

将 [Whisper large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo) 的 `model.safetensors` 放入 `Listenote/models/whisper/`，将 FFmpeg 放入 `Listenote/tools/ffmpeg.exe`，然后运行：

```powershell
.\.venv\Scripts\python.exe Listenote/app/main.py
```

应用默认启用离线模式，运行前需要准备好模型。第三方组件许可证见 [THIRD-PARTY.txt](Listenote/THIRD-PARTY.txt) 及相应目录。
