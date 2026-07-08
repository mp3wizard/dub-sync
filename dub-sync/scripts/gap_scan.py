#!/usr/bin/env python3
"""Find spots where the DUB source has a real audio dropout — the reference has speech
but the built dub is silent. TV rips fade out ~2-3s at commercial junctions, eating the
dubbed line there; correlation-window checks (dense_verify) average over 60s and miss it,
so scan at 1s resolution.

    python gap_scan.py --eng ORIGINAL.mp4 --built OUT.mkv                 # whole episode
    python gap_scan.py --eng ORIGINAL.mp4 --built OUT.mkv --from 890 --to 940   # a suspect region

Reports each second where built-dub RMS is near zero while the reference has audio. These
are source holes, not alignment errors — the subtitle covers the meaning; optionally fill
with fill_gap.py.
"""
import subprocess, argparse, numpy as np
SR=8000
def seg(path,stream,ss=None,t=None):
    c=["ffmpeg","-v","error"]
    if ss is not None: c+=["-ss",str(ss)]
    if t  is not None: c+=["-t",str(t)]
    c+=["-i",path,"-map",stream,"-ac","1","-ar",str(SR),"-f","f32le","-"]
    return np.frombuffer(subprocess.run(c,capture_output=True).stdout,dtype=np.float32)
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--eng",required=True); ap.add_argument("--built",required=True)
    ap.add_argument("--eng-stream",default="0:a:0"); ap.add_argument("--built-stream",default="0:a:0")
    ap.add_argument("--from",dest="f",type=float,default=0.0); ap.add_argument("--to",dest="t",type=float)
    ap.add_argument("--dub-silent",type=float,default=0.010,help="dub RMS below this = silent")
    ap.add_argument("--ref-active",type=float,default=0.020,help="ref RMS above this = has audio")
    a=ap.parse_args()
    dur=(a.t-a.f) if a.t else None
    eng=seg(a.eng,a.eng_stream,a.f if a.f else None,dur)
    tha=seg(a.built,a.built_stream,a.f if a.f else None,dur)
    n=min(len(eng),len(tha))//SR
    holes=[]
    for i in range(n):
        e=float(np.sqrt((eng[i*SR:(i+1)*SR]**2).mean()+1e-12))
        d=float(np.sqrt((tha[i*SR:(i+1)*SR]**2).mean()+1e-12))
        t=int(a.f)+i
        if d<a.dub_silent and e>a.ref_active:
            holes.append(t); print(f"  {t//60:02d}:{t%60:02d}  ref={e:.3f} dub={d:.3f}  <-- DUB DROPOUT")
    if not holes:
        print("no dub dropouts found in range.")
    else:
        # group consecutive
        groups=[]; s=holes[0]; p=holes[0]
        for h in holes[1:]:
            if h-p<=2: p=h
            else: groups.append((s,p)); s=h; p=h
        groups.append((s,p))
        print("\ndropout regions (fill_gap.py --cut-start/--cut-end around these):")
        for s,e in groups: print(f"   {s//60}:{s%60:02d} - {e//60}:{e%60:02d}  (~{e-s+1}s)")
if __name__=="__main__": main()
