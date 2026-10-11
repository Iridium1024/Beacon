"""Synthetic managed-runtime descendant; no DSH or network dependencies."""
import json
from pathlib import Path
import subprocess
import sys
import time

runtime = subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(20)'],
    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
Path(sys.argv[1]).write_text(json.dumps({'pid':runtime.pid}),encoding='utf-8')
time.sleep(20)
