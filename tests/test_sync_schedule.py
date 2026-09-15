"""Real signed exchanges: three-hour memory cadence, fast files and manual wakeup."""
from pathlib import Path
from unittest.mock import patch
import base64,json,secrets,sys,tempfile,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sync_bridge import SyncBridge
from sync_rustdesk import RustDeskSync
from sync_files import attach_files

class ScheduleTests(unittest.TestCase):
    def test_three_hours_does_not_delay_files_or_windows_manual_sync(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def config():return {'channel':secrets.token_hex(16),'pairing_key':base64.b64encode(secrets.token_bytes(32)).decode(),'listen_port':0,'peer_url':''}
            memory=config();files=config()
            left=SyncBridge(root/'win');right=SyncBridge(root/'mac')
            server=RustDeskSync(left,memory);client=None
            def attach(transport,data):
                (data/'queue').mkdir();(data/'old.json').write_text(json.dumps(files))
                (data/'agent-files.json').write_text(json.dumps({'state_dir':str(data/'queue'),'receive_dir':str(data/'received'),'pairing_config':str(data/'old.json')}))
                attach_files(transport,data)
            try:
                attach(server,left.root);server.start()
                client=RustDeskSync(right,{**memory,'peer_url':f'http://127.0.0.1:{server.server.server_port}'})
                attach(client,right.root)
                right.commit('memories',[{'id':'a','content':'first'}],[])
                client.poll_once()
                self.assertTrue(client.status()['confirmed'] and server.status()['confirmed'])
                last_sent=client.state['sent_at']
                view=right.read('memories');right.commit('memories',list(view)+[{'id':'b','content':'later'}],view)
                file=root/'note.txt';file.write_text('file stays responsive')
                queued=server.files.queue.enqueue(file)
                client.poll_once()
                self.assertEqual(client.state['sent_at'],last_sent)
                self.assertEqual(len(left.read('memories')),1)
                self.assertEqual(server.files.queue.status(queued['id'])['outgoing'][0]['status'],'delivered')
                self.assertTrue(server.request_sync()['sync_requested'])
                client.poll_once()
                self.assertEqual(len(left.read('memories')),2)
                self.assertTrue(client.status()['confirmed'] and server.status()['confirmed'])
                view=right.read('memories');right.commit('memories',list(view)+[{'id':'c','content':'scheduled'}],view)
                next_time=client.state['sent_at']+10801
                with patch('time.time',return_value=next_time):client.poll_once()
                self.assertEqual(len(left.read('memories')),3)
                self.assertEqual(server.server.accepted_connections,1)
            finally:
                if client:
                    client.stop();client.files.queue.close()
                server.stop();server.files.queue.close();left.close();right.close()

if __name__=='__main__':unittest.main()
