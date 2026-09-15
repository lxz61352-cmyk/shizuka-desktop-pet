"""Verify the distributed files without starting the application."""
from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parent
manifest=json.loads((root/'MANIFEST.json').read_text('utf-8'))
for name,digest in manifest['files'].items():
    p=(root/name).resolve()
    if not p.is_relative_to(root) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
        raise SystemExit('Verification failed: '+name)
print('Verified '+str(len(manifest['files']))+' files; version '+manifest['version'])
