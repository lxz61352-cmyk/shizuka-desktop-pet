"""Low-frequency mouth movement follows revealed characters in either bubble type."""
import time
from dialogue_style import punctuation_pause

class SpeechMotionMixin:
    def _speech_start(self,win):
        self._speech_window=win;self._speech_started=time.monotonic()
        self._speech_until=0;self._speech_pause_until=0

    def _speech_stop(self,win=None):
        if win is None or getattr(self,'_speech_window',None) is win:
            self._speech_window=None;self._speech_until=0

    def _speech_progress(self,win,text,finished=False):
        if getattr(self,'_speech_window',None) is not win:return
        if finished:self._speech_stop(win);return
        if not text:return
        now=time.monotonic();pause=punctuation_pause(text[-1])
        self._speech_pause_until=now+pause
        self._speech_until=now if pause else now+.3

    def _speaking_mouth(self,now=None):
        now=time.monotonic() if now is None else now
        win=getattr(self,'_speech_window',None)
        if win is None or win is not getattr(self,'_reply_win',None):return False
        try:
            if not win.winfo_exists() or not win.winfo_viewable():return False
        except Exception:return False
        if now>=getattr(self,'_speech_until',0) or now<getattr(self,'_speech_pause_until',0):return False
        # 1.4 openings per second; paragraph/network pauses and completed text close immediately.
        return ((now-self._speech_started)*1.4)%1<.44
