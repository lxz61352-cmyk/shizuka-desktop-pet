"""App-owned GUI acceptance in the release self-test's disposable data root."""
import json,time
from pathlib import Path
from unittest.mock import patch
from tkinter import ttk


def run(app,pet):
    checks=[]
    from background_smoke import run as background_smoke
    checks.extend(background_smoke(app,pet))
    import reply_turn
    import desktop_dialogue_profile as dialogue
    from types import SimpleNamespace as NS
    engine=NS(DESKTOP_DIALOGUE_PROFILE=dialogue.LATEST_PROFILE,
              ACTIVE_PACK=pet.ACTIVE_PACK,DATA_DIR=pet.DATA_DIR,
              CHAT_MAX_TOKENS=pet.CHAT_MAX_TOKENS,CHAT_RETRY_MAX_TOKENS=pet.CHAT_RETRY_MAX_TOKENS,
              api_model=lambda:'offline',load_settings=lambda:{},get_client=lambda:object(),
              clean_reply_style=pet.clean_reply_style)
    with patch('pre_reply_affect_runtime.prepare_reply',return_value=NS(rendered_context='')) as assessment,patch('pre_reply_fit.guidance_block',return_value=''):
        prepared=[reply_turn.prepare_profile(app,engine,'虚构测试消息',[],channel=channel,
                     interrupted=lambda:False,memory='虚构记忆') for channel in ('desktop','weixin')]
    assert assessment.call_count==2
    contexts=[p.messages[0]['content'].replace(reply_turn.CAPABILITIES[channel],'CHANNEL')
              for p,channel in zip(prepared,('desktop','weixin'))]
    assert contexts[0]==contexts[1]
    requests=[reply_turn.body_kwargs(engine,[dict(role='system',content=context)],p.provider)
              for p,context in zip(prepared,contexts)]
    assert requests[0]==requests[1] and requests[0]['stream']
    cleaners=[reply_turn.ReplyCleaner(engine,p.client,p.provider,lambda:False,'虚构测试消息',[],
              memory='虚构记忆',channel=channel) for p,channel in zip(prepared,('desktop','weixin'))]
    for cleaner in cleaners:
        cleaner.include_content([dict(type='text',text='附件原话'),dict(type='image_url',image_url={'url':'not-a-fact'})])
    assert cleaners[0].facts==cleaners[1].facts and 'not-a-fact' not in cleaners[0].facts
    with patch('self_history_guard.guard',side_effect=lambda client,model,text,*args,**kwargs:(text,[])):
        assert cleaners[0].clean('好，我知道了。')==cleaners[1].clean('好，我知道了。')
    assert dialogue.metadata(dialogue.LATEST_PROFILE)['reply_pipeline_revision']==reply_turn.REVISION
    checks.append('Desktop and WeChat share persona, affect preparation, attachment fact boundaries and output checks')
    import runtime_pre_reply_affect as affect
    import runtime_affect_event_lab as affect_events
    now='2026-10-03T17:00:00+08:00'
    affect_state=affect_events.empty(now)
    messages=[{'role':'assistant','content':'I am angry'},
              {'role':'user','content':'Please explain a new mathematics problem'}]
    payload=json.loads(affect.assessment_messages(messages,affect_state,now)[1]['content'])
    assert set(payload['state'])=={'events'} and not payload['reference_only']
    assert '/100' not in affect.render(affect_state)
    for n in range(8):
        text='minor event '+str(n)
        decision=dict(mood_delta=3,emotion='pleased',event_kind='pleasant_exchange',target='user',
                      cause=text,event_ref='',relation='new',intensity='clear')
        affect_state,_=affect.prepare(affect_state,'smoke-'+str(n),text,decision,now)
    assert affect_state['mood']==71
    checks.append('Affect assessment excludes self feedback and scores, expression is qualitative, and distinct minor events share a rolling budget')
    def widgets(parent):
        for child in parent.winfo_children():
            yield child
            yield from widgets(child)
    app.show_settings_center();app.root.update()
    win=app._settings_center
    from window_opening import MAX_PREPARE_SECONDS,FADE_SECONDS
    deadline=time.monotonic()+MAX_PREPARE_SECONDS+FADE_SECONDS+1
    while getattr(win,'_opening_pending',False) and time.monotonic()<deadline:
        app.root.update();time.sleep(.005)
    assert win._opening_result=='ready',getattr(win,'_opening_result',None)
    assert float(win.attributes('-alpha'))==1
    assert win._art_backdrop.signature==win._art_backdrop.layout_signature()
    pages=win._settings_pages
    assert len(pages.pages)==7
    for name,canvas in pages.canvases.items():
        pages.select(name);app.root.update()
        assert canvas.winfo_ismapped()
        assert canvas.winfo_rooty()+canvas.winfo_height()<=win.winfo_rooty()+win.winfo_height()
        canvas.yview_moveto(1);app.root.update()
        assert canvas.yview()[1]>.99
    from proactive_chat import state
    assert not state(app._weixin_store.data)['enabled']
    from proactive_chat import acceptable
    from proactive_content import prior_openings
    assert not acceptable('你平时会看这类耳机吗',[])
    assert not acceptable('你现在在哪？',[])
    assert not app._proactive_text_ok('最近出了个新品耳机。',{'id':'company'})
    assert acceptable('有些电影里的配角反而更有意思。',[])
    assert prior_openings([{'text':'某品牌新品耳机。'},{'text':'普通电影话题。'}])==['普通电影话题。']
    checks.append('Proactive topics reject consumer promotion and private probes, preserve casual directions, and exclude old product openings')
    controls=win._settings_controls
    expected=('_sound_mode','_speed','_voice_on','_tts_lang','_tts_en_phonemes','_tts_release','_idle_minutes',
              '_quiet_fullscreen','_quiet_games','_quiet_fold','_clip_on','_translate_on','_web_search_on',
              '_greeting_on','_summary_on','_usage_on','_animation_on','_ambient_actions_on','_land_on_windows',
              '_sensitive_topics_on','autostart','quiet_name','blur')
    assert all(name in controls for name in expected)
    from experience_settings import load
    assert not load(pet.DATA_DIR)['water_enabled']
    controls['water_times'].delete(0,'end');controls['water_times'].insert(0,'9:00，14:30')
    controls['water_save'].invoke()
    assert load(pet.DATA_DIR)['water_times']=='09:00, 14:30'
    controls['water_enabled'].invoke()
    assert app._experience['water_enabled'] and load(pet.DATA_DIR)['water_enabled']
    controls['water_times'].delete(0,'end');controls['water_times'].insert(0,'25:00')
    controls['water_save'].invoke()
    assert load(pet.DATA_DIR)['water_times']=='09:00, 14:30'
    controls['water_enabled'].invoke()
    controls['desktop_start'].delete(0,'end');controls['desktop_start'].insert(0,'22:00')
    controls['desktop_end'].delete(0,'end');controls['desktop_end'].insert(0,'06:00')
    controls['desktop_hours_save'].invoke()
    assert app._experience['desktop_start']==1320 and app._experience['desktop_end']==360
    controls['desktop_pause'].invoke();assert not app._casual_proactive_allowed()
    controls['desktop_resume'].invoke();assert load(pet.DATA_DIR)['desktop_paused_until']==0
    checks.append('Water controls persist valid times and enable state, reject invalid times; desktop quiet hours and pause controls persist')
    # Existing options must still update runtime state and the same settings file.
    before=app._animation_on
    controls['_animation_on'].invoke();app.root.update()
    assert app._animation_on is not before and pet.load_settings()['animation'] is app._animation_on
    controls['_animation_on'].invoke()
    with patch.object(pet,'gsv_available',return_value=False),patch.object(app,'_ensure_tts_server') as start_voice:
        controls['_voice_on'].invoke()
        assert not app._voice_on and not start_voice.called
    controls['quiet_name'].insert(0,'Fixture.exe');controls['quiet_add'].invoke()
    assert 'Fixture.exe' in app._quiet_apps and 'Fixture.exe' in pet.load_settings()['quiet_apps']
    controls['移除选中的程序'].invoke();assert not app._quiet_apps
    controls['blur'].delete(0,'end');controls['blur'].insert(0,'37');controls['save_art'].invoke()
    from experience_settings import load
    assert load(pet.DATA_DIR)['blur']==7.4
    win.destroy();checks.append('Settings center: seven persistent scrollable pages; WeChat proactive remains opt-in')
    checks.append('Former submenu options persist, voice checks availability, app list edits and blur percentage save')
    checks.append('Settings window becomes opaque only after final layout and first artwork frame are ready')

    app.open_chat_input(prefill='未发送的草稿');app.root.update();app.save_chat_and_close()
    assert json.loads((Path(pet.DATA_DIR)/'chat-draft.json').read_text('utf-8'))['text']=='未发送的草稿'
    app.open_chat_input();app.root.update();assert app._chat_entry.get()=='未发送的草稿'
    app.close_chat_win();checks.append('Composer draft survives close and is persisted locally')

    from dialogue_feedback import capture,FeedbackStore
    with patch.object(pet,'api_model',return_value='offline'):
        trace=capture(app,'desktop',[{'role':'system','content':'离线角色及相关记忆'},
                                     {'role':'user','content':'虚构消息'}])
    app._log_chat('assistant','虚构回复，用于界面验证。')
    row=app._chat_log[-1];assert row['trace_id']==trace
    app.show_reply_feedback(row);app.root.update()
    save=next(w for w in widgets(app._feedback_editor) if isinstance(w,ttk.Button) and w.cget('text')=='保存标记')
    save.invoke();app.root.update()
    feedback=FeedbackStore(pet.DATA_DIR).rows();assert feedback[-1]['trace']['id']==trace
    app.show_feedback();app.root.update()
    table=next(w for w in widgets(app._feedback_window) if isinstance(w,ttk.Treeview))
    table.selection_set(table.get_children()[-1]);app.root.update()
    app._feedback_window.destroy();checks.append('Reply feedback stores the actual request trace and previews selected export')

    mem=pet.get_memory();mem.add('用户今天在复习');mem.save()
    app.show_memory();app.root.update();app.show_memory_details(mem.items[0]['id']);app.root.update()
    win=app._memory_details
    editor=next(w for w in win.winfo_children() if w.winfo_class()=='Text')
    original=mem.items[0]['content']
    editor.delete('1.0','end');editor.insert('1.0','用户手动修正的虚构记忆\n第二行内容')
    save=next(w for w in win.winfo_children() if w.winfo_class()=='TButton' and w.cget('text')=='保存')
    save.invoke();app.root.update()
    assert mem.items[0]['content']=='用户手动修正的虚构记忆\n第二行内容'
    assert mem.items[0]['edited_by']=='user'
    app.undo_memory_change();app.root.update()
    assert mem.items[0]['content']==original and 'edited_by' not in mem.items[0]
    assert app._mem_edits[mem.items[0]['id']].get()==original
    checks.append('Single memory multiline editor saves content and evidence; undo restores both')
    app._close_memory_window()
    app.show_backup();app.root.update();app._backup_window.destroy()
    app.show_runtime_status();app.root.update();app._runtime_window.destroy()
    checks.append('Memory applicability/source, backup/restore and runtime-status panels open')

    with patch.object(app,'say',return_value=True):
        app._pomo_start('focus');app.root.update()
        assert not app.visible and app._pomo_phase=='focus'
        assert app._pomo_float is not None and app._pomo_float.attributes('-topmost')
        app._pomo_stop();app.root.update()
    checks.append('Focus Pomodoro folds the pet while the timer remains topmost')
    return checks
