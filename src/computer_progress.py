"""Read-only execution view; native DSH questions are answered in pet chat."""
import re
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from ui_theme import apply,copy_bindings,copy_text


class PendingQuestions:
    def __init__(self,agent):
        self.agent=agent;self.lock=threading.RLock();self.pending=None

    def install(self,event,token,origin):
        with self.lock:
            self.pending={'request_id':event['request_id'],'questions':event['questions'],
                          'index':0,'answers':[],'token':token,'origin':origin}
            return self.prompt()

    def prompt(self):
        item=self.pending
        if not item:return ''
        q=item['questions'][item['index']]
        text='主人，有一处想和您确认。\n'+q['question']
        if q.get('detail'):text+='\n'+q['detail']
        for index,option in enumerate(q.get('options',[]),1):
            text+='\n'+str(index)+'. '+option['label']
            if option.get('description'):text+='：'+option['description']
        return text

    def submit(self,text,origin):
        with self.lock:
            item=self.pending
            if not item or item['origin']!=origin:return None
            if item['token'].is_set():
                self.pending=None
                return '刚才的任务已经停下了，这条回答没有继续执行。'
            q=item['questions'][item['index']];options=q.get('options',[])
            chosen=[]
            if re.fullmatch(r'\d+(?:[、,，\s]+\d+)*',text.strip()):
                numbers=[int(n) for n in re.findall(r'\d+',text)]
                if all(1<=n<=len(options) for n in numbers) and (q.get('multiSelect') or len(numbers)==1):
                    chosen=[options[n-1]['label'] for n in dict.fromkeys(numbers)]
            elif text.strip() in [o['label'] for o in options]:chosen=[text.strip()]
            answer={'id':q['id'],'selected':chosen,'custom':'' if chosen else text}
            if item['index']+1<len(item['questions']):
                item['answers'].append(answer);item['index']+=1
                return self.prompt()
            # Keep the question pending if writing the answer fails. Never restart a task.
            self.agent.answer_question(item['request_id'],item['answers']+[answer])
            self.pending=None
            return '好，我按您说的继续。'

    def clear(self,token):
        with self.lock:
            if self.pending and self.pending['token'] is token:self.pending=None


class ComputerProgressMixin:
    def _computer_claim(self,token):
        self._computer_init()
        if not self._computer_job_lock.acquire(blocking=False):return False
        self._computer_cancel=token
        return True

    def _computer_release(self,token):
        questions=getattr(self,'_computer_questions',None)
        if questions:questions.clear(token)
        if getattr(self,'_computer_cancel',None) is token:
            self._computer_cancel=None
            lock=getattr(self,'_computer_job_lock',None)
            if lock and lock.locked():lock.release()

    def _computer_can_reply(self,my_conv,token):
        return my_conv==self._conv_id or getattr(self,'_computer_question_conv',None)==(token,self._conv_id)

    def _computer_open_progress(self,task,token):
        if not hasattr(self,'root'):return
        old=getattr(self,'_computer_progress_win',None)
        if old is not None and old.winfo_exists():old.destroy()
        win=self._computer_progress_win=tk.Toplevel(self.root)
        self._computer_progress_token=token
        win.title('静香 · DSH 执行过程');win.geometry('830x620');win.minsize(590,400)
        win.columnconfigure(0,weight=1);win.rowconfigure(1,weight=1)
        head=ttk.Frame(win,padding=(20,18,20,10));head.grid(row=0,column=0,sticky='ew')
        ttk.Label(head,text='文件任务',style='Pet.Title.TLabel').pack(side='left')
        self._computer_progress_status=tk.StringVar(value='正在连接 DSH')
        ttk.Label(head,textvariable=self._computer_progress_status,style='Pet.Muted.TLabel').pack(side='right')
        box=self._computer_progress_text=ScrolledText(win,wrap='word',state='disabled',spacing3=5)
        box.grid(row=1,column=0,sticky='nsew',padx=20);copy_bindings(box)
        box.tag_configure('step',foreground='#486773',font=('Microsoft YaHei UI',11,'bold'),spacing1=12)
        box.tag_configure('detail',foreground='#697780');box.tag_configure('error',foreground='#9C4949')
        foot=ttk.Frame(win,padding=(20,12));foot.grid(row=2,column=0,sticky='ew')
        ttk.Button(foot,text='复制所选',command=lambda:copy_text(box)).pack(side='left')
        ttk.Button(foot,text='回到最新',command=lambda:box.see('end')).pack(side='left',padx=8)
        self._computer_progress_stop=ttk.Button(foot,text='停止任务',command=lambda:token.set())
        self._computer_progress_stop.pack(side='right')
        apply(win);self._computer_progress_append(task+'\n','step');win.lift()

    def _computer_progress_append(self,text,tag='detail'):
        win=getattr(self,'_computer_progress_win',None)
        if win is None or not win.winfo_exists():return
        box=self._computer_progress_text;follow=box.yview()[1]>=.985
        box.configure(state='normal');box.insert('end',text,tag)
        # Full events stay in the task directory. Bound the Tk view's memory.
        if int(box.index('end-1c').split('.')[0])>4000:box.delete('1.0','1000.0')
        box.configure(state='disabled')
        if follow:box.see('end')

    def _computer_receive_progress(self,state,token,origin='desktop',channel=None):
        if token.is_set():return
        for event in state.get('events',[]):
            if event.get('type')=='question':
                phrase=self._computer_questions.install(event,token,origin)
                if origin=='weixin':self._log_chat('assistant',phrase,kind='weixin_file_question')
                if origin=='weixin' and channel:
                    def send(phrase=phrase,event=event):
                        if token.is_set():return
                        try:channel.notify_question(phrase,event['request_id'])
                        except Exception:
                            self._ui(lambda:self._computer_question_delivery_failed(token))
                    threading.Thread(target=send,daemon=True,name='shizuka-file-question').start()
                else:self._ui(lambda phrase=phrase:self._computer_ask_in_chat(phrase,token))
            elif event.get('type')=='question_cancelled':self._computer_questions.clear(token)
        self._ui(lambda:self._computer_draw_progress(state,token))

    def _computer_ask_in_chat(self,phrase,token):
        if token.is_set() or getattr(self,'_computer_cancel',None) is not token:return
        self.open_chat_input()
        self._computer_question_conv=(token,self._conv_id)
        from dialogue_style import LiteralReply
        self.say(LiteralReply(phrase),source='文件询问')

    def _computer_question_delivery_failed(self,token):
        # A failed delivery must not become an invented answer. Desktop is a fallback.
        questions=self._computer_questions
        with questions.lock:
            if not questions.pending or questions.pending['token'] is not token:return
            questions.pending['origin']='desktop';phrase=questions.prompt()
        self._computer_ask_in_chat(phrase,token)

    def _answer_computer_question(self,text,origin='desktop'):
        questions=getattr(self,'_computer_questions',None)
        if not questions:return None if origin=='weixin' else False
        with questions.lock:
            pending=questions.pending
            if not pending or pending['origin']!=origin:return None if origin=='weixin' else False
            token=pending['token']
            if text.strip() in ('/停止','/stop','停止任务','取消任务'):
                token.set();questions.clear(token);reply='好，这项任务先停在这里。'
            else:
                try:reply=questions.submit(text,origin)
                except Exception:reply='刚才的回答还没有送到，我先等着。您可以再发一次。'
        self._log_chat('user',text,kind='weixin_file_answer' if origin=='weixin' else 'computer_answer')
        if origin=='weixin':
            self._log_chat('assistant',reply,kind='weixin_file_question')
            return reply
        self._computer_question_conv=(token,self._conv_id)
        from dialogue_style import LiteralReply
        self.say(LiteralReply(reply),source='文件询问')
        return True

    def _computer_draw_progress(self,state,token):
        if getattr(self,'_computer_cancel',None) is token:
            executing=not state.get('waiting') and not any(r.get('type')=='turn_end' for r in state.get('events',[]))
            self._computer_state.update(status='等待您回复静香' if state.get('waiting') else self._scene('file_running',seconds=state['elapsed']),directory=state.get('directory',''),executing=executing)
        win=getattr(self,'_computer_progress_win',None)
        if win is None or not win.winfo_exists() or self._computer_progress_token is not token:return
        self._computer_progress_status.set('等待您回复静香' if state.get('waiting') else f"处理中 · {state['elapsed']} 秒")
        for row in state.get('events',[]):
            kind=row.get('type')
            if kind=='step':self._computer_progress_append('\n步骤 '+str(row.get('step',''))+'\n','step')
            elif kind=='tool_call':self._computer_progress_append('\n调用 '+row.get('name','工具')+'\n','step');self._computer_progress_append(row.get('text','')+'\n')
            elif kind=='tool_result':self._computer_progress_append('返回结果\n'+row.get('text','')+'\n','error' if row.get('error') else 'detail')
            elif kind=='text':self._computer_progress_append(row.get('text',''))
            elif kind=='bridge_ready':self._computer_progress_append('DSH 已连接\n')
            elif kind=='question':self._computer_progress_append('\n静香正在等您的回答。\n','step')
            elif kind=='question_answered':self._computer_progress_append('\n已收到回答，继续处理。\n','step')

    def _computer_finish_progress(self,result,token):
        win=getattr(self,'_computer_progress_win',None)
        if win is None or not win.winfo_exists() or self._computer_progress_token is not token:return
        labels={'completed':'已完成','cancelled':'已停止','timeout':'已超时','failed':'未完成'}
        self._computer_progress_status.set(labels.get(result['status'],'已返回'))
        if result['status']=='completed':
            win.destroy();self._computer_progress_win=None;self._computer_progress_token=None
            return
        self._computer_progress_stop.configure(state='disabled')
        self._computer_progress_append('\n'+labels.get(result['status'],'已返回')+'\n','step')
        self._computer_progress_append((result.get('output') or result.get('error') or result.get('stderr') or '')+'\n')
