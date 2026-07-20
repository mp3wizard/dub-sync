#!/usr/bin/env python3
"""Robust offset curve for HARD (weak-M&E) episodes — the rescue path when dubsync.py's
silence-anchored chunk aligner latches onto spurious far peaks and invents a huge
false ad-break gap (e.g. a +33s jump where the truth is +5s).

Method: conform the dub (PAL/fps) to the reference timeline, FFT-cross-correlate for a
single global base offset, then slide a wide window with a NARROW search constrained
around a running estimate. The narrow search is the whole point — it cannot jump to a
far spurious peak, so on weak M&E you get the true gentle staircase instead of noise.

    python robust_offset.py --eng ORIGINAL.mp4 --thai DUB.mp4            # print the curve + suggested segments
    python robust_offset.py --eng ORIGINAL.mp4 --thai DUB.mp4 --out thai_synced.flac   # ...and build the corrected audio

Then verify with dense_verify.py (never trust dubsync's sparse [verify] PASS on these).
"""
import subprocess, argparse, numpy as np, sys

SR, FRAME = 8000, 160
fps_env = SR / FRAME  # 50 Hz envelope

def probe_fps(path, stream_type="v"):
    r = subprocess.run(["ffprobe","-v","error","-select_streams",stream_type+":0",
        "-show_entries","stream=r_frame_rate","-of","default=nk=1:nw=1",path],
        capture_output=True, text=True).stdout.strip().splitlines()
    for v in r:
        if "/" in v:
            a,b=v.split("/");
            if float(b)!=0: return float(a)/float(b)
    return None

def full_env(path, stream):
    raw = subprocess.run(["ffmpeg","-v","error","-i",path,"-map",stream,"-ac","1",
        "-ar",str(SR),"-f","f32le","-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    n=(len(x)//FRAME)*FRAME
    e=np.sqrt((x[:n].reshape(-1,FRAME)**2).mean(1)+1e-9)
    return e-e.mean()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--eng",required=True); ap.add_argument("--thai",required=True)
    ap.add_argument("--eng-stream",default="0:a:0"); ap.add_argument("--thai-stream",default="0:a:0")
    ap.add_argument("--src-fps",type=float); ap.add_argument("--dst-fps",type=float)
    ap.add_argument("--win",type=float,default=90.0,help="correlation window sec")
    ap.add_argument("--step",type=float,default=30.0)
    ap.add_argument("--search",type=float,default=20.0,help="constrained search half-width sec")
    ap.add_argument("--step-thresh",type=float,default=1.5,help="offset jump that starts a new segment")
    ap.add_argument("--out",help="if given, build the conformed+placed dub audio here (flac)")
    a=ap.parse_args()

    dst=a.dst_fps or probe_fps(a.eng,"v") or probe_fps(a.eng,"a")
    src=a.src_fps or probe_fps(a.thai,"v") or probe_fps(a.thai,"a")
    if not dst or not src: sys.exit("could not detect fps; pass --src-fps/--dst-fps")
    F = src/dst   # stretch factor for the dub envelope onto the reference timeline
    print(f"[fps] eng(dst)={dst:.3f}  thai(src)={src:.3f}  stretch F={F:.5f}",flush=True)

    print("[extract] eng envelope ...",flush=True); eng=full_env(a.eng,a.eng_stream)
    print("[extract] thai envelope ...",flush=True); tha_raw=full_env(a.thai,a.thai_stream)
    tha=np.interp(np.arange(int(len(tha_raw)*F))/F, np.arange(len(tha_raw)), tha_raw)
    print(f"[len] eng {len(eng)/fps_env:.1f}s  thai_conf {len(tha)/fps_env:.1f}s",flush=True)

    # global base offset via FFT
    N=1<<int(np.ceil(np.log2(max(len(eng),len(tha))+1)))
    xc=np.fft.irfft(np.fft.rfft(eng,N)*np.conj(np.fft.rfft(tha,N)),N)
    lim=int(60*fps_env); xc=np.concatenate([xc[-lim:],xc[:lim]])
    base=(np.argmax(xc)-lim)/fps_env
    print(f"[global] base offset (eng-thai) = {base:+.2f}s",flush=True)

    WIN=int(a.win*fps_env); STEP=int(a.step*fps_env); SEARCH=int(a.search*fps_env)
    run=int(base*fps_env); rows=[]
    print("\n  thai_t   eng_t    offset   corr")
    for c in range(WIN//2, len(tha)-WIN//2, STEP):
        w=tha[c-WIN//2:c+WIN//2]; w=(w-w.mean())/(w.std()+1e-9)
        best,blag=-2,run
        for lag in range(run-SEARCH, run+SEARCH):
            s=eng[c+lag-WIN//2:c+lag+WIN//2]
            if len(s)!=WIN: continue
            s=(s-s.mean())/(s.std()+1e-9); v=float(w@s/WIN)
            if v>best: best,blag=v,lag
        if best>0.35: run=blag
        off=blag/fps_env; t=c/fps_env
        rows.append((t,off,best))
        print(f"  {t:6.0f}  {t+off:6.0f}   {off:+6.2f}s  {best:.2f}")

    # collapse into a staircase of segments (using reliable points)
    segs=[]; cur_off=None; seg_start=0.0
    for t,off,corr in rows:
        if corr<0.35: continue
        if cur_off is None:
            cur_off=off; seg_start=0.0
        elif abs(off-cur_off)>a.step_thresh:
            segs.append((seg_start, t, cur_off)); seg_start=t; cur_off=off
        else:
            cur_off=0.6*cur_off+0.4*off  # gentle track within a segment
    segs.append((seg_start, rows[-1][0]+a.step, cur_off if cur_off is not None else base))
    print("\n[segments] (thai_conf start, end, offset) — the true staircase:")
    for s0,s1,o in segs: print(f"   {s0:7.1f} - {s1:7.1f}   off +{o:.2f}")

    if a.out:
        print("\n[build] conforming dub audio + placing per staircase ...",flush=True)
        conf=1.0/F
        # aresample=48000 first: asetrate reinterprets whatever rate is already on the
        # stream, so without normalizing to 48000 up front, a source natively at e.g.
        # 44100Hz gets its rate relabeled from the WRONG base — silently pitching/
        # speeding the whole track by (native_rate/48000) instead of by `conf`.
        proc=subprocess.run(["ffmpeg","-v","error","-i",a.thai,"-map",a.thai_stream,
            "-af",f"aresample=48000,asetrate={int(48000*conf)},aresample=48000","-ac","2","-ar","48000",
            "-f","s16le","-"],capture_output=True)
        if proc.returncode!=0:
            sys.exit(f"ffmpeg failed extracting/conforming dub audio for --out build:\n{proc.stderr.decode(errors='replace')}")
        raw=proc.stdout
        c=np.frombuffer(raw,dtype=np.int16).reshape(-1,2)
        out=np.zeros((int(len(eng)/fps_env*48000),2),np.int16)
        for s0,s1,o in segs:
            a0=int(s0*48000); a1=min(int(s1*48000),len(c))
            if a0>=len(c): break
            src_=c[a0:a1]; d0=int((s0+o)*48000)
            if d0>=len(out) or d0+len(src_)<=0: continue  # segment placed entirely outside the output buffer
            d0c=max(0,d0); d1=min(d0+len(src_),len(out))
            n=d1-d0c
            if n<=0: continue
            out[d0c:d1]=src_[d0c-d0:d0c-d0+n]
        p=subprocess.Popen(["ffmpeg","-y","-v","error","-f","s16le","-ar","48000","-ac","2",
            "-i","-","-c:a","flac",a.out],stdin=subprocess.PIPE)
        p.communicate(out.tobytes())
        print(f"[done] wrote {a.out} (exit {p.returncode}). Now: dense_verify.py --eng ... --built <mux of this>")

if __name__=="__main__": main()
