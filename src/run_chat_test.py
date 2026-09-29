"""Friend-facing standalone chat app. No pet, voice, tools, telemetry or uploads."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from chat_test_core import ChatSession, APP_VERSION, PERSONA_LABEL, CHARACTERS, stream_reply, safe_error, validate_config
from chat_test_export import make_export, review_payload, save_export
from chat_test_settings import data_directory, load_config, save_config, KeyStore, load_natural_chat, save_natural_chat


class ChatWindow:
    def __init__(self, root=None, directory=None, transport=stream_reply, key_store=None, testing=False,
                 *, initial_key=None, natural_chat_default=False, connection=None, spoken=False, character='shizuka', outer_variant='baseline', outer_experiment=False):
        self.character = character
        self.outer_experiment = outer_experiment
        self.character_name = CHARACTERS[character]['name']
        self.root = root or tk.Tk()
        self.root.title(self.character_name + ' · 聊天测试 ' + ('K1' if character == 'kokona' else PERSONA_LABEL))
        self.root.geometry('850x740')
        self.root.minsize(620, 540)
        self.root.configure(bg='#f3f6fb')
        self.directory = Path(directory) if directory else data_directory()
        self.config = validate_config(connection) if connection is not None else load_config(self.directory)
        self.key_store = key_store or KeyStore()
        self.key = initial_key or ''
        self.private_keys = set()
        self.testing = testing
        if not testing and initial_key is None:
            try:
                self.key = self.key_store.read(self.config['api_base'])
            except OSError:
                pass
        if self.key:
            self.private_keys.add(self.key)
        self.transport = transport
        self.session = ChatSession(natural_chat=True if outer_experiment else load_natural_chat(self.directory, natural_chat_default),spoken=spoken,character=character,outer_variant=outer_variant)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.exported_count = 0
        self.live_started = False
        self.feedback = ''
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('TFrame', background='#f3f6fb')
        style.configure('TLabel', background='#f3f6fb', font=('Microsoft YaHei UI', 10))
        style.configure('TButton', font=('Microsoft YaHei UI', 10), padding=(10, 6))
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill='both', expand=True)
        top = ttk.Frame(outer)
        top.pack(fill='x', pady=(0, 8))
        ttk.Label(top, text=self.character_name, font=('Microsoft YaHei UI', 19, 'bold')).pack(side='left')
        ttk.Label(top, text='  桌面试聊 · 外层 O1' if outer_experiment else '  桌面试聊 · A / B', foreground='#58769b').pack(side='left', pady=(6, 0))
        self.settings_button = ttk.Button(top, text='连接设置', command=self.show_settings)
        self.settings_button.pack(side='right')
        self.new_button = ttk.Button(top, text='新建会话', command=self.new_session)
        self.new_button.pack(side='right', padx=6)
        mode_row = ttk.Frame(outer)
        mode_row.pack(fill='x', pady=(0, 10))
        self.natural_chat = tk.BooleanVar(value=self.session.natural_chat)
        self.mode_button = ttk.Checkbutton(mode_row, text='自然接话 B（试用）', variable=self.natural_chat,
                                          command=self.change_mode)
        if not outer_experiment:self.mode_button.pack(side='left')
        self.mode_label = ttk.Label(mode_row, foreground='#58769b')
        self.mode_label.pack(side='left', padx=12)
        self.spoken=tk.BooleanVar(value=self.session.spoken)
        self.spoken_button=ttk.Checkbutton(mode_row,text='口语表达（试用）',variable=self.spoken,command=self.change_spoken)
        if character == 'shizuka' and not outer_experiment:self.spoken_button.pack(side='right')
        self.refresh_mode_label()
        body = ttk.Frame(outer)
        body.pack(fill='both', expand=True)
        self.history = tk.Text(body, height=1, wrap='word', state='disabled', relief='flat', bg='white',
                               fg='#233247', font=('Microsoft YaHei UI', 11), padx=16, pady=14,
                               spacing1=3, spacing3=8)
        scroll = ttk.Scrollbar(body, command=self.history.yview)
        self.history.configure(yscrollcommand=scroll.set)
        self.history.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.history.tag_configure('user', foreground='#496b9b')
        self.history.tag_configure('assistant', foreground='#304357')
        self.history.tag_configure('system', foreground='#7a8798', font=('Microsoft YaHei UI', 9))
        self.status = ttk.Label(outer, text=self.ready_text(), foreground='#687b91')
        self.status.pack(fill='x', pady=8)
        self.entry = tk.Text(outer, height=3, wrap='word', font=('Microsoft YaHei UI', 11),
                             relief='solid', borderwidth=1, padx=9, pady=7)
        self.entry.pack(fill='x')
        self.entry.bind('<Return>', self.send)
        self.entry.bind('<Shift-Return>', lambda event: None)
        bottom = ttk.Frame(outer)
        bottom.pack(fill='x', pady=(8, 0))
        self.export_button = ttk.Button(bottom, text='导出聊天记录', command=self.show_export)
        self.export_button.pack(side='left')
        self.feedback_button = ttk.Button(bottom, text='写反馈', command=self.show_feedback)
        self.feedback_button.pack(side='left', padx=6)
        self.send_button = ttk.Button(bottom, text='发送', command=self.send)
        self.send_button.pack(side='right')
        self.stop_button = ttk.Button(bottom, text='停止', command=self.stop, state='disabled')
        self.stop_button.pack(side='right', padx=6)
        ttk.Label(outer, text='Enter 发送 · Shift+Enter 换行。聊天只在本次窗口中保留，关闭前请导出。',
                  foreground='#738196', font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(8, 0))
        self.append('system', '消息会发送到连接设置中的模型接口；记录与反馈只有你点击导出后才生成本地文件。'
                             '本程序不会自动上传聊天记录给开发者。')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.timer = self.root.after(60, self.pump)
        self.entry.focus_set()

    def ready_text(self):
        return '可以开始聊天。' if self.key else '先在「连接设置」填入测试专用 key；保存不会自动发请求。'

    def refresh_mode_label(self):
        if self.outer_experiment:
            from outer_dialogue_trial import LABELS
            self.mode_label.configure(text=LABELS[self.session.outer_variant]+' · '+self.session.meta['persona_revision']+' · 本窗口固定版本')
            return
        self.mode_label.configure(text=('B 接话' if self.session.natural_chat else 'A 接话')+
            (' · S3.1 口语' if self.session.spoken else ' · '+CHARACTERS[self.character]['label']))

    def change_spoken(self):
        if self.outer_experiment:
            self.spoken.set(self.session.spoken);return
        if self.session.busy:
            self.spoken.set(self.session.spoken);return
        try:self.session.set_spoken(self.spoken.get())
        except (ValueError,OSError) as exc:
            self.spoken.set(self.session.spoken);self.status.configure(text='口语版本切换失败，请检查角色卡文件。');return
        self.refresh_mode_label()
        self.append('system',('已启用 S3.1 口语试用。' if self.session.spoken else '已切回 S2.7 原口吻。')+'从下一条消息生效。')

    def change_mode(self):
        if self.outer_experiment:
            self.natural_chat.set(self.session.natural_chat);return
        if self.session.busy:
            self.natural_chat.set(self.session.natural_chat)
            return
        enabled = self.natural_chat.get()
        try:
            save_natural_chat(self.directory, enabled)
        except OSError:
            self.natural_chat.set(self.session.natural_chat)
            self.status.configure(text='未能保存开关，仍使用原来的模式。')
            return
        self.session.set_natural_chat(enabled)
        self.refresh_mode_label()
        self.append('system', ('已切换到 B 试用。' if enabled else '已切回 A 原版。') + '现有对话保留，从下一条消息生效。')

    def append(self, role, text):
        name = {'user': '你', 'assistant': self.character_name, 'system': '提示'}[role]
        self.history.configure(state='normal')
        self.history.insert('end', f'{name}：{text}\n\n', role)
        self.history.configure(state='disabled')
        self.history.see('end')

    def busy_widgets(self, busy):
        for widget in (self.send_button, self.new_button, self.settings_button, self.export_button, self.mode_button,self.spoken_button):
            widget.configure(state='disabled' if busy else 'normal')
        self.stop_button.configure(state='normal' if busy else 'disabled')

    def send(self, event=None):
        if event is not None and event.state & 0x1:
            return None
        if self.session.busy:
            return 'break'
        if not self.key:
            self.show_settings()
            return 'break'
        text = self.entry.get('1.0', 'end-1c').strip()
        if not text:
            return 'break'
        try:
            messages = self.session.begin(text, self.config['api_model'])
        except ValueError as exc:
            self.status.configure(text=str(exc))
            return 'break'
        self.entry.delete('1.0', 'end')
        self.append('user', text)
        self.busy_widgets(True)
        self.status.configure(text=self.character_name+'正在回复…')
        self.cancel = threading.Event()
        self.live_started = False
        config, key, cancel = dict(self.config), self.key, self.cancel
        def work():
            pieces = []
            def emit(delta):
                pieces.append(delta)
                self.events.put(('delta', delta))
            try:
                reply = self.transport(config, key, messages, cancel, emit)
                status = 'cancelled' if cancel.is_set() else 'complete'
                if not reply.strip() and status == 'complete':
                    self.events.put(('error', '本轮没有返回正文，请稍后重试。'))
                    status = 'failed'
                self.events.put(('done', (reply, status)))
            except Exception as exc:
                self.events.put(('error', safe_error(exc)))
                self.events.put(('done', (''.join(pieces), 'cancelled' if cancel.is_set() else 'failed')))
        threading.Thread(target=work, daemon=True).start()
        return 'break'

    def pump(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'delta':
                self.session.reply_started()
                self.history.configure(state='normal')
                if not self.live_started:
                    self.history.insert('end', self.character_name+'：', 'assistant')
                    self.live_started = True
                self.history.insert('end', value, 'assistant')
                self.history.configure(state='disabled')
                self.history.see('end')
            elif kind == 'error':
                self.status.configure(text=value)
            elif kind == 'done':
                if self.live_started:
                    self.history.configure(state='normal')
                    self.history.insert('end', '\n\n')
                    self.history.configure(state='disabled')
                self.session.finish(*value)
                self.busy_widgets(False)
                if value[1] == 'complete':
                    self.status.configure(text='可以继续聊，也可以写反馈或导出记录。')
                elif value[1] == 'cancelled':
                    self.status.configure(text='已停止；未自动重发。')
                self.entry.focus_set()
        self.timer = self.root.after(60, self.pump)

    def stop(self):
        self.cancel.set()
        self.stop_button.configure(state='disabled')
        self.status.configure(text='正在停止接收…接口可能已开始生成，请稍等本轮结束。')

    def has_unexported(self):
        return len(self.session.exchanges) > self.exported_count

    def new_session(self):
        if self.session.busy:
            return
        if self.has_unexported() and not messagebox.askyesno('新建会话',
                '本次聊天尚未全部导出。仍要清空并新建吗？', parent=self.root):
            return
        self.session = ChatSession(natural_chat=self.session.natural_chat,spoken=self.session.spoken,character=self.character,outer_variant=self.session.outer_variant)
        self.feedback = ''
        self.exported_count = 0
        self.history.configure(state='normal')
        self.history.delete('1.0', 'end')
        self.history.configure(state='disabled')
        self.append('system', '已开始空白会话。')
        self.status.configure(text=self.ready_text())

    def show_settings(self):
        if self.session.busy:
            return
        win = tk.Toplevel(self.root)
        win.title('连接设置')
        win.geometry('610x350')
        win.transient(self.root)
        win.grab_set()
        frame = ttk.Frame(win, padding=18)
        frame.pack(fill='both', expand=True)
        variables = {name: tk.StringVar(value=self.config[name]) for name in self.config}
        for row, (key, label) in enumerate((('api_base', '接口地址'), ('api_model', '模型名称'), ('api_mode', '接口类型'))):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=7)
            widget = ttk.Combobox(frame, textvariable=variables[key], values=('chat', 'responses'), state='readonly') \
                if key == 'api_mode' else ttk.Entry(frame, textvariable=variables[key])
            widget.grid(row=row, column=1, sticky='ew', padx=(10, 0))
        ttk.Label(frame, text='测试 key').grid(row=3, column=0, sticky='w', pady=7)
        key_value = tk.StringVar()
        ttk.Entry(frame, textvariable=key_value, show='•').grid(row=3, column=1, sticky='ew', padx=(10, 0))
        remember = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text='保存在此电脑的 Windows 凭据管理器', variable=remember).grid(row=4, column=1, sticky='w', pady=8)
        note = ttk.Label(frame, text='key 留空则保留当前接口已存凭据。软件包不内置共享 key。\n保存只更新设置；首次发送消息时才连接接口。',
                         foreground='#687b91', wraplength=480)
        note.grid(row=5, column=0, columnspan=2, sticky='w', pady=8)
        def save():
            try:
                config = validate_config({k: v.get() for k, v in variables.items()})
                key = key_value.get().strip()
                if not key:
                    key = self.key if config['api_base'] == self.config['api_base'] else self.key_store.read(config['api_base'])
                if not key:
                    raise ValueError('请填写这个接口的测试专用 key。')
                if remember.get():
                    self.key_store.write(config['api_base'], key)
                else:
                    self.key_store.delete(config['api_base'])
                save_config(self.directory, config)
                self.config, self.key = config, key
                self.private_keys.add(key)
                self.status.configure(text=self.ready_text())
                win.destroy()
            except (OSError, ValueError) as exc:
                note.configure(text=str(exc))
        ttk.Button(frame, text='保存', command=save).grid(row=6, column=1, sticky='e')
        frame.columnconfigure(1, weight=1)
        return win

    def show_feedback(self):
        win = tk.Toplevel(self.root)
        win.title('本次聊天反馈')
        win.geometry('580x300')
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text='哪些地方想继续聊，哪些地方有盘问、说教或接不住话的感觉？', wraplength=540).pack(padx=15, pady=12)
        entry = tk.Text(win, wrap='word', font=('Microsoft YaHei UI', 11), height=7)
        entry.pack(fill='both', expand=True, padx=15)
        entry.insert('1.0', self.feedback)
        def save():
            self.feedback = entry.get('1.0', 'end-1c')
            self.exported_count = -1
            win.destroy()
        ttk.Button(win, text='保存到本次导出', command=save).pack(anchor='e', padx=15, pady=12)
        return win

    def show_export(self):
        if self.session.busy:
            return
        if not self.session.exchanges:
            self.status.configure(text='聊过之后再导出即可。')
            return
        win = tk.Toplevel(self.root)
        win.title('检查隐私后导出 JSON')
        win.geometry('830x690')
        win.transient(self.root)
        win.grab_set()
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='已自动过滤常见联系方式、密钥、链接和文件路径。请检查姓名、学校、地址等内容；\n'
                  '可直接编辑下方 JSON，或添加需要隐藏的词。保存只生成本地文件，不会自动发送。', wraplength=780).pack(anchor='w')
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=10)
        ttk.Label(row, text='额外隐私词（用逗号分隔）：').pack(side='left')
        private = ttk.Entry(row)
        private.pack(side='left', fill='x', expand=True)
        text = tk.Text(frame, wrap='word', font=('Microsoft YaHei UI', 10), undo=True)
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        bottom = ttk.Frame(frame)
        bottom.pack(side='bottom', fill='x', pady=(10, 0))
        text.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        original = make_export(self.session.snapshot(), self.feedback, self.private_keys)
        text.insert('1.0', json.dumps(original, ensure_ascii=False, indent=2))
        def terms():
            return list(self.private_keys) + [word.strip() for word in private.get().replace('，', ',').split(',') if word.strip()]
        def redact_again():
            try:
                payload = review_payload(text.get('1.0', 'end-1c'), original, terms())
                text.delete('1.0', 'end')
                text.insert('1.0', json.dumps(payload, ensure_ascii=False, indent=2))
            except (ValueError, TypeError):
                messagebox.showerror('JSON 格式', '请保留有效 JSON；可以修改正文或删除消息条目。', parent=win)
        def save():
            try:
                payload = review_payload(text.get('1.0', 'end-1c'), original, terms())
                folder = filedialog.askdirectory(title='选择导出文件夹（按当前时间命名）', parent=win)
                if not folder:
                    return
                path = save_export(folder, payload)
                self.exported_count = len(self.session.exchanges)
                self.status.configure(text='已导出：' + path.name + '，请自行发送给测试发起人。')
                win.destroy()
            except (ValueError, TypeError, OSError):
                messagebox.showerror('未保存', '请检查 JSON 格式及所选文件夹的写入权限。', parent=win)
        ttk.Button(row, text='应用隐私词', command=redact_again).pack(side='right', padx=(6, 0))
        ttk.Button(bottom, text='已检查，保存 JSON', command=save).pack(side='right')
        ttk.Button(bottom, text='取消', command=win.destroy).pack(side='right', padx=6)
        return win

    def close(self):
        if self.has_unexported() and not self.testing and not messagebox.askyesno('关闭聊天',
                '还有未导出的聊天或反馈。关闭后本次内容不会保留，仍要关闭吗？', parent=self.root):
            return
        self.cancel.set()
        self.root.after_cancel(self.timer)
        self.root.destroy()


def self_test(report):
    """Exercise a real Tk window and export offline; never load a credential."""
    import tempfile
    import time
    import socket
    import re
    from unittest.mock import patch
    checks = []
    errors = []
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    with tempfile.TemporaryDirectory(prefix='shizuka-chat-smoke-') as folder:
        def fake(config, key, messages, cancel, emit):
            assert re.search(r'用户[^。]*不是心菜', messages[0]['content'])
            assert '"requested_help"' not in messages[0]['content']
            emit('离线测试回复。')
            return '离线测试回复。'
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('offline only')):
            win = ChatWindow(directory=folder, transport=fake, testing=True)
            win.root.report_callback_exception = lambda *args: errors.append(args[0].__name__)
            win.key = 'fixture-key-not-a-secret'
            win.root.update()
            checks.append({'window_constructed': win.history.winfo_width() > 300})
            def composer_visible():
                return all(widget.winfo_ismapped() and widget.winfo_height() > 10
                           and widget.winfo_rooty() + widget.winfo_height() <= win.root.winfo_rooty() + win.root.winfo_height()
                           for widget in (win.entry, win.send_button))
            checks.append({'composer_visible': composer_visible()})
            win.root.geometry('620x540')
            win.root.update()
            checks.append({'composer_visible_at_minimum': composer_visible()})
            win.root.geometry('850x740')
            win.root.update()
            checks.append({'original_default': not win.session.natural_chat})
            win.spoken_button.invoke()
            checks.append({'spoken_enabled':win.session.spoken})
            win.mode_button.invoke()
            checks.append({'b_enabled_and_saved': win.session.natural_chat and load_natural_chat(folder)})
            win.entry.insert('1.0', '今天只是想休息一下。邮箱 tester@example.invalid')
            win.send()
            checks.append({'busy_switch_disabled': str(win.mode_button.cget('state')) == 'disabled'})
            win.natural_chat.set(False)
            win.change_mode()
            checks.append({'late_switch_ignored': win.session.natural_chat and win.natural_chat.get()})
            win.spoken.set(False);win.change_spoken()
            checks.append({'busy_spoken_switch_ignored':win.session.spoken and win.spoken.get()})
            deadline = time.monotonic() + 5
            while win.session.busy and time.monotonic() < deadline:
                win.root.update()
                time.sleep(.02)
            checks.append({'fake_reply_received': win.session.exchanges[-1]['assistant'] == '离线测试回复。'})
            win.mode_button.invoke()
            checks.append({'rollback_preserves_chat': not win.session.natural_chat and len(win.session.exchanges) == 1})
            dialog = win.show_settings()
            win.root.update()
            checks.append({'connection_dialog': dialog.winfo_width() >= 600})
            dialog.destroy()
            dialog = win.show_feedback()
            next(w for w in descendants(dialog) if isinstance(w, tk.Text)).insert('1.0', '离线界面检查 私人学校')
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button)).invoke()
            dialog = win.show_export()
            win.root.update()
            private = next(w for w in descendants(dialog) if isinstance(w, ttk.Entry))
            private.insert(0, '私人学校')
            next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == '应用隐私词').invoke()
            with patch.object(filedialog, 'askdirectory', return_value=folder):
                next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == '已检查，保存 JSON').invoke()
            paths = list(Path(folder).glob('静香聊天_*.json'))
            content = paths[0].read_text('utf-8') if paths else ''
            checks.append({'export_button_saved': len(paths) == 1 and win.exported_count == 1})
            checks.append({'export_redacted': bool(content) and 'tester@example.invalid' not in content and '私人学校' not in content})
            checks.append({'export_reviewed': json.loads(content)['privacy']['human_review_confirmed']})
            checks.append({'export_captures_sent_mode': all(row['natural_chat'] is True for row in json.loads(content)['messages'])
                           and json.loads(content)['metadata']['natural_chat'] is False})
            checks.append({'export_captures_persona':all(row['persona_revision']=='s31-r' for row in json.loads(content)['messages'])})
            win.new_session()
            checks.append({'new_session_empty': not win.session.exchanges})
            checks.append({'new_session_keeps_mode': not win.session.natural_chat})
            checks.append({'new_session_keeps_spoken':win.session.spoken})
            win.spoken_button.invoke()
            checks.append({'spoken_rollback':not win.session.spoken})
            from openai import OpenAI
            OpenAI(api_key='offline-fixture', base_url='http://127.0.0.1:1').close()
            checks.append({'sdk_loads_offline': True})
            win.close()
            restarted = ChatWindow(directory=folder, testing=True, natural_chat_default=True)
            checks.append({'restart_keeps_selected_mode': not restarted.session.natural_chat})
            restarted.close()
    checks.append({'no_tk_callback_errors': not errors})
    data = {'app_version': APP_VERSION, 'model_calls': 0, 'checks': checks,
            'ok': all(all(row.values()) for row in checks)}
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if data['ok'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        if not args.report:
            parser.error('--self-test requires --report')
        return self_test(args.report)
    window = ChatWindow()
    window.root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
