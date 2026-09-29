"""Build isolated, allowlisted Windows bundles without touching the live install.

No settings, credentials, histories, test fixtures or research documents enter a
bundle. Output directories must be new. All acceptance checks are offline.
"""
import argparse
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from app_identity import APP_VERSION
from chat_test_core import APP_VERSION as CHAT_VERSION, PERSONA_REVISION


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def copy_runtime(source, target):
    for path in source.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
            continue
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)


def normalize_app_text(bundle):
    """Match repository LF rules without changing bundled third-party files."""
    suffixes = {'.py', '.md', '.txt', '.json', '.mjs', '.yml', '.yaml', '.bat', '.cmd', '.lock'}
    for path in bundle.rglob('*'):
        if (not path.is_file() or path.relative_to(bundle).parts[0] in ('_internal', 'LICENSES')
                or path.suffix not in suffixes):
            continue
        data = path.read_bytes()
        if b'\r\n' in data:
            path.write_bytes(data.replace(b'\r\n', b'\n'))


def license_files(bundle):
    copy_runtime(ROOT / 'LICENSES', bundle / 'LICENSES')
    versions = {'python': sys.version, 'packages': {}}
    for name in ('openai', 'httpx2', 'httpcore2', 'anyio', 'pydantic', 'pydantic_core',
                 'jiter', 'typing_extensions', 'typing-inspection', 'annotated-types',
                 'sniffio', 'idna', 'h11', 'truststore', 'pillow', 'pystray', 'qrcode',
                 'pyinstaller', 'pyinstaller-hooks-contrib','pypdfium2'):
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        versions['packages'][name] = dist.version
        for item in dist.files or ():
            if '.dist-info' not in str(item) or not any(word in item.name.lower() for word in ('license', 'copying', 'notice')):
                continue
            source = Path(dist.locate_file(item))
            if source.is_file():
                dest = bundle / 'LICENSES' / name / item.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
    write_json(bundle / 'LICENSES/build-versions.json', versions)


def audit(bundle):
    denied = {'data', 'tests', 'tools', '测试记录', '旧文件归档', '.git', '.venv', '研究',
              'chat_history', 'debug_sessions'}
    credential_names = {'api_key.txt', 'settings.json', 'connection.json', '.env',
                        'credentials.json', 'secrets.json'}
    secrets = re.compile(rb'(?i)\bsk-(?:proj-)?[a-z0-9_-]{24,}')
    failures = []
    count = 0
    for path in bundle.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle)
        count += 1
        # Python distributions legitimately contain internal tests/data. Our
        # application-owned directories have a strict separate allowlist.
        if rel.parts[0] != '_internal' and (denied.intersection(rel.parts) or path.name in credential_names):
            failures.append(rel.as_posix() + ': forbidden application path')
        if path.suffix.lower() in ('.json', '.txt', '.md', '.py', '.mjs', '.yml'):
            if secrets.search(path.read_bytes()):
                failures.append(rel.as_posix() + ': key-shaped literal (value not printed)')
    if failures:
        raise RuntimeError('Package audit failed: ' + '; '.join(failures))
    return {'files_checked': count, 'private_paths_excluded': True,
            'key_literal_scan': 'passed', 'scope': 'strict input allowlist + paths + sk-style plaintext literals; not universal PII detection'}


def build(kind, output, build_root, reports, desktop_profile=None):
    chat = kind == 'chat'
    name = 'ShizukaChatTest' if chat else 'Shizuka'
    version = CHAT_VERSION if chat else APP_VERSION
    directory = output / ('聊天测试版' if chat else '桌宠完整版') / f'{name}-{version}-Windows-x64'
    work = build_root / kind
    work.mkdir(parents=True, exist_ok=False)
    if directory.exists() or (directory.parent / (directory.name + '.zip')).exists():
        raise FileExistsError('Refusing to replace existing release: ' + str(directory))
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--onedir',
               '--name', name, '--icon', str(ROOT / 'assets/pet_icon.ico'),
               '--paths', str(ROOT / 'src'), '--collect-all', 'openai',
               '--distpath', str(work / 'dist'), '--workpath', str(work / 'work'), '--specpath', str(work)]
    for resource in ROOT.glob('src/*.txt'):
        if resource.name != 'requirements.txt':
            command += ['--add-data', str(resource) + ';.']
    if chat:
        command += ['--add-data', str(ROOT / ('characters/shizuka-side-motion/persona.' + PERSONA_REVISION + '.candidate.json')) + ';characters/shizuka-side-motion']
    else:
        command += ['--hidden-import', 'pystray._win32', '--copy-metadata', 'pystray']
        command += ['--collect-all','pypdfium2','--collect-all','pypdfium2_raw']
    command.append(str(ROOT / 'src' / ('run_chat_test.py' if chat else 'run_pet.py')))
    with (reports / f'{kind}-build.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    directory.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(work / 'dist' / name, directory)
    if not chat and desktop_profile:
        write_json(directory / 'desktop-dialogue.json', {'profile': desktop_profile})
    if not chat:
        for component in ('assets', 'characters', 'src'):
            copy_runtime(ROOT / component, directory / component)
        for doc in ('README.md', '更新公告.md', 'AI-DEVELOPMENT.md', 'verify_package.py',
                    '启动桌宠.bat', '源码启动.bat'):
            shutil.copy2(ROOT / doc, directory / doc)
        # Keep the readme's local links useful inside the downloaded bundle.
        for doc in ('开发与验证.md', '使用说明/桌宠本次打包说明.md', '使用说明/朋友聊天测试版.md'):
            target = directory / '文档' / doc
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / '文档' / doc, target)
        if (ROOT / 'version.json').exists():
            release = json.loads((ROOT / 'version.json').read_text('utf-8-sig'))
            if release.get('version') == version:
                shutil.copy2(ROOT / 'version.json', directory / 'version.json')
        # Modules using __file__ live in _internal in an onedir build.
        for asset in ROOT.glob('src/*.mjs'):
            shutil.copy2(asset, directory / '_internal' / asset.name)
    license_files(directory)
    guide = ROOT / '文档/使用说明' / ('朋友聊天测试版.md' if chat else '桌宠本次打包说明.md')
    shutil.copy2(guide, directory / '开始使用.md')
    report = reports / f'{kind}-frozen-smoke.json'
    subprocess.run([str(directory / (name + '.exe')), '--self-test', '--report', str(report)],
                   cwd=directory, timeout=180, check=True)
    smoke = json.loads(report.read_text('utf-8'))
    if smoke.get('errors') or smoke.get('ok') is False or not smoke.get('checks'):
        raise RuntimeError('Offline frozen acceptance failed')
    # A frozen GUI test has its own temporary data root; none may be published.
    normalize_app_text(directory)
    privacy = audit(directory)
    write_json(directory / 'BUILD-INFO.json', {'version': version, 'built_at': datetime.now().astimezone().isoformat(),
               'kind': kind, 'offline_gui_checks': len(smoke['checks']), 'model_requests_during_build': 0,
               'dialogue_profile': desktop_profile if not chat else None,
               'production_settings_included': False, 'credentials_included': False, 'audit': privacy})
    files = {p.relative_to(directory).as_posix(): sha(p) for p in sorted(directory.rglob('*')) if p.is_file()}
    write_json(directory / 'MANIFEST.json', {'version': version, 'files': files})
    archive = directory.parent / (directory.name + '.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as handle:
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                handle.write(path, directory.name + '/' + path.relative_to(directory).as_posix())
    with zipfile.ZipFile(archive) as handle:
        if handle.testzip() is not None:
            raise RuntimeError('ZIP integrity failure')
    record = {'directory': str(directory), 'archive': str(archive), 'zip_sha256': sha(archive),
              'zip_bytes': archive.stat().st_size, 'manifest_files': len(files),
              'offline_gui_checks': len(smoke['checks']), 'audit': privacy}
    write_json(reports / f'{kind}-package.json', record)
    print(json.dumps(record, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('chat', 'desktop', 'both'), default='both')
    parser.add_argument('--output', type=Path, default=ROOT / '发布包')
    parser.add_argument('--build-root', type=Path, default=ROOT / 'build' / ('release-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--desktop-profile', choices=('s31r-o1b',))
    args = parser.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)
    for kind in (('chat', 'desktop') if args.kind == 'both' else (args.kind,)):
        build(kind, args.output.resolve(), args.build_root.resolve(), args.reports.resolve(), args.desktop_profile)


if __name__ == '__main__':
    main()
