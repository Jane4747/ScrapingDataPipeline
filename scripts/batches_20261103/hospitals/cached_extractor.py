"""Cache evidence extraction; retain the original extractor's final aggregation.

Every cache key includes extractor code, page metadata, the scope decision, and
actual bytes of the saved body/text/attachments. Nothing is keyed by URL alone.
"""
from pathlib import Path
import argparse,hashlib,json,os,sys
import extractor

ORIGINAL_EXTRACT_TASK=extractor.extract_task
CODE_SHA=hashlib.sha256(Path(extractor.__file__).read_bytes()).hexdigest()
WRAPPER_SHA=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def evidence_fingerprint(page,base):
    values=[]
    for item in [page]+[a for a in page.get('attachments',[]) if isinstance(a,dict)]:
        for field in ['raw_path','text_path']:
            value=item.get(field)
            if not value:continue
            path=Path(value);path=path if path.is_absolute() else Path(base)/path
            try:digest=hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:digest='unavailable:'+type(exc).__name__
            values.append([str(path),digest])
    return values

def cache_extract_task(task):
    page,base,scope,*review=task
    root=os.environ.get('SIXPROVINCE_EXTRACT_CACHE')
    if not root:return ORIGINAL_EXTRACT_TASK(task)
    expected=os.environ.get('SIXPROVINCE_EXTRACTOR_SHA')
    if expected and expected!=CODE_SHA:
        raise RuntimeError('Extractor changed during the cached extraction; restart using one frozen version')
    payload=[CODE_SHA,WRAPPER_SHA,page,str(Path(base).resolve()),scope,review,evidence_fingerprint(page,base)]
    key=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    target=Path(root)/key[:2]/(key+'.json')
    if target.is_file():
        try:
            saved=json.loads(target.read_text(encoding='utf-8'))
            if saved.get('key')==key:return saved['outcome']
        except (OSError,ValueError,KeyError):pass
    outcome=ORIGINAL_EXTRACT_TASK(task)
    try:
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_suffix('.'+str(os.getpid())+'.tmp')
        temporary.write_text(json.dumps({'key':key,'extractor_sha256':CODE_SHA,'outcome':outcome},ensure_ascii=False),encoding='utf-8')
        temporary.replace(target)
    except OSError:
        # A cache failure must never turn a valid extraction into a missing row.
        pass
    return outcome

def main():
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--cache-dir',required=True)
    args,remaining=parser.parse_known_args()
    root=Path(args.cache_dir).resolve();root.mkdir(parents=True,exist_ok=True)
    os.environ['SIXPROVINCE_EXTRACT_CACHE']=str(root)
    os.environ['SIXPROVINCE_EXTRACTOR_SHA']=CODE_SHA
    extractor.extract_task=cache_extract_task
    sys.argv=[sys.argv[0],*remaining]
    print(json.dumps({'cache_dir':str(root),'extractor_sha256':CODE_SHA},ensure_ascii=False),flush=True)
    extractor.main()

if __name__=='__main__':main()
