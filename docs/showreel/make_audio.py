"""Synthesise the showreel's sound track from the animation's cue times.

    python docs/showreel/make_audio.py cues.json audio.wav

Only numpy. Every sound is made of sines and noise, shaped with envelopes and
filters, and placed where the picture does something: a pluck for each node of
the map as it lands, a sweep that pans with the x-ray beam, a switch click for
each Odoo fix. Under it, a chord progression and a quiet pulse at the tempo the
cuts already fall on (117.6 BPM).
"""
import json
import sys
import wave

import numpy as np

SR = 48000
DURATION = 15.0
N = int(SR * DURATION)
BEAT = 0.51
rng = np.random.default_rng(11)


def seconds(d):
    return np.arange(int(d * SR)) / SR


def db(x):
    return 10 ** (x / 20)


# ---------------------------------------------------------------- filters

def spectral(x, response):
    """Zero-phase filter: multiply the spectrum by response(freqs)."""
    n = len(x)
    size = 1 << (n - 1).bit_length()
    spec = np.fft.rfft(x, size)
    spec *= response(np.fft.rfftfreq(size, 1 / SR))
    return np.fft.irfft(spec, size)[:n]


def lowpass(x, fc, order=2):
    return spectral(x, lambda f: 1 / np.sqrt(1 + (f / fc) ** (2 * order)))


def highpass(x, fc, order=2):
    return spectral(x, lambda f: 1 / np.sqrt(1 + (fc / np.maximum(f, 1e-3)) ** (2 * order)))


def bandpass(x, lo, hi, order=2):
    return highpass(lowpass(x, hi, order), lo, order)


def sweep_bandpass(x, centre, q=2.0):
    """State-variable band-pass whose centre frequency follows an array, sample by sample."""
    out = np.empty_like(x)
    low = band = 0.0
    g_all = np.tan(np.pi * np.clip(centre, 20, SR * 0.45) / SR)
    k = 1 / q
    for i, v in enumerate(x):
        g = g_all[i]
        hp = (v - (k + g) * band - low) / (1 + g * (k + g))
        bp = g * hp + band
        lp = g * bp + low
        band, low = bp + g * hp, lp + g * bp
        out[i] = bp
    return out


# ---------------------------------------------------------------- the mix

class Mix:
    def __init__(self):
        self.dry = np.zeros((2, N))
        self.send = np.zeros((2, N))

    def add(self, sig, at, gain=1.0, pan=0.0, verb=0.25):
        sig = np.asarray(sig, dtype=float)
        if sig.ndim == 1:
            angle = (np.clip(pan, -1, 1) + 1) * np.pi / 4
            sig = np.vstack([sig * np.cos(angle), sig * np.sin(angle)]) * np.sqrt(2)
        start = int(round(at * SR))
        if start < 0:
            sig, start = sig[:, -start:], 0
        end = min(N, start + sig.shape[1])
        if end <= start:
            return
        part = sig[:, :end - start] * gain
        self.dry[:, start:end] += part
        self.send[:, start:end] += part * verb

    def render(self):
        # A small hall: decaying stereo noise as the impulse response.
        length = int(1.9 * SR)
        t = np.arange(length) / SR
        ir = []
        for _ in range(2):
            noise = rng.standard_normal(length) * np.exp(-t / 0.42)
            noise = lowpass(noise, 5500, 1)
            noise[: int(0.018 * SR)] = 0
            ir.append(noise / np.sqrt(np.sum(noise ** 2)))
        size = 1 << (N + length).bit_length()
        wet = np.vstack([np.fft.irfft(np.fft.rfft(self.send[c], size) * np.fft.rfft(ir[c], size), size)[:N]
                         for c in range(2)])
        out = self.dry + wet * 0.9
        out = highpass(out[0], 28, 2), highpass(out[1], 28, 2)
        out = np.vstack(out)
        # Gentle saturation, then peak at -1 dBFS.
        out = np.tanh(out * 1.3) / np.tanh(1.3)
        return out / np.max(np.abs(out)) * db(-1)


# ---------------------------------------------------------------- instruments

def env(n, attack, release, curve=4.0):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    r = np.exp(-curve * t / max(release, 1e-4))
    return a * r


def sine(freq, d, phase=0.0):
    t = seconds(d)
    return np.sin(2 * np.pi * freq * t + phase)


def glide(f0, f1, d, shape=6.0):
    t = seconds(d)
    f = f1 + (f0 - f1) * np.exp(-shape * t / d)
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def noise(d):
    return rng.standard_normal(int(d * SR))


def kick(d=0.3, f0=62, f1=48):
    body = glide(f0 * 2.2, f1, d, 9) * env(int(d * SR), 0.002, d, 6)
    body += glide(f0 * 4, f1 * 2, d, 12) * env(int(d * SR), 0.001, d * 0.5, 7) * 0.25
    click = highpass(noise(0.006), 2500) * env(int(0.006 * SR), 0.0002, 0.006, 6)
    out = body
    out[: len(click)] += click * 0.35
    return out


def sub_boom(d=1.8, f0=70, f1=38):
    return glide(f0, f1, d, 4) * env(int(d * SR), 0.004, d, 3.2)


def hat(d=0.05):
    return highpass(noise(d), 7000, 3) * env(int(d * SR), 0.0005, d, 7)


def tick(freq=2600, d=0.03):
    n = int(d * SR)
    return (sine(freq, d) * 0.7 + highpass(noise(d), 4000) * 0.3) * env(n, 0.0003, d, 9)


def blip(f0, f1, d=0.12):
    return glide(f0, f1, d, 3) * env(int(d * SR), 0.003, d, 4)


def pluck(freq, d=0.9):
    """A soft FM bell-pluck."""
    t = seconds(d)
    index = 2.4 * np.exp(-t * 9)
    mod = np.sin(2 * np.pi * freq * 2 * t) * index
    body = np.sin(2 * np.pi * freq * t + mod)
    return body * env(len(t), 0.002, d, 5)


def ding(freqs=(1318.5, 1975.5), d=0.9):
    t = seconds(d)
    out = sum(np.sin(2 * np.pi * f * t) * (0.6 ** i) for i, f in enumerate(freqs))
    out += 0.25 * np.sin(2 * np.pi * freqs[0] * 2.76 * t) * np.exp(-t * 18)
    return out * env(len(t), 0.001, d, 5)


def whoosh(d, lo, hi, q=1.4, attack=0.6):
    n = int(d * SR)
    x = np.linspace(0, 1, n)
    bell = np.where(x < attack, np.sin(np.pi / 2 * x / attack) ** 2, np.cos(np.pi / 2 * (x - attack) / (1 - attack)) ** 2)
    centre = lo * (hi / lo) ** bell
    return sweep_bandpass(noise(d), centre, q) * bell


def counter_ticks(mix, t0, t1, steps=18, gain=0.07, freq=3000, pan=0.0):
    """Ticks where an ease-out counter changes value: fast at first, then slowing down."""
    for k in range(1, steps + 1):
        p = k / steps
        u = -np.log2(1 - p * (1 - 2 ** -10)) / 10  # inverse of ease-out-expo
        mix.add(tick(freq * (1 + 0.02 * k), 0.02), t0 + u * (t1 - t0), gain * (1 - 0.4 * p), pan, 0.1)


def sparkle(mix, t0, t1, density, gain=0.05):
    """Granular glitter: short high sine grains, scattered in time and stereo."""
    t = t0
    while t < t1:
        rate = max(density((t - t0) / (t1 - t0)), 1e-3)
        t += rng.exponential(1 / rate)
        freq = rng.uniform(2800, 8500)
        d = rng.uniform(0.008, 0.03)
        grain = sine(freq, d) * np.hanning(int(d * SR))
        mix.add(grain, t, gain * rng.uniform(0.4, 1), rng.uniform(-0.9, 0.9), 0.35)


def pad(mix, chords, gain=0.035):
    """Slow chords: detuned sine pairs with a little harmonic colour, crossfaded."""
    fade = 0.45
    for start, end, freqs, bright in chords:
        a, b = max(0, start - fade / 2), min(DURATION, end + fade / 2)
        d = b - a
        t = seconds(d)
        shape = np.clip(np.minimum(t / fade, (d - t) / fade), 0, 1) ** 1.5
        for i, f in enumerate(freqs):
            voice = np.zeros_like(t)
            for detune in (-0.0018, 0.0018):
                ph = rng.uniform(0, 2 * np.pi)
                voice += np.sin(2 * np.pi * f * (1 + detune) * t + ph)
                voice += bright * 0.35 * np.sin(2 * np.pi * 2 * f * (1 + detune) * t + ph)
            voice *= 1 + 0.2 * np.sin(2 * np.pi * (0.13 + 0.05 * i) * t + i)
            weight = (0.5, 0.8, 1.0, 0.9, 0.8, 0.7)[i]  # keep the bass voice light
            mix.add(voice * shape * gain * weight, a, 1.0, (-1) ** i * 0.35, 0.5)


# ---------------------------------------------------------------- the score

def score(cues):
    T = cues['T']
    mix = Mix()
    beat = lambda k: 7.86 + k * BEAT  # the findings cards sit on beats 0, 2 and 4

    # Chords: Dm9, Bbmaj7 when the problems show, C for the report, Fmaj9 for the title.
    pad(mix, [
        (0.0, T['dim'], [73.42, 110.0, 174.61, 261.63, 329.63], 0.2),
        (T['dim'], T['report'], [58.27, 87.31, 146.83, 220.0, 329.63], 0.25),
        (T['report'], T['title'] + 0.28, [65.41, 98.0, 164.81, 196.0, 293.66], 0.35),
        (T['title'] + 0.28, DURATION, [87.31, 130.81, 164.81, 196.0, 220.0, 392.0], 0.5),
    ])

    # The pulse: from the reveal of the count to the title.
    for k in range(-11, 10):
        t = beat(k)
        if t < T['reveal'][0] - 0.02 or t > T['title']:
            continue
        mix.add(kick(), t, 0.5 if t > 3.7 else 0.35, 0, 0.05)
        if t > T['chart'] - 0.05:
            mix.add(hat(), t + BEAT / 2, 0.06, 0.25, 0.1)
            mix.add(hat(0.03), t + BEAT * 0.75, 0.03, -0.25, 0.1)

    # 01: the wall comes into focus; one tick per word; the tracking value is selected.
    mix.add(whoosh(0.9, 180, 1400, 1.2, 0.8), 0.0, 0.12, -0.2, 0.5)
    for i, w in enumerate(cues['words'][:6]):
        mix.add(tick(1900 + 90 * i, 0.025), w + 0.06, 0.05, -0.3 + 0.12 * i, 0.2)
    mix.add(blip(880, 1320, 0.14), T['focus'][0] + 0.05, 0.1, 0.5, 0.3)
    for k in range(10):
        mix.add(tick(3800 + 200 * (k % 3), 0.012), T['focus'][0] + 0.32 + k * 0.04, 0.03, 0.6, 0.1)

    # The pull-back, and the count it reveals.
    mix.add(whoosh(1.3, 120, 3200, 1.1, 0.55), T['pull'][0] - 0.1, 0.34, 0.0, 0.4)
    mix.add(sub_boom(1.6, 64, 40), T['reveal'][0], 0.35, 0, 0.2)
    counter_ticks(mix, T['reveal'][0], T['reveal'][0] + 0.6, 20, 0.06, 2600)

    # 02: the x-ray beam, panned with its position on screen.
    a, b = T['scan']
    d = b - a
    x = np.linspace(0, 1, int(d * SR))
    p = -(np.cos(np.pi * x) - 1) / 2
    body = sweep_bandpass(noise(d), 900 * (4.5 ** np.sin(np.pi * x)), 3.0) * np.sin(np.pi * x) ** 0.7
    hum = bandpass(np.sign(sine(110, d)) * 0.3, 200, 2400) * np.sin(np.pi * x)
    stereo = np.vstack([(body + hum) * np.cos((p * 2) * np.pi / 4), (body + hum) * np.sin((p * 2) * np.pi / 4)])
    mix.add(stereo * np.sqrt(2), a, 0.3, 0, 0.3)
    for k in range(40):
        t = a + d * k / 40 + rng.uniform(0, d / 40)
        mix.add(tick(rng.uniform(4000, 7000), 0.008), t, 0.035, (t - a) / d * 2 - 1, 0.1)

    # 03-04: events fly into the event log, then pour into the map.
    sparkle(mix, T['chart'], T['chart'] + 0.8, lambda u: 90 * np.sin(np.pi * min(u * 1.2, 1)), 0.035)
    mix.add(whoosh(1.0, 300, 2600, 1.6, 0.4), T['chart'] - 0.05, 0.12, 0.3, 0.4)
    sparkle(mix, T['swarm'], T['swarm'] + 1.4, lambda u: 140 * np.sin(np.pi * u), 0.04)
    mix.add(whoosh(1.5, 200, 4000, 1.8, 0.75), T['swarm'] - 0.1, 0.12, -0.2, 0.5)
    scale = [293.66, 349.23, 392.0, 440.0, 523.25, 587.33, 698.46, 783.99, 880.0, 1046.5]
    for i, node in enumerate(cues['nodes']):
        mix.add(pluck(scale[i % len(scale)]), node['t'] + 0.1, 0.13, 0.4 if not node['main'] else -0.15, 0.45)

    # 05: each problem lands on a beat; its fix switches on with a click and a bright ding.
    mix.add(sub_boom(1.2, 58, 40), T['dim'], 0.28, 0, 0.3)
    for s in T['cards'][:3]:
        mix.add(kick(0.5, 70, 42), s + 0.04, 0.55, 0, 0.1)
        mix.add(bandpass(noise(0.25), 300, 3500) * env(int(0.25 * SR), 0.001, 0.25, 7), s + 0.04, 0.16, 0, 0.3)
        counter_ticks(mix, s + 0.06, s + 0.62, 14, 0.05, 2300, -0.4)
        mix.add(tick(1500, 0.02), s + 0.6, 0.12, -0.5, 0.1)
        mix.add(tick(2600, 0.02), s + 0.66, 0.12, -0.5, 0.1)
        mix.add(ding(), s + 0.66, 0.1, -0.35, 0.5)

    # 06: the map shrinks into the report; tiles, counters, the command being typed.
    mix.add(whoosh(0.8, 2400, 250, 1.3, 0.25), T['report'] - 0.05, 0.2, 0.2, 0.4)
    for i, tt in enumerate(cues['tiles']):
        mix.add(tick(1700 + 120 * i, 0.03), tt, 0.07, 0.2 + 0.15 * i, 0.2)
    counter_ticks(mix, cues['tiles'][0], cues['tiles'][0] + 0.85, 16, 0.04, 3200, 0.4)
    for tt in cues['typing']:
        key = bandpass(noise(0.012), 1800, 6000) * env(int(0.012 * SR), 0.0003, 0.012, 7)
        key += sine(rng.uniform(160, 220), 0.02)[: len(key)] * 0.4
        mix.add(key, tt + rng.uniform(-0.006, 0.006), rng.uniform(0.07, 0.11), -0.45, 0.15)
    mix.add(ding((1567.98, 2349.3), 0.7), T['h5'][0] + 1.06, 0.06, -0.4, 0.4)
    mix.add(ding((2093.0, 3136.0), 0.6), cues['check'] + 0.1, 0.05, 0.4, 0.4)

    # 07: a riser, the X, the name.
    t0, hit = T['title'] - 0.62, T['title'] + 0.28
    d = hit - t0
    x = np.linspace(0, 1, int(d * SR))
    riser = sweep_bandpass(noise(d), 200 * (40 ** (x ** 1.6)), 2.0) * x ** 2.2
    riser += glide(180, 900, d, -2.5) * x ** 3 * 0.25
    mix.add(riser, t0, 0.3, 0, 0.4)
    mix.add(sub_boom(2.4, 76, 32), hit, 0.95, 0, 0.3)
    crash = np.vstack([bandpass(noise(2.2), 900, 9000, 1), bandpass(noise(2.2), 900, 9000, 1)])
    crash *= env(crash.shape[1], 0.001, 2.2, 5)
    mix.add(crash, hit, 0.2, 0, 0.6)
    for i, f in enumerate([1046.5, 1318.5, 1568.0, 2093.0, 2637.0]):
        shimmer = sine(f, 2.6) * env(int(2.6 * SR), 0.02, 2.6, 2.4) * (1 + 0.3 * sine(5 + i, 2.6))
        mix.add(shimmer, hit + 0.02 * i, 0.03, (-1) ** i * 0.5, 0.8)
    for i, tt in enumerate(cues['letters']):
        mix.add(tick(2400 + 60 * i, 0.015), tt + 0.05, 0.035, -0.6 + 0.08 * i, 0.3)

    out = mix.render()
    fade = np.clip((DURATION - np.arange(N) / SR) / 0.35, 0, 1)
    return out * fade * db(-3)  # about -15 LUFS, a comfortable level for the web


def write_wav(path, stereo):
    dithered = stereo * 32767 + rng.triangular(-1, 0, 1, stereo.shape)
    data = np.clip(np.round(dithered), -32768, 32767).astype('<i2').T.tobytes()
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data)


if __name__ == '__main__':
    cues_path, out_path = sys.argv[1], sys.argv[2]
    write_wav(out_path, score(json.load(open(cues_path, encoding='utf-8'))))
    print(f'Wrote {out_path}')
