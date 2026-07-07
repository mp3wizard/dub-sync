#!/usr/bin/env python3
"""Fill a short dub-source dropout (found by gap_scan.py) without losing content or
desyncing the rest. Pulls the post-gap dialogue up into the hole, then re-syncs QUICKLY
with atempo (pitch-PRESERVED) over a chosen window, so from the end of that window on the
audio matches the un-filled build exactly.

    python fill_gap.py --src thai_synced.flac --out thai_filled.flac \
        --cut-start 910 --cut-end 913 --resync 27

- --cut-start/--cut-end: the silent dropout (delete it; ~3s typical). Get these from gap_scan.
- --resync: seconds of post-gap audio to gently stretch so it re-syncs by (cut-start+resync+gap).
  Smaller = re-syncs sooner but more audible stretch. Pick so re-sync lands at a moment the
  user said should match the original (e.g. re-sync by 15:40 -> --resync so cut-start+... = 940).

Preserves total length (aligned to the reference timeline). atempo keeps pitch natural — do
NOT use a raw resample here (it drops pitch and sounds off). Have the user spot-check the
filled second AND the re-sync point.
"""
import subprocess, argparse, numpy as np, tempfile, os
SR=48000
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--src",required=True,help="dub audio already on the reference timeline (flac/wav)")
    ap.add_argument("--out",required=True)
    ap.add_argument("--cut-start",type=float,required=True); ap.add_argument("--cut-end",type=float,required=True)
    ap.add_argument("--resync",type=float,default=27.0)
    a=ap.parse_args()
    raw=subprocess.run(["ffmpeg","-v","error","-i",a.src,"-ac","2","-ar",str(SR),"-f","s16le","-"],
        capture_output=True).stdout
    arr=np.frombuffer(raw,dtype=np.int16).reshape(-1,2)
    g0,g1=int(a.cut_start*SR),int(a.cut_end*SR); cut=(g1-g0)/SR
    head=arr[:g0]; body=arr[g1:g1+int(a.resync*SR)]; tail=arr[g1+int(a.resync*SR):]
    target=a.resync+cut; tempo=a.resync/target
    print(f"cut {cut:.2f}s; stretch {a.resync:.1f}s -> {target:.2f}s (atempo {tempo:.3f}); "
          f"re-sync by ref {a.cut_start+target:.1f}s")
    with tempfile.TemporaryDirectory() as td:
        bi=os.path.join(td,"b.raw"); bo=os.path.join(td,"o.raw"); body.tofile(bi)
        subprocess.run(["ffmpeg","-y","-v","error","-f","s16le","-ar",str(SR),"-ac","2","-i",bi,
            "-filter:a",f"atempo={tempo}","-f","s16le","-ar",str(SR),"-ac","2",bo],check=True)
        body_s=np.fromfile(bo,dtype=np.int16).reshape(-1,2)
    out=np.concatenate([head,body_s,tail])
    if len(out)>len(arr): out=out[:len(arr)]
    elif len(out)<len(arr): out=np.concatenate([out,np.zeros((len(arr)-len(out),2),np.int16)])
    p=subprocess.Popen(["ffmpeg","-y","-v","error","-f","s16le","-ar",str(SR),"-ac","2","-i","-",
        "-c:a","flac",a.out],stdin=subprocess.PIPE); p.communicate(out.tobytes())
    print(f"wrote {a.out} (exit {p.returncode}); length preserved {len(arr)/SR:.1f}s")
if __name__=="__main__": main()
