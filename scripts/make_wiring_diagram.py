"""Draw docs/rig-diagram.svg: the imaging rig, and what connects it to the mini PC, the MCP server and the model."""
from html import escape
from pathlib import Path

W, H = 1180, 1020
INK, MUTED, GRID, PAPER = "#1f2328", "#656d76", "#d0d7de", "#ffffff"
FONT = "font-family=\"-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif\""
MONO = "font-family=\"ui-monospace, 'SF Mono', Menlo, Consolas, monospace\""
# status: (stroke, fill, dash)
ST = {
    "tested": ("#138a70", "#e4f4ef", None),
    "avail": ("#b87508", "#fdf3df", "7 4"),
    "none": ("#66738a", "#eff1f5", "2 4"),
    "chain": ("#1f86c4", "#e6f2fa", None),
    "sim": ("#6b57c9", "#eeeafc", "7 4"),
    "llm": ("#6b57c9", "#eeeafc", None),
}
out = []


def t(x, y, s, size=13, fill=INK, anchor="start", weight="normal", mono=False):
    out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" {MONO if mono else FONT}>{escape(s)}</text>')


def box(x, y, w, h, status, title, lines=(), tools=None, size=13, dash=True, radius=6):
    stroke, fill, d = ST[status]
    da = f' stroke-dasharray="{d}"' if (d and dash) else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.6"{da}/>')
    t(x + 10, y + 20, title, size, INK, weight="600")
    for i, line in enumerate(lines):
        t(x + 10, y + 38 + i * 15, line, 11.5, MUTED)
    if tools is not None:
        label = f"{tools} tools" if tools else "no tools"
        if w < 200:
            t(x + w - 8, y + h - 8, label, 10.5, stroke, "end", mono=True)
        else:
            t(x + w - 8, y + 18, label, 10.5, stroke, "end", mono=True)


def panel(x, y, w, h, label, sub=""):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="none" stroke="{GRID}" stroke-width="1.4"/>')
    t(x + 14, y + 22, label, 12, MUTED, weight="600")
    if sub:
        t(x + 14 + 8 * len(label) * 0.78 + 12, y + 22, sub, 11.5, MUTED)


def arrow(x1, y1, x2, y2, colour, dash=None, label=None, lx=None, ly=None, anchor="middle", both=False, width=2):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    ms = f' marker-start="url(#a-{colour[1:]})"' if both else ""
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" stroke-width="{width}"{da}{ms} marker-end="url(#a-{colour[1:]})"/>')
    if label:
        for i, line in enumerate(label.split("\n")):
            t(lx if lx is not None else (x1 + x2) / 2, (ly if ly is not None else (y1 + y2) / 2) + i * 14, line, 11.5, colour, anchor)


# ---------- defs ----------
out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Diagram of an imaging rig, the mini PC, the MCP server and the language model, marked by what the benchmark tests">')
out.append("<title>Imaging rig and benchmark: what connects to what</title>")
out.append("<defs>")
for col in sorted({ST[k][0] for k in ST}):
    out.append(f'<marker id="a-{col[1:]}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
out.append("</defs>")
out.append(f'<rect width="{W}" height="{H}" fill="{PAPER}"/>')

# ---------- title and key ----------
t(30, 38, "Imaging rig and benchmark", 24, weight="700")
t(30, 60, "Every part of a full rig, what connects to what, and what the benchmark touches.", 13.5, MUTED)
kx = 30
for status, label in (("tested", "Tested in the benchmark"), ("avail", "MCP tools exist, not tested"), ("none", "Not covered (no tools)"), ("sim", "Simulated in the benchmark")):
    stroke, fill, d = ST[status]
    da = f' stroke-dasharray="{d}"' if d else ""
    out.append(f'<rect x="{kx}" y="78" width="26" height="16" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1.6"{da}/>')
    t(kx + 34, 91, label, 12.5)
    kx += 34 + len(label) * 6.9 + 26

# ---------- the rig ----------
panel(30, 112, 1120, 420, "THE RIG", "as it would be set up in the field")
# mount, carrying the telescope
box(50, 150, 780, 255, "tested", "Mount", ["Equatorial GoTo head on a tripod: slews, tracks, parks."], tools=12)
box(70, 196, 740, 195, "none", "Telescope", ["Optical tube, about 430 mm focal length: a field of 1.3 by 1.0 degrees on this camera."], tools=0, dash=True)
# the light path, front to back
parts = [
    ("avail", "Flat panel", ["Even light for", "calibration", "frames"], 8, 96, 100),
    ("none", "Dew shield", ["and heater strap", "keep glass dry"], None, 100, 100),
    ("tested", "Focuser", ["Motorised: sets", "sharp focus"], 7, 96, 100),
    ("avail", "Rotator", ["Turns the camera", "to frame a target"], 9, 108, 100),
    ("tested", "Filter wheel", ["L, R, G, B and", "narrowband filters"], 5, 112, 100),
    ("tested", "Camera", ["Cooled sensor,", "2000 x 1500 px"], 4, 100, 100),
]
x = 84
xs = {}
for status, name, lines, tools, w, h in parts:
    box(x, 244, w, h, status, name, lines, tools, size=12.5)
    xs[name] = (x, w)
    x += w + 12
t(84, 372, "light enters here", 11.5, MUTED)
out.append(f'<line x1="170" y1="368" x2="780" y2="368" stroke="{MUTED}" stroke-width="1.4" marker-end="url(#a-{ST["none"][0][1:]})"/>')
t(780, 384, "to the sensor", 11.5, MUTED, "end")
# guide scope on the tube
box(884, 150, 248, 126, "avail", "Guide scope and camera", ["A second small scope riding on the", "tube. It watches a star and sends", "corrections to the mount, usually", "through PHD2 on the mini PC."], tools=8, size=12.5)
out.append(f'<line x1="810" y1="236" x2="884" y2="236" stroke="{ST["avail"][0]}" stroke-width="1.6" stroke-dasharray="4 3"/>')
# site equipment
box(884, 290, 248, 101, "none", "Power box and dew heaters", ["Switched 12 V for the gear, and the", "heater bands. A model cannot see or", "switch them."], tools=0, size=12.5)
box(50, 422, 360, 90, "avail", "Dome or roll-off roof", ["Opens, closes and follows the telescope.", "The simulated setup has none."], tools=14, size=12.5)
box(430, 422, 400, 90, "none", "Weather and safety monitor", ["Cloud, rain and wind sensors that say when it is unsafe", "to observe. No tools, so no safety test can use them."], tools=0, size=12.5)
box(852, 410, 280, 102, "none", "N.I.N.A. features with no tools", ["Sequencer, framing assistant, polar", "alignment and equipment profiles.", "A model cannot use any of them."], tools=0, size=12.5)
# the three bundles of wiring that leave the rig
for cx, status in ((120, "tested"), (330, "avail"), (560, "none")):
    pass

# ---------- wires from the rig to the mini PC ----------
tc, ac, nc = ST["tested"][0], ST["avail"][0], ST["none"][0]
arrow(110, 532, 110, 606, tc, None, "Mount, camera, focuser,\nfilter wheel\nUSB or serial, through ASCOM", 124, 560, "start", width=3)
arrow(375, 532, 375, 606, ac, "7 4", "Guide camera (PHD2),\nflat panel, rotator, dome", 389, 560, "start")
out.append(f'<line x1="640" y1="532" x2="640" y2="572" stroke="{nc}" stroke-width="2" stroke-dasharray="2 4"/>')
out.append(f'<line x1="626" y1="572" x2="654" y2="572" stroke="{nc}" stroke-width="3"/>')
t(664, 552, "Power and weather: no link", 11.5, nc)
t(664, 566, "to the software at all", 11.5, nc)

# ---------- the mini PC ----------
panel(30, 608, 470, 372, "MINI PC", "the N.I.N.A. node")
box(48, 640, 434, 56, "chain", "ASCOM drivers and Alpaca", ["The devices connect here. In the benchmark they are simulated."], size=12.5)
box(48, 708, 434, 96, "chain", "N.I.N.A. imaging software", ["Connects the devices, slews, captures, plate solves and", "autofocuses. The Advanced API plugin (2.2.15.2) exposes", "all of it as REST on port 1888."], size=13)
box(48, 816, 434, 56, "avail", "PHD2 (guiding)", ["A separate program that N.I.N.A. connects to. No task needs it."], size=12.5)
box(48, 884, 434, 84, "sim", "Sky Simulator  (benchmark only)", ["ASCOM Alpaca simulators for the camera, mount, focuser and", "filter wheel: they stand in for the real hardware above.", "Reset before every run, restarted over SSH if that fails."], size=13)

# ---------- the Mac ----------
panel(580, 608, 330, 372, "MAC", "the benchmark host")
box(598, 640, 294, 140, "chain", "Harness", ["Resets the simulators, runs one task with", "one model, reads the equipment's end", "state to score it, and logs every call.", "Then builds the charts and the README."], size=13)
box(598, 830, 294, 138, "chain", "MCP server", ["nina-advanced-mcp, started fresh for every", "run. 106 tools; the harness adds autofocus,", "centre-on-target and a capped wait."], tools=106, size=13)
arrow(745, 780, 745, 830, ST["chain"][0], None, "MCP over stdio", 757, 810, "start", both=True)

# ---------- the model ----------
panel(990, 608, 160, 372, "THE MODEL")
box(1004, 640, 132, 328, "llm", "One per run", ["gpt-4.1", "gpt-6-sol", "(OpenAI)", "", "Claude Haiku,", "Sonnet, Opus 5.5", "(Anthropic)", "", "deepseek-chat,", "DeepSeek V4 Pro", "", "qwen3:8b", "(local, Ollama)"], size=13)

# ---------- the links between the three ----------
cc = ST["chain"][0]
arrow(598, 735, 482, 735, cc, None, "reset and\nscore\n(REST)", 540, 700, "middle", both=True)
# the MCP server reaches the plugin by an elbow, up the gap between the two machines
out.append(f'<polyline points="598,900 540,900 540,785 482,785" fill="none" stroke="{cc}" stroke-width="2" marker-end="url(#a-{cc[1:]})" marker-start="url(#a-{cc[1:]})"/>')
t(540, 922, "tool calls:", 11.5, cc, "middle")
t(540, 936, "HTTP :1888", 11.5, cc, "middle")
arrow(892, 700, 1004, 700, ST["llm"][0], None, "chat API\nwith tools", 948, 680, "middle", both=True)
t(948, 726, "tool calls out,", 11.5, ST["llm"][0], "middle")
t(948, 740, "results back", 11.5, ST["llm"][0], "middle")
t(30, 1000, "Tool counts are the MCP tools whose names mention the device. The benchmark scores from the equipment's end state, not from what the model says.", 11, MUTED)

out.append("</svg>")
(Path(__file__).resolve().parents[1] / "docs" / "rig-diagram.svg").write_text("\n".join(out) + "\n")
print("written")
