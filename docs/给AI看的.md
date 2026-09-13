# 给 AI / 开发者看的：Shizuka 桌宠 V0.6.0

> 这是一份**自包含**的技术交接文档：程序是什么、怎么跑、怎么改、每个功能怎么实现的、更新了什么、还有什么没解决。
> 相对路径都以解压目录为根。

---

## 一、这是什么

一个 Windows 桌面宠物（Tk + Pillow）：角色是《World Dai Star》的静香，待在桌面左下角，支持聊天（任意 OpenAI 兼容接口，默认 DeepSeek）、记忆、待办提醒、剪贴板反应、开机问候、角色包切换、鼠标互动，以及背景音乐「i wanna」。

- 语言/运行：Python 3.13 + Tkinter + Pillow + pystray + openai；用 PyInstaller 打成 `Shizuka.exe`（onedir，旁边 `_internal/`）。
- 无控制台窗口（`--windowed`），崩溃写 `data/startup_error.log`。
- 单实例：Windows 命名互斥体 `Local\ShizukaDeskPet_SingleInstance`。
- 版本常量：`src/pet.py` 顶部 `APP_VERSION = "0.6.0"`。

### 目录结构

| 路径 | 说明 |
| --- | --- |
| `Shizuka.exe` + `_internal/` | 打包好的可运行程序（PyInstaller onedir） |
| `src/` | 完整 Python 源码（见下） |
| `characters/` | 角色包（正式：`shizuka-side-motion` 微动版、`shizuka-classic` 单图版） |
| `assets/` | 图片/音频（`i_wanna.mp3`、`reminder.wav`、`voice_ref1.wav`、图标、`bubble/`） |
| `voice_model/` | 训练好的「喜多郁代」音色模型（`.ckpt` + `.pth`，约 328MB）+ `说明.md` |
| `experiments/` | 试错素材归档，**不参与运行时扫描** |
| `tools/` `tests/` | 构建脚本、回归测试 |
| `references/` `LICENSES/` | 参考资料与第三方许可 |
| `data/` | **运行数据（首次运行自动创建；本包不含）** |
| `启动桌宠.bat` / `预览动作.bat` / `源码启动.bat` | 启动脚本 |

---

## 二、运行、构建、测试

- **运行（用户）**：双击 `Shizuka.exe`。程序按 `sys.executable` 的目录找 `assets/`、`characters/`、`data/`（frozen 时 `ROOT_DIR = dirname(sys.executable)`）。
- **源码运行**：装好含 Tcl/Tk 的 Python 与 `src/requirements.txt` 后运行 `源码启动.bat`；`run_pet.py` 是入口（捕获启动异常 → `data/startup_error.log` + MessageBox）。
- **构建**：`tools/build_release.py`（PyInstaller onedir + 显式收集 `assets/`/`src/` + 审计凭据与个人数据）。命令等价于：
  ```
  python -m PyInstaller --noconfirm --windowed --onedir --name Shizuka \
    --icon assets/pet_icon.ico --paths src --paths tools \
    --hidden-import pystray._win32 --collect-all openai --copy-metadata pystray \
    src/run_pet.py
  ```
  构建环境（本项目实测）：Python 3.13 + pillow 12.3.0 / pystray / openai 3.13.0 / PyInstaller 6.22.x。
- **测试**：`python -m unittest discover -s tests -p "test_*.py" -v`；`tests/smoke_windows.py`（用临时数据，不调真实 API）。
- **改代码不会改变已打包的 EXE**，必须重新构建。

---

## 三、代码入口与职责

| 文件 | 职责 |
| --- | --- |
| `src/run_pet.py` | 入口：错误日志、单实例、`--preview`、`--self-test` |
| `src/pet.py` | 主程序（约 7200 行）：Tk 窗口、鼠标事件、聊天/API、记忆、待办、剪贴板、问候、音乐/唱片、设置 |
| `src/character_packs.py` | 角色包校验、路径越界限制、正式列表与默认选择 |
| `src/pet_motion.py` | Pose、弹簧/单摆、持续抚摸、双跳、提起/下落状态 |
| `src/pet_triggers.py` | 动作触发、空闲、冷却、主动/自动来源 |
| `src/local_mesh.py`、`src/layered_renderer.py` | 局部网格变形、表情覆盖、zzz、Windows 色键透明 |
| `src/pet_ground.py` | 窗口重力、回弹、任务栏脚底定位（含负坐标副屏） |
| `src/pet_surfaces.py` | 只读枚举窗口几何、Z 序、PID；筛选下方可见上沿 |
| `tools/preview_character.py` | 与正式程序一致的鼠标互动离线预览 |

---

## 四、关键功能实现

### 1. 角色包与渲染

- 角色包在 `characters/<id>/character.json`（`renderer: layered` 或 `static`），人设在同目录 `persona.json`（SillyTavern Character Card V2）。`character_packs.discover_packs()` 扫描，`selected_pack()` 按 `data/settings.json` 的 `character_pack` 选。
- 微动版角色包是**分层 PNG 局部网格**：`layered_renderer.LayeredRenderer` + `local_mesh.LocalMesh` 做头/发梢/下半身变形，闭眼/说话/撇嘴/下落嘴型用局部覆盖贴片（在同一张立绘上做轻微差分/微动）。
- **透明是色键（chroma-key）**：`TRANS_COLOR = "#000001"`，`render_display()` 把 alpha 阈值化后填色键；`set_window_transparent()` 设 `-transparentcolor`。所以**不是真 alpha**（色键区自动穿透点击）。整体淡入淡出用窗口属性 `-alpha`（与色键可共存）。
- 性能：`_RenderWorker` 后台线程渲染最新姿态，主线程只取成品帧；`_groups` 基础组按高度缓存 + 动态小补丁每帧叠加；拖动时把「下半身拉伸 + 整体摆动」折进网格一次变换。

### 2. 聊天

- `DeskPet._ask_model()`：`system = load_persona() + CHAT_STYLE_HINT`（+ 相关记忆块），带最近 `history_max` 轮历史，历史后插一条 `STYLE_REMINDER`，再发用户消息；流式生成，边生成边按句合成/显示。
- `load_persona()` 读当前角色包的 `description + system_prompt + mes_example`，末尾追加 `KOKONA_RESTRAINT`（少提心菜）。
- **口癖兜底**：`clean_reply_style()`（模块级）用正则去掉回复**开头**的语气词起手（哦/噢/喔/嗯/呃/诶/欸/唉/哎/呵呵…）以及紧随的第一句句尾语气词；「哎呀/哎哟」等有负向保护。它被接在 `_ask_model` 的流式显示、`_stream_update`、`_stream_finish`、`_play_reply`、`say()`、`_translate_clip` 的点评上。函数幂等，喂回模型的历史也是清理后的。
- 人设改动**实时读取**，改完下一条即生效；卡片缺失回退 `DEFAULT_PERSONA`。

### 3. 记忆

- `data/memory.json`，`MemoryStore`（带锁）。显式「记住 X」→ 模型解析保留原文 → 永久记忆；未明说时模型判断是否值得长期记。
- 检索：优先本地语义检索 → **回退关键词重合**；按相关度排序注入（上限约 15 条，永久轻微加权）。启动时清理过期（25 天未引用按 30% 概率删）+ 模型合并近义重复。

### 4. 待办 / 提醒

- `data/todos.json`。是否待办由模型分类（`_classify_intent` → `_route_intent`）；时间必须落到具体钟点，模糊则追问并弹输入框；相对时间（「2 小时后」「3 天后」「20s」）**本地直接算**。`_reminder_loop` 每 20 秒检查到期；开机类在启动时触发；折叠时只发声、下次打开补说。

### 5. 剪贴板

- `_clip_loop` 每 1.5 秒查 `GetClipboardSequenceNumber`；仅对启动后的新内容反应。路由：图片文件路径 → 识图；网址 → `fetch_page_text`（`http_get` 会解 gzip/deflate）→ 概括；失效路径 → 试取图；外语 → `_translate_clip`；否则 `_react_clip`。这些被动反应 prompt 都明确「别一上来就鉴定/复述这是什么」。剪贴板内容**不当指令**、不设待办。

### 6. 开机问候 / 新闻

- `_gen_greeting`：概率 **35% 天气 / 35% 前台窗口 / 10% 暧昧 / 20% 新闻**；新闻取 `https://60s.viki.moe/v2/60s`；取不到退回普通主题。聊天里问新闻走 `_news_worker`。

### 7. 背景音乐「i wanna」与旋转唱片（V0.6.0 新增）

- **音频**：`assets/i_wanna.mp3`；`MUSIC_ALIAS = "deskpet_bgm"`，用独立 MCI 别名播放（与提示音互不打断）。`_mci_music_play/pause/resume/stop/mode` 是模块级函数；音量 `MUSIC_VOLUME = 850`（0–1000）。
- 状态机在 `DeskPet`：`_music_state ∈ {stopped, playing, paused}`；`_music_play/pause/resume/stop` + `_music_poll`（每秒查 MCI `status mode`，自然播完自动回 stopped）。
- **菜单**：`show_menu` 里 `_add_menu_music()` 按状态显示「播放 i wanna」或「暂停播放/结束播放」或「继续播放/结束播放」。
- **唱片外观**：`extract_mp3_cover()` 解析 ID3v2 APIC 取封面（无封面用深色兜底）；`make_vinyl_image()` 裁圆 + 中间挖小圆孔（4× 超采样抗锯齿）；`_rgba_to_key()` 转色键图。唱片窗口是独立 `Toplevel`，`-alpha` 做淡入淡出。
- **位置**：`_place_vinyl()` 读齿轮按钮实际坐标，排在**齿轮正下方**、与按钮列对齐、直径 = `_btn_size`；`_start_vinyl_follow()` 每 40ms 跟随角色移动/缩放，角色隐藏时一起收起。
- **旋转**：`_vinyl_spin()` 每 `VINYL_FRAME_MS=50` 转 `VINYL_SPIN_DEG=1.1°`；`_music_state=="playing"` 才转。
- **交互**：唱片 label 绑 `<Button-1>/<ButtonRelease-1>`——`_vinyl_press` 起 3 秒定时器；到点 `_vinyl_long_press()` → `_music_stop()`（淡出）；提前松手 `_vinyl_release()` → 播放则暂停、暂停则继续。相关常量在 `pet.py` 顶部 `VINYL_*`。

### 8. 提示音 / 音量

- `play_sound` → 后台线程 `_mci_play(path, "deskpet_snd", wait=True, volume=SOUND_VOLUME)`；提示音与音乐音量统一 `850/1000`（全声音 −15%）。MCI `setaudio <alias> volume to N`，0–1000。
- 三态设置：所有消息 / 仅待办 / 无（`_should_sound`）。菜单下栏「测试提示音」。

### 9. 语音朗读 / GPT-SoVITS 自动检测

- 应用本身保留语音能力（`VOICE_ENABLED = True`）。是否可用取决于**本机有没有装 GPT-SoVITS**：
  - `gsv_dir()` / `gsv_available()` / `gsv_py()`（模块级）自动寻找安装目录：先看环境变量 `GSV_DIR`/`GPTSOVITS_DIR`/`GPT_SOVITS_DIR`，再看 `settings.json` 的 `gsv_dir`，再在常见根目录（各盘根、桌面/文档/下载）下找 `*GPT-SoVITS*`；判定标准是「目录里有 `runtime\python.exe`（或 `python.exe`）**且**有 `api_v2.py`」。
  - 找得到：`_voice_on = settings["voice"] and VOICE_ENABLED and gsv_available()`，设置菜单里「语音朗读」是正常开关；打开时后台拉起 TTS 服务（`_ensure_tts_server`，端口 9880），并自动拉起语义服务（`_ensure_emb_server`，9881）。
  - 找不到：`_voice_on` 恒 False；菜单「语音朗读」行灰显提示「未检测到 gpt-sovits，语音功能暂时无法使用（点此指定目录）」；点击弹目录选择框（`_pick_gsv_dir`），选中有效目录后写入 `settings.json` 的 `gsv_dir`（`set_gsv_dir` + 缓存）即可用。
- **参考音色随包**：`assets/voice_ref1.wav` + `voice_ref1.txt`（约 0.5MB），用户装了 GPT-SoVITS 就能直接用，不用自己找音色。**GPT-SoVITS 本体约 14GB，不随包发布**。
- **训练模型也随包**：`voice_model/`（喜多郁代 `.ckpt` + `.pth`，约 328MB，v2ProPlus），配合 GPT-SoVITS 的 `tts_infer_pet.yaml` 使用；用法与来历见 `voice_model/说明.md`。
- 相关实现：`_tts_synth`（调 9880 合成）、`_speak`/`_speak_stream`/`_tts_enqueue`/`_tts_producer`/`_tts_loop`（生产者-消费者流水线）、`_voice_type_*`（文字按朗读时长逐字）、`_preheat_tts`、`_startup_gate`（未就绪先显示「语音服务加载中…」）、`_trim_wav_silence`。

### 10. 线程 / 锁 / 设置

- 后台线程统一经主线程队列 `_ui`/`_poll_ui` 操作 Tk。锁：`_FILE_LOCK`（文件写）、`_hist_lock`、`_chat_lock`、`_MCI_LOCKS`（每别名一把）、`_render_lock`、`get_client`/`get_memory` 双检锁。
- 设置持久化在 `data/settings.json`（`_save_settings`）；API Key 存 **Windows 凭据管理器**（`_cred_write`/`_cred_read`/`_cred_delete`，目标 `ShizukaDeskPet/api_key`，系统加密、绑定当前用户），**程序目录不留 Key 文件**；旧版 `api_key.txt` 首次启动自动迁移进凭据管理器并删除（`_migrate_api_key` / `_read_legacy_key_file`）。数据文件读坏时先备份 `.bad-<时间戳>` 再重建，防清空。

### 11. 开机自启 / 周期提醒 / 使用时长 / 自动更新

- **开机自启**：`autostart_command()` / `is_autostart_on()` / `set_autostart(on)` 读写注册表 `HKCU\...\Run` 下的 `ShizukaDeskPet`；菜单「开机自动启动」开关。
- **周期提醒**：数据存 `data/recurring.json`（`self.recurs`）；`freq` = daily / weekly / workday，`time` = `HH:MM`，`weekday` = 0-6（周一=0）。识别：`_classify_intent` 出现「每天/每日/每周/每星期/工作日」→ `action=add_recurring`，`_handle_add_recurring` 落库（缺内容/时间会追问，走 `self._pending_recur`）。触发：`_reminder_loop` 每 20 秒调 `_check_recurs()`，到点且当天未触发则提醒（错过超过 4 小时不再补）；`_parse_hhmm` 解析「9点/下午3点半/09:00」。
- **待办窗口双页签**：`show_todos` 里「待办 / 周期待办」两个页签（`_show_todo_tab` 切换 `_todo_page`/`_recur_page`）；周期页 `_build_recur_rows` 可编辑内容/频率/时间/星期、暂停、删除。
- **使用时长统计**：`data/usage.json`（`{"days": {日期: {exe: 秒}}}`，保留最近 14 天）。`_usage_loop` 每 5 秒采样一次前台程序（`get_foreground_app`）累加时长；`_system_idle_seconds()` 连续无键鼠超过 `USAGE_AWAY_MIN`（默认 5 分钟）时视为**离开、暂停统计**，但若 `_audio_peak()` 检测到正在放音频（看视频/听歌）则不算离开。面板：菜单「时长统计」→ `show_usage()`（各应用时长条形图 + 合计，底部可改离开阈值并写入 `settings.json` 的 `usage_away_min`）。日报：`_maybe_daily_report()` 在 `_foreground_loop` 里小概率触发一次「今天你都在忙什么」小总结（当天一次、需累计 ≥20 分钟）。
- **自动检查更新**：`check_latest_release()` 读 GitHub 仓库 `UPDATE_REPO` 的最新 **Release**，与 `APP_VERSION` 比较；启动后台检查一次。菜单「检查更新」正常显示「已是最新版本咯~」、有更新显示「·有更新·」；**左键**检查/更新（点击弹窗显示 Release 说明，确认后 `_download_and_update()` 下载 zip、解压，生成 `.bat`：等本进程退出 → `robocopy /E /XD data voice_model experiments /XF api_key.txt` 覆盖 → 重启 → 清理），**右键** `_confirm_toggle_update()` 可停止/重新接收更新（存 `settings.json` 的 `update_disabled`，禁用后该行显示「已禁用更新」、启动不再检查）。
  - **更新包**：Release 附件优先选名字带 `update` 的 zip（`tools/make_update_zip.py` 生成，排除 `voice_model`/`data`/`experiments`，约 70MB），这样更新不会重下 328MB 音色模型、也不会覆盖用户数据；找不到才退回第一个 zip。
  - **注意**：更新提示只跟 **GitHub Release** 有关，普通 commit 不会触发；要发新版就建一个带 tag 和 zip 附件的 Release。

---

## 五、数据文件

| 文件 | 内容 |
| --- | --- |
| `data/settings.json` | 功能开关 + 位置/缩放/接口配置 |
| `data/memory.json` | 记忆库 |
| `data/todos.json` | 待办 |
| `data/对话记录/对话记录.json` + `YYYY-MM-DD.md` | 对话记录（私人数据） |
| `data/startup_error.log` / `data/error.log` | 启动/回调错误 |

---

## 六、更新说明（版本历史）

> 版本号规则 `X.Y.Z`：大功能进中间位，小优化/修复进末位。

### 2026-09-13 — V0.6.0（合并版）

- **角色包与微动差分**（来自朋友的 0.5.6 大改版）：新增 `characters/` 角色包机制（`shizuka-side-motion` 微动版 + `shizuka-classic` 单图版），模块化拆分 `layered_renderer`/`local_mesh`/`pet_motion`/`pet_triggers`/`pet_ground`/`pet_surfaces`。
- **鼠标互动**：左键拖头抚摸、右键拖动提起/落下、左键单击聊天、双击跳两下、滚轮缩放、空闲打盹；新增「落在窗口上（试验）」、动作面板、角色切换。
- **性能**：拖动从 ~17fps 提到 ~60fps（网格折叠变换、基础组缓存、动态补丁、后台渲染线程、姿态量化跳过重绘、待机单核 ~12%）。
- **新增背景音乐「i wanna」**：设置菜单播放/暂停/继续/结束；齿轮下方显示**旋转唱片**（歌曲封面裁圆 + 中心挖孔），单击唱片暂停/继续，长按 3 秒结束，播放淡入、结束淡出。
- **修复聊天口癖**：模型老爱用「哦，……啊」「呵呵」起手；提示词压不住，改为在输出侧加确定性兜底 `clean_reply_style()`，对所有回复统一去起手语气词（含历史喂回也清理，减少自我模仿）。
- **音量统一**：提示音/音乐统一降到 85%（`850/1000`）。
- **语音朗读改为「自动检测」**：应用保留语音能力，启动时自动寻找本机 GPT-SoVITS；装了就能用（参考音色随包），没装则菜单显示「未检测到 gpt-sovits，语音功能暂时无法使用」，可点击手动指定目录，不影响其他功能。GPT-SoVITS 本体约 14GB，不随包发布。
- **新增开机自动启动**：菜单开关，写注册表 Run 键。
- **新增周期提醒**：识别「每天/每周/工作日」类文本 → 定期提醒；与待办同窗口、分「待办 / 周期待办」两个页签，可编辑频率/时间/星期。
- **新增使用时长统计**：每 5 秒采样前台程序累计时长；连续无键鼠超过阈值（默认 5 分钟、可调）且无音频播放时视为离开、暂停统计；菜单「时长统计」打开面板查看今日各应用时长；小概率触发「今天你都在忙什么」小日报。
- **新增自动检查更新**：启动后台检查 GitHub Release，菜单显示「已是最新版本咯~」或「·有更新·」，点击可下载并自动替换、重启。

### 2026-09-12（0.4.x 收尾）

- 新增「设置 API Key」居中窗口 + **Windows DPAPI 加密**存储 + **服务商自动识别**。
- 修复滚轮缩放卡顿/黑边（bytearray + BOX/BILINEAR + 事件合并 + 延后写盘）；修复窗口「先闪一下」（去掉重复事件绑定、去掉不可靠的 `-alpha` 淡入）。
- 剪贴板增强：图片文件路径 → 识图；网址 → 抓网页概括（修 gzip 解压）；翻译支持日/韩。
- 待办/记忆健壮性：读坏先备份再重建、全程加锁、id 改 uuid、相对时间本地算。
- 新增空闲主动搭话、随机新闻、前台感知；开机问候概率调整 35/35/10/20。

### 2026-09-11（0.4.x）

- 首次搭起：DeepSeek 聊天、流式输出、多轮上下文、记忆系统、待办提醒、剪贴板检测、开机问候、提示音三态、底部三按钮（待办/对话/设置）、拖动折叠、位置/缩放记忆、对话记录持久化。

---

## 七、未解决 / 待验证

- 语音朗读依赖本机 GPT-SoVITS（约 14GB，需 NVIDIA 显卡）；未安装时功能不可用（菜单会提示），参考音色已随包。
- 落窗口上（试验）：自定义边框窗口边缘可能有几像素偏差，靠 `GetWindowRect` 与 Tk DPI 坐标一致性缓解；欢迎实测。
- 头部是平面旋转，没有立体转头；点头/摇头/甩发梢/晃腿因不自然已停用；**未完成 Live2D Cubism 的 cmo3/moc3 绑定**（分层 PSD 供继续制作）。
- 双端记忆同步未启用。
- 唱片的封面提取只支持 ID3v2 的 APIC 帧；无内嵌封面时用深色兜底圆盘。
- 背景音乐走 MCI `mpegvideo`，个别声卡驱动对 `setaudio` 音量响应可能不准。

---

## 八、改代码注意事项

- **不引入未确认的新依赖**；遵循现有风格，改动尽量小。
- 跨线程不要直接碰 Tk，走 `_ui`/`_poll_ui`。
- 写含中文的脚本/文档注意编码；本机 PowerShell 5.1 按 GBK 处理中文路径，涉及中文文件名用 Python。
- 删文件走回收站；替换 EXE 前先停掉正在运行的实例。
- 改完源码**不会影响已打包的 EXE**，要重新构建。

---

## 九、构建环境与凭据

- 依赖锁定见 `src/requirements-win-py314.lock`（本项目实际用 Python 3.13 构建）；构建额外依赖 `tools/requirements-build.txt`（PyInstaller）。`LICENSES/build-versions.json` 记录构建环境。
- 发布审计（`tools/build_release.py`）会扫描 `sk-/AIza/gsk_/xai-` 等凭据模式与个人数据；**Key 不应出现在日志、ZIP 或截图里**。
