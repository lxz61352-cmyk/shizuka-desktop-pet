"""One settings entry point, sharing the application's existing saved options."""
import ntpath
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ui_theme import apply, PAGE_X
from settings_pages import SettingsPages

TITLES = ('常规', '聊天与角色', '主动搭话', '声音与提醒', '免打扰', '外观', '连接与数据')


def show(app, section=None):
    import pet
    from experience_settings import load, save, blur_from_percent
    from window_art import catalog, set_preferences
    old = getattr(app, '_settings_center', None)
    if old is not None and old.winfo_exists():
        app.close_popup(); old.deiconify(); old.lift()
        if section:old._settings_pages.select(section)
        return
    previous_app = pet.get_foreground_app()[1]
    win = app._experience_window('_settings_center', '设置中心', 960, 740)
    if win is None:return
    win.minsize(820, 560)
    prefs = load(pet.DATA_DIR)
    search = tk.StringVar(win)
    search_row = ttk.Frame(win); search_row.pack(fill='x', padx=PAGE_X, pady=(0, 10))
    ttk.Label(search_row, text='查找设置').pack(side='left', padx=(0, 10))
    ttk.Entry(search_row, textvariable=search).pack(side='left', fill='x', expand=True)
    pages = SettingsPages(win, TITLES); pages.pack(fill='both', expand=True, padx=PAGE_X, pady=(0, 18))
    win._settings_pages = pages; win._settings_controls = controls = {}
    groups = pages.bodies; searchable = []

    def heading(group, text):
        ttk.Label(groups[group], text=text, style='Pet.Section.TLabel').pack(anchor='w', pady=(12, 8))

    def note(group, text):
        ttk.Label(groups[group], text=text, wraplength=590, justify='left').pack(fill='x', pady=(2, 8))

    def action(group, label, command, key=None):
        button = ttk.Button(groups[group], text=label, command=command)
        button.pack(anchor='w', pady=5)
        searchable.append((group, label)); controls[key or label] = button
        return button

    def toggle(group, label, attr, changed=None):
        value = tk.BooleanVar(win, value=bool(getattr(app, attr, False)))
        def change():
            setattr(app, attr, value.get())
            if attr.startswith('_quiet_'):app._quiet_checked_at = 0.0
            if changed:changed(value)
            app._save_settings()
        button = ttk.Checkbutton(groups[group], text=label, variable=value, command=change)
        button.pack(anchor='w', pady=5)
        controls[attr] = button; searchable.append((group, label))
        return button, value

    def choice(group, label, options, attr, setter):
        row = ttk.Frame(groups[group]); row.pack(fill='x', pady=6)
        ttk.Label(row, text=label, width=16).pack(side='left')
        value = tk.StringVar(win, value=dict(options).get(getattr(app, attr, None), options[0][1]))
        box = ttk.Combobox(row, textvariable=value, values=[v for k,v in options], state='readonly', width=24)
        box.pack(side='left', fill='x', expand=True)
        box.bind('<<ComboboxSelected>>', lambda e:setter(next(k for k,v in options if v==value.get())))
        controls[attr] = box; searchable.append((group, label))
        return box

    heading('常规', '启动与桌面功能')
    autostart = tk.BooleanVar(win, value=pet.is_autostart_on()); startup_status = tk.StringVar(win)
    def save_startup():
        ok = pet.set_autostart(autostart.get())
        autostart.set(pet.is_autostart_on())
        startup_status.set('已保存。' if ok else '开机启动设置失败，请稍后重试。')
    startup = ttk.Checkbutton(groups['常规'], text='开机自动启动', variable=autostart, command=save_startup)
    startup.pack(anchor='w', pady=5); controls['autostart'] = startup; searchable.append(('常规','开机自动启动'))
    ttk.Label(groups['常规'], textvariable=startup_status).pack(anchor='w')
    for label, attr in [('开机问候','_greeting_on'), ('开机待办提醒','_summary_on'),
                        ('检测剪贴板','_clip_on'), ('翻译剪贴板','_translate_on'), ('记录窗口使用时长','_usage_on')]:
        toggle('常规', label, attr)
    note('常规', '开关与下拉选项修改后自动保存；需要填写数字的项目使用旁边的保存按钮。')

    heading('聊天与角色', '对话')
    toggle('聊天与角色','敏感话题模式（非露骨成人话题）','_sensitive_topics_on')
    toggle('聊天与角色','不确定的消息联网查证','_web_search_on')
    choice('聊天与角色','文字显示速度',[('fast','快'),('medium','中等'),('slow','慢')], '_speed', app._set_speed)
    for label, command in [('查看话题范围说明',app._show_sensitive_topic_help),('查看和标记对话',app.show_chat_log),
                           ('反馈记录与导出',app.show_feedback),('查看记忆与有效期',app.show_memory)]:
        action('聊天与角色', label, command)
    app._weixin_init()
    heading('聊天与角色', '微信连续消息')
    merge = tk.StringVar(win, value=str(app._weixin_store.data.get('chat_merge_seconds', .8)))
    row = ttk.Frame(groups['聊天与角色']); row.pack(fill='x', pady=6)
    ttk.Label(row, text='等待合并（秒）').pack(side='left')
    ttk.Spinbox(row, from_=0, to=2, increment=.2, textvariable=merge, width=8).pack(side='left', padx=10)
    def save_merge():
        try:
            seconds=float(merge.get())
            if not 0<=seconds<=2:raise ValueError
        except ValueError:return messagebox.showerror('合并等待','请输入 0–2 秒。',parent=win)
        app._weixin_store.update(chat_merge_seconds=seconds)
    ttk.Button(row,text='保存',command=save_merge).pack(side='left')
    note('聊天与角色','0 为关闭。连续收到短消息时，最长合并等待 3 秒。')

    from proactive_chat import state, command, describe, HELP
    pro = groups['主动搭话']; value = state(app._weixin_store.data)
    heading('主动搭话','微信主动聊天')
    enabled=tk.BooleanVar(win,value=value['enabled'])
    start=tk.StringVar(win,value='%02d:%02d'%divmod(value['start'],60)); end=tk.StringVar(win,value='%02d:%02d'%divmod(value['end'],60))
    frequency=tk.StringVar(win,value={1:'少',2:'偶尔',3:'多'}.get(value['daily_limit'],'偶尔'))
    ttk.Checkbutton(pro,text='允许微信主动搭话（无回复则暂停后续闲聊）',variable=enabled).pack(anchor='w',pady=6)
    row=ttk.Frame(pro); row.pack(fill='x',pady=8)
    ttk.Label(row,text='允许时段').pack(side='left'); ttk.Entry(row,textvariable=start,width=8).pack(side='left',padx=8)
    ttk.Label(row,text='至').pack(side='left'); ttk.Entry(row,textvariable=end,width=8).pack(side='left',padx=8)
    ttk.Combobox(row,textvariable=frequency,values=('少','偶尔','多'),state='readonly',width=8).pack(side='left')
    status=tk.StringVar(win,value=describe(value)); ttk.Label(pro,textvariable=status,wraplength=590).pack(fill='x',pady=8)
    def set_proactive():
        data=dict(app._weixin_store.data)
        current,reply=command('/主动 时间 '+start.get()+'-'+end.get(),data)
        if '格式' in reply or '有效时刻' in reply:return messagebox.showerror('时间设置',reply,parent=win)
        data['proactive_chat']=current; current,_=command('/主动 频率 '+frequency.get(),data)
        if enabled.get()!=current['enabled']:
            data['proactive_chat']=current; current,_=command('/主动 '+('开启' if enabled.get() else '关闭'),data)
        app._weixin_store.update(proactive_chat=current)
        channel=getattr(app,'_weixin_channel',None)
        if channel:channel.proactive_cancel.set()
        status.set(describe(current))
    action('主动搭话','保存微信主动设置',set_proactive)
    heading('主动搭话','桌面闲聊')
    desktop=tk.StringVar(win,value=prefs['desktop_proactive'])
    row=ttk.Frame(pro); row.pack(fill='x',pady=6)
    ttk.Label(row,text='闲聊频率').pack(side='left',padx=(0,12))
    ttk.Combobox(row,textvariable=desktop,values=('关闭','很少','偶尔','较活跃'),state='readonly',width=10).pack(side='left')
    def save_desktop(*args):
        prefs['desktop_proactive']=desktop.get(); app._experience=save(pet.DATA_DIR,prefs)
    desktop.trace_add('write',save_desktop)
    idle=tk.StringVar(win,value=str(app._idle_minutes)); idle_status=tk.StringVar(win)
    row=ttk.Frame(pro); row.pack(fill='x',pady=6)
    ttk.Label(row,text='空闲提醒间隔（分钟）').pack(side='left')
    idle_entry=ttk.Spinbox(row,from_=1,to=1440,textvariable=idle,width=7); idle_entry.pack(side='left',padx=10)
    controls['_idle_minutes']=idle_entry
    def save_idle():
        try:
            minutes=int(idle.get())
            if not 1<=minutes<=1440:raise ValueError
        except ValueError:idle_status.set('请输入 1–1440 的整数分钟。'); return
        app._idle_minutes=minutes; app._idle_chat_count=0; app._last_idle_alert=time.time(); app._save_settings()
        idle_status.set('已保存。')
    ttk.Button(row,text='保存',command=save_idle).pack(side='left'); idle_entry.bind('<Return>',lambda e:save_idle())
    ttk.Label(pro,textvariable=idle_status).pack(anchor='w')
    from proactive_topics import TOPIC_DESCRIPTION
    note('主动搭话',TOPIC_DESCRIPTION); note('主动搭话',HELP)

    heading('声音与提醒','提示音与音乐')
    choice('声音与提醒','提示音',[('all','全部消息'),('todo-files','待办提醒和文件完成'),('todo','仅待办提醒'),('none','关闭')],
           '_sound_mode',app._set_sound)
    action('声音与提醒','测试提示音',app.play_sound)
    volume=tk.StringVar(win,value=str(round(app._music_volume/10))); volume_status=tk.StringVar(win)
    row=ttk.Frame(groups['声音与提醒']); row.pack(fill='x',pady=6)
    ttk.Label(row,text='背景音乐音量').pack(side='left')
    ttk.Entry(row,textvariable=volume,width=7).pack(side='left',padx=10); ttk.Label(row,text='%').pack(side='left')
    def save_volume():
        try:
            percent=int(volume.get())
            if not 0<=percent<=100:raise ValueError
        except ValueError:volume_status.set('请输入 0–100 的整数。'); return
        app._set_music_volume(percent*10); volume_status.set('已保存。')
    ttk.Button(row,text='保存',command=save_volume).pack(side='left',padx=10)
    ttk.Label(groups['声音与提醒'],textvariable=volume_status).pack(anchor='w')
    heading('声音与提醒','语音朗读')
    voice_status=tk.StringVar(win)
    def voice_changed(value):
        if value.get() and not pet.gsv_available():
            value.set(False); app._voice_on=False; voice_status.set('尚未检测到 GPT-SoVITS，请先配置语音。'); return
        if value.get():threading.Thread(target=app._ensure_tts_server,daemon=True).start()
        else:app._stop_voice_playback()
    voice,voice_value=toggle('声音与提醒','语音朗读','_voice_on',voice_changed)
    voice_status.set('已检测到 GPT-SoVITS。' if pet.gsv_available() else '尚未检测到 GPT-SoVITS，请先配置语音。')
    ttk.Label(groups['声音与提醒'],textvariable=voice_status,wraplength=590).pack(anchor='w',pady=4)
    def configure_voice():
        app._pick_gsv_dir()
        voice_status.set('已检测到 GPT-SoVITS。' if pet.gsv_available() else '尚未检测到 GPT-SoVITS，请先配置语音。')
    action('声音与提醒','配置语音（GPT-SoVITS）',configure_voice)
    choice('声音与提醒','朗读语言',[('zh','中文'),('ja','日文')], '_tts_lang',app._set_tts_lang)
    toggle('声音与提醒','英文片段按英文音素朗读','_tts_en_phonemes')
    choice('声音与提醒','语音服务释放',[('now','隐藏即释放'),('1','隐藏 1 分钟后'),('5','隐藏 5 分钟后'),('off','不释放')],
           '_tts_release',app._set_tts_release)
    missed=tk.BooleanVar(win,value=prefs.get('startup_missed',False))
    def save_missed():
        prefs['startup_missed']=missed.get(); app._experience=save(pet.DATA_DIR,prefs)
    ttk.Checkbutton(groups['声音与提醒'],text='开机在通知页列出错过的事项',variable=missed,command=save_missed).pack(anchor='w',pady=12)

    heading('免打扰','什么时候安静')
    for label,attr in [('全屏程序时安静','_quiet_fullscreen'),('游戏进程时安静','_quiet_games'),('进入时自动折叠','_quiet_fold')]:
        toggle('免打扰',label,attr)
    heading('免打扰','指定程序')
    note('免打扰','这些程序在前台时也会进入免打扰。可以填写进程名（例如 Code.exe），或选择程序文件。')
    quiet=groups['免打扰']; name=tk.StringVar(win); picked=tk.StringVar(win); quiet_status=tk.StringVar(win)
    row=ttk.Frame(quiet); row.pack(fill='x',pady=6)
    entry=ttk.Entry(row,textvariable=name); entry.pack(side='left',fill='x',expand=True)
    def update_quiet():
        app._quiet_checked_at=0.0; app._save_settings(); names.configure(values=app._quiet_apps)
        picked.set(app._quiet_apps[0] if app._quiet_apps else '')
    def add_quiet(value=None):
        candidate=(value if value is not None else name.get()).strip()
        if (not candidate.lower().endswith('.exe') or any(c in candidate for c in '/\\:*?"<>|')
                or candidate.lower() in ('shizuka.exe','python.exe','pythonw.exe')):
            quiet_status.set('请输入其他程序的进程名，例如 Code.exe。'); return
        if candidate.lower() not in [x.lower() for x in app._quiet_apps]:app._quiet_apps.append(candidate)
        update_quiet(); name.set(''); picked.set(candidate); quiet_status.set('已加入免打扰名单。')
    ttk.Button(row,text='添加',command=add_quiet).pack(side='left',padx=(8,0)); controls['quiet_add']=row.winfo_children()[-1]
    entry.bind('<Return>',lambda e:add_quiet()); controls['quiet_name']=entry
    def pick_quiet():
        path=filedialog.askopenfilename(parent=win,title='选择免打扰程序',filetypes=[('程序','*.exe')])
        if path:add_quiet(ntpath.basename(path))
    action('免打扰','选择程序文件…',pick_quiet)
    if previous_app and previous_app.lower() not in ('shizuka.exe','python.exe','pythonw.exe'):
        action('免打扰','添加刚才的程序：'+previous_app,lambda:add_quiet(previous_app))
    names=ttk.Combobox(quiet,textvariable=picked,values=app._quiet_apps,state='readonly'); names.pack(fill='x',pady=8)
    if app._quiet_apps:picked.set(app._quiet_apps[0])
    def remove_quiet():
        app._quiet_apps=[x for x in app._quiet_apps if x!=picked.get()]; update_quiet(); quiet_status.set('已移除。')
    action('免打扰','移除选中的程序',remove_quiet)
    def clear_quiet():
        app._quiet_apps=[]; update_quiet(); quiet_status.set('名单已清空。')
    action('免打扰','清空名单',clear_quiet)
    ttk.Label(quiet,textvariable=quiet_status,wraplength=590).pack(anchor='w',pady=6)

    heading('外观','角色动作')
    for label,attr in [('角色动态','_animation_on'),('自动小动作','_ambient_actions_on'),('落在窗口上','_land_on_windows')]:
        toggle('外观',label,attr)
    heading('外观','窗口背景')
    art=groups['外观']; names_art=['随机背景']+[r['file'] for r in catalog()]
    selected=tk.StringVar(win,value=prefs['background_file'] or '随机背景')
    note('外观','用于普通功能窗口，聊天装饰框保持独立。')
    ttk.Combobox(art,textvariable=selected,values=names_art,state='readonly').pack(fill='x')
    blur=tk.StringVar(win,value=str(round(prefs['blur']*5))); dark=tk.DoubleVar(win,value=prefs['darkness'])
    ttk.Label(art,text='背景模糊度').pack(anchor='w',pady=(16,4))
    row=ttk.Frame(art); row.pack(fill='x')
    blur_entry=ttk.Entry(row,textvariable=blur,width=7,justify='right'); blur_entry.pack(side='left'); controls['blur']=blur_entry
    ttk.Label(row,text='%　（0–100 的整数）').pack(side='left',padx=6)
    ttk.Label(art,text='背景加深').pack(anchor='w',pady=(16,4))
    ttk.Scale(art,from_=.25,to=.85,variable=dark,style='Pet.Horizontal.TScale').pack(fill='x')
    art_status=tk.StringVar(win)
    def save_art():
        try:radius=blur_from_percent(blur.get())
        except ValueError as exc:
            art_status.set(str(exc)); blur_entry.focus_set(); blur_entry.selection_range(0,'end'); return
        prefs.update(background_file='' if selected.get()=='随机背景' else selected.get(),blur=radius,darkness=dark.get())
        app._experience=save(pet.DATA_DIR,prefs); set_preferences(app._experience)
        for window in app.root.winfo_children():
            backdrop=getattr(window,'_art_backdrop',None)
            if backdrop:backdrop.reload_preferences()
        blur.set(str(round(radius*5))); art_status.set('已保存并应用，下次打开也会使用这个设置。')
    blur_entry.bind('<Return>',lambda e:save_art()); action('外观','保存并应用',save_art,'save_art')
    ttk.Label(art,textvariable=art_status,wraplength=590).pack(anchor='w')

    heading('连接与数据','连接')
    for label,cmd in [('微信连接',app.show_weixin),('模型与接口',app._prompt_api_key),('运行状态与重连',app.show_runtime_status),
                      ('本地备份与恢复',app.show_backup)]:action('连接与数据',label,cmd)
    keywords={'常规':'剪贴板 翻译 启动 使用时长','聊天与角色':'反馈 导出 记忆 敏感 模型 连续 合并 显示速度',
              '主动搭话':'微信 主动 时间 频率 间隔','声音与提醒':'语音 提醒 音量 朗读 语言 释放',
              '免打扰':'全屏 游戏 折叠 名单 程序','外观':'背景 模糊 明暗 图片 动画 小动作',
              '连接与数据':'接口 备份 恢复 状态 连接'}
    def find(*args):
        text=search.get().strip()
        if not text:return
        match=next((group for group,label in searchable if text in label),None)
        if match is None:match=next((title for title,words in keywords.items() if text in title+words),None)
        if match:pages.select(match)
    search.trace_add('write',find)
    pages.select(section or TITLES[0])
    apply(win)
