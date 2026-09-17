

# Shizuka 桌宠 · AI Development

> 给 AI / 开发者看的**自包含**交接文档 + 开发约定：程序是什么、怎么跑、怎么改、每个功能怎么实现的、还有什么没解决。
> 相对路径都以解压目录为根。上一版本文档对应 V0.6.0，架构已在 V0.7.6 全部模块化，本文按 0.8.0 重写。

---

## 零、速览与开发约定

- **入口与模块**：入口 `src/run_pet.py`，主体 Tkinter/Pillow；功能分在 `computer_*`、`weixin_*`、`todo_*`、`conversation_*`、`memory_maintenance`、`research_watch`、`sync_*` 等模块。`app_identity.py` 管名称/版本，`characters/` 管角色卡与渲染配置。
- **运行 / 构建 / 测试**：建议 Windows x64 Python（依赖见 `src/requirements-win-py314.lock`）：建 `.venv`、装依赖、`python src/run_pet.py`。独立构建另需 PyInstaller，`python tools/build_windows.py`；测试 `python tools/run_tests.py`；EXE 离线验收 `Shizuka.exe --self-test --report <绝对JSON路径>`（自动用临时数据目录）。
- **文件执行**：走 DSH headless profile + 本次 overlay，`src/shizuka-dsh-bridge.mjs` 监听公开文本与工具事件并接入原生 ask_user_question；**没有换成另一个文件执行器，也不改 DSH 全局 profile**。思考等级由 `agentDefaultModel` 继承，本包不锁定最高等级；不记录、不展示内部 reasoning-delta。保留工具失败、取消和不确定状态，**不能仅凭进程退出就捏造任务成功**。
- **上下文与记忆**：对话上下文最多 100 条 / 48000 字符，完整 JSONL 归档不裁剪。`source` 说明与自动摘要**不是**实际对话；摘要/事实审阅只收「带用户原话来源的稳定事实」，不能把助手主动推测变成用户事实。
- **待办**：核心 `text/due/on_boot/done` 走 sync journal，`due` 是下一次实际提醒时间；`todo-details.json` 存备注/分类/周期/提醒渠道与投递状态。跨端适配要区分「应共享的备注/周期」与「端侧送达状态」，**不能把旁表跨端覆盖**。用途只有生活、研究。
- **同步**：签名 journal + 独立设备身份 + 幂等事件 + 冲突记录；默认每 10800 秒轻量检查，走文件队列。`sync_client.py` 可单独跑资料库界面。本包不含任何能连到既有设备的配对资料。
- **研究进展**：方向由用户在窗口里输入（回车确认，`research-profile.json` 的 `topics`/`queries`），靠 Crossref 公共元数据筛选；论文原文与来源只作数据、不能当执行指令；保留原刊名；无摘要时只能据题名评论，不能编造实验结果。中文方向会自动配一条英文检索词（`query_for` 映射），因为 Crossref 对英文摘要覆盖好得多（实测中文查询「偏微分方程数值解」50 篇命中里 0 篇有摘要，英文 35 篇里 19 篇有）。
- **动作系统**：支持原始层、可选 `expression_frames`/`body_frames`/`activity_frames` 和 `question_effect`；没有新活动图时走既有静香姿态，别把缺失差分说成真实 3D / Cubism；普通图与活动全身图不能随意叠加眼嘴。
- **本包性质**：由当前功能源码单独构建，**不继承任何个人运行资料**。发布时重新核验全部源码、资源、EXE 内代码、依赖缓存与压缩包，勿拷贝本机 `data`、凭据、聊天或调试会话。

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
| `AI-DEVELOPMENT.md` | 本文件：给 AI / 开发者的技术交接与开发约定 |
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
| `src/research_watch.py`、`assistant_features.py` | 文献筛选（关注方向输入、检索、阅读、聊天汇报）与「更多设置」二级菜单 |
| `src/paper_reader.py` | 读复制来的论文链接：DOI→Crossref、arXiv→摘要页、普通网页→citation_* 元数据与正文摘录；读不到只回理由 |
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
- **称呼**：`load_persona()` 把 `dialogue_style.ADDRESS_STYLE` 拼在**角色卡之后**——静香只说「你/您」，不喊「主人」，也不自称女仆；用户的角色卡是从别处拿来的女仆设定时，这条规则压在卡上面（`tests/test_research_chat.py::AddressTests` 守住）。`dialogue_grounding.GROUNDING_RULES` 里原来那句「自然需要时称主人」已删掉，提醒/待办/文献提醒这些**预制文案**里也不再有「主人」。

### 3. 记忆

- `data/characters/<角色>/memory.json`，`MemoryStore`（带锁）。显式「记住 X」→ 模型解析保留原文 → 永久记忆；未明说时模型判断是否值得长期记。检索优先本地语义检索，回退关键词重合，按相关度注入。
- **记忆只增不删**：`MemoryStore.clean()` / `dedup()` 都是空操作（只 `normalize()`），不做按时间/概率/条数的淘汰；`find_similar()` 只在 strip 后**完全相同**时判定重复，不做「互相包含 / 字面重合度很高」的合并（会把不同的事误并成一条）。`memory-review.json` 记录哪些旧对话已审阅，避免重复刷记忆；`topics` 只是索引，不删原记录。

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

- `weather.py`：`_geo_ip()` 按顺序尝试**全部 HTTPS** 的免费定位源——pconline（国内、GBK）→ `api.vore.top/api/IPdata`（国内、中文省市）→ ipwho.is（国外、英文城市）；以前的明文 `http://ip-api.com` 已去掉（它的免费端点不支持 HTTPS，实测 `https://ip-api.com/json/` 返回 403 `SSL unavailable`）。国内源放最前是因为国外源会跟着梯子出口走（实测本机被 ipwho.is 判成 Tokyo，pconline 正确给出四川成都）。`_net_mode()` 探测外网是否可达并**缓存 30 分钟**（`_NET_MODE_TTL`），中途开关梯子不必重启。外网可达走 Open-Meteo（地理编码 + 当前/未来三天），否则走中国气象局 `weather.cma.cn`，两边互为兜底。WMO 天气码用 `_WMO_ZH` 转中文。
- **天气取不到时按原因直说，不猜城市**：`_cma_station()` **只接受精确匹配**，否则返回 None（以前会退回「第一个候选」，把同名地名的天气静默安到用户头上）；地名变体只用 `_name_variants()`（原样、去「市/省」后缀），**刻意不剥「区/县」**——否则北京的「朝阳区」会剥成「朝阳」撞上辽宁朝阳市。`weather_report(detail)` 返回 `{city,text,source,reason}`，`reason ∈ {'', no-location, no-match, no-network}`：开机问候拿不到天气就退化成不带天气的普通问候（`_greeting_weather()` 返回 `''`），主动提问则按 reason 播 `dialogue_style` 里的 `weather_no_location / no_match / no_network`（角色包可覆盖）。
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

- **电脑助手**：`/电脑 <任务>` 或明确文件指令 → 本机 DSH（headless profile + 本次 overlay，`src/shizuka-dsh-bridge.mjs`）。进度窗只读，需要确认的问题回到聊天里问。配置在 `data/computer-assistant.json`（工作文件夹、Node 路径、dsh bin.js、操作范围、任务模型）。**任务没跑成时会写 `data/computer-tasks/<id>/failure.log`**（任务内容、使用模型、最近 40 条事件、stderr 末尾），并在 `data/error.log` 留一行索引——用户常不在电脑前，事后看日志即可。
- **微信**：`weixin_channel` 负责协议与收发，`weixin_ui` 负责扫码/设置；支持对话、识图、`/图片`、`/电脑` 等远程指令，待办提醒也可走微信。绑定状态存 `data/weixin-state.json`。图片按天编号存到工作区 `微信图片/`，指代用「图N」（支持中文数字）；**没指定图片时带最近 2 张（10 分钟内），本条消息自带的图片全带上（最多 3 张）**；聊天分支会把图转 data URL 直接附给模型（按路径缓存 10 分钟），所以「讲下图3」「那第二问呢」都能看图回答。序号按天重置、索引只留最近 50 条，`resolve()` 会跨天回退到「最近一次用过这个序号」的图——**这时 `ImageIndex.note_for()` 会在给模型的提示里写明「不是今天收到的，下面是 9月16日 的图」**，免得模型默默照着另一张图回答。去重记录 `seen` 按**时间**保留（`SEEN_TTL_SECONDS=30 天`，另有 `SEEN_MAX=10000` 硬上限），不再只按 2000 条 FIFO 淘汰。
- **研究进展**：`research_watch` 按 `data/research-profile.json` 的 `queries`（检索词，最多 6 条，`fetch_candidates` 只用前 6）检索 Crossref，`topics`（用户原话）给模型判断相关性；模型按摘要判断相关性，缺摘要时只依据题名评论，不编造结论。窗口里：输入框回车/「添加并检索」→ 立刻 `_research_check(force=True)`；标签点 × 取消关注（`_flow_layout` 用 place 按算好的坐标排，一行放不下自动换行——grid 的列宽是整块共用的，第二行更宽的标签会把第一行顶出窗口；`pack(in_=…)` 只算几何不真画，别用）；「从最近对话猜方向」读最近 40 条消息让模型给候选（只提议，点了才加）；点结果标题看公开摘要与 DOI、点「让静香讲讲这篇」按摘要讲一遍（无摘要时明说只能凭题名推测）。`query_for` 记录「中文方向 → 英文检索词」的映射；去掉「区/县」式的过度翻译没有意义，但**不要**把 `queries` 当成用户可见的方向列表——界面显示的是 `topics`。
  - **聊天里问进展**：`intent_routing.research_question()` 本地先认「最新进展 / 最近有什么新论文 / 有没有新文献」（≤30 字、不带「这篇/刚才」这类指代、不是「怎么查…」的方法问题），命中直接给 `action=research`；没命中的靠 `router_prompt` 的 research 意图，所以闸门正则里要有「进展」。`_route_intent` 的 research 分支现在调 `_report_research()`：先 `say()` 汇报手上的结果（题名用《》包起来，朗读时会各占一轮气泡），再 `_research_check(force=True, notify="chat")` 补查一轮，有新发现的照常播报（`notify="chat"` 时不受「主动提醒」开关限制，因为是用户主动问的）。
- **复制论文网页 → 讲解**：`paper_reader.read_paper()` 统一返回 `{title,journal,date,authors,abstract,text,source,readable,reason}`。DOI 走 Crossref（无摘要或摘要太短才去抓页面），arXiv 的 abs/pdf 链接统一换成摘要页（**arXiv API 对本机请求返回 406，别指望它**；PDF 链接先换摘要页、真正的 `.pdf` 不下载），普通网页抽 `citation_*` 元数据 + 正文；`clean_body()` 丢掉导航短行（arXiv 摘要页的「正文」几乎全是导航）。读不到时只给理由（`pdf/no-network/not-found/blocked/not-paper/paywall/title-only`），由 `failure_line()` 说人话，**绝不猜内容**。剪贴板路由在 `pet._clip_route()`：图片文件 / 图片直链 / `paper` / 普通网页 / 图片路径 / 普通文本（纯 DOI 号也算 `paper`，限 200 字以内），`_read_clip_paper()` 抓完开「文献窗口」并把讲解同时念出来。
- **同步**：`sync_runtime/sync_client/sync_store/sync_transport/sync_rustdesk/...` 用签名 journal、独立设备身份、幂等事件；默认每 3 小时（`memory_interval_seconds`，60~604800 秒）轻量检查，另有手动同步。`SyncStore` 现在有**压实**：`compact()` 把当前状态写成快照表、并把已压实的事件搬进 `events_archive` 冷表，本地读只回放「快照 + 基线之后的热事件」；`bundle()`/`conflicts()` 仍读**完整历史**（热表 ∪ 归档表），所以信封格式没变、对端不缺历史、冲突检测也不退化。`SyncBridge` 每 200 次提交检查一次（`maybe_compact()`，阈值 `COMPACT_AFTER_EVENTS=5000`），失败只记在 `status()['compact_error']`、不影响保存。实测 2 万条记录 `rows()` 从 221ms 降到 48ms。

### 12. 线程 / 锁 / 设置 / 凭据

- 后台线程统一经主线程队列 `_ui`/`_poll_ui` 操作 Tk。锁：`_FILE_LOCK`（文件写）、`_hist_lock`、`_chat_lock`、`_MCI_LOCKS`（每别名一把）、`_render_lock`、`get_client`/`get_memory` 双检锁。
- 设置持久化在 `data/settings.json`（`_save_settings` 写的是**显式字段字典**，新增设置项要同时改 `load_settings` 和 `_save_settings`）。
- API Key 存 **Windows 凭据管理器**（`_cred_write`/`_cred_read`，目标 `ShizukaDeskPet/api_key`；读取时 `ShizukaAssistant/api_key` 也认，兼容 0.7.6 改过的名字），**程序目录不留 Key 文件**；旧 `api_key.txt` 首次启动自动迁移并删除。
- 数据文件读坏先备份 `.bad-<时间戳>` 再重建，防清空。

### 13. 主动发言（前台程序 / 空闲搭话 / 启动问候）

- 三条触发链：`_foreground_loop`（每 45 秒看前台窗口；进程变了、距上次主动评论 ≥`PROACTIVE_COOLDOWN`=300 秒、同一进程 `FG_REPEAT_GAP`=1800 秒内不重复，再按 `FG_COMMENT_CHANCE`=10% 概率才开口）、`_idle_loop`/`_check_idle`（每 30 秒看系统空闲；到 `idle_minutes*60*(n+1)` 且距上次主动 ≥5 分钟，每段空闲最多 `IDLE_CHAT_MAX`=2 次）、启动问候（`_do_greeting`，距上次问候不足 10 分钟就跳过）。
- **方向池**：`dialogue_style.PROACTIVE_DIRECTIONS`（角色包 `dialogue-style.json` 里的 `proactive_directions` 可整体覆盖）。触发时 `_pick_proactive_direction()` 按 `weight` 随机挑一个（同一方向不连续用两次），方向 + 事实一起进 `_proactive_prompt()`。默认权重：具体观察 30 / 实用提醒 20 / 相关小知识 15 / 承接上文 10 / 轻幽默 10 / 具体提问 10 / 安静陪伴 5。
- **硬约束**：必须落到给到的具体信息（程序名 / 窗口标题 / 时间 / 最近聊过的话题），一个都落不上就返回空字符串（不说话）；禁止「哦，这是……」鉴定式起手、复述标题原文、编造与说教。
- **内容去重**：`_proactive_recent_ok` / `_proactive_remember`（`dialogue_grounding`）记住最近 20 条主动发言，新句子与最近 6 条完全重复、互相包含、或字符二元组重合度 ≥0.7 就丢弃。

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

### 2026-09-16 — 源码修复（未发版，待并入下次发版）

> 只改了源码与测试，**没有动 `APP_VERSION` / `version.json` / `MANIFEST.json`**。发版前请按第二章跑一次 `tools/make_release.py` 重生成清单（现在 `MANIFEST.json` 与 `VERIFICATION.json` 还是 0.8.1 发版时的旧快照）。

- **渲染**：`LayeredRenderer._groups()` 在 `recover + prepare` 时不再无条件取 `expression_frames['neutral']`（缺该帧的角色包会让渲染线程抛 KeyError，`_take_render` 随即永久退回静态立绘）；恢复帧的键改用 `character.json` 里作者写的 `id`，`pet_motion.recovery_phase` 与渲染器同源，不再两边各自按下标拼 `frame-N`。
- **角色包校验**：新增 `interaction_regions`（键名、四元组、方向、坐标范围）与 `sleep_effect_anchor` 校验——`pet.py` 会直接下标比较这些数字，以前写错只能等到运行时崩。
- **待办**：删除待办时一并清掉 `todo-details.json` 的旁表条目（以前只增不减）并取消在途提醒/正在显示的气泡；删除前先把未落库的 `routine_memory` 写进长期记忆。`_reminder_loop` 单轮异常改为记 `error.log` 后继续排下一轮，不再静默失败。
- **记忆**：删掉旧的 `_extract_memories`（没有 quote 接地校验的宽松路径，已无调用点），避免被误接回绕过 `memory_maintenance` 的 source/quote/stable 校验。
- **口吻**：起手语气词与「(你)又在/还在」正则只在 `dialogue_style` 定义一处，`pet.clean_reply_style` 复用同一份（以前两套规则对同一句话结果不同）。
- **缓存 / 网络**：`_MODEL_CAPS` 加上限（64，超出丢最早的）；`_EMB_CACHE` 超限改成丢最早一批而不是整表清空；`weather._NET_MODE` 加 30 分钟 TTL，中途开关梯子不必重启。
- **电脑助手**：`task_model(..., has_images=True)` 真正生效——DeepSeek 官方接口下带图任务即使选「继承 DSH 默认」也强制视觉模型（否则 `read_image` 会被路由门禁拒绝）；进度窗开始渲染 `model` 事件（以前写进 `events.jsonl` 却从不显示）。
- **更新**：`launch_swap` 写 bat 时把路径里的 `%` 转义成 `%%`（引号挡不住 cmd 的变量展开）。
- **清理**：删掉没人读取的 `_history` / `_hist_lock` / `_append_history`（`_history_max` 更名为语义明确的 `_recall_exclude_turns`）、`dialogue_bubble` 的 `_reading_until`、`CLIP_PASSIVE_SOURCES` 里不可达的 `'识图'`；`sync_transport.make_transport` 对退役的旧通道也先校验一次配置。
- **测试**：新增 `tests/test_character_pack_regions.py`、`tests/test_renderer_recover.py`、`tests/test_todo_delete_cleanup.py`、`tests/test_runtime_bounds.py`，并在 `test_task_model.py` 补「继承 + 带图」用例；单测总数 114 → 137。
- **天气（第二批）**：`_geo_ip()` 全部换成 HTTPS 源（pconline → `api.vore.top` → ipwho.is），去掉明文 `http://ip-api.com`；`_cma_station()` 只接受精确匹配、地名变体不剥「区/县」；新增 `weather_report()` 返回 `reason`，开机问候取不到天气就退化成普通问候，主动提问按原因直说（新增 3 条 `dialogue_style` 话术）。
- **微信（第二批）**：去重记录按时间保留（30 天，硬上限 10000 条）；跨天「图N」回退时在提示里写明是哪天的图（`ImageIndex.note_for()`）。
- **同步（第二批）**：`SyncStore` 增加压实（快照表 + `events_archive` 归档冷表 + `compact()/maybe_compact()`），`bundle()/conflicts()` 走完整历史、`_insert` 同时查归档表保证幂等与冲突语义不变；`SyncBridge` 每 200 次提交检查一次并暴露 `compact_error`；新增 `tests/test_weather_fallback.py`、`tests/test_weixin_retention.py`、`tests/test_sync_compaction.py`，单测总数 137 → 175。
- **保留项**：`Pose.leg_sway` 整条链（`pet_motion` 的 `leg` + `LocalMesh` 的 `leg_regions` + `character_packs` 校验）是**有意保留**的通道，朋友可能要继续做腿部动作，别当死代码删掉。
- **双端共享禁用（第三批）**：`sync_runtime.SYNC_ENABLED = False` 一个开关同时停掉菜单、后台传输与排期（`get_runtime()` 直接返回 None，待办/记忆/聊天记录退回本地 JSON）；菜单显示「双端共享记忆（开发中）」「立即同步记忆（开发中）」，点了只回一句 `SYNC_WIP_REPLY`。离线验收新增一项（9 → 10）。
- **回复长度策略（第四批）**：`PLAIN_STYLE` 第一句改成「篇幅跟问题需要的信息量匹配」——一个词/是不是/能不能这类简单问题一两句答完、不许顺带讲背景用法延伸；复杂问题或明确要求「详细讲讲」才展开；讲题、代码、技术推导不受限；拿不准先按短的答。实测同一问题 198 → 81 字，复杂比较题仍有 464 字。另加手机端提示（`weixin_ui`）。
- **公式排版（第四批）**：`PLAIN_STYLE` 要求式子独立成行、长段落空行分段、符号用 Unicode（∂ ∫ √ ² …）、下标全篇统一、禁用 LaTeX 记号（`\frac` `$…$`）、排版不许堆公式。实测最长段落 233 → 100 字符；合成测试里旧版曾整段吐 LaTeX（15 处）→ 0 处；**注意**：真实日志里 LaTeX 残留本来就只有 1 处（还是文件任务报错里的 JS 模板），所以这条主要是防御性的。
- **研究进展启用（第五批）**：`RESEARCH_ENABLED = True`，菜单去掉「开发中」，补上关注方向输入界面（回车确认）、标签删除、`query_for` 中文→英文检索词映射、从最近对话猜方向、点结果看摘要并让静香讲、检查间隔可调（1–168 小时）。离线验收的第 7 项从「功能保持关闭」改成「关键词输入/落盘/文案」的实证检查。新增 `tests/test_research_keywords.py`、`tests/test_dialogue_style.py` 扩到 13 个用例，单测总数 175 → 216。

### 2026-09-16 — V0.8.1

- **多屏窗口定位**：`pet.py` 新增 `_screen_bounds` / `_dialog_geometry` / `_place_dialog` / `_move_dialog`，所有对话框（待办、待办编辑器、对话记录、微信、电脑助手、DSH 进度、研究进展、双端同步、模型与接口、更新四窗、记忆窗、时长窗）与 `messagebox` / `filedialog` 都摆到桌宠所在显示器；`_place_dialog` 对未传尺寸的新 Toplevel 走 withdraw→update→geometry→deiconify（新窗口在 `update_idletasks` 前 `winfo_reqwidth()` 返回 200x200），传了尺寸的直接设 geometry。
- **模型统一**：模型名只在 `api_runtime.DEEPSEEK_MODEL = 'deepseek-v4-flash-vision-exp'` 定义一处，`pet.py` / `computer_agent.py` 引用，bridge 不再维护白名单；DeepSeek 官方接口下 `deepseek-chat` / `deepseek-v4-flash` / `deepseek-flash` / `deepseek-v4-pro` 归一，自定义 base 保留用户填的；电脑助手窗口新增「任务模型」下拉（跟随聊天/视觉/继承 DSH 默认）+「实际使用：xxx」。
- **电脑助手（DSH）**：bridge 兼容两版提问 API（旧 `registerProvider` / 新 Cordis waterfall `user-questions/request`），apply 不再抛错（抛错会让插件树 FIBLED 失败、任务直接崩）；提问加 30 分钟上限、失败也发 `question_cancelled`；带图任务强制视觉模型；失败写 `data/computer-tasks/<id>/failure.log` + `data/error.log` 索引。
- **微信看图/讲题**：聊天分支把图转 data URL（按路径缓存 10 分钟）附给模型（原来只发路径文字，模型「看不到图」）；「图N」支持中文数字、编号对不上时反问候选；未指定时带最近 2 张（10 分钟内）；带图消息不再一律当文件任务，只有 `/电脑` 或意图路由判成 `computer_task` 才走 DSH；截图内容等于桌宠刚说的话则只回 SKIP。
- **主动发言降噪**：前台程序 `FG_COMMENT_CHANCE=0.1` + 5 分钟冷却（没抽中不记账）；`dialogue_style.PROACTIVE_DIRECTIONS` 方向池（具体观察 30 / 实用提醒 20 / 相关小知识 15 / 承接 10 / 轻幽默 10 / 具体提问 10 / 安静陪伴 5），角色包 `characters/shizuka-side-motion/dialogue-style.json` 可整体覆盖；本地闸门丢弃「我就在这儿」类空话、最近 20 条去重、启动问候 10 分钟内跳过；提示词收紧（禁鉴定式起手、复述标题、推测句式、按时间/窗口名推断状态，天气只准用给定数据）；`clean_filler_tail()` 剪掉剪贴板反应尾巴。
- **待办与更新修复**：完成待办（含提前完成/结束周期）清 notice 并取消提醒；准点提醒（lead=0）加 600 秒宽限；「晚上12点」→次日 0 点；「停止接收更新」不再被 `_save_settings` 覆盖、bat 重启路径加引号、pending 标记移到安装之后、检查失败与「已是最新」区分显示、probe 用归一后的模型名、补 400 说明。
- **其它**：`_cancel_reply` 清语音气泡状态；`gsv_py` 兼容根目录 python；`_take_render` 记真实堆栈；`usage` 字典加锁；余额气泡用 `winfo_exists`；`recall` 不召回本轮刚落的当前消息；`load_style` / memory-review 用 `utf-8-sig`；`_MODEL_CAPS` 加锁；清掉若干死代码。
- 新增 `tests/test_weixin_images.py`、`test_task_model.py`、`test_proactive.py`、`test_dialogue_style.py`；新增离线预演工具 `tools/preview_proactive.py`、`tools/preview_dialogue.py`。
- 注：`src/file_transfer.py` 的 `status()` 被拆成两条 SQL，与原实现行为完全等价，非本轮改动。
- 清掉遗留死代码（全仓无引用、0.8.0 起就是死的）：`pet.py` 的 `detect_provider` / `get_mem` / `rounded_rect_points` / `_is_todo_query` / `_record_new_memories` / `_voice_bubble_show` / `_parse_time_desc` / `_fmt_todo_when` 与常量 `SWAY_DIZZY_COOLDOWN` / `PERSONA_DIR`（指向不存在的 `persona/`）/ `STYLE_REMINDER` / `REQUIREMENTS_FILE` / `PIN_KEYWORDS` / `DISPLAY_W` / `GREETING_THEMES` / `GREETING_IDEAS` / `IDLE_CHAT_SEC`，`sync_store.py` 的 `decode_bundle`（连 `encode_bundle` 都不存在）。
- `tools/make_release.py` 的 `package_paths()` 现在跳过 `__pycache__` 与 `.pyc/.pyo`（此前有 85 个陈旧字节码被打进发布包）。

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

- **研究进展已重新打开**：0.8.0 曾整体禁用（`RESEARCH_ENABLED=False`），现已改成 `True`，并补上了缺的那一环——**关注方向的输入界面**（原先窗口里只显示「关注方向：」后面一片空白，用户根本没法配方向）。现在流程是：输入框回车确认 → 写 `topics`（用户原话）+ `queries`（检索词）+ `query_for`（两者映射）→ 立刻检索一次。检索仍是 Crossref 按 45 天窗口筛新论文；**复制的论文网页会抓题名/摘要/正文摘录**（`paper_reader`），但**PDF 正文不解析**（`.pdf` 链接只换成摘要页，纯 PDF 直链直接说读不了）；`check_hours` 默认 6 小时、`enabled` 默认关闭（要用户勾「主动提醒」才自动查，在聊天里主动问不受这个开关限制）。
- **角色包可切换（但界面里没有选择器）**：`character_packs.selected_pack()` 会读 `settings.json` 的 `character_pack`，**指定的包存在就用它**，不存在才回退到 `shizuka-side-motion`。内置两个包的 `character_id` 都是 `shizuka`，共用同一个数据目录，换包不会换记忆/聊天/待办。要在界面里做切换器，只要写这个设置项并重启即可（`shizuka-classic` 是 `static` 渲染器，`_do_wheel_apply`/`_animate_pet` 都有 `_animator is None` 的分支）。
- **Responses API 未接**：`api_mode` / `_responses_via_chat` 在 0.7.4 有，0.7.6 重构后没移植。方案已确认：在 `api_runtime.configure_client` 里按 `api_mode` 分流，`_responses_via_chat` 用非流式 `responses.create` 包成「假流」；**DeepSeek 的 `/responses` 实测 400 + 偶发空，必须记住不支持并退回 chat**；带图片的消息要把内容转成 `input_text`/`input_image`。
- 翻译只对 `foreign` 生效（拉丁字母 ≥12 且远多于汉字），`hello world` 这类短英文不翻译，阈值可放宽。
- 圆角用色键透明实现，系统关「透明效果」时四角可能显黑。
- 落窗口上（试验）：自定义边框窗口边缘可能有几像素偏差。
- 头部是平面旋转，没有立体转头；**未完成 Live2D Cubism 的 cmo3/moc3 绑定**。
- 唱片的封面提取只支持 ID3v2 的 APIC 帧；背景音乐走 MCI `mpegvideo`，个别声卡对 `setaudio` 音量响应不准。
- 天气/新闻/更新都依赖网络：GitHub 直连被墙时靠镜像，镜像也可能失效。天气的城市识别现在是**宁可不说**：气象局站点没有精确匹配就不报天气（主动问会直说没能确认城市，开机问候退化成不带天气的问候），见「四、6」；IP 定位的三个 HTTPS 源也都可能被墙或限流。

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
