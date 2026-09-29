"""O1 controlled outer-layer trial; no persona edits or response rewriting."""

REVISION = 'outer-o1-v1'
VARIANTS = ('baseline', 'no_frame', 'conversational')
LABELS = {
    'baseline': 'A · 当前外层',
    'no_frame': 'B · 去掉粗分类',
    'conversational': 'C · 简短接话原则',
}
CONVERSATIONAL = (
    '【接话方式】这是与熟人的一次来回。随口分享或玩笑，先给你对眼前内容的反应；'
    '这个反应本身就可以是整条回复，有具体的新内容想说时再接着说。'
    '问句来自你真正好奇的细节或回答所缺的信息，已经知道的事不用再问。'
    '需要帮忙时再展开办法；普通接话或拒绝之后可以停，不必再安排事情、点评或另找话题。'
    '按当时的语气说，允许省略双方明白的成分、自然的语气词和半句话，长短随内容变化。'
    '认真问题要回答充分，保留准确的事实、推导和必要格式，口吻不影响讲解。'
)


def validate_variant(value):
    if value not in VARIANTS:
        raise ValueError('未知的外层实验版本。')
    return value


def render_blocks(frame_text, semantics, output_format, variant='baseline'):
    validate_variant(variant)
    parts = [frame_text] if variant == 'baseline' else []
    parts.append(semantics)
    if variant == 'conversational':
        parts.append(CONVERSATIONAL)
    parts.append(output_format)
    return '\n\n'.join(parts)
