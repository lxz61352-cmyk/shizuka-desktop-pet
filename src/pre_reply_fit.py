"""回复前的一次接话判断，供桌面端与微信端共用。

模块本身是 `response_fit`（试验模块，标签与指令都在那里）；这里只负责"调一次、
校验、把白名单标签与固定指引拼成一段 system 追加文本"。

受控对照（`测试记录/接话判断受控对照-2026-09-30/`）：A 直接回复、B 先判断再回复、
C 再删一次。用户评分认为 **B 更自然**，因此把它接进来。

失败一律返回空串——判断是增益，不是必经步骤，不能因为它让回复发不出去。
"""
from copy import deepcopy

REVISION = 'pre-reply-fit-bridge-v1'


def should_assess_fit(profile):
    """限速配置已先做情绪判断；不再多占一个请求槽延迟正文。"""
    return float((profile or {}).get('min_interval') or 0) <= 0


def guidance_block(client, model, visible, *, acquire=lambda: None, timeout=45, max_tokens=400):
    """返回要追加到 system 的接话参考；任何失败返回空串。

    `visible` 是 role/content 的对话列表，最后一条必须是最新用户消息。
    """
    try:
        import response_fit as fit
        request = fit.assessment_messages(visible)
    except Exception:
        return ''
    try:
        acquire()
        text = ''
        with client.chat.completions.create(
                model=model, messages=deepcopy(request), temperature=0, max_tokens=max_tokens,
                response_format={'type': 'json_object'},
                extra_body={'thinking': {'type': 'disabled'}}, stream=True,
                wait_seconds=timeout) as stream:
            for chunk in stream:
                for choice in getattr(chunk, 'choices', None) or ():
                    value = getattr(getattr(choice, 'delta', None), 'content', None)
                    if isinstance(value, str):
                        text += value
        plan = fit.validate(text, visible)
        return fit.render(plan)
    except Exception:
        return ''
