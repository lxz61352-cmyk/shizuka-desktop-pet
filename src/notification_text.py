"""Full archived notice with an optional concise spoken version."""
import re


class SpokenNotice(str):
    def __new__(cls, text, speech_text):
        notice = super().__new__(cls, text)
        notice.speech_text = str(speech_text)
        return notice


def spoken_excerpt(text, limit=180):
    """Take complete sentences only; never cut a number or a qualifier midway."""
    text = re.sub(r'https?://\S+', '', str(text)).strip()
    result = ''
    for sentence in re.findall(r'[^。！？!?\n]+[。！？!?]?|\n', text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(result) + len(sentence) > limit:
            break
        result += sentence
    return result
