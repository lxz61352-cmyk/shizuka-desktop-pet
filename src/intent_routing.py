"""Local fast paths never infer side effects from quoted text or discussion."""
import re

RESOURCE = r'文件|文件夹|目录|桌面|硬盘|磁盘|工作区|回收站|截图|[A-Za-z]:[\\/]|\.(?:txt|md|pdf|pptx?|docx?|xlsx?|csv|py|json)\b'
ACTION = r'读取|打开|查找|搜索|查一下|查看|创建|新建|生成|制作|编辑|修改|整理|复制|移动|重命名|删除|保存|列出'

_TOPIC = r'(?:进展|动态|更新|论文|文献|paper|研究)'
_REFERENCE = r'这个|那个|这篇|那篇|刚才|之前|上面|你说|你讲|你提|教我|解释|区别'
# 「怎么查最新论文」是在问方法，不是要我汇报进展
_HOWTO = r'(?:怎么|如何|怎样|在哪)(?:查|找|搜|看|读|获取|下载|订阅|设|开|关)'


def research_question(text):
    """聊天框里问「最新进展 / 最近有什么新论文」这类：本地直接认，不必等模型路由器。
    指代某一篇（这篇/那篇/刚才…）的追问不算——那是在聊具体的文献。"""
    t = (text or "").strip()
    if not t or len(t) > 30:
        return False
    if re.search(_REFERENCE, t) or re.search(_HOWTO, t):
        return False
    if not re.search(_TOPIC, t, re.I):
        return False
    return bool(re.search(r'最新|最近|近期|新(?:的)?(?:论文|文献)|有没有|有什么', t))


_API_TOPIC = r'(?:接口|api)'
_API_ASK = r'(?:哪个|哪一个|哪一?种|什么|啥|类型|模式|是不是|用的?是|走的?是|还是)'
# 说「接口/API」但其实是聊代码的，别抢过来答自己那点事（「类型」不算「类」）
_API_CODE = r'代码|函数|类(?!型)|封装|重构|实现|设计|单测|怎么写|怎么用|文档|签名|重载'


def api_question(text):
    """问「现在用的是 chat 还是 response 接口」这类：本地直接回答，不经过模型。

    两条接口是同一个模型同一套提示词，回复内容上看不出区别，
    只能由桌宠照实报自己这次请求走的端点，顺带可以现场验一条。
    """
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    if not re.search(_API_TOPIC, t, re.I):
        return False
    if re.search(_API_CODE, t, re.I):
        return False
    if re.search(r'chat|responses?', t, re.I):
        return True                                    # 直接问两条路里的哪一条
    if re.search(r'(?:接口|api)[^，。！？\s]{0,4}(?:类型|模式)', t, re.I):
        return True                                    # 「接口类型是什么」「接口用什么类型」
    if re.search(r'(?:测|试|验|检查)\s*(?:一下|一遍)?\s*(?:接口|api)', t, re.I):
        return True                                    # 「测一下接口」
    return bool(re.search(r'现在|当前|你', t) and re.search(_API_ASK, t))


def api_wants_test(text):
    """不只是问，还想现场验一下（「测一下接口」「验一下 response」）。"""
    return bool(re.search(r'测|试|验|检查', text or ''))


def local_intent(text):
    # Return None only when the short model router is useful.
    # 注意：这里没命中的一律直接当 chat（不走模型路由器），所以「使用时长」这类词必须列进来。
    if research_question(text):
        return {'action': 'research'}
    if api_question(text):
        return {'action': 'api_info'}
    if not re.search(RESOURCE + r'|待办|提醒|记忆|记住|记得|论文|研究进展|进展|文献|完成|做完|搞定|弄完|弄好|做好了'
                     r'|使用时长|窗口时长|窗口使用|使用统计|时长统计|用了多久|用了多长时间'
                     r'|用了哪些|用了什么|都在忙什么|忙了些什么'
                     r'|天气|气温|温度|下雨|下雪|带伞|冷不冷|热不热|穿什么|穿衣|多少度'
                     r'|新闻|有什么新鲜事|今天发生了什么',
                     text, re.I):
        return {'action': 'chat'}
    # A direct instruction with a concrete local resource can start DSH immediately.
    # Questions about ability, hypothetical/negative instructions still go to the router.
    command=r'^(?:(?:请(?:你)?|麻烦(?:你)?)(?:帮我|替我)?|帮我|替我|给我)(?:在[^，。！？“”「」"`]{1,90})?(?:'+ACTION+r')'
    discussion=r'不要|别|不必|不用|如果|假如|假设|能不能|如何|怎么|怎样|为何|什么|为什么|告诉|教我|介绍|解释|讲解|讲讲|方法|教程|建议|示例|语法|意思|学会|讨论|说明|流程|思路|是否|能否|是不是|可不可以|吗|[？?“”‘’「」"`]'
    if (re.match(command, text) and re.search(RESOURCE, text, re.I)
            and not re.search(discussion, text)):
        return {'action': 'computer_task'}
    return None


def router_prompt(text):
    return ('判断用户当前意图，只输出JSON {"action":"chat","content":"原文中提及的事项","content_clear":true}。'
            'action只能为chat/query_todo/delete_todo/complete_todo/research/computer_task/add_todo/usage_report/weather/news。'
            '普通聊天、能力咨询、操作方法、假设和引用均chat；明确本地文件读写、查找、整理任务为computer_task；'
            '询问待办query_todo；明确删除或完成待办用delete_todo/complete_todo；'
            '用户说某件事已经做完、做好、搞定、检查过了（如「收到，已经检查了」「已经喝了水了」），'
            '而这件事对得上现有待办时用 complete_todo，content 填他说的那件事（没点名就用他的原话）；'
            '请求查最新研究论文用research；'
            '设置新待办用add_todo：content 填去掉「提醒我/记一下/帮我」等前缀后的事项本身（如“晾衣服”“给妈妈打电话”），'
            'content_clear 为 true；只说时间没说做什么（如“提醒我明天9点”）则 content 留空、content_clear 为 false。'
            '询问天气、气温、下雨下雪、冷不冷热不热、要不要带伞、穿什么（如“今天天气怎么样”“会下雨吗”“要带伞吗”）用weather；'
            '要求或询问新闻（如“讲个新闻”“今天有什么新闻”）用news；'
            '要求查看今天在电脑上的使用时长/窗口使用统计（如“看看我今天用了多久”“今天用了哪些软件”'
            '“窗口使用统计”“窗口使用时长”“汇报一下使用时长”“统计一下今天用了多久”'
            '“今天都在忙什么”）用usage_report。其他字段不需要。'
            '询问“你记得什么/记过哪些事”一律归chat，由对话自然回答，不要罗列记忆清单。用户资料：'+text)
