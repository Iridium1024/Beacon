"""Optional redacted evidence sink selected only by the offline test runner."""
import hashlib
import json
import os
from pathlib import Path


def record(test, handles):
    path=os.environ.get('BEACON_TEST_PROCESS_AUDIT')
    if not path:return
    entries=[]
    for handle in handles:
        nonce=getattr(handle,'beacon_nonce',None)
        entries.append({'pid':handle.pid,'exitCode':handle.poll(),
            'launchDigest':hashlib.sha256(nonce.encode()).hexdigest()[:12] if nonce else None,
            'identitySource':'retained-Popen','treeOwned':getattr(handle,'beacon_tree_owned',None)})
    root=Path(test.temp.name)
    traces=[]
    paths=[*root.glob('*.trace'),root/'receiver-trace.json',root/'synthetic-managed-runtime.json']
    for trace in paths[:100]:
        if not trace.exists():continue
        item=json.loads(trace.read_text(encoding='utf-8'))
        traces.append({'pid':item['pid'],'state':item.get('state'),'identitySource':'synthetic-trace'})
    with Path(path).open('a',encoding='utf-8') as output:
        output.write(json.dumps({'test':test.id(),'processes':entries,'traces':traces},ensure_ascii=False)+'\n')
