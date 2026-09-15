"""Run shared tests with fresh data and no network/credential use."""
from pathlib import Path
import os,sys,tempfile,unittest
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
with tempfile.TemporaryDirectory(prefix='shizuka-unit-') as folder:
    os.environ['SHIZUKA_DATA_DIR']=folder
    result=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(str(root/'tests')))
    raise SystemExit(0 if result.wasSuccessful() else 1)
