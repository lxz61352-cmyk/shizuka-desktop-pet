"""Authored full-frame activities driven by actual application state."""
from pet_motion import Pose
from dataclasses import replace
import time

PHYSICAL_STATES={'dragging','falling','landing','recover','pat','happy'}

def select_activity(pose,working=False,reminder=False,exiting=False,awaiting=False):
    if exiting:return Pose(state='exit',eye_open=1,mouth_open=False)
    if pose.state in PHYSICAL_STATES:return pose
    if awaiting:return Pose(state='awaiting_answer',eye_open=1,mouth_open=False)
    if reminder:return Pose(state='reminder',eye_open=1,mouth_open=False)
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

    def _activity_pose(self,pose):
        key=self._awaiting_question_key()
        now=time.monotonic()
        if key!=getattr(self,'_awaiting_art_key',None):
            self._awaiting_art_key=key;self._awaiting_art_started=now
        notice=getattr(self,'_activity_reminder_win',None)
        try:reminder=notice is not None and notice.winfo_exists() and self._reply_win is notice
        except Exception:reminder=False
        reminder=reminder or time.monotonic()<getattr(self,'_activity_saved_until',0)
        state=getattr(self,'_computer_state',{})
        token=getattr(self,'_computer_cancel',None)
        working=bool(state.get('executing') and token is not None and not token.is_set())
        result=select_activity(pose,working=working,reminder=reminder,exiting=getattr(self,'_exit_bowing',False),awaiting=key is not None)
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
