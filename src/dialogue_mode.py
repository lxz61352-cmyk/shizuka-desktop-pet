"""Optional B trial: soften inferred help intent without changing the raw classifier."""
from copy import deepcopy

REVISION = 'intent-b-v1'


def reply_frame(frame, natural_chat=False):
    result = deepcopy(frame)
    if natural_chat is True:
        result['known_context'].pop('requested_help', None)
        result['known_context'].pop('requested_help_evidence', None)
        if result['current_signal']['kind'] == 'request':
            result['current_signal']['kind'] = 'question_or_request'
    return result
