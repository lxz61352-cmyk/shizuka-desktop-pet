"""Content rules for unsolicited conversation, never for requested replies."""
import re

INSTRUCTION=('主动搭话不介绍、评价或推荐消费产品，不提品牌型号、产品配色、价格、购买选择或新品发布。'
             '不要借日常闲聊、已知兴趣或旧消息把商品话题带回来。'
             '可以有不同方向，不必每次提问。不要索要或推测用户的具体位置、联系方式、身份、'
             '收入财务、感情关系或健康隐私，不追查谁在身边、做了什么或事情进展。'
             '资料中出现产品也不是主动聊产品的许可；没有合适内容时保持安静。')

_DEVICES=re.compile(
    r'耳机|耳塞|手机|平板|相机|镜头|音箱|音响|键盘|鼠标|显示器|显卡|游戏机|'
    r'笔记本电脑|智能手表|智能手环|路由器|充电器|充电宝|数码产品|'
    r'家电|冰箱|洗衣机|扫地机|吸尘器|新车|车型|购车|护肤品|化妆品|保健品|产品型号|'
    r'\b(?:headphones?|earbuds?|smartphones?|AirPods|iPhone|iPad|MacBook|Galaxy|PlayStation|Xbox)\b',re.I)
_PROMOTION=re.compile(
    r'新品|新款|新产品|新机|售价|价格|开卖|开售|预售|促销|优惠|领券|种草|带货|性价比|'
    r'买哪(?:个|款)|值得(?:买|入手)|推荐.{0,8}(?:购买|入手|产品)|'
    r'(?:[¥￥$]\s*\d|\d+(?:\.\d+)?\s*(?:元|块钱|美元))')
_PRIVATE=re.compile(r'住址|身份证|手机号|电话号码|联系方式|银行卡|存款|债务|病历|诊断|密码|'
                    r'你的.{0,4}(?:收入|工资|感情|恋爱)|你.{0,8}(?:赚多少|收入多少|工资多少|住哪|住在|在哪里|在哪儿|在哪个|具体位置|具体地址|有没有对象|和谁在一起)|'
                    r'你.{0,8}(?:在哪(?:[？?，。]|$)|跟谁住|和谁住|喜欢谁|病情|感情状况|真实姓名)|'
                    r'(?:发我|告诉我|给我|说说|报一下).{0,10}(?:位置|定位|地址|收入|工资|感情|病情)')


def product_topic(text):
    return bool(_DEVICES.search(str(text or '')) or _PROMOTION.search(str(text or '')))


def private_topic(text):
    return bool(_PRIVATE.search(str(text or '')))


def unsuitable(text):
    return product_topic(text) or private_topic(text)


def prior_openings(history,limit=8):
    """Past openings are repetition warnings, never a source for a new topic."""
    return [r.get('text','') for r in history[-limit:] if not unsuitable(r.get('text',''))]
