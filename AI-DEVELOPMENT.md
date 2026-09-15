# 开发交接

入口 src/run_pet.py，主体为 Tkinter/Pillow；功能分在 computer_*、weixin_*、todo_*、conversation_*、memory_maintenance、research_watch、sync_* 等模块。app_identity.py 管理名称/版本，characters 管理角色卡与渲染配置。

建议 Windows x64 Python 3.14：创建 .venv，安装 src/requirements-win-py314.lock，执行 python src/run_pet.py。独立构建另需 PyInstaller，运行 python tools/build_windows.py。测试使用 python tools/run_tests.py；EXE 离线验收使用 Shizuka.exe --self-test --report <绝对JSON路径>，自动使用临时数据目录。

文件执行通过 DSH headless profile 加本次 overlay；src/shizuka-dsh-bridge.mjs 监听公开文本和工具事件，并接入原生 ask_user_question。没有切换成另一个文件执行器；不修改 DSH 全局 profile。任务思考等级由 agentDefaultModel 继承，本包不锁定最高等级。不记录或展示内部 reasoning-delta。保留工具失败、取消和不确定状态，不能仅凭进程退出就捏造任务成功。

对话上下文最多100条/48000字符，完整 JSONL 归档不会裁剪。source 说明、自动摘要不是实际对话；摘要/事实审阅仅收带用户原话来源的稳定事实，不能把助手主动推测变成用户事实。

待办核心 text/due/on_boot/done 走 sync journal；due 是下一次实际提醒时间。todo-details.json 保存 notes/manual_note、category、schedule、提醒渠道和投递状态。后续跨平台适配须区分应共享的备注/周期与端侧送达状态，设计兼容迁移与去重；不能直接把旁表跨端覆盖。当前只有两个用途：生活和研究。

共享服务用签名 journal、独立设备身份、幂等事件和冲突记录；默认每10800秒，文件队列保持轻量检查。sync_client.py 可单独运行资料库界面。部署自行配置配对及通道，本包不含任何可连到既有设备的资料。

研究默认空配置，通过 Crossref 公共元数据筛选，论文原文与来源为数据，不能作为执行指令。保留原文期刊名称；无摘要时评论只能根据题名，不能编造实验结果。UI中“立即检查”与主动提醒仍可用，首次需配置自己的方向。

动作系统支持原始层、可选 expression_frames/body_frames/activity_frames 和 question_effect。没有新活动图时走既有静香姿态；不要把缺失差分描述成真实3D或Cubism效果。普通图与活动全身图不能随意叠加眼嘴。

本包是从当前功能源码单独构建的静香版本；不会继承任何个人运行资料。发布时重新核验全部源码、资源、EXE内代码、依赖缓存和压缩包，勿拷贝本机 data、凭据、聊天或调试会话。
