from __future__ import annotations
import os, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path
APP_DIR=Path(__file__).resolve().parents[1]; PORT=int(os.environ.get("YT_NEWS_PORT","8787")); URL=f"http://127.0.0.1:{PORT}"
DATA=APP_DIR/'data'; VENV=APP_DIR/'.venv'; PY=VENV/'Scripts'/'python.exe'; PID=DATA/'server.pid'; LOG=DATA/'server.log'; ERR=DATA/'server-error.log'
def ready():
    try: urllib.request.urlopen(URL,timeout=1); return True
    except Exception: return False
def main():
    DATA.mkdir(exist_ok=True)
    if ready(): webbrowser.open(URL); return 0
    if not PY.exists(): subprocess.check_call([sys.executable,'-m','venv',str(VENV)])
    subprocess.check_call([str(PY),'-m','pip','install','--disable-pip-version-check','-q','-r',str(APP_DIR/'requirements.txt')])
    env=os.environ.copy(); env['YT_NEWS_NO_BROWSER']='1'
    with LOG.open('w') as out, ERR.open('w') as err:
        proc=subprocess.Popen([str(PY),'run.py'],cwd=APP_DIR,env=env,stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
    PID.write_text(str(proc.pid))
    for _ in range(80):
        if ready(): webbrowser.open(URL); print(f"YT News Studio is running at {URL}"); return 0
        if proc.poll() is not None: break
        time.sleep(.25)
    print(f"App did not start. See {ERR}"); return 1
if __name__=='__main__': raise SystemExit(main())
