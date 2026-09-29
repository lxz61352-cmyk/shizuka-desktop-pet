"""Offline timing, migration and conversation-feedback regressions; no model requests."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import chat_test_core as core
import chat_test_export as export
import chat_timeline as timeline
from interaction_frame import build_interaction_frame

NOW = '2026-09-28T12:00:00.000+08:00'
HISTORY = [{'role': 'user', 'content': '上午还有事情要做'},
           {'role': 'assistant', 'content': '嗯'}]


def timeline_cases():
    return [dict(history=HISTORY, timestamps=stamps, now=NOW) for stamps in (
        ['2026-09-28T11:59:00.000+08:00', '2026-09-28T11:59:02.000+08:00'],
        ['2026-09-27T23:58:00.000+08:00', '2026-09-27T23:59:00.000+08:00'],
        ['2026-09-20T08:00:00.000+08:00', '2026-09-20T08:00:05.000+08:00'],
        ['2026-09-28T03:59:00.000Z', '2026-09-28T12:59:05.000+09:00'],
        [None, None], ['2026-09-28T11:00:00.000+08:00', None],
        ['2026-09-28T13:00:00.000+08:00', '2026-09-28T13:00:05.000+08:00'],
        ['2026-09-28T11:00:00.000+08:00', '2026-09-28T10:59:00.000+08:00'],
        ['2026-02-30T12:00:00+08:00', '2026-09-28T12:00:00'],
        ['2026-09-28T12:00:00+08:99', 'not a date'],
    )] + [dict(history=[{'role': 'user', 'content': '别老拿之前的事套我'},
                       {'role': 'assistant', 'content': '好。'},
                       {'role': 'user', 'content': '今天这饭不好吃'}],
               timestamps=[], now=NOW)]


class TimelineTests(unittest.TestCase):
    def test_gaps_across_minutes_days_weeks_and_timezone_offsets(self):
        expected = [(58, 2), (43260, 60), (705595, 5), (55, 5)]
        for case, (gap, internal_gap) in zip(timeline_cases(), expected):
            value = timeline.build_timeline(**case)
            self.assertEqual(value['seconds_since_last_message'], gap)
            self.assertEqual(value['messages'][1]['gap_seconds'], internal_gap)
            self.assertFalse(value['clock_anomaly'])

    def test_unknown_old_records_are_not_backdated_from_export_or_session_time(self):
        for case in timeline_cases()[4:6]:
            value = timeline.build_timeline(**case)
            self.assertIsNone(value['seconds_since_last_message'])
            self.assertIsNone(value['messages'][1]['at'])
            self.assertIsNone(value['messages'][1]['gap_seconds'])

    def test_clock_reversal_and_future_records_do_not_produce_negative_intervals(self):
        for case in timeline_cases()[6:8]:
            value = timeline.build_timeline(**case)
            self.assertTrue(value['clock_anomaly'])
            self.assertIsNone(value['messages'][1]['gap_seconds'])
        self.assertIsNone(timeline.build_timeline(**timeline_cases()[6])['seconds_since_last_message'])

    def test_bad_dates_offsets_and_free_text_cannot_become_timestamp_metadata(self):
        for value in [None, {}, 123, 'secret', '2026-09-28T12:00:00',
                      '2026-02-30T12:00:00+08:00', '2026-09-28T24:00:00Z',
                      '2026-09-28T12:00:00+08:99', '2026-09-28T12:00:00+24:00']:
            self.assertIsNone(timeline.valid_timestamp(value), repr(value))
        for value in [NOW, '2026-09-28T04:00:00Z', '2024-02-29T12:00:00.01-03:30']:
            self.assertEqual(timeline.valid_timestamp(value), value)

    def test_record_once_preserve_first_reply_time_and_separate_completion(self):
        clock_values = iter([NOW, '2026-09-28T12:00:02.000+08:00',
                             '2026-09-28T12:00:07.000+08:00', '2026-09-28T15:00:00.000+08:00'])
        session = core.ChatSession(persona='synthetic persona', clock=lambda: next(clock_values))
        first = session.begin('hi', 'offline')
        self.assertIn(NOW, first[0]['content'])
        session.reply_started()
        session.reply_started()  # More chunks cannot move the first-receipt time.
        session.finish('hello')
        turn = session.exchanges[0]
        self.assertEqual(turn['user_at'], NOW)
        self.assertEqual(turn['assistant_at'], '2026-09-28T12:00:02.000+08:00')
        self.assertEqual(turn['ended_at'], '2026-09-28T12:00:07.000+08:00')
        request = session.begin('another topic', 'offline')
        self.assertEqual(request[1:3], [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'hello'}])
        data=json.loads(request[0]['content'].split(timeline.CONTRACT+'\n',1)[1])
        self.assertEqual(data['seconds_since_last_message'],10798)

    def test_trimmed_context_indices_match_messages_even_with_failed_turns(self):
        session = core.ChatSession(persona='fixture')
        session.exchanges = [dict(user=str(i), assistant='a', status='complete',
                                  user_at=NOW, assistant_at=NOW) for i in range(55)]
        session.exchanges[-1].update(status='failed', assistant='partial')
        h, stamps = session.history(), session.history_timestamps()
        self.assertEqual(len(h), 99)
        self.assertEqual(len(stamps), len(h))
        self.assertEqual(h[0]['content'], '5')
        self.assertEqual(h[-1]['content'], '54')
        self.assertEqual(timeline.build_timeline(h, stamps, NOW)['messages'][-1]['history_index'], 98)
        self.assertNotIn('partial', json.dumps(h))

    def test_legacy_records_and_feedback_survive_restore_without_mutation(self):
        saved = [{'user': '别老拿之前的事套我', 'assistant': '好', 'status': 'complete'},
                 {'user': '今天这饭不好吃', 'assistant': '', 'status': 'failed', 'user_at': NOW}]
        before = deepcopy(saved)
        session = core.ChatSession(persona='fixture', clock=lambda: NOW)
        session.exchanges = json.loads(json.dumps(saved))
        h = session.history()
        value = timeline.build_timeline(h, session.history_timestamps(), NOW)
        self.assertEqual(value['feedback_user_indices'], [0])
        self.assertIsNone(value['messages'][0]['at'])
        self.assertEqual(session.exchanges, before)
        next_request = session.begin('换个话题', 'offline')
        data=json.loads(next_request[0]['content'].split(timeline.CONTRACT+'\n',1)[1])
        self.assertEqual(data['feedback_user_indices'],[0])

    def test_export_and_review_preserve_message_times_without_other_fields(self):
        snap = {'metadata': {'timeline_revision': timeline.REVISION}, 'exchanges': [
            dict(user='a', assistant='b', status='cancelled', user_at=NOW,
                 assistant_at=NOW, ended_at=NOW, secret='never export'),
            dict(user='old', assistant='old reply', status='complete')]}
        data = export.make_export(snap)
        reviewed = export.review_payload(json.dumps(data), data)
        self.assertEqual(reviewed['messages'][0]['recorded_at'], NOW)
        self.assertEqual(reviewed['messages'][1]['ended_at'], NOW)
        self.assertIsNone(reviewed['messages'][2]['recorded_at'])
        self.assertNotIn('never export', json.dumps(reviewed))


class ContinuedFeedbackTests(unittest.TestCase):
    def test_direct_objections_to_supervision_are_feedback_without_topic_keywords(self):
        for text in ['吃个饭而已别老拿复习的事情套我了……', '别再催我了',
                     '你怎么老拿上次的事情说事', '不要总是督促我', '别管我',
                     '别拿项目的事情压我', '你总是盯着我']:
            self.assertEqual(build_interaction_frame(text)['current_signal']['kind'],
                             'relationship_feedback', text)

    def test_quotes_third_parties_hypotheticals_and_requested_supervision_do_not_count(self):
        for text in ['朋友说别老拿复习的事情套我', '“别再催我了”这句台词怎么翻译？',
                     '如果我说别再催我了，你会怎么回答', '希望你一直督促我',
                     '请你总是催我', '不是你总是盯着我', '不用催我吗？', '别让他一直催我']:
            self.assertNotEqual(build_interaction_frame(text)['current_signal']['kind'],
                                'relationship_feedback', text)


if __name__ == '__main__':
    unittest.main()
