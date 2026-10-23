"""Draw docs/telescope-rig.svg: a labelled line drawing of a telescope rig for readers who have never seen one.

The rig follows a real compact-mount set-up: a black pier, the red mount body, a red dovetail bar, a white refractor with a
guide scope on top, and the camera train at the back. It is drawn facing left; the whole picture is mirrored from the
"facing right" coordinates used below, and the text inside it is mirrored back.
"""
import math
from html import escape
from pathlib import Path

W, H = 1180, 735
INK, MUTED, GRID, PAPER = "#1f2328", "#656d76", "#d0d7de", "#ffffff"
RED = "#c2413b"
FONT = "font-family=\"-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif\""
ROBOT, POWER, PASSIVE = "#138a70", "#b87508", "#66738a"
TAGS = {"ROBOTIC": ROBOT, "POWERED": POWER, "PASSIVE": PASSIVE}
out = []
SW = 2.3  # one line weight for the whole drawing


def t(x, y, s, size=13, fill=INK, anchor="start", weight="normal"):
    out.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" {FONT}>{escape(s)}</text>')


def ut(x, y, s, size=12, fill=INK, weight="normal"):
    """Text inside the mirrored drawing, flipped back so it reads normally, centred on x."""
    out.append(f'<text transform="translate({x:.1f} {y:.1f}) scale(-1 1)" font-size="{size}" fill="{fill}" text-anchor="middle" font-weight="{weight}" {FONT}>{escape(s)}</text>')


# the tube's own coordinates (x along the tube from the rear, y across) mapped to the picture, before mirroring
ANG = math.radians(-48)
CX, CY, MID = 560, 300, 165
COS, SIN = math.cos(ANG), math.sin(ANG)


def P(lx, ly):
    dx, dy = lx - MID, ly
    return (CX + dx * COS - dy * SIN, CY + dx * SIN + dy * COS)


def M(p):                       # a point of the drawing, as it lands on the page after mirroring
    return (W - p[0], p[1])


def path(d, stroke=INK, fill="#ffffff", w=SW, dash=None, cap="round"):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="round"{da}/>')


def box(x, y, w, h, stroke=INK, fill="#ffffff", rx=4, wd=SW):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{wd}" stroke-linejoin="round"/>')


def line(x1, y1, x2, y2, stroke=INK, w=SW):
    out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{w}" stroke-linecap="round"/>')


out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="A labelled line drawing of a telescope rig: pier, motorised mount, telescope, guide scope, focuser, filter wheel, camera, and the mini computer that controls them">')
out.append("<title>An astrophotography rig</title>")
out.append(f'<rect width="{W}" height="{H}" fill="{PAPER}"/>')
t(30, 40, "An astrophotography rig", 25, weight="700")
kx = 30
for tag, label in (("ROBOTIC", "moves, or is controlled by a computer"), ("POWERED", "electrical, simple on/off"), ("PASSIVE", "no electronics")):
    out.append(f'<rect x="{kx}" y="62" width="64" height="18" rx="9" fill="none" stroke="{TAGS[tag]}" stroke-width="1.5"/>')
    t(kx + 32, 75, tag, 10, TAGS[tag], "middle", "700")
    t(kx + 72, 75, label, 12, MUTED)
    kx += 72 + len(label) * 6.2 + 30

# ground
out.append(f'<rect x="0" y="650" width="{W}" height="{H - 650}" fill="#f3f5f8"/>')
out.append(f'<line x1="0" y1="650" x2="{W}" y2="650" stroke="{GRID}" stroke-width="1.5"/>')

# ================= the rig, drawn facing right, then mirrored =================
out.append(f'<g transform="translate({W} 0) scale(-1 1)">')

# --- where the mount sits: the Dec housing is well below the tube, joined to it by a red elbow ---
dec = P(MID, 96)
U48 = (math.cos(math.radians(48)), -math.sin(math.radians(48)))     # up the polar axis
bx, by = dec[0] - 150 * U48[0], dec[1] - 150 * U48[1]                 # the foot of the mount, on the pier
# --- the pier: a black column on a flange ---
top = by + 48
path(f"M{bx - 62:.0f},646 A62,10 0 0 0 {bx + 62:.0f},646 A62,10 0 0 0 {bx - 62:.0f},646 Z", INK)
path(f"M{bx - 32:.0f},648 L{bx - 32:.0f},{top:.0f} A32,7 0 0 1 {bx + 32:.0f},{top:.0f} L{bx + 32:.0f},648", INK)
path(f"M{bx - 32:.0f},{top:.0f} A32,7 0 0 0 {bx + 32:.0f},{top:.0f}", INK, "none")
line(bx - 14, top + 22, bx - 14, 638, "#9aa3b0", 1.4); line(bx + 14, top + 22, bx + 14, 638, "#9aa3b0", 1.4)
# --- the red turret on top of the pier, with its clamp knob ---
path(f"M{bx - 30:.0f},{top:.0f} L{bx - 30:.0f},{by + 22:.0f} A30,6 0 0 1 {bx + 30:.0f},{by + 22:.0f} L{bx + 30:.0f},{top:.0f} A30,6 0 0 1 {bx - 30:.0f},{top:.0f} Z", RED)
path(f"M{bx - 30:.0f},{by + 22:.0f} A30,6 0 0 0 {bx + 30:.0f},{by + 22:.0f}", RED, "none")
path(f"M{bx + 30:.0f},{by + 34:.0f} L{bx + 48:.0f},{by + 34:.0f}", RED, "none", 5)
out.append(f'<circle cx="{bx + 52:.0f}" cy="{by + 34:.0f}" r="9" fill="#ffffff" stroke="{RED}" stroke-width="{SW}"/>')
line(bx + 46, by + 34, bx + 58, by + 34, RED, 1.8); line(bx + 52, by + 28, bx + 52, by + 40, RED, 1.8)
# --- the black polar-axis housing, running up from the red body to the Dec block ---
out.append(f'<g transform="translate({bx:.1f} {by:.1f}) rotate(-48)">')
path("M100,-24 L128,-24 L128,24 L100,24 Z", INK)
for gx in (108, 116):
    line(gx, -24, gx, 24, "#9aa3b0", 1.3)
out.append("</g>")
# --- the AM5 body: a red block along the polar axis, with its label ---
out.append(f'<g transform="translate({bx:.1f} {by:.1f}) rotate(-48)">')
path("M-4,-34 L96,-34 Q108,-34 108,-22 L108,22 Q108,34 96,34 L-4,34 Q-16,34 -16,22 L-16,-22 Q-16,-34 -4,-34 Z", RED)
path("M12,-20 L82,-20 L82,20 L12,20 Z", RED, "none", 1.5)
out.append("</g>")

# --- the telescope, in the tube's own coordinates ---
out.append(f'<g transform="translate({CX} {CY}) rotate(-48) translate({-MID} 0)">')
# the Dec block: a T across the top of the polar axis, with a red band, and the red saddle plate under the dovetail
path("M120,44 L210,44 L210,60 L120,60 Z", RED)
for kx_ in (126, 204):
    out.append(f'<circle cx="{kx_}" cy="52" r="3" fill="#ffffff" stroke="{RED}" stroke-width="1.6"/>')
box(138, 60, 56, 82, INK, "#ffffff", 12)
path("M156,60 L170,60 L170,142 L156,142 Z", RED)
path("M30,30 L300,30 L300,44 L30,44 Z", RED)                                            # the red dovetail bar
for kx_ in (66, 250):
    path(f"M{kx_},44 L{kx_ + 18},44 L{kx_ + 18},58 L{kx_},58 Z", RED)
for rx_ in (84, 238):
    path(f"M{rx_},-30 L{rx_ + 12},-30 L{rx_ + 12},30 L{rx_},30 Z", RED)                  # red rings round the tube
box(0, -30, 330, 60, INK, "#ffffff", 10)                                                  # the white tube
path("M330,-36 L394,-36 L394,36 L330,36 Z", INK)                                         # the dew shield
line(346, -36, 346, 36, INK, 1.6)
path("M352,-38 L364,-38 L364,38 L352,38 Z", "#b87508")                                    # the heater band
path("M398,-44 L406,-44 L406,44 L398,44 Z", "#b87508", "#fff7dd", 1.8, "4 3")           # the flat panel (optional)
# guide scope on the tube, black with red rings, and its camera
for lx_ in (112, 232):
    line(lx_, -52, lx_, -30, RED, 3)
    path(f"M{lx_ - 8},-84 L{lx_ + 8},-84 L{lx_ + 8},-48 L{lx_ - 8},-48 Z", RED)
box(88, -80, 190, 28, INK, "#ffffff", 8)
path("M278,-82 L300,-82 L300,-50 L278,-50 Z", INK)
path("M52,-78 L88,-78 L88,-54 L52,-54 Z", RED)
# the rear train, going back: focuser, rotator, filter wheel, camera
path("M-42,-24 L0,-24 L0,24 L-42,24 Z", INK)
for gx in (-34, -26, -18, -10):
    line(gx, -24, gx, 24, "#9aa3b0", 1.3)
path("M-30,-40 L-12,-40 L-12,-24 L-30,-24 Z", INK)                                        # the focuser motor
path("M-64,-28 L-42,-28 L-42,28 L-64,28 Z", INK, "#ffffff", SW, "5 3")                   # the rotator (optional)
path("M-114,-34 L-64,-34 L-64,34 L-114,34 Z", INK)                                        # the filter wheel
for i, col in enumerate(("#d64545", "#2e9e5b", "#3b6fd6", "#9aa3b0")):
    out.append(f'<circle cx="-89" cy="{-21 + i * 14}" r="5" fill="#ffffff" stroke="{col}" stroke-width="2"/>')
path("M-178,-28 L-114,-28 L-114,28 L-178,28 Z", RED)                                      # the camera
for i in range(5):
    line(-170 + i * 10, -28, -170 + i * 10, -40, RED, 2.2)
path("M-188,-20 L-178,-20 L-178,20 L-188,20 Z", INK)
out.append("</g>")

# --- the mini PC and the cables ---
pc = (705, 590, 150, 54)
ports = [P(-188, 0), P(-89, 34), P(-20, 24), (bx + 40, by + 34), P(52, -66)]
for i, (x0, y0) in enumerate(ports):
    lane, yend = 628 + i * 4, pc[1] + 14 + i * 7
    path(f"M{x0:.0f},{y0:.0f} C{x0:.0f},{y0 + 70:.0f} {x0 + 40:.0f},{lane} {x0 + 110:.0f},{lane} L690,{lane} C700,{lane} 698,{yend} 705,{yend}", "#2b3138", "none", 2.6)
x_, y_, w_, h_ = pc
path(f"M{x_},{y_ + 8} Q{x_},{y_} {x_ + 8},{y_} L{x_ + w_ - 8},{y_} Q{x_ + w_},{y_} {x_ + w_},{y_ + 8} L{x_ + w_},{y_ + h_ - 8} Q{x_ + w_},{y_ + h_} {x_ + w_ - 8},{y_ + h_} L{x_ + 8},{y_ + h_} Q{x_},{y_ + h_} {x_},{y_ + h_ - 8} Z", INK)
line(x_ + 14, y_ + 16, x_ + 70, y_ + 16, INK, 2.4)
out.append(f'<circle cx="{x_ + w_ - 20}" cy="{y_ + 17}" r="4" fill="#ffffff" stroke="{ROBOT}" stroke-width="2"/>')
ut(x_ + w_ / 2, y_ + 42, "MINI PC", 11, INK, "700")
ut(560, 678, "USB cables", 12, MUTED)
out.append("</g>")


# ================= callouts (on the page, so they read normally) =================
def callout(x, y, w, title, text, tag, anchor, side):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="84" rx="6" fill="#ffffff" stroke="{GRID}" stroke-width="1.3"/>')
    out.append(f'<rect x="{x}" y="{y}" width="5" height="84" rx="2" fill="{TAGS[tag]}"/>')
    t(x + 16, y + 21, title, 14, weight="700")
    for i, ln in enumerate(text):
        t(x + 16, y + 38 + i * 15, ln, 12, MUTED)
    pw = 8 * len(tag) + 14
    out.append(f'<rect x="{x + w - pw - 10}" y="{y + 9}" width="{pw}" height="16" rx="8" fill="none" stroke="{TAGS[tag]}" stroke-width="1.4"/>')
    t(x + w - pw / 2 - 10, y + 21, tag, 9.5, TAGS[tag], "middle", "700")
    ex = x + w if side == "left" else x
    out.append(f'<line x1="{ex}" y1="{y + 42}" x2="{anchor[0]:.1f}" y2="{anchor[1]:.1f}" stroke="{MUTED}" stroke-width="1.2"/>')
    out.append(f'<circle cx="{anchor[0]:.1f}" cy="{anchor[1]:.1f}" r="4" fill="{INK}"/>')


LX, LW = 30, 262
callout(LX, 108, LW, "Flat panel (optional)", ["A lamp held over the lens for", "calibration photos."], "ROBOTIC", M(P(402, -20)), "left")
callout(LX, 204, LW, "Dew heater", ["A heated band that stops the lens", "fogging up on cold, damp nights."], "POWERED", M(P(358, 30)), "left")
callout(LX, 300, LW, "Telescope", ["Gathers faint starlight and focuses", "it into an image. Glass and metal,", "no electronics."], "PASSIVE", M(P(300, 10)), "left")
callout(LX, 396, LW, "Mount", ["The robot arm: a compact mount with", "built-in gears. It swings the telescope", "across the sky and follows it."], "ROBOTIC", M((bx + 70 * U48[0], by + 70 * U48[1])), "left")
callout(LX, 492, LW, "Pier", ["A solid column that holds the mount", "steady, at a comfortable height."], "PASSIVE", M((bx, 575)), "left")
callout(LX, 588, LW, "Mini PC", ["The brain at the telescope: a small", "computer that talks to every motor and", "camera over USB. A model controls it."], "ROBOTIC", M((855, 617)), "left")

RX, RW = 888, 262
callout(RX, 108, RW, "Guide scope", ["A second small telescope with its own", "camera. It watches one star and corrects", "the mount's tracking drift."], "ROBOTIC", M(P(170, -68)), "right")
callout(RX, 228, RW, "Focuser", ["A tiny motor that slides the camera", "in and out until stars are sharp."], "ROBOTIC", M(P(-20, -24)), "right")
callout(RX, 324, RW, "Rotator (optional)", ["Turns the camera, to frame a", "target at the right angle."], "ROBOTIC", M(P(-53, 0)), "right")
callout(RX, 420, RW, "Filter wheel", ["A motorised carousel of coloured", "filters. Each photo uses one."], "ROBOTIC", M(P(-100, -22)), "right")
callout(RX, 516, RW, "Camera", ["A cooled astronomy camera. Chilling", "the sensor cuts noise so faint", "objects show."], "ROBOTIC", M(P(-150, 14)), "right")
t(30, 718, "Also found in bigger set-ups, and not drawn: an observatory dome, weather and safety sensors, and a switched power box.", 11.5, MUTED)

out.append("</svg>")
(Path(__file__).resolve().parents[1] / "docs" / "telescope-rig.svg").write_text("\n".join(out) + "\n")
print("written")
