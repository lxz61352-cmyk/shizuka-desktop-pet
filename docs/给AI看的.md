# 给 AI / 开发者看的：Shizuka 桌宠 V0.8.0

> 这是一份**自包含**的技术交接文档：程序是什么、怎么跑、怎么改、每个功能怎么实现的、还有什么没解决。
> 相对路径都以解压目录为根。上一版本文档对应 V0.6.0，架构已在 V0.7.6 全部模块化，本文按 0.8.0 重写。

---

## 一、这是什么

一个 Windows 桌面宠物（Tk + Pillow）：角色是《World Dai Star》的静香，待在桌面上，支持聊天（任意 OpenAI 兼容接口，默认 DeepSeek）、记忆、待办提醒、剪贴板反应、天气/新闻、开机问候、角色包、鼠标互动、背景音乐、可选语音朗读、使用时长统计、文件助手、微信远程、文献筛选、双端记忆同步和自动更新。

- 语言/运行：Python 3.13 + Tkinter + Pillow + pystray + openai；用 PyInstaller 打成 `Shizuka.exe`（onedir，旁边 `_internal/`）。
- 无控制台窗口（`--windowed`），崩溃写 `data/startup_error.log`。
- 单实例：Windows 命名互斥体 `Local\ShizukaAssistant_SingleInstance`。
- **版本常量在 `src/app_identity.py` 的 `APP_VERSION`**（0.7.6 起从 `pet.py` 挪走）；`APP_NAME` / `APP_ID` 也在这里。

### 目录结构

| 路径 | 说明 |
| --- | --- |
| `Shizuka.exe` + `_internal/` | 打包好的可运行程序（PyInstaller onedir）。**`_internal/base_library.zip` 是运行必需文件**，`.gitignore` 里特意用 `!_internal/*.zip` 放行 |
| `src/` | 完整 Python 源码（约 60 个模块） |
| `characters/` | 角色包（`shizuka-side-motion` 微动版、`shizuka-classic` 单图版），人设卡是同目录 `persona.json`（SillyTavern V2） |
| `assets/` | 图片/音频（`i_wanna.mp3`、`reminder.wav`、`voice_ref1.wav`、图标、`bubble/`） |
| `voice_model/` | 「喜多郁代」音色模型（`.ckpt` + `.pth`，约 328MB，走 Git LFS）+ `说明.md` |
| `docs/` | 发布文档（本文） |
| `tools/` `tests/` | 构建/发版脚本、回归测试 |
| `更新公告.md` | 更新重启后弹出的公告，按 `## vX.Y.Z` 分节 |
| `version.json` | `{"version","asset","notes"}`，更新检查的镜像备用源读它 |
| `MANIFEST.json` / `VERIFICATION.json` / `verify_package.py` | 发布包文件哈希清单与校验脚本 |
| `data/` | **运行数据（首次运行自动创建；本包不含）** |
| `启动桌宠.bat` / `源码启动.bat` / `预览动作.bat` | 启动脚本（源码启动= `pythonw src/run_pet.py`，预览= `Shizuka.exe --preview`） |

---

## 二、运行、构建、测试、发版

- **运行（用户）**：双击 `Shizuka.exe`。程序按 `sys.executable` 的目录找 `assets/`、`characters/`、`data/`（frozen 时 `ROOT_DIR = dirname(sys.executable)`）。
- **源码运行**：装好含 Tcl/Tk 的 Python（3.10~3.13）与 `src/requirements.txt` 后运行 `源码启动.bat`；`run_pet.py` 是入口（捕获启动异常 → `data/startup_error.log` + MessageBox）。
- **构建**：`python tools/build_windows.py`（PyInstaller onedir，参数见脚本）。构建产物直接覆盖根目录的 `Shizuka.exe` + `_internal/`。构建环境（本项目实测）：Python 3.13.14 + PyInstaller 6.22.3。
- **测试**：`python tools/run_tests.py`（用临时数据目录，不调真实 API）。
- **离线验收**：`Shizuka.exe --self-test --report <绝对JSON路径>`（用临时数据目录跑 `release_smoke.py`，不联网、不读凭据）。
- **发版**：`python tools/make_release.py`——重新生成 `version.json`、`VERIFICATION.json`、`MANIFEST.json` 并打出 `Shizuka-<版本>-Windows-x64.zip` 与 `Shizuka-<版本>-update.zip`。之后建 GitHub Release（tag `v<版本>`，附件挂 update 包）。
- **改代码不会改变已打包的 EXE**，必须重新构建。

---

## 三、代码入口与职责

| 文件 | 职责 |
| --- | --- |
| `src/run_pet.py` | 入口：错误日志、单实例、`--preview`、`--self-test` |
| `src/app_identity.py` | 名称/版本/默认角色 |
| `src/pet.py` | 主程序：Tk 窗口、鼠标事件、菜单、渲染调度、提示音/音乐、语音服务、设置持久化、待办与提醒循环、剪贴板、前台感知、问候、使用时长 |
| `src/speech_motion.py`、`src/activity_states.py` | 说话/动作状态机、活动帧调度 |
| `src/dialogue_*.py` | 聊天、上下文拼接、口吻清理、被动发言闸门（`dialogue_grounding`）、显式记忆 |
| `src/conversation_memory.py` | 统一近期上下文与长期事实提炼 |
| `src/memory_maintenance.py` | 记忆审阅/整理（带来源） |
| `src/todo_*.py` | 待办：模型整理（`todo_model`）、提醒策略（`todo_schedule`）、周期（`todo_recurrence`）、备注、语音、编辑窗、回复 |
| `src/intent_routing.py` | 本地快速通道 + 交给模型的意图路由提示词 |
| `src/weather.py` / `src/news.py` / `src/weather_features.py` | 定位+天气（双源）、新闻、天气/新闻问答 |
| `src/updater.py` / `src/update_features.py` | 检查更新、镜像下载、覆盖安装、更新公告 |
| `src/computer_agent.py`、`computer_ui.py`、`computer_progress.py` | 本机 DSH 文件助手（配置、任务、只读进度窗） |
| `src/weixin_channel.py`、`weixin_ui.py` | 微信绑定、收发、识图、远程指令 |
| `src/research_watch.py`、`assistant_features.py` | 文献筛选与「更多设置」二级菜单（**研究进展当前整体禁用**，见下） |
| `src/sync_*.py` | 双端记忆/聊天/待办同步（签名 journal、设备身份、冲突记录） |
| `src/character_packs.py`、`character_persona.py` | 角色包校验与路径限制、人设卡读取 |
| `src/layered_renderer.py`、`local_mesh.py`、`pet_motion.py`、`pet_triggers.py`、`pet_ground.py`、`pet_surfaces.py` | 局部网格变形、弹簧/单摆、动作触发、重力与窗口承接 |
| `src/ui_theme.py`、`dialogue_bubble.py`、`conversation_ui.py` | 统一控件主题、可滚动气泡、聊天输入/记录 |
| `tools/preview_character.py` | 与正式程序一致的鼠标互动离线预览 |

---

## 四、关键功能实现

### 1. 角色包与渲染

- 角色包在 `characters/<id>/character.json`（`renderer: layered` 或 `static`），人设在同目录 `persona.json`。`character_packs.discover_packs()` 扫描，`selected_pack()` 按 `data/settings.json` 的 `character_pack` 选。
- 微动版是**分层 PNG 局部网格**：`LayeredRenderer` + `LocalMesh` 做头/发梢/下半身变形，闭眼/说话/撇嘴/下落嘴型用局部覆盖贴片。
- **透明是色键（chroma-key）**：`TRANS_COLOR = "#000001"`，`render_display()` 把 alpha 阈值化后填色键；`set_window_transparent()` 设 `-transparentcolor`。所以**不是真 alpha**（色键区自动穿透点击）。整体淡入淡出用窗口属性 `-alpha`。
- 圆角窗口（聊天输入框、气泡）用 `ui_theme.round_window()`：色键透明 + Canvas 画**采样过的圆弧多边形**（不要用 `create_polygon(smooth=True)`，那样只切掉 1~2px，看着还是方的）。内容必须四边缩进 `radius`，否则会盖住圆角。
- 性能：`_RenderWorker` 后台线程渲染最新姿态，主线程只取成品帧；基础组按高度缓存 + 动态补丁叠加。

### 2. 聊天与上下文

- `DeskPet._ask_model()`：`system = load_persona() + 聊天风格 + 相关记忆 + 待办备注上下文`，带统一近期上下文（最多 100 条 / 48000 字），流式生成，边生成边按句合成/显示。
- **口癖兜底**：`clean_reply_style()` 用正则去掉回复开头的语气词起手和紧随的第一句句尾语气词；接在流式显示、`_play_reply`、`say()`、剪贴板点评等所有出口。函数幂等，喂回模型的历史也是清理后的。
- `[历史消息时间：…]` 这类上下文元信息在 `clean_text` 里被正则剥离，提示词也禁止复述，否则模型会念出来。
- 人设改动**实时读取**，改完下一条即生效。

### 3. 记忆

- `data/characters/<角色>/memory.json`，`MemoryStore`（带锁）。显式「记住 X」→ 模型解析保留原文 → 永久记忆；未明说时模型判断是否值得长期记。检索优先本地语义检索，回退关键词重合，按相关度注入。
- 启动清理过期（25 天未引用按概率删）+ 模型合并近义重复；`memory-review.json` 记录哪些旧对话已审阅，避免重复刷记忆。

### 4. 待办 / 提醒

- `todos.json` 只存核心字段（`text/due/on_boot/done`）；`todo-details.json` 存备注、分类（生活/研究）、周期规则、提醒渠道和投递状态（**旁表，不跨端覆盖**）。
- 建待办两条路：自然语言（`intent_routing` → `add_todo` → `_handle_add_todo`，相对时间本地算、模糊追问）和 `/待办`（模型整理成多条，带备注/时间/提前量/周期）。
- `_reminder_loop` 每 20 秒检查到期；开机类在启动时触发；折叠时只发声、下次打开补说。提前提醒/周期由 `todo_schedule` 算，事件类默认提前 1 小时，「有空时」默认每天 09:00 直到完成。
- **完成即收尾**：待办被标记完成（含提前完成、`_todo_end_series` 结束周期）时会清掉 `notice` 并 `_todo_cancel_notices`，不留「已完成但未提醒」的尾巴。
- **准点提醒**：`lead_minutes=0` 时 `due == event_at`，事件一开始 `event_expired` 就成立、会被整条跳过；`_todo_check_reminders` 因此留了 `REMINDER_GRACE=600` 秒宽限，保证这次提醒还能发出去（只发一次）。

### 5. 剪贴板 / 截图

- `_clip_loop` 每 1.5 秒查 `GetClipboardSequenceNumber`；仅对启动后的新内容反应。路由：图片文件路径 → 识图；网址 → `fetch_page_text`（`http_get` 解 gzip/deflate）→ 概括；失效路径 → 试取图；外语 → 翻译；否则 → 普通反应。
- **去重**：`_clip_repeat/_clip_remember` 记住最近回应过的内容（文字还认「同一段被逐渐加长/截短」；图片按 sha1 精确匹配 + `clip_image_phash()` 的 dHash 16×16 近似匹配，所以「同一画面重新截一次 / 换个程序再复制」也算重复）。记录落盘在 `data/clip-recent.json`（`load_clip_recent`/`_save_clip_recent`，保留 `CLIP_MEMORY=200` 条、`CLIP_RECENT_TTL` 内有效），**重启不清空**；启动时 `_clip_primed` 会把剪贴板里已有的图片也记成基线（`_prime_clip_image`），所以重启后不会对启动前的旧截图再反应一次。频率只留 3~5 秒防抖，不再用长间隔卡（长间隔会让「复制了却不理人」）。
- 被动发言的闸门在 `dialogue_grounding`：`_claim_passive` 对剪贴板/截图用独立短间隔，且不占用「主动搭话间隔」，否则主动搭话会被饿死。剪贴板内容**不当指令**、不设待办。

### 6. 天气 / 新闻

- `weather.py`：`_geo_ip()` 先查国内 IP 库（GBK）再回退 ip-api；`_net_mode()` 探测外网是否可达并缓存。外网可达走 Open-Meteo（地理编码 + 当前/未来三天），否则走中国气象局 `weather.cma.cn`，两边互为兜底。WMO 天气码用 `_WMO_ZH` 转中文。
- `news.py`：`get_news()` 取 `https://60s.viki.moe/v2/60s` 的当日标题列表。
- 问答走 `weather_features._weather_worker / _news_worker`（拿数据 → 交给模型用角色口吻回答）；启动时 `_prefetch_geo()` 后台预热，`_greeting_weather()` 有 35% 概率把真实天气带进开机问候。

### 7. 语音朗读 / GPT-SoVITS

- 应用保留语音能力（`VOICE_ENABLED = True`）。是否可用取决于**本机有没有装 GPT-SoVITS**：`gsv_dir()/gsv_available()/gsv_py()` 先看环境变量 `GSV_DIR`/`GPTSOVITS_DIR`/`GPT_SOVITS_DIR`，再看 `settings.json` 的 `gsv_dir`，再在常见根目录找 `*GPT-SoVITS*`；判定标准是「有 `runtime\python.exe` 且有 `api_v2.py`」。
- 服务：TTS 走 `http://127.0.0.1:9880/tts`（`api_v2.py` + `tts_infer_pet.yaml`），语义检索服务 9881。`_ensure_tts_server` / `_ensure_emb_server` 后台拉起；**健康检查**：TTS 请求超时自动杀进程重拉，语义服务卡死由主循环重拉（否则会「端口开着但不出声」）。
- 流水线：`_tts_synth` → `_speak`/`_speak_stream`/`_tts_enqueue`/`_tts_producer`/`_tts_loop`；`_voice_type_*` 让文字按朗读时长逐字出；`_startup_gate` 未就绪先显示「语音服务加载中…」（最多等 4 分钟）。
- 参考音色 `assets/voice_ref1.wav` 随包；GPT-SoVITS 本体约 14GB，不随包发布。

### 8. 背景音乐「i wanna」与旋转唱片

- `assets/i_wanna.mp3`；`MUSIC_ALIAS = "deskpet_bgm"` 独立 MCI 别名（与提示音互不打断），音量 850/1000。
- 状态机 `_music_state ∈ {stopped, playing, paused}`；`_music_poll` 每秒查 MCI `status mode`，自然播完自动回 stopped。
- 唱片：`extract_mp3_cover()` 取 ID3v2 APIC 封面（无封面深色兜底）→ `make_vinyl_image()` 裁圆挖孔 → 独立 `Toplevel`，排在齿轮正下方、随角色移动缩放，`VINYL_SPIN_DEG=1.1°`/`VINYL_FRAME_MS=50` 旋转。
- 交互：`_vinyl_press` 起 3 秒定时器，到点 `_music_stop()`；提前松手则播放↔暂停。

### 9. 提示音 / 使用时长

- `play_sound` → 后台线程 MCI `deskpet_snd`（`wait=True`），音量 `SOUND_VOLUME=850`。四档：`all` / `todo-files`（默认）/ `todo` / `none`，由 `_should_sound` 判定；聊天回复也要响（`_ask_model` 开头补一次），否则只有 `say()` 路径会响。
- `usage.json`（`{"days": {日期: {exe: 秒}}}`，保留最近 14 天）。`_usage_loop` 每 5 秒采样前台程序；连续无键鼠超过 `usage_away_min`（默认 5 分钟）且无音频播放时视为离开、暂停统计。问「我今天用了多久」由 `usage_report` 意图直接汇报。

### 10. 检查更新

- `updater.check_latest_release()` 先直连 GitHub API（超时 4s），失败转镜像读 `version.json`；返回 `(有更新, 版本, 下载地址, 说明)`。`UPDATE_REPO` 在 `updater.py` 顶部。
- 菜单「检查更新」左键检查/更新（确认窗 → `download_package()` 下载解压 → `launch_swap()` 写 bat：等本进程退出 → `robocopy /E /XD data voice_model experiments /XF api_key.txt` 覆盖 → 重启 → 清理），**右键**可停止/重新接收更新（`settings.json` 的 `update_disabled`）。
- 更新重启后 `_show_update_done()` 弹一次公告：优先取随包 `更新公告.md` 里该版本那一节（`read_announcement`），其次 Release 说明；弹完删除 `data/_pending_update.json`。
- **更新提示只跟 GitHub Release 有关**，普通 commit 不会触发；发新版要建带 tag 和 zip 附件的 Release。

### 11. 电脑助手 / 微信 / 研究 / 同步

- **电脑助手**：`/电脑 <任务>` 或明确文件指令 → 本机 DSH（headless profile + 本次 overlay，`src/shizuka-dsh-bridge.mjs`）。进度窗只读，需要确认的问题回到聊天里问。配置在 `data/computer-assistant.json`（工作文件夹、Node 路径、dsh bin.js、操作范围）。
- **微信**：`weixin_channel` 负责协议与收发，`weixin_ui` 负责扫码/设置；支持对话、识图、`/图片`、`/电脑` 等远程指令，待办提醒也可走微信。绑定状态存 `data/weixin-state.json`。
- **研究进展**：`research_watch` 按 `data/research-profile.json` 的 `topics`/`queries` 检索，模型按摘要判断相关性；缺摘要时只依据题名评论，不编造结论。
- **同步**：`sync_runtime/sync_client/sync_store/sync_transport/sync_rustdesk/...` 用签名 journal、独立设备身份、幂等事件；默认每 3 小时（`memory_interval_seconds`，60~604800 秒）轻量检查，另有手动同步。

### 12. 线程 / 锁 / 设置 / 凭据

- 后台线程统一经主线程队列 `_ui`/`_poll_ui` 操作 Tk。锁：`_FILE_LOCK`（文件写）、`_hist_lock`、`_chat_lock`、`_MCI_LOCKS`（每别名一把）、`_render_lock`、`get_client`/`get_memory` 双检锁。
- 设置持久化在 `data/settings.json`（`_save_settings` 写的是**显式字段字典**，新增设置项要同时改 `load_settings` 和 `_save_settings`）。
- API Key 存 **Windows 凭据管理器**（`_cred_write`/`_cred_read`，目标 `ShizukaDeskPet/api_key`；读取时 `ShizukaAssistant/api_key` 也认，兼容 0.7.6 改过的名字），**程序目录不留 Key 文件**；旧 `api_key.txt` 首次启动自动迁移并删除。
- 数据文件读坏先备份 `.bad-<时间戳>` 再重建，防清空。

---

## 五、数据文件

| 文件 | 内容 |
| --- | --- |
| `data/settings.json` | 功能开关 + 位置/缩放/接口配置 + `update_disabled` |
| `data/characters/<角色>/memory.json` | 记忆库 |
| `data/characters/<角色>/todos.json` + `todo-details.json` | 待办核心字段 + 旁表（备注/分类/周期/通知状态） |
| `data/characters/<角色>/usage.json` | 使用时长（最近 14 天） |
| `data/characters/<角色>/对话记录/对话记录.json` + `YYYY-MM-DD.md` | 对话记录（私人数据） |
| `data/characters/<角色>/memory-review.json` | 已审阅的旧对话标记 |
| `data/computer-assistant.json`、`data/computer-tasks/` | 文件助手配置与每次任务记录 |
| `data/research-watch.json`、`data/research-profile.json` | 文献筛选状态与关注方向 |
| `data/weixin-state.json` | 微信绑定与消息状态 |
| `data/_pending_update.json` | 待弹出的更新公告标记（弹完删除） |
| `data/startup_error.log` / `data/error.log` / `data/sound.log` / `data/tts_server.log` | 日志 |

> 0.7.4 的数据在 `data/` 根下，0.7.6 起在 `data/characters/<角色>/`；迁移时注意这个差异。

---

## 六、版本历史（简）

### 2026-09-16 — V0.8.0

- 「研究进展」整体禁用：`assistant_features.RESEARCH_ENABLED = False`，菜单显示「研究进展（开发中）」，`_research_loop` 不排期、不自动检查、不主动播报；代码都在，改回 `True` 恢复。
- 修复召回自抄袭：`conversation_memory.recall()` 只召回用户原话 + 自动摘要（原来助手自己的旧回复也会被召回，模型会整段照抄），词重合门槛提到 2；风格提示词加「别照抄历史 / 看不懂就说不明白」。
- 修复剪贴板/截图重复反应：去重记录落盘（`data/clip-recent.json`，重启不清空）、启动时把已有图片也记成基线、处理时加锁、图片加 dHash 近似去重（详见「剪贴板 / 截图」一节）。
- 删除 `pet.py` 里两组重复定义的函数（`_kill_proc_tree`、`_emb_port_open`）。
- `更新公告.md` 的 `## v0.7.6` 更正为 `## v0.7.6beta`；README 与本文档同步 0.8.0。
- 新增 `tests/test_conversation_recall.py`、`tests/test_clip_dedup.py`。

### 2026-09-15 — V0.7.7

- 补回 0.7.6 丢掉的功能：语音朗读（GPT-SoVITS）、背景音乐 i wanna + 旋转唱片、窗口使用时长与时长日报、使用统计意图、开机自动启动、查询余额、微信识图、提示音「全部消息」档。
- 新增天气查询、新闻播报、检查更新与更新公告（`weather.py`/`news.py`/`updater.py`/`update_features.py`）。
- 修复：自然语言设待办失效（`_route_intent` 的 `add_todo` 分支被换成「请用 /待办」，`_handle_add_todo` 成了死代码）、粘贴板/截图按长间隔卡住（改为按内容去重）、圆角只有上半（底栏没缩进把下面两角盖住 + `smooth=True` 只切 1px）、API Key 读取兼容、左键拖动、折叠头像拖动、聊天框加载、语音服务卡死自愈、`[历史消息时间]` 被念出、聊天回复不响提示音。
- 「更多设置」从独立窗口改成二级菜单（原窗口在开着语音时点开会崩：`_add_menu_tts_release` 给 `_add_menu_option` 传了它不接受的 `width`），菜单顺序按 6 组重排。

### 2026-09-15 — V0.7.6（朋友的功能共享版，已整合）

- 模块化重构；统一近期上下文（最多 100 条 / 48000 字）+ 自动摘要 + 原话来源记忆与主题索引。
- 待办大改（`/待办`、生活/研究、提前/周期提醒、桌面+微信双通道）；DSH 文件助手；文献筛选；签名同步。
- 可滚动气泡、活动帧、更多设置窗口、角色 persona 化；有界等待 API。

### 版本线：正式版 vs beta（乌贼版）

- **正式版**：本仓库这条线，版本号 `0.7.x`，从 `E:\Shizuka-v0.8.0-test` 构建，发到 GitHub Release。
- **beta（乌贼版）**：朋友（乌贼）那条线，代码差别很大，**没有功能说明文档**，一律按「**版本号 + beta**」存档在 `E:\Shizuka-版本存档\beta\`，例如 `Shizuka-0.7.6beta-Windows-x64.zip`、`Shizuka-0.5.6beta-Windows-x64.zip`；包内顶层文件夹同名、**内容一字不改**。
- **新功能的来源**：拿两个 beta 之间的差异来挑要吸收什么（0.6.0 吸收了 0.5.6 的角色包与微动差分；0.7.7 吸收了 0.7.6 的全部并补回 0.7.4 的功能），吸收进正式版后按正式版流程发版。所以 beta 包不要改动内容，否则 diff 会混入噪声。
- 乌贼那条线目前没接 git；如果他愿意往正式版仓库推一个分支，再改成按分支管理。
- 注意：`更新公告.md` 里的 `## v0.7.6beta` 一节描述的是**合并基线**（乌贼那版带来的东西），我们正式发布过的版本只有 0.7.0 / 0.7.3 / 0.7.4 / 0.7.7 / 0.8.0。

### 更早（0.7.4 及以前）

聊天/记忆/待办/剪贴板/开机问候/提示音三态/底部三按钮/拖动折叠/位置缩放记忆/对话记录；0.7.0 起加入更新公告与自动更新；0.7.2 天气新增国内源；0.7.3 更新走镜像 + token 余额 + GPT-SoVITS 自动配置。

---

## 七、未解决 / 待验证

- **研究进展整体禁用**：这个功能朋友那边也确认还没完全做好，所以先关掉了。开关在 `assistant_features.RESEARCH_ENABLED = False`：菜单显示「研究进展（开发中）」，点了只回一句提示；`_research_loop` 不再排期、不自动检查、不主动播报；聊天里被路由到 `research` 也只会得到「还在开发中」。代码（`research_watch.py` + `_research_*`）都还在，改回 `True` 即可恢复。
- **没有角色选择器**：`character_packs.selected_pack()` 会读 `settings.json` 的 `character_pack`，但最后**固定返回 `shizuka-side-motion`**（注释写明「one fixed identity and no character picker」）。`characters/shizuka-classic` 还留在磁盘上但选不到；如果以后要做切换，得把那个返回值改回 `chosen`。
- **Responses API 未接**：`api_mode` / `_responses_via_chat` 在 0.7.4 有，0.7.6 重构后没移植。方案已确认：在 `api_runtime.configure_client` 里按 `api_mode` 分流，`_responses_via_chat` 用非流式 `responses.create` 包成「假流」；**DeepSeek 的 `/responses` 实测 400 + 偶发空，必须记住不支持并退回 chat**；带图片的消息要把内容转成 `input_text`/`input_image`。
- 翻译只对 `foreign` 生效（拉丁字母 ≥12 且远多于汉字），`hello world` 这类短英文不翻译，阈值可放宽。
- 圆角用色键透明实现，系统关「透明效果」时四角可能显黑。
- 落窗口上（试验）：自定义边框窗口边缘可能有几像素偏差。
- 头部是平面旋转，没有立体转头；**未完成 Live2D Cubism 的 cmo3/moc3 绑定**。
- 唱片的封面提取只支持 ID3v2 的 APIC 帧；背景音乐走 MCI `mpegvideo`，个别声卡对 `setaudio` 音量响应不准。
- 天气/新闻/更新都依赖网络：GitHub 直连被墙时靠镜像，镜像也可能失效。

---

## 八、改代码注意事项

- **不引入未确认的新依赖**；遵循现有风格，改动尽量小。
- 跨线程不要直接碰 Tk，走 `_ui`/`_poll_ui`。
- 写含中文的脚本/文档注意编码；本机 PowerShell 5.1 按 GBK 处理中文路径，含中文文件名用 Python 处理。
- 删文件走回收站；替换 EXE 前先停掉正在运行的实例。
- 改完源码**不会影响已打包的 EXE**，要重新构建。
- 版本号只在 `src/app_identity.py` 改一处；改完记得同步 `更新公告.md` 和 `version.json`（`tools/make_release.py` 会处理后者）。

---

## 九、构建环境与凭据

- 依赖锁定见 `src/requirements-win-py314.lock`（本项目实际用 Python 3.13 构建）；`LICENSES/build-versions.json` 记录构建环境。
- 发布前跑 `python tools/make_release.py` 重生成 `MANIFEST.json`，再用 `python verify_package.py` 校验；`VERIFICATION.json` 记录版本、单测数、离线验收项数与审计结果。
- 审计要求：**Key 不应出现在日志、ZIP、仓库或截图里**；发布前扫一遍 `sk-`、`Bearer`、本机路径、`data/` 是否泄漏。
