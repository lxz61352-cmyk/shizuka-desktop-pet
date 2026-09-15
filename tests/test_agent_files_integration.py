from pathlib import Path
import base64,json,secrets,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sync_bridge import SyncBridge
from sync_rustdesk import RustDeskSync
from sync_files import attach_files

def pairing():
    return {'channel':secrets.token_hex(16),'pairing_key':base64.b64encode(secrets.token_bytes(32)).decode(),
            'peer_url':'','listen_port':0}

class AgentFileIntegrationTests(unittest.TestCase):
    def test_old_file_pairing_and_new_memory_share_one_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);memory_config=pairing();file_config=pairing()
            left=SyncBridge(root/'win');right=SyncBridge(root/'mac')
            server=RustDeskSync(left,memory_config);client=None
            def setup_files(transport,data):
                queue=data/'AgentFiles';queue.mkdir()
                keyfile=data/'old-file-pairing.json';keyfile.write_text(json.dumps(file_config))
                (data/'agent-files.json').write_text(json.dumps({'state_dir':str(queue),'receive_dir':str(data/'Downloads'),
                                                             'pairing_config':str(keyfile)}))
                attach_files(transport,data)
            try:
                setup_files(server,left.root);server.start()
                client=RustDeskSync(right,{**memory_config,'peer_url':f'http://127.0.0.1:{server.server.server_port}'})
                setup_files(client,right.root)
                note=root/'handoff.txt';note.write_text('isolated handoff')
                queued=server.files.queue.enqueue(note)
                right.commit('memories',[{'id':'m','content':'isolated memory'}],[])
                self.assertFalse(client.tick().get('error'))
                client.files.tick()
                self.assertFalse(client.files.last_error)
                self.assertEqual((right.root/'Downloads/handoff.txt').read_text(),'isolated handoff')
                self.assertEqual(server.files.queue.status(queued['id'])['outgoing'][0]['status'],'delivered')
                self.assertEqual(len(left.read('memories')),1)
                self.assertEqual(server.server.accepted_connections,1)
            finally:
                if client:
                    client.stop();client.files.queue.close()
                server.stop();server.files.queue.close();left.close();right.close()

if __name__=='__main__':unittest.main()
