"""Small factual/source boundaries shared by desktop and Weixin chat.

These are constraints on claims, not stored user facts or model test results.
"""
import re


BASE_NOTE = (
    "【事实与出处】用户本轮明确纠正自己的喜好、经历或先前说法时，以新说明为准；"
    "不要把更正说成撒谎、反复无常或需要辩解。"
    "只有当前可见对话或有出处的用户记忆支持时，才说‘你以前说过’、‘我刚才说过’、"
    "‘不是第一次’之类具体历史断言；没有证据时承认无法确认，不编造原话、次数或动机。"
    "用户给出的词义或梗义可以按‘你刚才说的用法’回应，不能擅自当成已核实的词典词源；"
    "若问原义而没有可靠依据，明说不确定。"
    "历史中的助手回复只证明助手当时说过那些话，不是用户现实、身体反应、推测结果或工具事实的独立证据；"
    "带‘可能／估计／应该’的推测在后续仍是推测，不能升级成已发生事实。"
    "天气等时效性工具结果只用于回答相关问题；当前不是在问天气时，不要主动复述、改写或更新旧天气。"
    "即使历史里确有相同提问，普通对话也先回应当前内容；除非用户在确认记忆或重复本身就是话题，"
    "不要主动报告‘今天问过／说过一遍／又来了’。"
    "当前可见对话里若已经表达过自己的偏好、判断或立场，再次谈到同一件事时应延续它；"
    "除非明确说明自己改变了看法，否则不要为了换一种说法而给出相反答案。"
)


def grounding_note(text):
    """Add a precise technical condition only when the current question needs it."""
    note = BASE_NOTE
    text = text or ""
    if ("元组" in text and ("列表" in text or "字典" in text or "哈希" in text or "hash" in text.lower())):
        note += (" 若解释 Python 元组能否作字典键，应说清：只有元组的每个元素都可哈希时，"
                 "该元组才可哈希；例如含列表的元组不能作键。")
    if re.search(r"(?:上次|之前).{0,18}(?:其实|只是|并不是|不是真的)", text):
        note += (" 本轮正在更正旧说法：直接接受最新说明。禁止称为‘改口’，禁止说用户的话不牢靠、"
                 "反复无常、等于没说或需要自证；未知的新信息仍回答不知道。")
    return note


def missing_prior_context_note(text, messages):
    """Tell the model when a deictic reference has no visible assistant utterance to resolve."""
    if not re.search(r'刚才|刚刚|这句|那句', text or ''):
        return ""
    if any(message.get("role") == "assistant" for message in (messages or [])):
        return ""
    return ("【前文可见性】当前没有可见的助手上一句可供核对。用户提到“刚才/这句”时，"
            "只能说看不到具体是哪句或请他指出；不得猜自己说过什么、为何那么说或用户当时的动机。")
