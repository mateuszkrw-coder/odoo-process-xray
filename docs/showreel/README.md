# The showreel

The 15-second video at the top of the project README. It is code, not an edit:
[`showreel.js`](showreel.js) draws every frame on a canvas as a function of time, from
the demo's real event log. Each of the 2,984 dots is one event from Odoo's chatter,
and every number on screen comes from the same analysis as the report
([`make_data.py`](make_data.py) writes it to `data.js`).

| Seconds | What it shows |
|---|---|
| 0 – 2.7 | Odoo's chatter: one card per tracked change, 2,984 of them |
| 2.7 – 3.8 | The x-ray: every card becomes an event |
| 3.8 – 5.0 | The event log: one row per order, time from left to right |
| 5.0 – 7.3 | The process map fills up: one dot per event, one count per order |
| 7.3 – 11.0 | Where orders get stuck, where it concentrates, and the Odoo setting that fixes it |
| 11.0 – 13.0 | One command, one HTML report |
| 13.0 – 15.0 | Title |

## Watch it live

Open [`index.html`](index.html) in a browser: space pauses, the arrow keys step.
`index.html?t=8.5` shows a single frame.

## Render it

```bash
npm install -D playwright          # or point NODE_PATH at a global install
python docs/showreel/make_data.py  # only if the demo data changed
node docs/showreel/render.mjs      # about 15 minutes on 4 cores
```

This writes `docs/showreel.mp4` (1080p60, with sound), `docs/showreel.avif` (the
looping version in the README: an animated AVIF autoplays like a GIF at a fraction of
the size) and `docs/showreel.png` (a still for readers who prefer reduced motion).
The [demo workflow](../../.github/workflows/demo.yml) publishes the MP4 on GitHub Pages,
which is where the README's "Watch in HD" link points: GitHub's own file view only
offers an MP4 as a download.
Headless Chromium draws each frame 8 times across a 180° shutter for motion blur,
WebGL adds bloom, lens fringing and a vignette, and ffmpeg encodes. `--sub 1` renders a
quick draft without motion blur.

The sound track is synthesised as well ([`make_audio.py`](make_audio.py), numpy
only): a chord progression, a quiet pulse at the tempo the cuts fall on, and a sound
for each thing that happens on screen, timed from the animation's own cues.

Fonts: Inter Tight, Instrument Serif and JetBrains Mono, under the SIL Open Font
License ([`fonts/OFL.txt`](fonts/OFL.txt)).
