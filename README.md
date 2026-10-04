# Shizuka 桌宠

（这一段话是真人写的）
  - 由于本人没有什么开发技术，只会当ai驾驶员，所以就全部由大肥鱼代写了。如果项目中出现了左右脑互搏或者讲的不清楚的地方可以交给agent研究。
  - 特别感谢Cuttlefish先生和GPT-6 Astra的大力支持
  - wds你怎么就要似了😭

## 使用说明（由gpt代写）

这是一个《World Dai Star》Shizuka 的 Windows 桌宠，当前版本为 **v0.9.0**。可以放在桌面上聊天、记待办，也可以通过微信从手机上找她。

[下载完整包](https://github.com/lxz61352-cmyk/shizuka-desktop-pet/releases/latest) · [更新公告](更新公告.md) · [反馈问题](https://github.com/lxz61352-cmyk/shizuka-desktop-pet/issues)

## 现在能做什么

- **桌面和微信聊天**：使用统一的对话链路，支持看图、读文本与 PDF、接收附件和引用回复。聊天需要自己配置模型接口与 API Key。
- **联网查询**：目前适配 DeepSeek API，其他模型暂未适配联网功能。
- **主动搭话与心情**：可开启主动搭话，调整频率和静默时间；话题避免广告和过度窥探隐私。心情会随对话变化，目前仍在优化。
- **记忆与待办**：保留聊天上下文和长期记忆；可以通过聊天快捷添加、查看和处理待办，也可以在窗口中编辑备注、时间和提醒。
- **窗口外观**：工具窗口使用 Qt，背景随机展示卡面图片，支持调整亮度和模糊度。保留最小化、最大化和关闭按钮。
- **日常工具**：番茄钟、天气和新闻、使用时长统计、桌面互动、音乐及可选语音朗读。
- **电脑助手**：通过本机 DSH 读取、创建、编辑和整理文件，需要另外配置 DSH 与工作目录。

## 下载后怎么用

1. 下载 `Shizuka-0.9.0-Windows-x64.zip`，完整解压到自己能写入的目录。
2. 双击 `Shizuka.exe`。不用安装 Python；不要拆开 `_internal`、`qt-windows`、`assets`、`characters` 等配套文件夹，也不要只下载一个 EXE。
3. 从桌宠菜单打开「模型与接口」，填写自己的接口地址、模型和 Key。聊天主要用 DeepSeek 测试，也支持 OpenAI 兼容接口；各服务商的具体适配情况可能不同。
4. 想从手机聊天，打开「微信连接」扫码绑定。电脑和桌宠需要保持运行。

平台为 **Windows x64**，Windows 11 已实测，Windows 10 待测。语音和电脑助手是独立配置的，不启用也可以正常聊天。

## 更新与个人数据

旧用户可以在程序内检查更新，或者下载 `Shizuka-0.9.0-update.zip` 手动覆盖。手动更新前退出桌宠并备份 `data`，保留自己的数据目录和语音模型。

聊天、记忆、待办和个人设置保存在本机。发布包不包含开发者的 API Key、微信绑定、聊天记录、GPT-SoVITS 环境或语音模型权重；转发程序时不要把自己的 `data`、微信附件和备份一起打包。

## 源码与开发

源码运行需要 Python 和 [src/requirements.txt](src/requirements.txt) 中的依赖，入口为 `src/run_pet.py`。桌宠与特殊浮层使用 Tkinter，普通工具窗口由独立的 Qt Quick 进程渲染。

构建和回归测试说明见 [AI-DEVELOPMENT.md](AI-DEVELOPMENT.md)。窗口组件的构建工具为 `tools/build_qt_windows.py`，发布时需要同时携带 `qt-windows` 目录。
