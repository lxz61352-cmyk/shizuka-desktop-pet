"""Run shared tests with fresh data and no network/credential use."""
from pathlib import Path
import os,sys,tempfile,unittest
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
with tempfile.TemporaryDirectory(prefix='shizuka-unit-') as folder:
    os.environ['SHIZUKA_DATA_DIR']=folder
    result=unittest.TextTestRunner().run(unittest.defaultTestLoader.discover(str(root/'tests')))
    code=0 if result.wasSuccessful() else 1
# 测试结果已经拿到了，直接硬退出：正常退出时 Tk 拆解释器会在别的线程上触发
# Tcl_AsyncDelete（0xC0000005），把「测试通过」弄成看起来像崩溃。
os._exit(code)
