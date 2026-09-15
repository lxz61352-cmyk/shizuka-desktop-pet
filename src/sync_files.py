"""Optional existing agent file queue, independent of character memory pairing."""
import json
from pathlib import Path
from file_transfer import FileQueue, FileTransfer


def attach_files(transport, data_root):
    path=Path(data_root)/"agent-files.json"
    if not path.exists():return
    settings=json.loads(path.read_text("utf-8-sig"))
    state=Path(settings["state_dir"]).expanduser().resolve()
    receive=Path(settings["receive_dir"]).expanduser().resolve()
    pairing=Path(settings["pairing_config"]).expanduser().resolve()
    if not state.is_dir() or not pairing.is_file():
        raise ValueError("Existing agent file queue/pairing was not found; not creating a new pairing")
    config=json.loads(pairing.read_text("utf-8-sig"))
    # Old files retain their own pairing. Only the local route and the shared
    # connection come from the active memory transport; no second worker.
    config.update(peer_url=transport.peer_url,timeout_seconds=transport.timeout,poll_seconds=transport.interval)
    queue=FileQueue(state,receive)
    try:
        transport.files=FileTransfer(queue,config,session=transport.session)
        transport.files.metadata_provider=transport.sync_control
    except BaseException:
        queue.close()
        raise
