"""Transport selection; current installations use the existing RustDesk tunnel."""
import base64, urllib.parse


def validate_config(config):
    if config.get("transport") != "rustdesk-tcp":
        raise ValueError("请选择当前 RustDesk 配对文件；旧 Taildrop 配置已退役。")
    from sync_rustdesk import IDENTITY
    if not IDENTITY.fullmatch(str(config.get("channel",""))):raise ValueError("Invalid pairing channel")
    try:key=base64.b64decode(config.get("pairing_key",""),validate=True)
    except (ValueError,TypeError):raise ValueError("Invalid pairing key")
    if len(key)!=32:raise ValueError("Invalid pairing key")
    port=config.get("listen_port",47631)
    if type(port) is not int or not 1<=port<=65535:raise ValueError("Invalid local port")
    if config.get("peer_url"):
        value=urllib.parse.urlsplit(config["peer_url"])
        if (value.scheme!="http" or value.hostname!="127.0.0.1" or not value.port
                or value.username or value.password or value.query or value.fragment or value.path not in ("","/")):
            raise ValueError("Peer must be the local RustDesk forwarding port")


def make_transport(bridge, config):
    if config.get("transport")=="rustdesk-tcp":
        validate_config(config)
        from sync_rustdesk import RustDeskSync
        return RustDeskSync(bridge,config)
    # Compatibility only for old isolated pilot tests, never offered as a new pairing.
    # 旧通道也在这里校验一次：否则配置错误要等到 TaildropSync 内部才报，来源不直观。
    from sync_taildrop import TaildropSync, validate_config as validate_legacy
    validate_legacy(config)
    return TaildropSync(bridge,config)
