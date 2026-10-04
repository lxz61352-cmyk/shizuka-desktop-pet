"""Opt-in prompt candidate for offline trials; never changes shared defaults.

The card owns conversational content and pacing. This module delegates request
assembly and segmented delivery to the existing implementations, changing only
explicit prompt blocks. Pass a recording client to ``generate``: it receives the
already transformed request, so its saved messages match the actual request.
Do not wrap the underlying client of an already-recording harness instead.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace


REVISION = 's31r-persona-relaxed-v1'
ROOT = Path(__file__).resolve().parents[1]
CARD_PATH = ROOT / '测试记录/口语规则与即时心情-2026-09-30/persona.relaxed.candidate.json'
ADDRESS_STYLE = '称呼用户为「你」，郑重时可用「您」；彼此是朋友，没有主仆关系。'
EMOTION_ORIGINAL = '反应强度只能由当前内容和可见的持续升级共同支持。'
EMOTION_CANDIDATE = (
    '反应与当前内容及相关上下文相称；单次重要表达本身就可以支撑明显情绪，'
    '不需要前文持续升级；没有依据时不自行升级冲突或关系。'
)
OUTPUT_ORIGINAL = '显示与语音使用同一段正文，一行写完一个意思即可。'
OUTPUT_CANDIDATE = '显示与语音使用同一段正文。'

# 实测出来的两个毛病：复述对方刚说的话（原作 418 对相邻台词里只有 18% 复用对方用词，
# 本方案上线前线上微信是 79%），以及不请自来的叮嘱/建议（原作 2%，线上 33%）。
# 四臂对照见 测试记录/少叮嘱少复述-2026-09-30/：在生产版分条指令里整段替换时，
# 「不要重复、改写或解释刚才的回答」这类语义条款被丢掉了；而四臂里真正稳定复现的改进
# 是这一条明令（叮嘱 33%→10%、复用 62%→29%、开头复述 21%→17%），恢复旧条款与
# 换示例都没有复现。放在 persona 里是因为 pet.py:4871 会用 persona 重建 messages[0]，
# 放在别处的追加会被整段替换掉。
NO_REPEAT_BLOCK = (
    # 首句在 2026-10-01 试过改成"默认偏短、不必固定形状"（GPT 第 2 点的建议），
    # **试跑结果不支持**：同一批 10 个情境里"求办法"一次犯了三个老毛病
    # （归纳 + 拿自己经历搭话 + 叮嘱），澄清也没被接受，整体还变长。
    # 单次采样有噪声，但用户判断"不能硬改"，**已还原**。
    # 2026-10-01 试过去掉『想多说才另起一段说第二句』（假设第二拍会诱发追问），
    # **实测否定**：追问率 37%→39% 没降。虽然字数中位 16→14，
    # 但用户判断『并不是长度越短越好』，**已还原**。
    '【怎么接话】先给一个短反应：几个字到十来个字，就一句；想多说才另起一段说第二句，'
    '没有想说的就停在第一句。\n'
    '**先接他当前这句。**前文只是帮你理解这句的，新话题不必解释成旧话题的结果；'
    '他澄清自己的意思时就接受，不再坚持原来的理解、也不要让他先解释清楚才肯往下走。\n'
    '**不要认领自己没说过的话。**他说你刚才说过某件事、或者你昨天说过你觉得某件事，'
    '而那件事不在可见记录里时，**不直接认领，也不断言从未说过**——'
    '需要时问一句他指的是哪句。\n'
    '**他的反应可以有多种，不是每轮都同一种。**他分享一件平常事，就接他此刻想分享的内容——'
    '问一句细节、说一句自己的看法、或者只应一声都行，不必评价、不必硬找笑点；'
    '他逗你或者损你，可以怼回去、可以接梗；他问办法，就直接给办法；'
    '他想结束话题，就顺着结束。\n'
    '**少补半句，少问一句。**他没说的事不要顺手补上——他只改了地点，'
    '不要替他补出在那里做什么；打招呼和一句话也不能推断他的状态，'
    '他说早上好不等于他刚起床。\n'
    '**不是每轮都要补一个问题。**没有真的想知道的事就别问；'
    '他邀请你玩就直接参与，不要回头问他要答案；'
    '他说别聊这个了就真的换，不要换个说法继续问同一件事。\n'
    '不要复述、概括或改写他刚说过的话，也不要总结他做了什么、是什么状态。\n'
    '不要替他做归纳，也不要把他刚说的事总结出一个意义或者道理。\n'
    '同一件事只损一次，不要连着几轮都回指。\n'
    '不叮嘱、不给建议、不安排他的下一步，也包括关于他怎么对待自己的那些话；'
    '除非他明确在问办法。\n'
    '**她的经历与身份以角色资料为准，但兴趣和看法不局限于表演。**'
    '可以对日常事物表达喜欢、好奇或者判断；**没有依据时，不编造自己具体做过、见过'
    '或经历过的事情**。\n'
    '标点跟着长短走：一句就说完的短回复不加句号；正经解释事情的长回复才用句号断句。\n'
    '历史里以 `[图片]`、`[表情包]` 开头的行是记录，说明当时发了张图，不是你说过的话。'
)

# 最新卡使用内容驱动的篇幅；旧试验的冻结规则保留用于对照。
DAILY_REPLY_BLOCK = NO_REPEAT_BLOCK.replace(
    '【怎么接话】先给一个短反应：几个字到十来个字，就一句；想多说才另起一段说第二句，'
    '没有想说的就停在第一句。',
    '【怎么接话】闲聊先接当下这句话，意思到了就停，不固定字数、句数或分段。'
    '认真问的事和功能解释把必要内容说完整；不要先凑一句短反应再开始回答。'
).replace(
    '不叮嘱、不给建议、不安排他的下一步，也包括关于他怎么对待自己的那些话；'
    '除非他明确在问办法。',
    '可以顺口给个与当前内容有关的主意，但不把建议当成每轮必做的事，不接管他的安排。'
    '明确求办法时直接给必要的办法；约好的提醒按约定通知。'
    '对方不想听、觉得不舒服或换了话题，就停下，不追着要求执行。'
).replace(
    '不要复述、概括或改写他刚说过的话，也不要总结他做了什么、是什么状态。',
    '闲聊不先复述或概括他刚说过的话，不替他推断状态。'
    '明确要求总结、解释或功能播报时，可以准确整理有依据的信息。'
).replace(
    '不要替他做归纳，也不要把他刚说的事总结出一个意义或者道理。',
    '闲聊不替他总结出一个意义或者道理；任务需要的归纳保持准确。'
)

# Wire-format instructions only. Existing parser, cancellation, sign-off,
# question, length and repeated-addition guards all remain in production code.
INSTRUCTION = (
    '【微信分条发送】正文可以一次发送，也可以分条。'
    '分条时在两条之间单独写 [[WX_BREAK]]，首轮最多用两次；直接空一行，程序同样会分开送达。'
    '公式、代码块和一个推导步骤内部不放分条标记。'
    '要申请程序允许的至多一次续写，在本次正文末尾写 [[WX_MORE]]；不申请就省略。'
    '控制标记须原样写在代码之外，只输出正文和控制标记，不解释协议。'
)
CONTINUATION = (
    '【一次补充机会】上面的 assistant 正文已经逐条发给用户。'
    '此次最多追加一条正文，不再使用 [[WX_BREAK]] 或 [[WX_MORE]]。'
    '不追加时只输出 [[WX_END]]，不要把结束标记与正文同时输出。'
    '控制标记须原样写在代码之外；只输出正文或结束标记，不输出协议说明。'
)


def _replace_once(value, old, new, label):
    if value.count(old) != 1:
        raise ValueError(f'{label}: expected exactly one unchanged source block')
    return value.replace(old, new, 1)


def persona_core(card_path=CARD_PATH, pack=None):
    """Compile the candidate through the shared loader, with a shorter address."""
    from dialogue_architecture_v2 import persona_core as compile_card
    from dialogue_style import ADDRESS_STYLE as original_address

    # The shared loader deliberately tolerates unreadable cards; a controlled
    # trial must fail instead of silently running its missing-card fallback.
    data = json.loads(Path(card_path).read_text(encoding='utf-8-sig'))['data']
    for field in ('description', 'personality', 'scenario', 'system_prompt', 'mes_example'):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f'candidate card requires a nonempty {field}')
    persona = compile_card(card_path, pack)
    suffix = '\n' + original_address
    if not persona.endswith(suffix):
        raise ValueError('shared persona no longer ends with the address block')
    block = DAILY_REPLY_BLOCK if Path(card_path).name == 'persona.daily-examples.v1.json' else NO_REPEAT_BLOCK
    return persona[:-len(suffix)] + '\n' + ADDRESS_STYLE + '\n\n' + block


def compose_messages(persona, text, history, *, capabilities='', context_blocks=(),
                     timeline='', natural_chat=True, actor_names=('静香',),
                     outer_variant='no_frame', sensitive_topics=False):
    """Shared composition, with scoped candidate emotion and formatting text."""
    from enhanced_dialogue import compose_messages as shared_compose
    from interaction_frame import contract_text
    from dialogue_architecture_v2 import output_contract

    messages = shared_compose(persona, text, history, capabilities=capabilities,
        context_blocks=context_blocks, timeline=timeline, natural_chat=natural_chat,
        actor_names=actor_names, outer_variant=outer_variant, sensitive_topics=sensitive_topics)
    semantics = contract_text()
    candidate_semantics = _replace_once(semantics, EMOTION_ORIGINAL,
                                        EMOTION_CANDIDATE, 'emotion contract')
    output = output_contract()
    candidate_output = _replace_once(output, OUTPUT_ORIGINAL,
                                     OUTPUT_CANDIDATE, 'output contract')
    system = messages[0]['content']
    system = _replace_once(system, '\n\n' + semantics + '\n\n',
                           '\n\n' + candidate_semantics + '\n\n', 'assembled semantics')
    # A context quotation must not be rewritten along with the real block.
    system = _replace_once(system, output, candidate_output, 'assembled output')
    messages[0]['content'] = system
    return messages


def rewrite_segment_request(kwargs, *, final_guidance=''):
    """Copy a production-generated request before recording/sending it.

    Requires the exact initial protocol suffix and, for a continuation, the
    exact final system block. User text and earlier system/history quotations
    are untouched. Plain/JSON calls should not use this segmented-only adapter.
    Optional guidance is appended once to the last system, after the protocol.
    """
    import weixin_segments as segments

    if not isinstance(final_guidance, str):
        raise TypeError('final_guidance must be a string')
    messages = deepcopy(kwargs.get('messages'))
    if (not isinstance(messages, list) or len(messages) < 2 or
            messages[0].get('role') != 'system' or
            not isinstance(messages[0].get('content'), str)):
        raise ValueError('segmented request requires a leading system and dialogue')
    suffix = '\n\n' + segments.INSTRUCTION
    if not messages[0]['content'].endswith(suffix):
        raise ValueError('missing exact production segment instruction suffix')
    messages[0]['content'] = messages[0]['content'][:-len(suffix)] + '\n\n' + INSTRUCTION
    if messages[-1].get('role') == 'system':
        if (messages[-1].get('content') != segments.CONTINUATION or
                messages[-2].get('role') != 'assistant'):
            raise ValueError('unexpected continuation request shape')
        messages[-1]['content'] = CONTINUATION
    elif messages[-1].get('role') != 'user':
        raise ValueError('initial segmented request must end with the current user')
    if final_guidance:
        for message in reversed(messages):
            if message.get('role') == 'system':
                message['content'] += '\n\n' + final_guidance
                break
    return dict(kwargs, messages=messages)


def generate(client, kwargs, progress, clean, on_sent, acquire=lambda: None, *,
             final_guidance='', retry_empty=None):
    """Reuse production delivery with candidate prompts before client recording.

    No transport is created here. Trials supply an in-memory ReplyProgress sink.
    Production stream parsing, delivery bounds and continuation guards remain
    unchanged, including the 1200-token limit on the optional second request.
    """
    import weixin_segments as segments

    # Validate the initial shape before production's error handler can turn a
    # configuration mistake into a generated-reply failure or fallback message.
    preview = deepcopy(kwargs.get('messages'))
    if (not isinstance(preview, list) or not preview or
            preview[0].get('role') != 'system' or
            not isinstance(preview[0].get('content'), str)):
        raise ValueError('candidate generation requires a leading system')
    preview[0]['content'] += '\n\n' + segments.INSTRUCTION
    rewrite_segment_request(dict(kwargs, messages=preview), final_guidance=final_guidance)
    transform_errors = []

    def create(**request):
        try:
            actual = rewrite_segment_request(request, final_guidance=final_guidance)
        except (ValueError, TypeError) as error:
            transform_errors.append(error)
            raise
        return client.chat.completions.create(**actual)

    proxy = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = segments.generate(proxy, kwargs, progress, clean, on_sent, acquire, retry_empty=retry_empty)
    if transform_errors:
        raise transform_errors[0]
    return result
