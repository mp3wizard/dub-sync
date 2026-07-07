#!/usr/bin/env python3
"""
dubsync.py - Sync a foreign-language dub audio track onto a different video release
and mux both audio tracks into an MKV, scene-aligned.

Handles: framerate mismatch (e.g. PAL 25fps vs 23.976fps film speedup) AND
non-linear "staircase" drift from commercial-break cuts (per-chunk re-alignment).

Cross-language safe: aligns on the shared music & effects (M&E) energy envelope,
not dialog, so a Thai dub aligns against an English reference.

Usage:
  python dubsync.py --eng ENG.(mp4|mkv) --thai THA.(mp4|mkv) --out OUT.mkv
        [--work DIR] [--thai-lang tha] [--eng-lang eng]
        [--default thai|eng] [--src-fps F] [--dst-fps F]
        [--pitch-mode asetrate|atempo] [--min-chunk 25] [--keep-temp] [--report-only]

Requires: ffmpeg + ffprobe on PATH, python3 + numpy.
Prints a verification report (residual offset across the episode). Exit 0 = built.
Designed to run UNATTENDED across a season: fails fast + loud on bad inputs.
"""
import argparse, subprocess, sys, os, json, wave, tempfile, shutil
import numpy as np

def run(cmd, capture=True):
    return subprocess.run(cmd, capture_output=capture, text=True)

def run_checked(cmd, desc):
    """Run a command; on nonzero exit, print stderr and abort. Returns the result."""
    r = run(cmd)
    if r.returncode != 0:
        sys.stderr.write(f"ERROR: {desc} failed (exit {r.returncode}):\n{(r.stderr or r.stdout or '').strip()}\n")
        sys.exit(2)
    return r

def probe(path):
    # returns dict: fps(float|None), dur(float), audio(dict|None)
    r = run(["ffprobe","-v","error","-show_entries",
             "stream=index,codec_type,codec_name,channels,r_frame_rate:format=duration",
             "-of","json",path])
    if r.returncode != 0 or not r.stdout.strip():
        sys.stderr.write(f"ERROR: ffprobe failed on {path}:\n{(r.stderr or '').strip()}\n"); sys.exit(2)
    d = json.loads(r.stdout)
    fps=None; a=None; dur=float(d.get("format",{}).get("duration",0) or 0)
    for s in d.get("streams",[]):
        if s.get("codec_type")=="video" and fps is None:
            try:
                num,den = s["r_frame_rate"].split("/"); den=float(den)
                if den > 0: fps=float(num)/den
            except (ValueError, ZeroDivisionError, KeyError):
                pass  # malformed r_frame_rate -> leave fps=None, validated by caller
        if s.get("codec_type")=="audio" and a is None:
            a={"index":s["index"],"codec":s.get("codec_name"),"ch":s.get("channels")}
    return {"fps":fps,"dur":dur,"audio":a}

def env_from_wav(path, hop=0.02):
    w=wave.open(path,'rb'); n=w.getnframes(); sr=w.getframerate()
    x=np.frombuffer(w.readframes(n),dtype=np.int16).astype(np.float32); w.close()
    win=int(sr*hop); nfr=len(x)//win
    if nfr < 2:
        sys.stderr.write(f"ERROR: {path} is empty or shorter than one hop "
                         f"({n} frames) — upstream ffmpeg extraction likely failed.\n")
        sys.exit(2)
    x=x[:nfr*win].reshape(nfr,win)
    e=np.log1p(np.sqrt((x**2).mean(1)+1e-6))
    e=(e-e.mean())/(e.std()+1e-9)
    return e, 1.0/hop

def xcorr_offset(ref, seg, efps, base, srch, seg_t0):
    """best lag (seconds) placing seg (starting at seg_t0 in its own timeline) into ref,
       searching ref around [seg_t0+base-srch, +srch]. returns (offset,corr) or None.
       Rejects a peak pinned to the search-window edge (a clamped, untrustworthy match)."""
    lo=seg_t0+base-srch; hi=seg_t0+len(seg)/efps+base+srch
    ea=max(0,int(lo*efps)); eb=min(len(ref),int(hi*efps))
    r=ref[ea:eb]
    if len(r) < len(seg)+5: return None
    N=1<<int(np.ceil(np.log2(len(r)+len(seg))))
    cc=np.fft.irfft(np.fft.rfft(r,N)*np.conj(np.fft.rfft(seg,N)),N)
    cc=np.concatenate((cc[-(len(seg)-1):], cc[:len(r)]))
    lags=np.arange(-(len(seg)-1),len(r))
    k=int(np.argmax(cc))
    corr=cc[k]/(np.linalg.norm(r)*np.linalg.norm(seg)+1e-9)
    off=(ea/efps + lags[k]/efps) - seg_t0
    # peak pinned to either edge of the searched region => true offset is likely outside
    # the window; treat as unmeasurable unless correlation is very strong.
    if (k <= 1 or k >= len(lags)-2) and corr < 0.6:
        return None
    return off, float(corr)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--eng",required=True); ap.add_argument("--thai",required=True)
    ap.add_argument("--out",required=True); ap.add_argument("--work",default=None)
    ap.add_argument("--thai-lang",default="tha"); ap.add_argument("--eng-lang",default="eng")
    ap.add_argument("--default",choices=["thai","eng"],default="thai")
    ap.add_argument("--src-fps",type=float,default=None); ap.add_argument("--dst-fps",type=float,default=None)
    ap.add_argument("--pitch-mode",choices=["asetrate","atempo"],default="asetrate")
    ap.add_argument("--min-chunk",type=float,default=25.0)
    ap.add_argument("--silence-db",type=float,default=-25.0)
    ap.add_argument("--search",type=float,default=5.5,
                    help="per-chunk offset search half-width (s); widen for large ad-break jumps")
    ap.add_argument("--keep-temp",action="store_true")
    ap.add_argument("--report-only",action="store_true",help="detect+verify, do not mux")
    A=ap.parse_args()

    work = A.work or tempfile.mkdtemp(prefix="dubsync_")
    os.makedirs(work, exist_ok=True)
    def wp(n): return os.path.join(work,n)
    def cleanup():
        if not A.keep_temp and not A.work:
            shutil.rmtree(work, ignore_errors=True)

    pe=probe(A.eng); pt=probe(A.thai)
    if not pe.get("audio"): sys.stderr.write("ERROR: --eng has no audio stream\n"); sys.exit(2)
    if not pt.get("audio"): sys.stderr.write("ERROR: --thai has no audio stream\n"); sys.exit(2)
    src_fps = A.src_fps or pt["fps"]; dst_fps = A.dst_fps or pe["fps"]
    if not src_fps or not dst_fps:
        sys.stderr.write("ERROR: could not determine fps; pass --src-fps/--dst-fps\n"); sys.exit(2)
    if pe["dur"] <= 0 or pt["dur"] <= 0:
        sys.stderr.write("ERROR: could not determine a valid duration for an input\n"); sys.exit(2)
    speed = dst_fps/src_fps   # >1 means thai must be slowed (thai faster/PAL)
    print(f"[probe] eng fps={dst_fps:.3f} dur={pe['dur']:.1f}s audio={pe['audio']}")
    print(f"[probe] thai fps={src_fps:.3f} dur={pt['dur']:.1f}s audio={pt['audio']}")
    print(f"[conform] speed factor dst/src={speed:.5f}  (thai audio x{1/speed:.5f} duration)")

    # --- conform filter for thai audio ---
    if abs(speed-1.0) < 1e-4:
        af_conform = "anull"
    elif A.pitch_mode=="asetrate":
        af_conform = f"asetrate=48000*{dst_fps}/{src_fps},aresample=48000"
    else:
        af_conform = f"atempo={speed:.6f}"

    # --- extract: eng 8k env, thai conformed 8k env, thai conformed 48k raw (all checked) ---
    print("[extract] eng envelope 8k ...")
    run_checked(["ffmpeg","-y","-v","error","-i",A.eng,"-map","0:a:0","-ac","1","-ar","8000",
                 "-c:a","pcm_s16le",wp("eng8k.wav")], "extract eng 8k")
    print("[extract] thai conformed envelope 8k ...")
    run_checked(["ffmpeg","-y","-v","error","-i",A.thai,"-map","0:a:0","-af",af_conform,
                 "-ac","1","-ar","8000","-c:a","pcm_s16le",wp("tha8k.wav")], "extract thai 8k")
    print("[extract] thai conformed 48k stereo raw ...")
    run_checked(["ffmpeg","-y","-v","error","-i",A.thai,"-map","0:a:0","-af",af_conform,
                 "-f","s16le","-ac","2","-ar","48000",wp("tha48.raw")], "extract thai 48k raw")

    E,efps=env_from_wav(wp("eng8k.wav"))
    T,_  =env_from_wav(wp("tha8k.wav"))
    DUR=len(T)/efps

    # --- silence detect on thai conformed (via re-decode; -v info required) ---
    print("[silence] detecting silences in thai ...")
    r=run(["ffmpeg","-v","info","-i",A.thai,"-af",
           f"{af_conform},silencedetect=noise={A.silence_db}dB:d=0.3","-f","null","-"])
    if r.returncode != 0:
        sys.stderr.write(f"ERROR: silencedetect pass failed:\n{(r.stderr or '').strip()}\n"); sys.exit(2)
    log=(r.stderr or "")+(r.stdout or "")
    vals=[]
    for line in log.splitlines():
        for key in ("silence_start:","silence_end:"):
            if key in line:
                try: vals.append(float(line.split(key)[1].split("|")[0].strip()))
                except: pass
    mids=[(vals[i]+vals[i+1])/2 for i in range(0,len(vals)-1,2)]
    mids=[m for m in mids if 20<m<DUR-15]
    # Fallback: if silence detection yields too few boundaries, chunk at a fixed interval
    # rather than collapsing to one mega-chunk (which would treat ad-cuts as linear drift).
    if len(mids) < 3:
        sys.stderr.write(f"WARNING: only {len(mids)} silence points found; falling back to "
                         f"fixed {max(A.min_chunk,40):.0f}s chunking (per-chunk align still applies).\n")
        step=max(A.min_chunk,40.0)
        mids=[float(x) for x in np.arange(step, DUR-15, step)]
    bounds=[0.0]
    for m in mids:
        if m-bounds[-1] >= A.min_chunk: bounds.append(m)
    if DUR-bounds[-1] < 15: bounds[-1]=DUR
    else: bounds.append(DUR)
    # densify: a chunk that spans a long stretch can't track drift that occurs inside it, and
    # dubs with a loud/continuous mix yield few silences -> too-coarse chunks (poor sync). Split
    # any span > MAXC into ~55s pieces at fixed points. Safe: within a plateau both sides share
    # the offset (seamless join), and real offset jumps sit at ad-break silences (already bounds).
    MAXC=70.0
    dense=[bounds[0]]
    for b in bounds[1:]:
        span=b-dense[-1]
        if span>MAXC:
            ncut=int(np.ceil(span/55.0)); start=dense[-1]
            for k in range(1,ncut): dense.append(start+span*k/ncut)
        dense.append(b)
    bounds=dense
    chunks=[(t0,t1) for t0,t1 in zip(bounds[:-1],bounds[1:]) if t1-t0 >= 1.0]
    print(f"[chunk] {len(chunks)} chunks from {len(mids)} silence points")

    # --- measure per-chunk offset (seeded local search, monotonic-biased) ---
    def meas(t0,t1,base,srch):
        a=int(t0*efps); b=int(t1*efps); seg=T[a:b]
        if len(seg)<efps*6: return None
        return xcorr_offset(E,seg,efps,base,srch,t0)
    # robust global seed: the offset near the START is always small (just the intro
    # difference), so probe several early windows with a PHYSICAL search cap and take the
    # median of the confident ones. A single wide-±50 seed can latch a spurious far peak
    # on weakly-correlated (heavily re-dubbed) episodes and then monotonic-lock the whole
    # track to a wrong offset.
    seeds=[]
    for frac in (0.06,0.10,0.14,0.20):
        c=DUR*frac; rr=meas(c-25,c+25,0,18)
        if rr and rr[1]>0.22: seeds.append(rr[0])
    base=float(np.median(seeds)) if seeds else 0.0
    raw=[]; cor=[]
    for (t0,t1) in chunks:
        r=meas(t0,t1,base+3.5,A.search)
        if r: raw.append(r[0]); cor.append(r[1])
        else: raw.append(np.nan); cor.append(0.0)
        if r and r[1]>0.33: base=max(base, r[0]-0.3)
    raw=np.array(raw); cor=np.array(cor)

    if np.all(np.isnan(raw)):
        sys.stderr.write("ERROR: every chunk failed cross-correlation — inputs may not be the "
                         "same content, or audio is corrupt.\n"); sys.exit(2)

    # --- clean: rolling-median outlier reject + data-driven tail clamp + monotonic ---
    clean=raw.copy()
    for i in range(len(clean)):
        a=max(0,i-3); b=min(len(clean),i+4); med=np.nanmedian(raw[a:b])
        if np.isnan(raw[i]) or abs(raw[i]-med)>3.0: clean[i]=med
    # tail clamp: end-credits often diverge (dub vs original differ) and measure as noise.
    # Clamp trailing chunks past the last confident one to that last reliable offset. NOTE: no
    # global monotonic assumption — offsets can DRIFT EITHER WAY (a residual speed mismatch, as
    # on 24fps-vs-23.976 dubs, makes the offset ramp down) as well as JUMP UP at ad-break cuts.
    last=0
    for i in range(len(clean)):
        if cor[i]>=0.42 and not np.isnan(clean[i]): last=i
    for j in range(last+1,len(clean)): clean[j]=clean[last]
    # any residual NaN (a whole neighbourhood failed) -> interpolate; abort if unrecoverable
    if np.any(np.isnan(clean)):
        goodm=~np.isnan(clean)
        if not goodm.any():
            sys.stderr.write("ERROR: offset cleaning left all-NaN — cannot build.\n"); sys.exit(2)
        idx=np.arange(len(clean)); clean=np.interp(idx, idx[goodm], clean[goodm])
    # light 3-point median smooth to kill single-chunk jitter (preserves both staircases and
    # linear drift; does NOT force monotonicity).
    offs=clean.copy()
    for i in range(len(clean)):
        a=max(0,i-1); b=min(len(clean),i+2); offs[i]=float(np.median(clean[a:b]))

    # --- build + verify (factored so a self-heal pass can rebuild and compare) ---
    SR=48000
    thai=np.fromfile(wp("tha48.raw"),dtype=np.int16).reshape(-1,2).astype(np.float32)
    fade=int(0.012*SR)

    def build(off_arr):
        """place each chunk at (t0+offset) on the ref timeline; fade only at real seams;
           guard against overlap. Writes out48.raw. Returns (place, out_n, placed_samples)."""
        maxoff=max(0.0,float(np.max(off_arr)))
        out_n=int(round(max(pe["dur"], DUR+maxoff)*SR))   # never truncate real placed content
        out=np.zeros((out_n,2),dtype=np.float32)
        place=[None]*len(chunks); prev_db=-1
        for i,((t0,t1),o) in enumerate(zip(chunks,off_arr)):
            sa=max(0,int(round(t0*SR))); sb=min(len(thai),int(round(t1*SR)))
            seg=thai[sa:sb]; L=len(seg)
            if L<=0: continue
            da=int(round((t0+o)*SR)); db=da+L
            if da<0: seg=seg[-da:]; da=0; L=len(seg); db=da+L   # thai pre-roll before ref t=0
            if L<=0: continue
            if db>out_n: seg=seg[:out_n-da]; L=len(seg); db=da+L
            if L<=0: continue
            if da<prev_db:                 # rounding/rare overlap: trim head, never double-add
                trim=prev_db-da
                if trim>=L: continue
                seg=seg[trim:]; da=prev_db; L=len(seg); db=da+L
            place[i]=[da,db,seg.copy()]; prev_db=db
        placed=0
        for i,p in enumerate(place):
            if p is None: continue
            da,db,seg=p
            prev=next((place[j] for j in range(i-1,-1,-1) if place[j]), None)
            nxt =next((place[j] for j in range(i+1,len(place)) if place[j]), None)
            fin =(prev is None) or (da-prev[1] > 2)
            fout=(nxt  is None) or (nxt[0]-db > 2)
            if fin and len(seg)>fade:  seg[:fade]*=np.linspace(0,1,fade)[:,None]
            if fout and len(seg)>fade: seg[-fade:]*=np.linspace(1,0,fade)[:,None]
            out[da:db]+=seg; placed+=len(seg)
        peak=float(np.max(np.abs(out))) if out.size else 0.0   # abs(-32768)=32768 is valid
        if peak>32768: sys.stderr.write(f"WARNING: output peaked at {peak:.0f} before clip (overlap?)\n")
        np.clip(out,-32768,32767,out=out)
        out.astype(np.int16).tofile(wp("out48.raw"))
        return place, out_n, placed

    def verify():
        """cross-correlate the built track back against the reference at 19 points.
           Returns (samples[(cen,off,corr)], good[abs offsets], median_residual)."""
        run_checked(["ffmpeg","-y","-v","error","-f","s16le","-ar","48000","-ac","2","-i",wp("out48.raw"),
                     "-ac","1","-ar","8000","-c:a","pcm_s16le",wp("out8k.wav")], "downsample built track")
        O,_=env_from_wav(wp("out8k.wav"))
        samples=[]
        for f in np.arange(0.05,0.96,0.05):
            cen=DUR*f
            a=max(0,int((cen-45)*efps)); b=min(len(O),int((cen+45)*efps)); seg=O[a:b]
            r=xcorr_offset(E,seg,efps,0,8,a/efps)
            if r: samples.append((cen, r[0], r[1]))
        good=[abs(o) for (_,o,c) in samples if c>0.30 and abs(o)<3]
        med=float(np.median(good)) if good else 9.9
        return samples, good, med

    place,out_n,placed = build(offs)
    samples,good,med = verify()
    # (Automated residual "self-heal" was evaluated and removed: on weak-correlation episodes
    #  the verify itself is unreliable, so a correction can silently shift an already-good region
    #  without the guard noticing. Such episodes need manual sync, not auto-correction.)

    print(f"[build] placed {placed/SR:.1f}s onto {out_n/SR:.1f}s timeline "
          f"(gaps {out_n/SR-placed/SR:.1f}s at ad-breaks)")
    print("\n[verify] residual offset across episode (want ~0; large only at ad-break gaps):")
    for (cen,off,c) in samples:
        flag=" <-- gap/uncertain" if (abs(off)>1 and c>0.3) else ""
        print(f"    t~{cen:6.0f}s  resid={off:+.2f}s corr={c:.2f}{flag}")
    med_resid=med
    verdict = "PASS" if med_resid<0.4 else ("OK" if med_resid<0.8 else "CHECK")
    if len(good) < 5: verdict = "CHECK"   # too few reliable samples to trust the median
    print(f"[verify] median residual (real content) = {med_resid:.2f}s over {len(good)} samples => {verdict}")

    print("\n[offsets] per-chunk final offset (thai_start -> offset):")
    for i,((t0,t1),o) in enumerate(zip(chunks,offs)):
        print(f"    {i:2d} {t0:7.1f}-{t1:7.1f}s  off {o:+6.2f}  corr {cor[i]:.2f}")

    if A.report_only:
        print("\n[report-only] skipping encode/mux."); cleanup(); return

    # --- encode thai flac + mux mkv (both checked) ---
    print("\n[encode] thai -> FLAC ...")
    run_checked(["ffmpeg","-y","-v","error","-f","s16le","-ar","48000","-ac","2","-i",wp("out48.raw"),
                 "-c:a","flac","-compression_level","4",wp("tha_synced.flac")], "encode FLAC")
    print("[mux] building MKV ...")
    cmd=["ffmpeg","-y","-v","error","-i",A.eng,"-i",wp("tha_synced.flac"),
         "-map","0:v:0","-map","1:a:0","-map","0:a:0","-c:v","copy","-c:a","copy",
         "-metadata:s:a:0",f"language={A.thai_lang}","-metadata:s:a:0","title=Thai Dub (synced)",
         "-metadata:s:a:1",f"language={A.eng_lang}","-metadata:s:a:1","title=Original",
         "-disposition:a:0",("default" if A.default=="thai" else "0"),
         "-disposition:a:1",("default" if A.default=="eng" else "0"),
         A.out]
    run_checked(cmd, "mux MKV")
    print(f"[done] {A.out}  (residual {med_resid:.2f}s, {verdict})")
    cleanup()

if __name__=="__main__":
    main()
