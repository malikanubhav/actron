#!/usr/bin/env python3
"""Record observed contract-demo phases as an honest HTML replay and MP4.

Requires ffmpeg with drawtext and DejaVu Sans Mono. No external providers or models
are impersonated: every frame labels the controlled provider/coding fixtures.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = "REAL FalkorDB + git/checks | FAKE Slack/Linear/GitHub | CONTROLLED coding"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".actron/demo.mp4")
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "ACTRON_DEMO_TRACE": "1"}
    completed = subprocess.run(
        ["uv", "run", "actron", "demo"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    captured = completed.stdout + completed.stderr
    output.with_suffix(".stdout.txt").write_text(captured)
    print(captured)
    if completed.returncode:
        raise SystemExit("Demo failed; retained actual output, no successful video generated")
    trace = []
    for line in completed.stdout.splitlines():
        if "ACTRON_TRACE " in line:
            trace.append(json.loads(line.split("ACTRON_TRACE ", 1)[1]))
    if len(trace) < 7:
        raise SystemExit("Full observed workflow trace missing; refusing to invent video frames")
    trace.append(
        {
            "title": "Verification completed",
            "lines": [line for line in captured.splitlines() if " passed" in line]
            + [
                "Observed provider-contract demo only.",
                "No live API, model comparison or hosted deployment claimed.",
            ],
        }
    )
    output.with_suffix(".trace.json").write_text(json.dumps(trace, indent=2))
    cards = "".join(
        "<article><p>"
        + html.escape(LABEL)
        + "</p><h1>"
        + html.escape(item["title"])
        + "</h1><pre>"
        + html.escape("\n".join(item["lines"]))
        + "</pre><footer>"
        + f"{index + 1} / {len(trace)} · Recorded from passing executable workflow"
        + "</footer></article>"
        for index, item in enumerate(trace)
    )
    page = """<!doctype html><meta charset="utf-8"><title>Actron observed local demo</title>
<style>body{margin:0;background:#091222;color:#e6eefc;font:17px monospace}article{display:none;
box-sizing:border-box;min-height:90vh;padding:5vw}article.active{display:block}p,footer{color:#97b7d9}
h1{font-size:30px;max-width:1000px}pre{white-space:pre-wrap;line-height:1.7}button{padding:12px;
margin:8px;background:#203650;color:white;border:1px solid #7b9abd;cursor:pointer}nav{padding:0 5vw}</style>"""
    page += (
        cards
        + """<nav><button id="previous">Previous</button><button id="next">Next</button>
<button id="play">Play / pause</button></nav><script>const slides=[...document.querySelectorAll('article')];
let current=0,timer=null;function show(n){slides[current].classList.remove('active');
current=(n+slides.length)%slides.length;slides[current].classList.add('active')}slides[0].classList.add('active');
document.querySelector('#previous').onclick=()=>show(current-1);
document.querySelector('#next').onclick=()=>show(current+1);
document.querySelector('#play').onclick=()=>{if(timer){clearInterval(timer);timer=null}else{timer=setInterval(()=>show(current+1),6000)}};
document.onkeydown=e=>{if(e.key==='ArrowRight')show(current+1);if(e.key==='ArrowLeft')show(current-1)};</script>"""
    )
    output.with_suffix(".html").write_text(page)
    font = subprocess.check_output(["fc-match", "-f", "%{file}", "monospace"], text=True).strip()
    with tempfile.TemporaryDirectory(prefix="actron-video-") as temporary:
        directory = Path(temporary)
        images = []
        for index, item in enumerate(trace):
            text = "ACTRON | OBSERVED LOCAL WORKFLOW\n\n" + LABEL + "\n\n"
            text += "\n".join(textwrap.wrap(item["title"], 82)) + "\n\n"
            for line in item["lines"]:
                text += "\n".join(textwrap.wrap(line, 90, break_long_words=True)) + "\n"
            text += f"\nFrame {index + 1}/{len(trace)} | Captured execution; fixture authority is simulated"
            textfile, picture = directory / f"frame-{index}.txt", directory / f"frame-{index}.png"
            textfile.write_text(text)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=0x091222:s=1280x720",
                    "-vf",
                    f"drawtext=fontfile='{font}':textfile='{textfile}':expansion=none:fontcolor=0xe6eefc:fontsize=21:x=36:y=38:line_spacing=8",
                    "-frames:v",
                    "1",
                    "-threads",
                    "1",
                    str(picture),
                ],
                check=True,
            )
            images.append(picture)
        listing = directory / "slides.txt"
        listing.write_text(
            "".join(f"file '{picture}'\nduration 6\n" for picture in images)
            + f"file '{images[-1]}'\n"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-vf",
                "fps=24",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
        )
    print("Recorded:", output)
    print("Replay:", output.with_suffix(".html"))
    print("Observed trace:", output.with_suffix(".trace.json"))


if __name__ == "__main__":
    main()
