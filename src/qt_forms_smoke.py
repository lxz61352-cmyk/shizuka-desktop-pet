def run():
    import ctypes,json,os,socket,sys,tempfile,time,traceback
    import threading
    from pathlib import Path
    from unittest.mock import patch

    STAGE=Path(__file__).resolve().parent
    ROOT=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(r'E:\Shizuka-v0.8.0-test')
    sys.path[:0]=[str(STAGE),str(ROOT/'src')]
    os.environ['SHIZUKA_WINDOW_BACKEND']='qt';os.environ['SHIZUKA_QT_SOURCE']='1'
    checks=[];errors=[]
    with tempfile.TemporaryDirectory(prefix='shizuka-forms-test-') as folder:
        os.environ['SHIZUKA_DATA_DIR']=folder
        import pet,tkinter as tk
        from tkinter import ttk
        from qt_forms import install
        from window_opening import dialog_window
        app=None;bridge=None
        with patch.object(pet,'read_api_key',return_value=''),patch.object(pet,'_embed_texts',return_value=None),patch.object(pet.DeskPet,'_migrate_api_key'),patch.object(pet.DeskPet,'_todo_start_memory_review'),patch.object(pet.DeskPet,'_todo_check_reminders'),patch.object(socket.socket,'connect',side_effect=AssertionError('Offline fixture')),patch.object(ctypes.windll.user32,'GetAsyncKeyState',return_value=0):
            try:
                app=pet.DeskPet();install(app);app.root.report_callback_exception=lambda *a:errors.append(''.join(traceback.format_exception(*a)))
                app.root.update();app._motion.reset();app._ground.cancel()
                def wait(predicate):
                    deadline=time.monotonic()+25
                    while not predicate():
                        app.root.update();time.sleep(.02)
                        if time.monotonic()>deadline:raise AssertionError('Presentation timeout: '+str(errors))
                calls=[];win=dialog_window(app.root);win.title('虚构控件测试');win.geometry('720x580')
                entry=ttk.Entry(win);entry.insert(0,'初始文字');entry.pack(fill='x')
                secret=ttk.Entry(win,show='*');secret.insert(0,'fictional-private-placeholder');secret.pack(fill='x')
                choice=tk.BooleanVar(value=False);check=ttk.Checkbutton(win,text='虚构开关',variable=choice,command=lambda:calls.append('toggle'));check.pack()
                button=ttk.Button(win,text='虚构按钮',command=lambda:calls.append(entry.get()));button.pack()
                combo=ttk.Combobox(win,values=['一','二'],state='readonly');combo.set('一');combo.pack();combo.bind('<<ComboboxSelected>>',lambda e:calls.append(combo.get()))
                tree=ttk.Treeview(win,columns=['name'],show='headings',height=4);tree.heading('name',text='测试列表');tree.pack(fill='x')
                for i in range(1200):tree.insert('','end',iid=str(i),values=['虚构记录 '+str(i)])
                tree.bind('<<TreeviewSelect>>',lambda e:calls.append('selected'));tree.bind('<Double-1>',lambda e:calls.append('double'))
                text=tk.Text(win,height=3);text.insert('1.0','虚构多行');text.pack(fill='x')
                canvas=tk.Canvas(win,height=60);canvas.pack(fill='x');item=canvas.create_text(20,10,anchor='nw',text='虚构点击',tags='demo');canvas.tag_bind('demo','<Button-1>',lambda e:calls.append('canvas'))
                closed=[];win.protocol('WM_DELETE_WINDOW',lambda:closed.append('cancelled'))
                wait(lambda:hasattr(app,'_qt_windows'))
                bridge=app._qt_windows;form=win._qt_form
                wait(lambda:form.ident in bridge.presented)
                assert not bridge.errors,bridge.errors
                assert win.attributes('-alpha')==1 and form.original['attributes']('-alpha')==0
                assert not getattr(win,'_art_backdrop',None) and not getattr(win,'_opening_started',False)
                assert 'fictional-private-placeholder' not in json.dumps(form.last)
                checks.append('Actual Qt form rendered; private Tk model remains invisible, no photo renderer/fade, secret values omitted')
                def act(action,widget=None,**extra):return bridge.action('form',dict(form=form.ident,action=action,widget=str(widget) if widget else '',**extra))
                act('edit',entry,value='测试修改');act('invoke',button);assert calls[-1]=='测试修改'
                act('invoke',check);assert choice.get() and calls[-1]=='toggle'
                act('edit',combo,value='二');assert combo.get()=='二' and calls[-1]=='二'
                act('select',tree,rows=['1199']);assert tree.selection()==('1199',) and 'selected' in calls
                act('double',tree,row='1199');assert 'double' in calls
                act('canvas',canvas,item=item,x=20,y=10);assert 'canvas' in calls
                act('edit',text,value='新虚构内容');assert text.get('1.0','end-1c')=='新虚构内容'
                act('close');assert closed==['cancelled'] and win.winfo_exists()
                checks.append('Original edit, toggle, combo, selection, double-click, canvas and cancellable close callbacks work')
                child=tk.Label(win,text='Temporary child');child.destroy()
                assert form.ident in app._qt_forms.forms and form.ident in bridge.opened
                checks.append('Destroying a child control preserves its tool window')
                form.destroy()
                form.destroy()
                assert form.ident not in app._qt_forms.forms and form.ident not in bridge.opened
                checks.append('Repeated adapter destruction is safe and releases the tool registration')
                direct=dialog_window(app.root);direct.title('Direct destruction fixture');tk.Label(direct,text='Fixture').pack()
                wait(lambda:direct._qt_form.ident in bridge.presented)
                direct_form=direct._qt_form;direct.tk.call('destroy',str(direct))
                assert direct_form.ident not in app._qt_forms.forms and direct_form.ident not in bridge.opened
                checks.append('Direct Tcl destruction also removes the Qt tool window')
                def qt_removed(ident):
                    status=json.loads((Path(pet.DATA_DIR)/'qt-window-runtime.json').read_text('utf-8'))
                    return ident not in status['windows']
                memory=pet.get_memory()
                with memory._lock:memory.items=[dict(id='fixture-'+str(i),content='虚构记忆 '+str(i),created=time.time(),status='active',expires_at=0,type='long_term') for i in range(1200)]
                app._update_init()
                routes_extra=[('pomodoro-settings',app.show_pomodoro_settings),('model-settings',app._prompt_api_key),('task-progress',lambda:app._computer_open_progress('虚构任务，仅测试显示',threading.Event())),('update-preference',app._confirm_toggle_update),('update-confirm',lambda:app._confirm_update((True,'99.0','https://example.invalid','虚构更新说明，不下载'))),('update-progress',lambda:app._show_update_progress('99.0')),('date-picker',lambda:app._todo_calendar(app.root,tk.StringVar(value='2026-10-04'))),('paper-reader',lambda:app._research_read(dict(title='虚构文章',abstract='虚构摘要'))),('memory-details',lambda:app.show_memory_details('fixture-0'))]
                routes=[('settings',app.show_settings_center),('computer',app.show_computer_assistant),('wechat',app.show_weixin),('memory',app.show_memory),('feedback',app.show_feedback),('runtime',app.show_runtime_status),('backup',app.show_backup),('usage',app.show_usage),('materials',lambda:app.manage_attachments([],lambda:None)),('reply-feedback',lambda:app.show_reply_feedback(dict(id='fictional',role='assistant',text='虚构回复'))),('notice',lambda:app.show_notice(dict(id='fictional',text='虚构通知',source='测试',created=time.time())))]
                coverage=[]
                routes+=routes_extra
                for name,route in routes:
                    before=set(app._qt_forms.forms);route()
                    wait(lambda:bool(set(app._qt_forms.forms)-before))
                    new=set(app._qt_forms.forms)-before;wait(lambda:new<=bridge.presented)
                    current=app._qt_forms.forms[next(iter(new))]
                    assert current.last['nodes'],name
                    coverage.append(dict(tool=name,controls=len(current.last['nodes']),types=sorted({n['kind'] for n in current.last['nodes']})))
                    checks.append(name+' actual tool route presents Qt controls')
                    if name=='memory':
                        canvas=app._mem_canvas
                        assert len(canvas.find_all())>=6000
                        node=next(n for n in current.last['nodes'] if n['kind']=='canvas');assert len(node['items'])<100
                        item=canvas.find_withtag('memfield:0')[0]
                        current.action(dict(action='canvas',widget=str(canvas),item=item,double=True,x=45,y=10))
                        assert app._mem_editor and app._mem_editor[0]==0
                        box=app._mem_editor[1]
                        current.action(dict(action='edit',widget=str(box),value='修改后的虚构记忆'))
                        current.action(dict(action='event',widget=str(box),sequence='<Return>'))
                        assert app._mem_edits['fixture-0'].get()=='修改后的虚构记忆'
                        current.action(dict(action='scrollTo',widget=str(canvas),position=.99))
                        node=next(n for n in current.last['nodes'] if n['kind']=='canvas');assert len(node['items'])<100
                        checks.append('1200 memories publish only visible primitives; double edit targets one row and commits correctly')
                    # Leave settings alive to test page navigation, close other fixtures.
                    if name=='settings':
                        for label in ('聊天与角色','主动搭话','声音与提醒','免打扰','外观','连接与数据','常规'):
                            node=next(n for n in current.last['nodes'] if n.get('text')==label and n['kind']=='radio')
                            current.action(dict(action='invoke',widget=node['id']))
                        current.destroy()
                    elif name in ('computer','wechat'):
                        current.action(dict(action='close'))
                        wait(lambda:current.ident not in app._qt_forms.forms and qt_removed(current.ident))
                        assert current.ident not in bridge.opened and not current.window.winfo_exists()
                        checks.append(name+' default close removes both private model and Qt window')
                        before=set(app._qt_forms.forms);route()
                        wait(lambda:bool(set(app._qt_forms.forms)-before))
                        reopened=app._qt_forms.forms[next(iter(set(app._qt_forms.forms)-before))]
                        wait(lambda:reopened.ident in bridge.presented)
                        reopened.action(dict(action='escape'))
                        wait(lambda:reopened.ident not in app._qt_forms.forms and qt_removed(reopened.ident))
                        assert reopened.ident not in bridge.opened and not reopened.window.winfo_exists()
                        checks.append(name+' reopens after close and Escape removes the reopened window')
                    else:current.destroy()
                wait(lambda:bridge.incoming.empty())
                assert not bridge.errors,(bridge.errors,errors)
                checks.append('All seven settings pages reuse their original controls and callbacks')
            except Exception:errors.append(traceback.format_exc())
            finally:
                if app:app._closing=True;app.root.destroy()
                if bridge:
                    try:bridge.process.wait(timeout=4)
                    except Exception:bridge.process.terminate()
    result=dict(checks=checks,errors=errors,coverage=locals().get('coverage',[]))
    report=Path(sys.argv[sys.argv.index('--report')+1]);report.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    if sys.stdout:print(json.dumps(dict(checks=len(checks),errors=len(errors))))
    return 1 if errors else 0
