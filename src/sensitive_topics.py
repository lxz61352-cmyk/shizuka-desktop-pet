"""One persisted content preference for desktop and WeChat (not a keyword ban)."""
SETTING = 'sensitive_topics'
ATTRIBUTE = '_sensitive_topics_on'
LABEL = '敏感话题模式'
HELP = ('关闭：遇到荤话或性化互动，简短收住这个话题，仍可继续普通聊天。\n\n'
        '开启：可回应非露骨的成人话题，不主动展开色情内容。\n\n'
        '两种模式都保留正常感情交流、健康知识、普通新闻和游戏讨论；'
        '不开放色情描写、未成年人性化互动、极端主义宣扬或现实伤害指导。\n\n'
        '桌面和微信共用，保存后从下一条回复生效，重启后保留。')


def enabled(app):
    value=getattr(app,ATTRIBUTE,None)
    if value is None:
        value=(getattr(app,'_settings',None) or {}).get(SETTING,False)
    return value is True


def policy(allow=False):
    mode=('当前敏感话题模式：开启。可自然回应成年人之间非露骨的玩笑或成人话题，'
          '但不主动挑起、追问性细节或升级尺度。' if allow is True else
          '当前敏感话题模式：关闭。用户开荤话或要求性化互动时，用角色口吻简短收住该话题；'
          '收住后就停，不问为什么想聊这个，不补充或换一种说法延续。用户换回普通话题就正常继续，不结束程序或所有聊天。')
    return ('【本轮话题设置】'+mode+
            '模式优先于旧对话或角色卡中的尺度描述。两种模式都不生成色情描写、性行为细节，'
            '不进行涉及未成年人或年龄不明、学生角色的性化互动。'
            '极端主义宣扬、现实伤害指导、严重侮辱性低俗请求简短拒绝。'
            '正常感情交流、性健康科普、求助、普通政治新闻以及游戏或作品中的战斗讨论照常回答；'
            '根据语境区分，不按关键词误拦，也不向用户解释这段设置。')
