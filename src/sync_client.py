"""Portable local memory library for Windows and macOS."""
import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
import time
import uuid
import webbrowser
from sync_bridge import SyncBridge
from sync_store import FIELDS, Snapshot
from sync_transport import make_transport

HTML = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>静香 · 双端同步</title>
<style>
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#302b3d;background:#f7f5fa}*{box-sizing:border-box}[hidden]{display:none!important}
body{max-width:980px;margin:auto;padding:36px 24px}header{display:flex;align-items:center;justify-content:space-between;gap:20px}
h1{font-size:27px;margin:0}p{color:#726a7f;font-size:14px;line-height:1.7}.card{background:white;border:1px solid #e7e2ed;border-radius:16px;padding:22px;margin:20px 0}
button{border:1px solid #ded7e8;border-radius:8px;padding:9px 14px;background:white;color:#594777;cursor:pointer}button:hover{background:#f1edf7}
.primary{background:#756092;color:white}.primary:hover{background:#665180}nav{display:flex;gap:8px;flex-wrap:wrap}nav button.active{background:#756092;color:white}
input,textarea{border:1px solid #ded7e8;border-radius:8px;padding:10px;font:inherit;max-width:100%}textarea{width:100%;min-height:78px;resize:vertical}
.row{padding:16px 0;border-bottom:1px solid #eee9f2}.row:last-child{border:0}.body{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7}.meta{font-size:12px;color:#857b91;margin:8px 0}
.buttons{display:flex;gap:8px;margin-top:10px}.small{font-size:12px;padding:5px 10px}#status{font-size:16px;font-weight:600}#detail,#error{white-space:pre-wrap;overflow-wrap:anywhere}#error{color:#9b3d58}label{display:block;font-size:13px;margin:12px 0 6px}#conflicts{font-size:13px}details{margin:15px 0}
</style><header><div><h1>静香 · 双端同步</h1><p>长期记忆、聊天记录和待办，随设备一起延续。</p></div><button id="sync" class="primary">立即同步</button></header>
<section class="card"><div id="status">正在读取…</div><p id="detail"></p><p id="error"></p><details><summary>冲突记录与设备信息</summary><pre id="conflicts"></pre></details></section>
<nav><button data-c="memories" class="active">长期记忆</button><button data-c="chats">聊天记录</button><button data-c="todos">待办</button></nav>
<section class="card"><div id="editor"><label id="input-label">添加记忆</label><textarea id="input" placeholder="输入一条需要长期保存的内容"></textarea><label id="due-label" hidden>提醒时间（可选）</label><input id="due" type="datetime-local" hidden><div class="buttons"><button id="add" class="primary">添加</button></div><p id="chat-hint" hidden>此处可追加历史备注，不会调用 AI 回复；完整 Mac 桌宠界面尚未接入。</p></div><div id="rows"></div></section>
<p>记忆自动同步每 3 小时检查一次，也可点击“立即同步”。文件传输与轻量手动请求独立检查，保持响应。离线时可本地编辑，恢复后合并。连续三次连接失败暂停重连；检查通道后重启此客户端，不会重启屏幕远控。此处是资料库，完整 Mac 桌宠后续接入。</p>
<script>
const token=__TOKEN__;let current='memories',state=null;
const $=id=>document.getElementById(id);
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'X-Shizuka-Token':token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const v=await r.json();if(!r.ok)throw Error(v.error||'请求失败');return v}
function stamp(t){return t?new Date(t*1000).toLocaleString():'尚无'}
async function refresh(){try{state=await api('/state');const s=state.transport;$('status').textContent=s.confirmed?'两端已确认当前数据':s.pending?'有本地更新待发送':'已发送，等待对端合并确认';$('detail').textContent=`对端：${s.peer} · 本机角色：${state.character}\n最近发送：${stamp(s.sent_at)} · 最近收到：${stamp(s.received_at)}`;$('error').textContent=[s.error,s.receive_error].filter(Boolean).join('\n');$('conflicts').textContent=JSON.stringify({device:state.device,counts:state.counts,conflicts:state.conflicts},null,2);render()}catch(e){$('error').textContent=e.message}}
function button(text,fn){const b=document.createElement('button');b.className='small';b.textContent=text;b.onclick=fn;return b}
async function change(op,row,patch){try{await api('/change',{op,collection:current,observed:row,clock:state.views[current].clock,patch});await refresh()}catch(e){$('error').textContent=e.message}}
function render(){const root=$('rows');root.replaceChildren();const rows=state.views[current].rows;for(const r of [...rows].reverse()){const el=document.createElement('div');el.className='row';const body=document.createElement('div');body.className='body';body.textContent=(r.pinned?'📌 ':'')+(r.done?'✓ ':'')+(r.content||r.text||'');el.append(body);const meta=document.createElement('div');meta.className='meta';meta.textContent=(current==='chats'?(r.role||'记录')+' · ':'')+(r.created>1e9?stamp(r.created):'历史导入')+(r.due?' · 提醒 '+stamp(r.due):'');el.append(meta);if(current!=='chats'){const buttons=document.createElement('div');buttons.className='buttons';buttons.append(button(current==='todos'?(r.done?'恢复待办':'完成'):(r.pinned?'取消置顶':'置顶'),()=>change('edit',r,current==='todos'?{done:!r.done}:{pinned:!r.pinned})));buttons.append(button('编辑',()=>{const text=prompt('修改内容',r.content||r.text||'');if(text&&text.trim())change('edit',r,current==='memories'?{content:text.trim()}:{text:text.trim()})}));buttons.append(button('删除',()=>{if(confirm('删除此条记录？删除也会同步到另一台设备。'))change('delete',r,{})}));el.append(buttons)}root.append(el)}if(!rows.length){root.textContent='还没有记录，可以先添加一条记忆或待办。'}}
for(const b of document.querySelectorAll('nav button'))b.onclick=()=>{current=b.dataset.c;document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x===b));$('input-label').textContent=current==='memories'?'添加记忆':current==='todos'?'添加待办':'追加历史备注';$('due').hidden=$('due-label').hidden=current!=='todos';$('chat-hint').hidden=current!=='chats';render()};
$('add').onclick=async()=>{const text=$('input').value.trim();if(!text)return;const patch=current==='memories'?{content:text}:current==='chats'?{text,role:'user',kind:'manual-note'}:{text,due:$('due').value?new Date($('due').value).getTime()/1000:null};await change('add',null,patch);if(!$('error').textContent)$('input').value=''};
$('sync').onclick=async()=>{try{$('sync').disabled=true;await api('/sync',{});await refresh()}catch(e){$('error').textContent=e.message}finally{$('sync').disabled=false}};
refresh();setInterval(refresh,5000);
</script></html>'''


class Client:
    def __init__(self, data, config, character="shizuka"):
        self.bridge = SyncBridge(data, character)
        self.transport = make_transport(self.bridge, config)
        from sync_files import attach_files
        attach_files(self.transport,data)

    def state(self):
        result = self.bridge.status()
        result["conflicts"] = self.bridge.store.conflicts()
        result["views"] = {}
        for collection in FIELDS:
            view = self.bridge.read(collection)
            result["views"][collection] = {"rows": list(view), "clock": view.clock}
        result["transport"] = self.transport.status()
        return result

    def change(self, request):
        collection, operation = request.get("collection"), request.get("op")
        if collection not in FIELDS or operation not in {"add", "edit", "delete"}:
            raise ValueError("Invalid operation")
        if operation == "add":
            row = {"id": uuid.uuid4().hex, "created": time.time()}
            if collection == "memories":
                row.update(pinned=False, last_used=time.time(), use_count=0)
            if collection == "todos":
                row.update(done=False, on_boot=False, due=None)
            if collection == "chats":
                row.update(role="user", kind="manual-note", device=self.bridge.store.device)
            before = Snapshot()
        else:
            if collection == "chats":
                raise ValueError("聊天记录在此界面中只允许追加")
            row = deepcopy(request.get("observed"))
            if not isinstance(row, dict) or "id" not in row:
                raise ValueError("Missing original record")
            clock = request.get("clock")
            if not isinstance(clock, dict) or any(not isinstance(k, str) or type(v) is not int or not 0 <= v < 2**53 for k, v in clock.items()):
                raise ValueError("Invalid view clock")
            before = Snapshot([deepcopy(row)], clock)
        patch = request.get("patch", {})
        if not isinstance(patch, dict) or not patch.keys() <= FIELDS[collection]:
            raise ValueError("Invalid edited fields")
        row.update(patch)
        self.bridge.commit(collection, [] if operation == "delete" else [row], before)
        return {"ok": True}


def serve(client, port=0, open_browser=True, ready_file=None, on_ready=None):
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, code, value, html=False):
            raw = value.encode("utf8") if html else json.dumps(value, ensure_ascii=False).encode("utf8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def valid(self, token_required=True):
            origin = "http://127.0.0.1:" + str(self.server.server_port)
            if self.headers.get("Host") != origin[7:] or self.headers.get("Origin", origin) != origin:
                self.respond(403, {"error": "Local origin required"})
                return False
            if token_required and not secrets.compare_digest(self.headers.get("X-Shizuka-Token", ""), token):
                self.respond(403, {"error": "Invalid local session"})
                return False
            return True

        def do_GET(self):
            if not self.valid(self.path != "/"):
                return
            if self.path == "/":
                self.respond(200, HTML.replace("__TOKEN__", json.dumps(token)), html=True)
            elif self.path == "/state":
                self.respond(200, client.state())
            else:
                self.respond(404, {"error": "Not found"})

        def do_POST(self):
            if not self.valid():
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 1024 * 1024 or self.headers.get_content_type() != "application/json":
                    raise ValueError("Invalid request body")
                request = json.loads(self.rfile.read(length))
                if self.path == "/change":
                    result = client.change(request)
                elif self.path == "/sync":
                    result = client.transport.request_sync()
                else:
                    self.respond(404, {"error": "Not found"})
                    return
                self.respond(200, result)
            except (ValueError, KeyError, TypeError) as exc:
                self.respond(400, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    url = "http://127.0.0.1:" + str(server.server_port)
    if ready_file:
        Path(ready_file).write_text(url, encoding="utf8")
    if on_ready:
        on_ready(url)
    print("Shizuka sync: " + url, flush=True)
    print("Data: " + str(client.bridge.root), flush=True)
    client.transport.start()
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        client.transport.stop()
        if getattr(client.transport,"files",None):client.transport.files.queue.close()
        server.server_close()
        client.bridge.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent / "pairing.json"))
    default_data = Path.home() / ("Library/Application Support/ShizukaSync" if sys.platform == "darwin" else "ShizukaSync")
    parser.add_argument("--data", default=str(default_data))
    parser.add_argument("--character", default="shizuka")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--ready-file")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).expanduser().read_text("utf-8-sig"))
    client = Client(Path(args.data).expanduser(), config, args.character)
    if args.once:
        print(json.dumps(client.transport.tick(force=True), ensure_ascii=False, indent=2))
        client.bridge.close()
    else:
        serve(client, open_browser=not args.no_browser, ready_file=args.ready_file)


if __name__ == "__main__":
    main()
