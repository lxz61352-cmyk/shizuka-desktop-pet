"""Small settings controls; no new window or per-reminder widget instances."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog


def water_controls(app, win, parent, prefs, controls):
    import pet
    from experience_settings import save
    from habit_reminders import parse_times
    enabled = tk.BooleanVar(win, value=prefs['water_enabled'])
    times = tk.StringVar(win, value=prefs['water_times'])
    status = tk.StringVar(win)
    def persist(changes):
        value = save(pet.DATA_DIR, dict(prefs, **changes))
        prefs.update(value);app._experience = value
    def toggle():
        persist({'water_enabled':enabled.get()})
        status.set('已开启喝水提醒。' if enabled.get() else '已关闭喝水提醒。')
    box = ttk.Checkbutton(parent, text='开启喝水提醒', variable=enabled, command=toggle)
    box.pack(anchor='w', pady=5);controls['water_enabled'] = box
    row = ttk.Frame(parent);row.pack(fill='x', pady=6)
    ttk.Label(row, text='每天提醒时间').pack(side='left')
    entry = ttk.Entry(row, textvariable=times);entry.pack(side='left',fill='x',expand=True,padx=8)
    controls['water_times'] = entry
    def save_times():
        try:value = parse_times(times.get())
        except ValueError as exc:status.set(str(exc));return
        persist({'water_times':value});times.set(value);status.set('提醒时间已保存。')
    button = ttk.Button(row,text='保存时间',command=save_times);button.pack(side='left')
    controls['water_save'] = button
    audio = tk.StringVar(win)
    def audio_label():audio.set('提示音：'+(Path(prefs['water_sound']).name if prefs['water_sound'] else 'notice14（内置喝水提示音）'))
    audio_label();ttk.Label(parent,textvariable=audio,wraplength=590).pack(anchor='w',pady=4)
    row = ttk.Frame(parent);row.pack(fill='x',pady=5)
    def choose():
        path = filedialog.askopenfilename(parent=win,title='选择喝水提示音',filetypes=[('音频文件','*.mp3 *.wav'),('所有文件','*.*')])
        if not path:return
        if Path(path).suffix.lower() not in ('.mp3','.wav') or not Path(path).is_file():
            status.set('请选择 MP3 或 WAV 音频文件。');return
        persist({'water_sound':path});audio_label();status.set('喝水提示音已保存。')
    ttk.Button(row,text='选择提示音…',command=choose).pack(side='left')
    ttk.Button(row,text='试听喝水提示音',command=app._play_water_sound).pack(side='left',padx=8)
    def reset():persist({'water_sound':''});audio_label()
    ttk.Button(row,text='恢复 notice14',command=reset).pack(side='left')
    ttk.Label(parent,textvariable=status,wraplength=590).pack(anchor='w',pady=4)
    ttk.Label(parent,text='可填多个时间，以逗号分隔，例如 10:00, 14:00, 16:00。\n电脑和桌宠需保持运行；在桌面提醒，遵守免打扰与提示音总开关。\n忙碌时最多等待 10 分钟，超时跳过；折叠时只响提示音并记录通知。',
              wraplength=590,justify='left').pack(fill='x',pady=(2,8))


def desktop_controls(app, win, parent, prefs, controls):
    import pet
    from experience_settings import save
    from proactive_controls import tomorrow, desktop_eligible
    start = tk.StringVar(win,value='%02d:%02d'%divmod(prefs['desktop_start'],60))
    end = tk.StringVar(win,value='%02d:%02d'%divmod(prefs['desktop_end'],60))
    after = tk.StringVar(win,value=str(prefs['desktop_after_chat']))
    status = tk.StringVar(win)
    def describe():
        with app._chat_lock:rows = list(app._chat_log[-120:])
        status.set('桌面闲聊：'+desktop_eligible(prefs,rows)[1]+'。')
    def persist(changes):
        value = save(pet.DATA_DIR,dict(prefs,**changes));prefs.update(value);app._experience=value;describe()
    row = ttk.Frame(parent);row.pack(fill='x',pady=6)
    ttk.Label(row,text='允许时段').pack(side='left')
    for key,var in [('desktop_start',start),('desktop_end',end)]:
        entry=ttk.Entry(row,textvariable=var,width=8);entry.pack(side='left',padx=8);controls[key]=entry
    def save_hours():
        try:
            from habit_reminders import parse_times
            s=parse_times(start.get());e=parse_times(end.get()) if end.get().strip()!='24:00' else '24:00'
            if ',' in s or ',' in e:raise ValueError('每个输入框填写一个时刻。')
            def minutes(value):
                h,m=map(int,value.split(':'));return h*60+m
            a,b=minutes(s),minutes(e)
            if a==b:raise ValueError('开始与结束时间不能相同；全天可填 00:00 至 24:00。')
            persist({'desktop_start':a,'desktop_end':b});start.set(s);end.set(e)
        except ValueError as exc:status.set(str(exc))
    button=ttk.Button(row,text='保存时段',command=save_hours);button.pack(side='left');controls['desktop_hours_save']=button
    row=ttk.Frame(parent);row.pack(fill='x',pady=6)
    ttk.Label(row,text='聊天结束后至少安静（分钟）').pack(side='left')
    ttk.Spinbox(row,from_=0,to=1440,textvariable=after,width=7).pack(side='left',padx=8)
    def save_after():
        try:
            value=int(after.get())
            if not 0<=value<=1440:raise ValueError
            persist({'desktop_after_chat':value})
        except ValueError:status.set('请输入 0–1440 的整数分钟。')
    ttk.Button(row,text='保存',command=save_after).pack(side='left')
    row=ttk.Frame(parent);row.pack(fill='x',pady=5)
    for label,key,value in [('今天暂停闲聊','desktop_pause',None),('恢复闲聊','desktop_resume',0)]:
        button=ttk.Button(row,text=label,command=lambda v=value:persist({'desktop_paused_until':tomorrow() if v is None else v}))
        button.pack(side='left',padx=(0,8));controls[key]=button
    describe();ttk.Label(parent,textvariable=status,wraplength=590).pack(anchor='w',pady=5)
    ttk.Label(parent,text='时段支持跨午夜；全天填 00:00 至 24:00。暂停仅影响桌面闲聊，待办和喝水提醒仍按各自设置运行。',wraplength=590).pack(fill='x',pady=4)
