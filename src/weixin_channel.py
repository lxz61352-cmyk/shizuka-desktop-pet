"""Text-only Weixin iLink transport, owner binding and durable duplicate guard.

Protocol reference: https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol.md
No desktop WeChat automation, no OpenClaw runtime, no model credentials here.
"""
import base64
import hashlib
import json
from pathlib import Path
import queue
import re
import secrets
import socket
import threading
import time
from urllib import error, parse, request
from computer_agent import write_json

BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"
CHANNEL_VERSION = "2.4.8"
IMAGE_MAX_BYTES = 16 * 1024 * 1024
COMMAND_RE = re.compile(r"^/(?:电脑|文件|dsh)(?=$|\s|[:：])", re.I)
# 文字里出现这些词，说明用户在指代某张图片
IMAGE_WORD_RE = re.compile(r"图\s*(?:\d|[一二三四五六七八九十]+)|第\s*[0-9一二三四五六七八九十]+\s*张|倒数|最新|刚才|刚刚|上一张|最后一张|这张|那张|该图|图片|照片|截图|图像", re.I)
# 出现这些动词，说明用户是在「拿图片做事」，而不是随口提一句
ACTION_RE = re.compile(r"做|写|生成|整理|改|转|处理|分析|识别|提取|翻译|制作|搞|弄|用|根据|基于")
LATEST_IMAGE_HOURS = 1 / 6    # 没指定图片时，多久内收到的最新图片默认带上（10 分钟）
LATEST_IMAGE_COUNT = 2        # 没指定图片时默认带几张：带两张，方便「那第二问呢」这类追问
CURRENT_IMAGE_COUNT = 3       # 本条消息自带图片时最多带几张
IMAGE_BLOCK_MARK = "[图片]"    # 提示块标记：上层据此判断「这条消息带了图片」
# 像在问/看图的口吻 → 默认把最新图片带上
IMAGE_ASK_RE = re.compile(r"[?？]|吗|呢|谁|什么|哪|怎么|为什么|为啥|是不是|多少|几|如何|怎样|认得|认得出|看得出|看看|瞧瞧|瞅瞅|解读|讲讲|讲下|讲解|说说|说一下|解释")
PENDING_IMAGE_SECONDS = 900   # 反问「哪一张」后等用户回答的有效时间
PENDING_TEXT_SECONDS = 180    # 用户先说「附图…」后，等图片发过来的时间
# 「附图 / 见图 / 如图…」这类说法 = 图片随后就到，先说任务再等图
ATTACH_WORD_RE = re.compile(r"附图|见图|如图|见下|见上|附上|附件|下附|图中|图里|这张图|那张图|这幅图|上面的图|下面的图")
_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
SEEN_TTL_SECONDS = 30 * 24 * 3600   # 已处理消息的去重记录保留多久（秒）
SEEN_MAX = 10000                    # 去重记录的硬上限，防御短时间被灌爆


def _day_label(day):
    """'20260916' → '9月16日'；识别不了就原样返回。"""
    text = str(day or "")
    if len(text) == 8 and text.isdigit():
        return "%d月%d日" % (int(text[4:6]), int(text[6:8]))
    return text


def cn_number(value):
    """把「2 / 二 / 十二 / 二十三」这类说法转成整数，识别不了返回 0。"""
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    if text in _CN_DIGITS:
        return _CN_DIGITS[text]
    if text == "十":
        return 10
    if len(text) == 2 and text[0] == "十" and text[1] in _CN_DIGITS:
        return 10 + _CN_DIGITS[text[1]]
    if len(text) == 2 and text[1] == "十" and text[0] in _CN_DIGITS:
        return _CN_DIGITS[text[0]] * 10
    if len(text) == 3 and text[1] == "十" and text[0] in _CN_DIGITS and text[2] in _CN_DIGITS:
        return _CN_DIGITS[text[0]] * 10 + _CN_DIGITS[text[2]]
    return 0


def trusted_cdn(value):
    """CDN 下载地址只允许 HTTPS 微信域名，避免把服务器返回的任意 URL 当下载源。"""
    url = parse.urlsplit(value)
    host = (url.hostname or "").lower()
    if (url.scheme != "https" or not host.endswith(".weixin.qq.com")
            or url.username or url.password or url.port not in (None, 443)):
        raise ValueError("图片下载地址不属于受支持的 HTTPS 微信域名")
    return value


def decode_aes_key(value):
    """图片密钥：32 位十六进制，或 base64(16 字节原始密钥 / 32 位十六进制字符串)。"""
    if isinstance(value, (bytes, bytearray)):
        text = bytes(value).decode("ascii", "ignore")
    else:
        text = str(value or "")
    text = text.strip()
    if not text:
        return b""
    if len(text) == 32 and all(c in "0123456789abcdefABCDEF" for c in text):
        return bytes.fromhex(text)
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception:
        return b""
    if len(raw) == 16:
        return raw
    if len(raw) == 32:
        try:
            return bytes.fromhex(raw.decode("ascii"))
        except Exception:
            return b""
    return b""


def aes_ecb_decrypt(key, data):
    """AES-128-ECB + PKCS#7 解密，走 Windows CNG（不引入第三方依赖）。"""
    import ctypes
    from ctypes import wintypes
    bcrypt = ctypes.WinDLL("bcrypt", use_last_error=True)
    ULONG, PULONG = wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)
    bcrypt.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(ctypes.c_void_p), wintypes.LPCWSTR, wintypes.LPCWSTR, ULONG]
    bcrypt.BCryptOpenAlgorithmProvider.restype = ctypes.c_long
    bcrypt.BCryptSetProperty.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_char_p, ULONG, ULONG]
    bcrypt.BCryptSetProperty.restype = ctypes.c_long
    bcrypt.BCryptGetProperty.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_char_p, ULONG, PULONG, ULONG]
    bcrypt.BCryptGetProperty.restype = ctypes.c_long
    bcrypt.BCryptGenerateSymmetricKey.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p, ULONG, ctypes.c_char_p, ULONG, ULONG]
    bcrypt.BCryptGenerateSymmetricKey.restype = ctypes.c_long
    bcrypt.BCryptDecrypt.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ULONG, ctypes.c_void_p, ctypes.c_char_p, ULONG, ctypes.c_char_p, ULONG, PULONG, ULONG]
    bcrypt.BCryptDecrypt.restype = ctypes.c_long
    bcrypt.BCryptDestroyKey.argtypes = [ctypes.c_void_p]
    bcrypt.BCryptCloseAlgorithmProvider.argtypes = [ctypes.c_void_p, ULONG]
    algorithm = ctypes.c_void_p()
    if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm), "AES", None, 0) != 0:
        raise ValueError("系统不支持 AES 解密")
    key_handle = ctypes.c_void_p()
    try:
        mode = ctypes.create_unicode_buffer("ChainingModeECB")
        bcrypt.BCryptSetProperty(algorithm, "ChainingMode", ctypes.cast(mode, ctypes.c_char_p), ctypes.sizeof(mode), 0)
        object_length = ULONG()
        bcrypt.BCryptGetProperty(algorithm, "ObjectLength", ctypes.cast(ctypes.byref(object_length), ctypes.c_char_p),
                                 ctypes.sizeof(object_length), ctypes.byref(ULONG()), 0)
        key_object = ctypes.create_string_buffer(object_length.value)
        if bcrypt.BCryptGenerateSymmetricKey(algorithm, ctypes.byref(key_handle), key_object, object_length.value,
                                             key, len(key), 0) != 0:
            raise ValueError("图片密钥无法用于解密")
        output = ctypes.create_string_buffer(len(data) + 16)
        written = ULONG()
        status = bcrypt.BCryptDecrypt(key_handle, data, len(data), None, None, 0, output, len(output),
                                      ctypes.byref(written), 0)
        if status != 0:
            raise ValueError("图片解密失败")
        plain = output.raw[:written.value]
        pad = plain[-1] if plain else 0
        if 1 <= pad <= 16 and plain.endswith(bytes([pad]) * pad):
            plain = plain[:-pad]
        return plain
    finally:
        if key_handle:
            bcrypt.BCryptDestroyKey(key_handle)
        bcrypt.BCryptCloseAlgorithmProvider(algorithm, 0)


def image_extension(data):
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    return ".jpg"


def trusted_base(value):
    url = parse.urlsplit(value)
    host = (url.hostname or "").lower()
    if (url.scheme != "https" or not host.endswith(".weixin.qq.com")
            or url.username or url.password or url.port not in (None, 443)
            or url.path not in ("", "/") or url.query or url.fragment):
        raise ValueError("微信接口地址不属于受支持的 HTTPS 微信服务")
    return "https://" + host


class ApiError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__("微信接口返回错误（代码 %s）" % code)


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class CdnRedirect(request.HTTPRedirectHandler):
    """CDN 下载允许跳转，但每一跳都必须是受支持的 HTTPS 微信域名。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = parse.urljoin(req.full_url, newurl)
        trusted_cdn(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


class ILinkClient:
    def __init__(self, base=BASE_URL, token="", opener=None):
        self.base, self.token = trusted_base(base), token
        self.opener = opener or request.build_opener(NoRedirect())
        self.media_opener = request.build_opener(CdnRedirect())

    def download(self, media, aeskey=""):
        """下载微信图片（自动用 aeskey 解密）。"""
        if not isinstance(media, dict):
            raise ValueError("图片缺少下载信息")
        url = media.get("full_url") or ""
        if not url:
            parameter = media.get("encrypt_query_param")
            if not isinstance(parameter, str) or not parameter:
                raise ValueError("图片缺少下载地址")
            url = CDN_BASE + "/download?encrypted_query_param=" + parse.quote(parameter, safe="")
        with self.media_opener.open(request.Request(trusted_cdn(url), headers={"iLink-App-Id": "bot"}), timeout=60) as response:
            raw = response.read(IMAGE_MAX_BYTES + 1)
        if len(raw) > IMAGE_MAX_BYTES:
            raise ValueError("图片超过 16MB，已跳过")
        key = decode_aes_key(aeskey) or decode_aes_key(media.get("aes_key"))
        return aes_ecb_decrypt(key, raw) if key else raw

    def call(self, endpoint, payload=None, timeout=20):
        headers = {"iLink-App-Id": "bot", "iLink-App-ClientVersion": str((2 << 16) | (4 << 8) | 8)}
        body = None
        if payload is not None:
            headers.update({"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
                "X-WECHAT-UIN": base64.b64encode(str(secrets.randbits(32)).encode()).decode()})
            payload = dict(payload)
            if self.token:
                headers["Authorization"] = "Bearer " + self.token
                payload["base_info"] = {"channel_version": CHANNEL_VERSION, "bot_agent": "ShizukaAssistant/0.1.0"}
            body = json.dumps(payload, ensure_ascii=False).encode("utf8")
        req = request.Request(self.base + "/ilink/bot/" + endpoint, data=body, headers=headers)
        try:
            with self.opener.open(req, timeout=timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("微信接口响应过大")
            result = json.loads(raw)
        except error.HTTPError as exc:
            raise ApiError("HTTP " + str(exc.code)) from None
        except (TimeoutError, socket.timeout):
            raise TimeoutError("微信连接等待超时") from None
        except error.URLError:
            raise ConnectionError("暂时无法连接微信服务，请检查网络") from None
        if not isinstance(result, dict):
            raise ValueError("微信接口响应格式异常")
        for key in ("ret", "errcode"):
            if result.get(key) not in (None, 0):
                raise ApiError(result[key])
        return result

    def qr(self):
        result = self.call("get_bot_qrcode?bot_type=3", {"local_token_list": []})
        if not all(isinstance(result.get(k), str) and result[k] for k in ("qrcode", "qrcode_img_content")):
            raise ValueError("微信服务未返回有效二维码")
        return result

    def qr_status(self, code, verify=""):
        query = {"qrcode": code}
        if verify:
            query["verify_code"] = verify
        return self.call("get_qrcode_status?" + parse.urlencode(query), timeout=35)

    def updates(self, cursor):
        return self.call("getupdates", {"get_updates_buf": cursor}, timeout=40)

    def send(self, peer, context, text, client_id):
        if not peer or not context:
            raise ValueError("缺少微信对话信息，无法回复")
        return self.call("sendmessage", {"msg": {"from_user_id": "", "to_user_id": peer,
            "client_id": client_id, "message_type": 2, "message_state": 2,
            "context_token": context, "item_list": [{"type": 1, "text_item": {"text": text}}]}})


class ProtectedStore:
    """Session, owner, cursor and replay journal encrypted with the host's codec."""
    def __init__(self, data_root, crypt):
        self.path = Path(data_root) / "weixin-state.json"
        self.crypt = crypt
        self.lock = threading.RLock()
        self.data = {"enabled": False, "allow_computer": False, "session": None,
                     "cursor": "", "seen": {}, "last_result": ""}
        if self.path.exists():
            wrapper = json.loads(self.path.read_text("utf8"))
            value = json.loads(crypt(base64.b64decode(wrapper["protected"], validate=True), False))
            if not isinstance(value, dict):
                raise ValueError("微信连接配置格式异常")
            self.data.update(value)

    def save(self):
        with self.lock:
            blob = self.crypt(json.dumps(self.data, ensure_ascii=False).encode("utf8"), True)
            write_json(self.path, {"version": 1, "protected": base64.b64encode(blob).decode("ascii")})

    def update(self, **values):
        with self.lock:
            self.data.update(values)
            self.save()

    def claim(self, message_id):
        with self.lock:
            seen = self.data["seen"]
            if message_id in seen:
                return False
            now = time.time()
            seen[message_id] = now
            # 按时间淘汰（不再只按条数）：老消息本来就过不了 receive() 里
            # create_time_ms >= bound_at-5 那道门，保留期与它对齐后判重语义才自洽。
            cutoff = now - SEEN_TTL_SECONDS
            for stale in [key for key, at in seen.items()
                          if not isinstance(at, (int, float)) or at < cutoff]:
                seen.pop(stale, None)
            # 再留一个硬上限：万一短时间被灌爆，也不让加密状态文件无限增长。
            while len(seen) > SEEN_MAX:
                del seen[next(iter(seen))]
            # Save BEFORE starting a file operation: interrupted tasks are never replayed.
            self.save()
            return True


def session_from_login(result):
    required = ("bot_token", "ilink_bot_id", "ilink_user_id")
    if not all(isinstance(result.get(k), str) and result[k] for k in required):
        raise ValueError("微信未返回完整的账号绑定信息，请重新扫码")
    return {"token": result["bot_token"], "bot_id": result["ilink_bot_id"],
            "owner": result["ilink_user_id"], "base": trusted_base(result.get("baseurl") or BASE_URL),
            "bound_at": time.time()}


class ImageIndex:
    """按天递增的图片序号 + 自然语言指代解析。索引存 <图片目录>/index.json。"""
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = {"day": "", "seq": 0, "items": []}
        try:
            if self.path.exists():
                loaded = json.loads(self.path.read_text("utf-8-sig"))
                if isinstance(loaded, dict):
                    self.data.update({k: loaded[k] for k in ("day", "seq", "items") if k in loaded})
        except Exception:
            pass

    def _save(self):
        try:
            write_json(self.path, self.data)
        except Exception:
            pass

    def add(self, build_path, label=""):
        """占用当天下一个序号并登记；build_path(n, day) 返回最终文件路径。"""
        with self.lock:
            day = time.strftime("%Y%m%d")
            if self.data.get("day") != day:
                self.data["day"] = day
                self.data["seq"] = 0
                self.data["items"] = []
            self.data["seq"] = int(self.data.get("seq", 0)) + 1
            record = {"n": self.data["seq"], "day": day,
                      "path": str(build_path(self.data["seq"], day)), "at": time.time(), "label": label}
            self.data["items"].append(record)
            del self.data["items"][:-50]
            self._save()
            return record

    def drop(self, record):
        with self.lock:
            self.data["items"] = [i for i in self.data["items"] if i.get("path") != record.get("path")]
            self._save()

    def recent(self, limit=5, hours=48):
        cutoff = time.time() - hours * 3600
        items = [i for i in self.data.get("items", [])
                 if i.get("at", 0) >= cutoff and Path(i.get("path", "")).is_file()]
        return items[-limit:]

    def note_for(self, records):
        """用户明确指了图时给模型的说明。

        序号按天重置，`resolve()` 会跨天回退到「最近一次用过这个序号」的图；命中里
        只要有不是今天的图，就必须写明是哪天的，否则模型会默默照着另一张图回答。
        """
        today = self.data.get("day")
        others = sorted({_day_label(r.get("day")) for r in records
                         if r.get("day") and r.get("day") != today and _day_label(r.get("day"))})
        if not others:
            return "用户指的是这些图片："
        return ("用户说的图N不是今天收到的（今天的编号里没有这个序号），下面是 "
                + "、".join(others) + " 的图；拿不准就请他重说是哪天的图N。")

    def resolve(self, text):
        """解析「图2 / 第2张 / 倒数第2张 / 最新那张」；返回 (命中的记录, 今天不存在的序号)。"""
        items = self.data.get("items", [])
        today = self.data.get("day")
        found, unknown = [], []

        def take(record):
            if record and record not in found:
                found.append(record)

        for match in re.finditer(r"倒数第\s*([0-9]+|[一二三四五六七八九十]+)\s*张", text):
            value = cn_number(match.group(1))
            if value and 1 <= value <= len(items):
                take(items[-value])
        for match in re.finditer(r"(?:今天)?(?:(?<!倒数)第\s*([0-9]+|[一二三四五六七八九十]+)\s*张|图\s*([0-9]+|[一二三四五六七八九十]+))", text):
            value = cn_number(match.group(1) or match.group(2))
            if not value:
                continue
            hit = [i for i in items if i.get("day") == today and i.get("n") == value]
            if not hit:
                # 序号按天重置；当天没有这个号时退回「最近一次用过这个序号」的图，别直接判不存在
                hit = [i for i in items if i.get("n") == value]
            if hit:
                take(hit[-1])
            elif value not in unknown:
                unknown.append(value)
        if re.search(r"最新(?:的)?(?:那|这)?张|刚才(?:那|这)?张|刚刚(?:那|这)?张|上一张|最后一张|这张|那张|附图|见图|如图|见下|附上", text):
            if items:
                take(items[-1])
        return found, unknown


class WeixinChannel:
    def __init__(self, store, responder, status=None, client=None, media_dir=None):
        self.store, self.responder = store, responder
        self.session = dict(store.data["session"] or {})
        if not self.session.get("owner") or not self.session.get("token"):
            raise ValueError("请先扫码绑定微信")
        self.client = client or ILinkClient(self.session["base"], self.session["token"])
        self.status = status or (lambda value: None)
        self.media_dir = media_dir
        self._images = None
        self.stopped = threading.Event()
        self.task_cancel = threading.Event()
        self.send_lock = threading.Lock()
        self.jobs = queue.Queue(maxsize=8)
        self.task_lock = threading.RLock()
        self.active = False
        self.answer_pending = None

    def start(self):
        self.poller = threading.Thread(target=self._poll, name="deskpet-weixin-poll", daemon=True)
        self.worker = threading.Thread(target=self._work, name="deskpet-weixin-task", daemon=True)
        self.worker.start()
        self.poller.start()

    def cancel_task(self):
        with self.task_lock:
            self.task_cancel.set()
            while True:
                try:
                    self.jobs.get_nowait()
                except queue.Empty:
                    break

    def stop(self):
        self.stopped.set()
        self.cancel_task()

    def reply(self, message, text, suffix="result"):
        if self.stopped.is_set():
            return
        text = str(text).strip() or "本轮没有返回文字结果。"
        if len(text) > 9000:
            text = text[:9000] + "\n（内容较长，完整文件任务结果请在电脑的任务记录中查看。）"
        for index in range(0, len(text), 1500):
            if self.stopped.is_set():
                break
            client_id = "deskpet-" + message["key"][:40] + "-" + suffix + "-" + str(index // 1500)
            with self.send_lock:
                self.client.send(self.session["owner"], message["context"], text[index:index+1500], client_id)

    def image_index(self):
        if self._images is None:
            try:
                base = Path(self.media_dir()) if callable(self.media_dir) else None
            except Exception:
                base = None
            if base is None:
                return None
            try:
                base.mkdir(parents=True, exist_ok=True)
            except Exception:
                return None
            self._images = ImageIndex(base / "index.json")
        return self._images

    def save_images(self, items, key):
        index = self.image_index()
        if index is None:
            return []
        saved = []
        for item in items:
            info = item.get("image_item")
            if not isinstance(info, dict):
                continue
            try:
                data = self.client.download(info.get("media") or {}, info.get("aeskey") or "")
            except Exception:
                continue
            if not data:
                continue
            extension = image_extension(data)
            stamp = time.strftime("%H%M%S")
            record = index.add(lambda n, day: index.path.parent / ("图%d-%s-%s%s" % (n, day, stamp, extension)))
            try:
                Path(record["path"]).write_bytes(data)
            except Exception:
                index.drop(record)
                continue
            saved.append(record)
        return saved

    @staticmethod
    def image_block(records, note):
        lines = ["- 图%d（%s）= %s" % (r["n"], r.get("day", ""), r["path"]) for r in records]
        return IMAGE_BLOCK_MARK + "（%s\n%s）" % (note, "\n".join(lines))

    def image_context(self, text, images):
        """返回 (要附的提示, 需要反问的候选, 是否该等图片)，三者最多一个生效。
        用「图N」明确指定且存在 → 带上（可一次带多张）；编号对不上 → 给候选让用户确认；
        本条消息自带图片 → 都带上；完全没提图 → 带最近几张（默认 2 张，方便追问上一张）。"""
        index = self.image_index()
        if index is None:
            return "", [], False
        found, unknown = index.resolve(text)
        if found:
            return self.image_block(found, index.note_for(found)), [], False
        if images:
            # 本条消息附带的图片：都带上（最近的排最后）
            return self.image_block(images[-CURRENT_IMAGE_COUNT:], "本条消息附带的图片："), [], False
        if unknown:
            candidates = index.recent(5)
            if candidates:
                return "", candidates, False
            return "最近没有收到编号为图%d 的图片。" % unknown[0], [], False
        task_like = bool(COMMAND_RE.match(text) or IMAGE_WORD_RE.search(text)
                         or ATTACH_WORD_RE.search(text) or ACTION_RE.search(text)
                         or IMAGE_ASK_RE.search(text))
        latest = index.recent(LATEST_IMAGE_COUNT, hours=LATEST_IMAGE_HOURS)
        if latest and task_like:
            return self.image_block(latest, "用户未指定图片，带上最近收到的这几张（最新的在最后）："), [], False
        if not latest and ATTACH_WORD_RE.search(text) and (COMMAND_RE.match(text) or ACTION_RE.search(text)):
            # 手头一张图都没有，但说了「附图 / 见图」→ 先等他把图发过来
            return "", [], True
        return "", [], False

    def image_list_text(self):
        index = self.image_index()
        records = index.recent(10) if index else []
        if not records:
            return "最近没有收到图片。"
        lines = ["- 图%d（%s）%s" % (r["n"], time.strftime("%m-%d %H:%M", time.localtime(r.get("at", 0))),
                                    r.get("label") or "") for r in records]
        return "最近收到的图片：\n" + "\n".join(lines) + "\n用「图N」指代即可。"

    def reminder_ready(self):
        with self.store.lock:
            context=self.store.data.get('notification_context') or {}
            session=self.store.data.get('session') or {}
            return bool(not self.stopped.is_set() and self.store.data.get('enabled')
                and context.get('owner')==session.get('owner')==self.session.get('owner')
                and context.get('bot')==session.get('bot_id')==self.session.get('bot_id') and context.get('context'))

    def notify_owner(self,text,identity):
        with self.send_lock:
            if not self.reminder_ready():raise ValueError('请先连接微信，并向绑定的助手发送一条消息')
            with self.store.lock:context=dict(self.store.data['notification_context'])
            client_id='shizuka-reminder-'+hashlib.sha256(identity.encode()).hexdigest()[:40]
            self.client.send(self.session['owner'],context['context'],str(text)[:1500],client_id)

    def notify_question(self,text,identity):
        if not self.reminder_ready():raise ValueError('微信对话尚未连接')
        with self.store.lock:context=dict(self.store.data['notification_context'])
        for index in range(0,len(text),1500):
            with self.send_lock:
                if not self.reminder_ready():raise ValueError('微信连接已结束')
                self.client.send(self.session['owner'],context['context'],text[index:index+1500],
                    'shizuka-question-'+identity+'-'+str(index//1500))

    def receive(self, raw):
        if (self.stopped.is_set() or raw.get("message_type") != 1 or raw.get("message_state") != 2
                or raw.get("from_user_id") != self.session["owner"] or raw.get("group_id")
                or raw.get("delete_time_ms") or raw.get("to_user_id") != self.session["bot_id"]):
            return
        if raw.get("create_time_ms", 0) / 1000 < self.session.get("bound_at", 0) - 5:
            return
        context = raw.get("context_token")
        if not isinstance(context, str) or not context:
            return
        items = [i for i in raw.get("item_list", []) if isinstance(i, dict)]
        texts = [i.get("text_item", {}).get("text", "") for i in items if i.get("type") == 1]
        text = "\n".join(t for t in texts if isinstance(t, str)).strip()
        identity = raw.get("message_id") or raw.get("msg_id") or raw.get("client_id")
        if identity is None:
            return  # no reliable id => never run a remote file operation
        key = hashlib.sha256((self.session["owner"] + ":" + str(identity)).encode()).hexdigest()
        if not self.store.claim(key):
            return
        self.store.update(notification_context={'owner':self.session['owner'],'bot':self.session['bot_id'],
                                               'context':context})
        message = {"key": key, "context": context, "text": text, "images": []}
        image_items = [i for i in items if i.get("type") == 2]
        if image_items:
            message["images"] = self.save_images(image_items, key)
        now = time.time()
        pending = self.store.data.get("pending_image")
        if pending and now - pending.get("at", 0) > PENDING_IMAGE_SECONDS:
            pending = None
            self.store.update(pending_image=None)
        pending_text = self.store.data.get("pending_text")
        if pending_text and now - pending_text.get("at", 0) > PENDING_TEXT_SECONDS:
            pending_text = None
            self.store.update(pending_text=None)
        if message["images"] and text:
            self.store.update(pending_text=None)   # 图文同到：以本条文字为准
            pending_text = None
        if text in ("/停止", "/stop", "停止任务", "取消任务"):
            self.store.update(pending_image=None, pending_text=None)
            self.cancel_task()
            self.reply(message, "已发出停止指令，待执行任务已取消；已经完成的文件更改会保留。", "stop")
        elif text in ("/状态", "/status"):
            self.reply(message, "电脑在线。" + ("正在处理任务。" if self.active else "当前没有正在执行的任务。"), "status")
        elif text in ("/结果", "/result"):
            self.reply(message, self.store.data.get("last_result") or "目前没有可查看的结果。", "last")
        elif text in ("/图片", "/images"):
            self.reply(message, self.image_list_text(), "images")
        elif text in ("/帮助", "/help"):
            self.reply(message, "可以直接聊天。/待办 加事项与时间，可以创建待办；到期可通过微信提醒。\n"
                                "发来的图片会按天编号存到电脑工作区，之后用「/电脑 用图2 写一份文档」这样指代就行。\n"
                                "文件任务：/电脑 加具体要求。\n/图片：看最近收到的图片编号\n/停止：停止任务\n"
                                "/状态：查看连接与任务状态\n/结果：查看最近结果\n请保持电脑和桌宠运行。", "help")
        elif pending and not COMMAND_RE.match(text):
            # 正在等「哪一张」的回答；但用户要是直接发了新指令（如 /电脑 …），
            # 就以新指令为准，别把指令当成选图回答。
            task = pending.get("task") or text
            self.store.update(pending_image=None)
            index = self.image_index()
            found, _ = index.resolve(text) if index else ([], [])
            if found:
                self.queue_job(message, task + "\n\n" + self.image_block(found, "用户确认的图片："))
            else:
                candidates = index.recent(5) if index else []
                block = self.image_block(candidates, "用户未指明序号，请按描述从候选里判断该用哪张：") if candidates else ""
                self.queue_job(message, (task + "\n\n" + block).strip())
        elif not text and image_items:
            if message["images"]:
                if pending_text:
                    self.store.update(pending_text=None)
                    self.queue_job(message, pending_text["task"] + "\n\n"
                                   + self.image_block(message["images"], "用户随后发来的图片："))
                    return
                numbers = "、".join("图%d" % r["n"] for r in message["images"])
                self.reply(message, "%s 收到了，已存到电脑工作区。\n想让我讲讲或看图，直接说「讲下图%d」就行；\n要拿它写文件，发「/电脑 用图%d 写一份说明文档」这样的指令。"
                           % (numbers, message["images"][-1]["n"], message["images"][-1]["n"]), "image")
            else:
                self.reply(message, "图片没能下载成功，请再发一次。", "image_failed")
        elif not text or len(text) > 20000:
            self.reply(message, "先支持文字和图片，文字任务请不超过 20000 字。", "unsupported")
        else:
            self.store.update(pending_text=None, pending_image=None)
            if self.answer_pending:
                answer=self.answer_pending(text)
                if answer is not None:
                    self.reply(message,answer,'answer')
                    return
            block, ask, wait = self.image_context(text, message["images"])
            if wait:
                self.store.update(pending_text={"task": text, "at": time.time()})
                self.reply(message, "好，把图片发过来，我收到就按你说的做。", "wait_image")
                return
            if ask:
                self.store.update(pending_image={"task": text, "at": time.time()})
                lines = "\n".join("- 图%d（%s）" % (r["n"], r["day"]) for r in ask)
                self.reply(message, "你说的是哪张？\n" + lines + "\n回「图2」这样就行。", "ask_image")
                return
            self.queue_job(message, (text + "\n\n" + block).strip() if block else text)

    def queue_job(self, message, text):
        """把消息排进任务队列（带"队列已满"提示）。"""
        message["text"] = text
        full = False
        with self.task_lock:
            try:
                self.jobs.put_nowait(message)
            except queue.Full:
                full = True
        if full:
            self.reply(message, "待处理消息较多，请稍后再发，或发送 /停止 取消队列。", "busy")

    def _poll(self):
        backoff = 1
        self.status({"status": "已连接，等待微信消息"})
        while not self.stopped.is_set():
            try:
                result = self.client.updates(self.store.data.get("cursor", ""))
                if self.stopped.is_set():
                    break
                for message in result.get("msgs", []):
                    if isinstance(message, dict):
                        try:
                            self.receive(message)
                        except (ApiError, ConnectionError, TimeoutError):
                            self.status({"status": "回复暂未送达，可发送 /结果 查看；不会重复执行文件任务"})
                if result.get("get_updates_buf"):
                    self.store.update(cursor=result["get_updates_buf"])
                backoff = 1
                self.stopped.wait(.1)
            except TimeoutError:
                continue
            except ApiError as exc:
                if exc.code == -14:
                    self.status({"status": "微信登录已失效，请重新扫码"})
                    self.stop()
                    break
                self.status({"status": str(exc) + "，正在重连"})
                self.stopped.wait(backoff)
                backoff = min(backoff * 2, 30)
            except Exception:
                self.status({"status": "微信连接中断，正在重试"})
                self.stopped.wait(backoff)
                backoff = min(backoff * 2, 30)

    def _work(self):
        while not self.stopped.is_set():
            # Fetch and install cancellation token under the same lock as /stop.
            with self.task_lock:
                try:
                    message = self.jobs.get_nowait()
                except queue.Empty:
                    message = None
                if message:
                    self.task_cancel = threading.Event()
                    token = self.task_cancel
                    self.active = True
            if not message:
                self.stopped.wait(.1)
                continue
            try:
                self.status({"status": "正在处理微信任务", "task": message["text"]})
                self.store.update(last_result="上一项任务正在处理；若程序意外退出，请先核对任务记录，再重新发起任务。")
                result = self.responder(message["text"], token, self.status)
                if token.is_set():
                    result = "本轮任务已停止，已完成的文件更改会保留。"
            except Exception:
                result = "本轮未能完成，请在电脑端检查接口或电脑助手配置。"
            self.store.update(last_result=result)
            self.status({"status": "最近一轮已返回", "output": result})
            try:
                self.reply(message, result)
            except Exception:
                self.status({"status": "结果尚未送达，可发送 /结果 查看；文件任务不会重复执行"})
            finally:
                with self.task_lock:
                    self.active = False
