"""Authored full-frame activities driven by actual application state."""
from pet_motion import Pose
from dataclasses import replace
import time

PHYSICAL_STATES={'dragging','falling','landing','recover','pat','happy'}
REMINDER_HOP_SEC=3.0     # 提醒期间每 3 秒蹦一组，一组两下（和双击她一样）

def select_activity(pose,working=False,reminder=False,exiting=False,awaiting=False,
                    researching=False,listening=False):
    if exiting:return Pose(state='exit',eye_open=1,mouth_open=False)
    if pose.state in PHYSICAL_STATES:return pose
    if awaiting:return Pose(state='awaiting_answer',eye_open=1,mouth_open=False)
    if reminder:return Pose(state='reminder',eye_open=1,mouth_open=False)
    if listening:return Pose(state='listening',eye_open=1,mouth_open=False)
    if researching:return Pose(state='researching',eye_open=1,mouth_open=False)
    if working:return Pose(state='working',eye_open=1,mouth_open=False)
    return pose

class ActivityMixin:
    def _awaiting_question_key(self):
        questions=getattr(self,'_computer_questions',None)
        if questions:
            with questions.lock:
                pending=questions.pending
                if pending and pending['token'] is getattr(self,'_computer_cancel',None) and not pending['token'].is_set():
                    return ('file',pending['request_id'],pending['index'])
        pending=getattr(self,'_pending_todo',None)
        if pending and pending.get('need') in ('content','time') and not getattr(self,'_awaiting_todo_processing',False):
            asked_at=pending.setdefault('asked_at',time.monotonic())
            if time.monotonic()-asked_at<=1800:return ('todo',id(pending),pending['need'])
            self._pending_todo=None
        for channel,target in list(getattr(self,'_todo_reply_targets',{}).items()):
            if target.get('choosing') and not target.get('handled') and time.monotonic()-target['at']<=1800:
                return ('completion',channel,target['at'])
        return None

    def _reminder_art_active(self,now=None):
        """抱闹钟的差分该不该露面：提醒气泡还挂着、语音还在念、或刚提醒完的尾巴。
        语音那条路不走 _play_reply，所以不能只看窗口，还要看时间兜底。"""
        now=time.monotonic() if now is None else now
        notice=getattr(self,'_activity_reminder_win',None)
        try:
            if notice is not None and notice.winfo_exists() and self._reply_win is notice:
                return True
        except Exception:
            pass
        return now<getattr(self,'_activity_saved_until',0) or now<getattr(self,'_reminder_art_until',0)

    def _research_art_active(self,now=None):
        """看手机的差分：搜索进行中，或者还在最短展示/收尾的时间里。"""
        now=time.monotonic() if now is None else now
        return bool(getattr(self,'_researching_active',False)) or now<getattr(self,'_researching_until',0)

    def _update_reminder_hop(self,now):
        """提醒期间每 3 秒蹦一组，一组两下（就是双击她那个动作）。"""
        if not self._reminder_art_active(now):
            self._reminder_hop_last=None
            return
        motion=getattr(self,'_motion',None)
        if motion is None or not getattr(self,'visible',False) or getattr(self,'_quitting',False):
            return
        if motion.action is not None:      # 正在蹦/正在摸头，等这一组跑完
            return
        last=getattr(self,'_reminder_hop_last',None)
        if last is not None and now-last<REMINDER_HOP_SEC:
            return
        self._reminder_hop_last=now
        self._start_action('happy',now)

    def _activity_pose(self,pose):
        key=self._awaiting_question_key()
        now=time.monotonic()
        if key!=getattr(self,'_awaiting_art_key',None):
            self._awaiting_art_key=key;self._awaiting_art_started=now
        reminder=self._reminder_art_active(now)
        state=getattr(self,'_computer_state',{})
        token=getattr(self,'_computer_cancel',None)
        working=bool(state.get('executing') and token is not None and not token.is_set())
        result=select_activity(pose,working=working,reminder=reminder,
                               exiting=getattr(self,'_exit_bowing',False),awaiting=key is not None,
                               researching=self._research_art_active(now),
                               listening=self._music_on())
        if result.state=='awaiting_answer':
            result=replace(result,activity_progress=min(1,max(0,(now-self._awaiting_art_started)/.22)))
        return result

    def _computer_execution_finished(self,token):
        if getattr(self,'_computer_cancel',None) is token:self._computer_state['executing']=False

    def _begin_exit_bow(self):
        """Called after normal shutdown cleanup. Artwork never delays exit for a model call."""
        animator=getattr(self,'_animator',None)
        if not self.visible or animator is None or 'exit' not in animator.activity_frames:
            self._finish_quit();return
        try:
            self._exit_bowing=True
            self._hide_buttons();self._cancel_reply();self.close_chat_win();self.close_popup()
            with self._render_lock:
                frame=animator.frame(self._cur_h,pose=Pose(state='exit'),animated=False,color_key=True)
            self._set_pet_image(frame);self.pet.lift();self.pet.update_idletasks()
            self._exit_bow_after=self.root.after(850,self._finish_quit)
        except Exception:
            self._finish_quit()
