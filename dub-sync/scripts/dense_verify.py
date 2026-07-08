#!/usr/bin/env python3
"""Dense, honest verification of a BUILT dub track — the check dubsync.py's own
[verify] should have been. Its verify samples only silence-bounded "real content"
points (often <10, clustered in one half) and flags the rest gap/uncertain, so it can
print PASS on a build whose OTHER half is badly misaligned. That exact false-PASS shipped
a 28s-off episode once.

This instead correlates the built dub against the reference every INTERVAL seconds across
the WHOLE timeline and reports coverage. Verdict downgrades when coverage is thin.

    python dense_verify.py --eng ORIGINAL.mp4 --built OUT.mkv
    python dense_verify.py --eng ORIGINAL.mp4 --built OUT.mkv --built-stream 0:a:0

Residual ~0 with decent corr = aligned there. |residual|>0.5s at corr>=0.35 = real
misalignment. Run this on every weak-correlation episode; do NOT trust a bare [verify] PASS.
"""
import subprocess, argparse, numpy as np
SR,FRAME=8000,160; fps=SR/FRAME
def env(path,stream):
    raw=subprocess.run(["ffmpeg","-v","error","-i",path,"-map",stream,"-ac","1","-ar",str(SR),
        "-f","f32le","-"],capture_output=True).stdout
    x=np.frombuffer(raw,dtype=np.float32); n=(len(x)//FRAME)*FRAME
    e=np.sqrt((x[:n].reshape(-1,FRAME)**2).mean(1)+1e-9); return e-e.mean()
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--eng",required=True); ap.add_argument("--built",required=True)
    ap.add_argument("--eng-stream",default="0:a:0")
    ap.add_argument("--built-stream",default="0:a:0",help="the synced dub track in the built file")
    ap.add_argument("--interval",type=float,default=60.0)
    ap.add_argument("--win",type=float,default=60.0); ap.add_argument("--search",type=float,default=6.0)
    a=ap.parse_args()
    print("[extract] ...",flush=True)
    eng=env(a.eng,a.eng_stream); tha=env(a.built,a.built_stream)
    WIN=int(a.win*fps); SEARCH=int(a.search*fps)
    print("\n  t(mm:ss)  residual  corr")
    bad=[]; reliable=0; total=0
    for t in range(int(a.interval),int(len(tha)/fps)-int(a.win/2),int(a.interval)):
        c=int(t*fps); w=tha[c-WIN//2:c+WIN//2]
        if len(w)<WIN: continue
        total+=1; w=(w-w.mean())/(w.std()+1e-9)
        b=eng[max(0,c-WIN//2-SEARCH):c+WIN//2+SEARCH]
        best,blag=-2,0
        for lag in range(0,len(b)-len(w)+1):
            s=b[lag:lag+len(w)]; s=(s-s.mean())/(s.std()+1e-9); v=float(w@s/len(w))
            if v>best: best,blag=v,lag
        resid=(blag-SEARCH)/fps; flag=""
        if best>=0.35:
            reliable+=1
            if abs(resid)>0.5: flag="  <-- OFF"; bad.append((t,resid,best))
        print(f"  {t//60:02d}:{t%60:02d}    {resid:+5.2f}s   {best:.2f}{flag}")
    cov = reliable/total if total else 0
    print(f"\ncoverage: {reliable}/{total} windows reliable ({cov*100:.0f}%);  {len(bad)} misaligned")
    if bad: print("  misaligned:", ", ".join(f"{t//60}:{t%60:02d}({r:+.1f})" for t,r,_ in bad))
    if bad: verdict="FAIL — real misalignment found (fix offsets / gap_scan)"
    elif cov<0.5: verdict="CHECK — too little of the episode is verifiable (weak M&E); SPOT-CHECK the low-corr regions by ear"
    else: verdict="PASS — densely verified, no misalignment"
    print("VERDICT:",verdict)
if __name__=="__main__": main()
