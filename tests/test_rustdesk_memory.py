from pathlib import Path
import base64,secrets,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sync_bridge import SyncBridge
from sync_rustdesk import RustDeskSync
from conversation_memory import summary_record


class RustDeskMemoryTests(unittest.TestCase):
    def test_actual_signed_exchange_shares_chats_summaries_and_memory(self):
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            left=SyncBridge(a);right=SyncBridge(b)
            config={"channel":secrets.token_hex(16),"pairing_key":base64.b64encode(secrets.token_bytes(32)).decode(),
                    "listen_port":0,"peer_url":"","poll_seconds":60}
            server=RustDeskSync(left,config);client=None
            try:
                server.start()
                client=RustDeskSync(right,{**config,"peer_url":f"http://127.0.0.1:{server.server.server_port}"})
                rows=[{"id":"u","created":1,"role":"user","kind":"chat","text":"合成项目进度"},
                      {"id":"a","created":2,"role":"assistant","kind":"chat","text":"已讨论样品测试"}]
                left.commit("chats",rows+[summary_record(rows,"样品测试待完成",3)],[])
                right.commit("memories",[{"id":"mac","content":"Mac 新增的实验记录","created":4}],[])
                state=client.tick(force=True)
                self.assertFalse(state.get("error"),state)
                self.assertEqual(len(right.read("chats")),3)
                self.assertEqual(len(left.read("memories")),1)
                connections=server.server.accepted_connections
                self.assertFalse(client.tick(force=True).get("error"))
                self.assertEqual(server.server.accepted_connections,connections)
            finally:
                if client:client.stop()
                server.stop();left.close();right.close()


if __name__=="__main__":unittest.main()
