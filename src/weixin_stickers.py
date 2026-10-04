"""微信表情包：按情绪和强度挑一张，按概率决定发不发，走已验证的上传与发送。

协议只支持图片（`MessageItemType` 里没有表情类型），所以表情包以**图片气泡**送达。
发送要三步（见 测试记录/微信发图验证-2026-10-01/）：
  getuploadurl → POST 密文到 CDN（响应头 x-encrypted-param）→ sendmessage 的 image_item

素材与词条：
  data/stickers/index.json  登记表；文件名本身也带词条（`名称_最低强度_别名.png`）

三条保守规则：
  · 任何失败都只是"这次不发"，绝不抛错影响正常回复；
  · 同一个表情不连着发第二次；
  · 概率是额外闸门——判到了情绪也未必发，避免刷屏。
"""
import base64
import hashlib
import json
import random
import secrets
from pathlib import Path
from urllib import parse, request

REVISION = 'weixin-stickers-v1'
CDN_BASE = 'https://novac2c.cdn.weixin.qq.com/c2c'
UPLOAD_TYPE_IMAGE = 1
# 用户 2026-10-01 决定：门槛先定 clear（实测 strong 极少出现，绑死在它上面等于功能不存在）。
DEFAULT_MIN_INTENSITY = 'clear'

# 概率上限：**任何配置都不许把概率推到 1.0**。
# 这是「发送时机全部走概率」的真正保证——系数或单张图的 chance 写错
# 也变不成必发。
MAX_CHANCE = 0.5
DEFAULT_CHANCE = 0.35
# 情绪系数：越常见的情绪，发图越克制。生效概率 = 全局 chance × 系数。
# 用户 2026-10-01 提的：`amused`（觉得好笑）在日常里出现得最多，直接挂表情包会太频繁。
# 十一个情绪**全部显式给系数**。
# 原来只写了三个，其余走缺省的 1.0——等于「有没有写」决定了概率，
# 缺省那条路没设防。
DEFAULT_EMOTION_WEIGHT = {"amused": 0.4, "pleased": 0.4, "speechless": 0.5, "puzzled": 0.5, "annoyed": 0.5, "embarrassed": 0.5, "sad": 0.6, "concerned": 0.6, "excited": 0.7, "surprised": 0.7, "neutral": 0.0}
ORDER = {'none': 0, 'light': 1, 'clear': 2, 'strong': 3}


class StickerBook:
    """读登记表、挑图、记最近发过哪张。"""

    def __init__(self, root, *, rng=None, chance=None):
        self.root = Path(root)
        self.index = self.root / 'index.json'
        self.rng = rng or random.random
        self._chance = chance

    def load(self):
        try:
            data = json.loads(self.index.read_text('utf-8'))
        except Exception:
            return []
        rows = data.get('stickers')
        return [r for r in rows if isinstance(r, dict) and r.get('file')] if isinstance(rows, list) else []

    def policy(self):
        try:
            data = json.loads(self.index.read_text('utf-8'))
            value = data.get('policy')
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    @property
    def chance(self):
        """全局基准概率。"""
        if self._chance is not None:
            return float(self._chance)
        try:
            return float(self.policy().get('chance', DEFAULT_CHANCE))
        except Exception:
            return DEFAULT_CHANCE

    def chance_for(self, row, emotion):
        """这一张、这个情绪的实际概率。

        两层：单张图可以覆盖自己的概率；否则用 全局 chance × 情绪系数。
        系数是"越常见的情绪越克制"那条政策的载体——加新表情时不用一个个调。
        """
        own = row.get('chance') if isinstance(row, dict) else None
        if isinstance(own, (int, float)) and 0.0 <= float(own) <= 1.0:
            # 单张图也受上限约束：配置写 1.0 只会被压到 MAX_CHANCE，不会变成必发
            return min(MAX_CHANCE, float(own))
        weights = self.policy().get('emotion_weight')
        if not isinstance(weights, dict):
            weights = DEFAULT_EMOTION_WEIGHT
        try:
            weight = float(weights.get(emotion, 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        return max(0.0, min(MAX_CHANCE, self.chance * weight))

    def path_of(self, row):
        return self.root / str(row['file'])

    def pick(self, emotion, intensity, *, exclude=None):
        """按情绪与强度挑一张；不该发就返回 None。

        强度门槛取登记表里每一项的 min_intensity（缺省用全局政策）。
        """
        if not emotion or emotion == 'neutral':
            return None
        level = ORDER.get(str(intensity), 0)
        matched = []
        for row in self.load():
            if emotion not in (row.get('emotion'), *(row.get('aliases') or [])):
                continue
            need = ORDER.get(str(row.get('min_intensity') or DEFAULT_MIN_INTENSITY), 2)
            if level < need:
                continue
            path = self.path_of(row)
            if not path.is_file():
                continue
            if exclude and row['file'] == exclude:
                continue
            matched.append(row)
        if not matched:
            return None
        # 概率按"这一张 + 这个情绪"算，不是全局一个数。
        row = matched[int(self.rng() * len(matched)) % len(matched)]
        if self.rng() >= self.chance_for(row, emotion):
            return None
        return row


def review_messages(peer, data, aeskey):
    return {'filekey': secrets.token_hex(16), 'media_type': UPLOAD_TYPE_IMAGE, 'to_user_id': peer,
            'rawsize': len(data), 'rawfilemd5': hashlib.md5(data).hexdigest(),
            'filesize': len(data) + (16 - len(data) % 16), 'no_need_thumb': True,
            'aeskey': aeskey.hex()}


def aes_key_field(aeskey):
    """image_item.media.aes_key 的取值——**不是** base64(16 字节原始密钥)。

    官方 SDK（src/cdn/upload.ts 存 `aeskey.toString("hex")`，
    src/messaging/send.ts 发 `Buffer.from(uploaded.aeskey).toString("base64")`）
    实际发出去的是 **base64(那 32 个字符的 hex 字符串)**，共 44 字符。

    这个差别不是格式偏好，是能不能显示的问题。实测（2026-10-01，同一张图连发两条）：
      · base64(16 字节原始密钥)，24 字符 → 微信显示「图片已过期或已被清理」
      · base64(hex 字符串)，44 字符     → 正常显示
    所以**必须**按官方这个写法，不要"顺手简化"回 24 字符。
    """
    return base64.b64encode(aeskey.hex().encode('ascii')).decode('ascii')


def send_image(client, peer, context, path, client_id):
    """把一张本地图片发到微信。成功返回 **message_id**（供引用缓存用），失败返回空串。

    返回 message_id 而不是单纯 True/False，是因为发送方要拿它写进引用缓存——
    不写的话，用户引用这张表情包再问时查不到原文，会回
    「这条引用的原消息没有保存在本机」。文本回复在 `_send` 里就是这么做的。
    """
    from weixin_channel import aes_ecb_encrypt
    try:
        data = Path(path).read_bytes()
    except Exception:
        return ''
    if not data:
        return ''
    aeskey = secrets.token_bytes(16)
    payload = review_messages(peer, data, aeskey)
    try:
        uploaded = client.call('getuploadurl', payload, timeout=30)
        if uploaded.get('ret') not in (0, None):
            return ''
        full = (uploaded.get('upload_full_url') or '').strip()
        param = uploaded.get('upload_param')
        if not full and not param:
            return ''
        url = full or (CDN_BASE + '/upload?encrypted_query_param=' + parse.quote(param, safe='')
                       + '&filekey=' + parse.quote(payload['filekey'], safe=''))
        body = aes_ecb_encrypt(aeskey, data)
        req = request.Request(url, data=body, method='POST',
                              headers={'Content-Type': 'application/octet-stream'})
        with request.urlopen(req, timeout=60) as response:
            download_param = response.headers.get('x-encrypted-param')
        if not download_param:
            return ''
        item = {'type': 2, 'image_item': {
            'media': {'encrypt_query_param': download_param,
                      'aes_key': aes_key_field(aeskey), 'encrypt_type': 1},
            'mid_size': payload['filesize']}}
        out = client.call('sendmessage', {'msg': {
            'from_user_id': '', 'to_user_id': peer, 'client_id': client_id,
            'message_type': 2, 'message_state': 2, 'context_token': context,
            'item_list': [item]}}, timeout=30)
        return str((out or {}).get('message_id') or '')
    except Exception:
        return ''
