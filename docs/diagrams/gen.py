"""Generate the README diagrams as draw.io files, then export each to PNG in docs/images/.

    python docs/diagrams/gen.py            # writes docs/diagrams/*.drawio and docs/images/*.png (needs the drawio CLI)

One palette, one set of helpers, one function per diagram. Edit the function, re-run, commit both files.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
IMAGES = HERE.parent / "images"

INK = "#14442F"        # headings, strong text
BODY = "#3E5248"       # body text
DEEP = "#1E7E5A"       # primary green
BRIGHT = "#2FA374"     # accent green
SOFT = "#EAF7F0"       # card fill
PAGE = "#F7FBF9"       # canvas
LINE = "#CDE9DC"       # card border
MUTED = "#8AA597"      # secondary lines
WHITE = "#FFFFFF"
SLATE = "#2B3A4A"      # request-path boxes
SLATE_SOFT = "#EEF2F6"
AMBER = "#B7791F"      # warnings, sparingly
AMBER_SOFT = "#FFF6E5"
FONT = "Helvetica"


def _html(s: str) -> str:
    """The cell value of an html=1 label: escaped, with newlines as line breaks."""
    return escape(s).replace("\n", "&lt;br&gt;")


class D:
    def __init__(self, name: str, w: int, h: int):
        self.name, self.w, self.h, self.cells, self.n = name, w, h, [], 0
        self.rect(0, 0, w, h, PAGE, shadow=0, arc=0)

    def _id(self) -> str:
        self.n += 1
        return f"c{self.n}"

    def rect(self, x, y, w, h, fill, stroke="none", sw=1, arc=12, shadow=0, dashed=0, grad=None):
        i = self._id()
        g = f"gradientColor={grad};gradientDirection=east;" if grad else ""
        self.cells.append(
            f'<mxCell id="{i}" value="" style="rounded=1;arcSize={arc};absoluteArcSize=1;fillColor={fill};{g}'
            f'strokeColor={stroke};strokeWidth={sw};shadow={shadow};dashed={dashed};" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return i

    def text(self, x, y, w, h, s, size=20, color=BODY, bold=False, align="center", valign="middle", mono=False):
        i = self._id()
        fam = "Menlo" if mono else FONT
        self.cells.append(
            f'<mxCell id="{i}" value="{_html(s)}" style="text;html=1;whiteSpace=wrap;align={align};'
            f'verticalAlign={valign};fontFamily={fam};fontSize={size};fontColor={color};fontStyle={1 if bold else 0};'
            f'spacing=2;" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>'
            f'</mxCell>')
        return i

    def card(self, x, y, w, h, title, body="", fill=WHITE, stroke=LINE, title_color=INK, size=22, body_size=17,
             accent=None):
        self.rect(x, y, w, h, fill, stroke=stroke, sw=2, shadow=1)
        if accent:
            self.rect(x, y, 10, h, accent, arc=6)
        if body:
            self.text(x + 20, y + 12, w - 36, 34, title, size=size, color=title_color, bold=True, align="left")
            self.text(x + 20, y + 48, w - 36, h - 58, body, size=body_size, align="left", valign="top")
        else:
            self.text(x + 16, y, w - 32, h, title, size=size, color=title_color, bold=True)

    def chip(self, x, y, w, h, s, fill=SOFT, color=DEEP, size=16, mono=False):
        self.rect(x, y, w, h, fill, stroke=LINE, sw=1, arc=h // 2)
        self.text(x + 6, y, w - 12, h, s, size=size, color=color, bold=True, mono=mono)

    def badge(self, x, y, d, s, fill=DEEP, size=20):
        i = self._id()
        self.cells.append(
            f'<mxCell id="{i}" value="{escape(s)}" style="ellipse;fillColor={fill};strokeColor=none;fontColor={WHITE};'
            f'fontFamily={FONT};fontSize={size};fontStyle=1;" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{d}" height="{d}" as="geometry"/></mxCell>')

    def arrow(self, pts, color=DEEP, w=3, dashed=0, label="", size=15, end="block", start="none"):
        i = self._id()
        (x1, y1), (x2, y2) = pts[0], pts[-1]
        mids = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in pts[1:-1])
        arr = f'<Array as="points">{mids}</Array>' if mids else ""
        self.cells.append(
            f'<mxCell id="{i}" value="{escape(label)}" style="endArrow={end};endFill=1;startArrow={start};startFill=1;'
            f'html=1;strokeColor={color};strokeWidth={w};dashed={dashed};fontFamily={FONT};fontSize={size};'
            f'fontColor={BODY};labelBackgroundColor={PAGE};rounded=1;" edge="1" parent="1">'
            f'<mxGeometry relative="1" as="geometry"><mxPoint x="{x1}" y="{y1}" as="sourcePoint"/>'
            f'<mxPoint x="{x2}" y="{y2}" as="targetPoint"/>{arr}</mxGeometry></mxCell>')

    def save(self):
        xml = (f'<mxfile><diagram name="{self.name}"><mxGraphModel dx="{self.w}" dy="{self.h}" grid="0" '
               f'pageWidth="{self.w}" pageHeight="{self.h}" background="{PAGE}"><root><mxCell id="0"/>'
               f'<mxCell id="1" parent="0"/>{"".join(self.cells)}</root></mxGraphModel></diagram></mxfile>')
        src = HERE / f"{self.name}.drawio"
        src.write_text(xml)
        return src


# --- 1. where tierbook sits ----------------------------------------------------------------------------------------

def architecture():
    d = D("architecture", 1600, 830)
    d.text(40, 24, 1520, 50, "tierbook sits beside the request path, not on it", size=32, color=INK, bold=True)
    d.text(40, 72, 1520, 34, "The router answers each request. tierbook decides, from graded outcomes, what the router "
           "should do, and says how sure it is.", size=19)
    # request path band
    d.rect(40, 130, 1520, 300, SLATE_SOFT, stroke="#D5DEE7", sw=2, arc=18)
    d.text(64, 140, 300, 34, "REQUEST PATH", size=17, color=SLATE, bold=True, align="left")
    d.text(1180, 140, 360, 34, "per request, milliseconds", size=15, color=SLATE, align="right")
    d.card(70, 200, 230, 190, "Clients & agents", "chat, coding agents, batch jobs", fill=WHITE, stroke="#C9D3DD",
           title_color=SLATE)
    d.card(370, 200, 280, 190, "Gateway", "auth, quota, billing\nstratoclave: OpenAI-\ncompatible + rates API",
           fill=WHITE, stroke="#C9D3DD", title_color=SLATE)
    d.card(720, 200, 300, 190, "Router", "classify, then pick a model\nvLLM Semantic Router\n(or any router that\nreads config)",
           fill=WHITE, stroke="#C9D3DD", title_color=SLATE)
    for i, t in enumerate(("Metered APIs · Claude, GPT, Qwen", "Self-hosted LLM · vLLM on GPUs",
                           "Prismyra · decision model + CPU student")):
        d.card(1090, 176 + i * 82, 440, 66, t, fill=WHITE, stroke="#C9D3DD", title_color=SLATE, size=18)
    d.arrow([(300, 295), (370, 295)], color=SLATE)
    d.arrow([(650, 295), (720, 295)], color=SLATE)
    d.arrow([(1020, 295), (1090, 295)], color=SLATE)
    # certification plane band
    d.rect(40, 500, 1520, 300, SOFT, stroke=LINE, sw=2, arc=18)
    d.text(64, 510, 330, 34, "CERTIFICATION PLANE — tierbook", size=17, color=DEEP, bold=True, align="left")
    d.text(1180, 510, 360, 34, "per window, minutes", size=15, color=DEEP, align="right")
    steps = (("ingest", "call logs + your\ngrades → observations"), ("derive", "cheapest arm per accepted\ntask, checked on held-out"),
             ("export", "router config, Prismyra\nlearn spec, or a table"), ("drift", "price moved? quality\nmoved? what to measure"))
    for i, (t, s) in enumerate(steps):
        x = 90 + i * 365
        d.badge(x, 590, 48, str(i + 1))
        d.card(x + 60, 566, 270, 120, t, s, accent=BRIGHT, size=24, body_size=16)
        if i < 3:
            d.arrow([(x + 330, 626), (x + 365, 626)], color=DEEP)
    d.chip(90, 720, 420, 40, "every threshold is declared by you — no defaults", size=15)
    d.chip(530, 720, 420, 40, "a choice is checked on items it was not made on", size=15)
    d.chip(970, 720, 560, 40, "price changes re-derive with nothing re-measured", size=15)
    # cross arrows
    d.arrow([(510, 390), (510, 465), (400, 465), (400, 566)], color=MUTED, dashed=1, label="usage + rates", size=15)
    d.arrow([(1310, 424), (1310, 465), (1220, 465), (1220, 566)], color=MUTED, dashed=1, label="routed outcomes",
            size=15)
    d.arrow([(990, 566), (990, 465), (870, 465), (870, 390)], color=DEEP, w=4, label="config", size=15)
    return d


# --- 2. the ops loop -----------------------------------------------------------------------------------------------

def ops_loop():
    d = D("ops-loop", 1600, 900)
    d.text(40, 24, 1520, 50, "One loop, run as often as prices, models or traffic move", size=32, color=INK,
           bold=True)
    cx, cy = 800, 500
    nodes = (
        (cx - 120, 130, "measure", "send items to arms\n(drive.py)"),
        (cx + 330, 250, "grade", "your grader: tests,\nkeys, labels"),
        (cx + 330, 560, "ingest", "observations:\none per attempt"),
        (cx - 120, 690, "derive", "certify per task type\n(held-out check)"),
        (cx - 570, 560, "export", "vLLM-SR config ·\nPrismyra router"),
        (cx - 570, 250, "drift", "re-derive · contradict ·\nneeds measurement"),
    )
    for i, (x, y, t, s) in enumerate(nodes):
        d.card(x, y, 240, 120, t, s, accent=DEEP, size=24, body_size=16)
        d.badge(x - 24, y - 24, 50, str(i + 1), fill=BRIGHT if i % 2 else DEEP)
    pts = ((cx + 120, 190, cx + 330, 290), (cx + 450, 370, cx + 450, 560), (cx + 330, 640, cx + 120, 740),
           (cx - 120, 750, cx - 330, 640), (cx - 450, 560, cx - 450, 370), (cx - 330, 290, cx - 120, 190))
    for x1, y1, x2, y2 in pts:
        d.arrow([(x1, y1), (x2, y2)], color=MUTED, w=4)
    d.rect(cx - 210, cy - 110, 420, 200, WHITE, stroke=LINE, sw=2, arc=24, shadow=1)
    d.text(cx - 200, cy - 100, 400, 40, "what each step reads", size=20, color=DEEP, bold=True)
    d.text(cx - 190, cy - 60, 380, 140, "candidates.json — arms, prices\ndeclarations.json — floors, alpha,\n"
           "split, freshness\nobservations.jsonl — the record", size=17, mono=False)
    d.text(40, 840, 1520, 40, "Exit codes: 0 done · 2 refused input · 3 a deployed assignment was contradicted — "
           "a scheduler can tell “the world moved” from “the run failed”.", size=17, color=BODY)
    return d


# --- 3. anatomy of a certificate -----------------------------------------------------------------------------------

def certificate():
    d = D("certificate", 1600, 760)
    d.text(40, 24, 1520, 50, "How one task type gets an assignment", size=32, color=INK, bold=True)
    # items
    d.rect(60, 120, 330, 520, WHITE, stroke=LINE, sw=2, shadow=1)
    d.text(80, 134, 290, 40, "graded items", size=22, color=INK, bold=True, align="left")
    for r in range(8):
        for c in range(6):
            held = (r * 6 + c) % 2 == 0
            d.rect(90 + c * 46, 200 + r * 50, 36, 36, BRIGHT if held else "#B8D8C9", arc=8)
    d.chip(90, 610 - 10, 130, 30, "held-out", fill=BRIGHT, color=WHITE, size=14)
    d.chip(232, 610 - 10, 130, 30, "selection", fill="#B8D8C9", color=INK, size=14)
    d.text(60, 650, 330, 60, "split by hash(salt, item) — the salt is declared", size=15)
    # selection
    d.arrow([(390, 320), (470, 320)])
    d.card(470, 200, 480, 240, "1  select on the selection half",
           "among arms whose lower bound clears\nyour floor, the cheapest per accepted task\n\n"
           "spend per accepted = all attempts' spend\n(failures included) / accepted items",
           accent=DEEP, size=22, body_size=17)
    d.arrow([(950, 320), (1030, 320)])
    d.card(1030, 200, 500, 240, "2  check on the held-out half",
           "the chosen arm only, one interval:\n\n· lower ≥ floor → certified\n· floor inside → unconfirmed\n"
           "· upper < floor → contradicted", accent=BRIGHT, size=22, body_size=17)
    d.card(470, 480, 480, 160, "the shipped numbers", "rate, bound and cost come from the held-out\nhalf; "
           "selection figures are kept for audit", size=20, body_size=16)
    d.card(1030, 480, 500, 160, "always reported beside it", "the single best arm on the same items,\n"
           "the fallback, and the guarantee in words", size=20, body_size=16)
    return d


# --- 4. distillation lane ------------------------------------------------------------------------------------------

def distillation():
    d = D("distillation", 1600, 850)
    d.text(40, 24, 1520, 50, "Teach on a GPU, serve on a CPU — and let the certificate decide when", size=32,
           color=INK, bold=True)
    d.text(40, 72, 1520, 34, "Prismyra labels traffic in the background; its LightGBM student is refitted each window; "
           "tierbook switches only when the student clears your floor.", size=18)
    d.card(60, 150, 300, 180, "Prismyra", "decision model on a GPU\nreads once, answers with\nlabel probabilities",
           accent=DEEP)
    d.arrow([(360, 240), (440, 240)])
    d.card(440, 150, 300, 180, "experience log", "every answer under a tag\n(prismyra.learn); the\nstudent is refit each window", accent=DEEP)
    d.arrow([(740, 240), (820, 240)])
    d.card(820, 150, 330, 180, "LightGBM student", "CPU · registered features\n(text embeddings) · hard\nor soft "
           "teacher labels", accent=BRIGHT)
    d.arrow([(1150, 240), (1230, 240)])
    d.card(1230, 150, 310, 180, "tierbook derive", "student · student+Prismyra\n(confidence) · Prismyra ·\nAPIs — "
           "cheapest that clears", accent=BRIGHT)
    d.arrow([(1385, 330), (1385, 420), (210, 420), (210, 330)], color=DEEP, w=4,
            label="export-policy --target prismyra-learn → router block (serving: being verified)", size=16)
    # results strip
    d.text(60, 460, 1480, 40, "Measured on financial-news sentiment, 9 windows of 1,000 items "
           "(docs/verify/v0.5.0-distillation-loop.md)", size=18, color=DEEP, bold=True, align="left")
    cols = (("floor 0.85", "Prismyra certified\n$0.0000469 / accepted\n\nstudent+Prismyra cheaper\n($0.0000113) but "
             "unconfirmed", AMBER_SOFT, AMBER),
            ("floor 0.80", "student+Prismyra chosen,\nunconfirmed on held-out\n\n$0.0000081 / accepted", AMBER_SOFT,
             AMBER),
            ("floor 0.75", "CPU student alone certified\nfrom window 3\n\n$0.00000069 / accepted\n≈ 1/68 of Prismyra",
             SOFT, DEEP))
    for i, (t, s, fill, accent) in enumerate(cols):
        d.card(60 + i * 500, 510, 470, 230, t, s, fill=fill, accent=accent, size=26, body_size=18)
    d.text(60, 770, 1480, 90, "The floor is yours to declare: the same evidence gives Prismyra at 0.85 and the CPU "
           "student at 0.75. Prismyra's own admission bar asks whether a student is close to its teacher; tierbook's "
           "certificate asks whether an arm clears your floor on gold labels at the lowest cost.", size=17,
           align="left", valign="top")
    return d


# --- 5. interfaces -------------------------------------------------------------------------------------------------

def interfaces():
    d = D("interfaces", 1600, 820)
    d.text(40, 24, 1520, 50, "What tierbook reads and writes, per neighbour", size=32, color=INK, bold=True)
    d.rect(620, 300, 360, 220, DEEP, grad=BRIGHT, arc=24, shadow=1)
    d.text(630, 330, 340, 60, "tierbook", size=40, color=WHITE, bold=True)
    d.text(630, 390, 340, 100, "observations in\npolicy out", size=22, color=WHITE)
    blocks = (
        (60, 130, "stratoclave gateway", ("reads  GET /api/mvp/me/rates", "reads  usage-history cost_microusd",
                                          "sends  /v1/chat/completions")),
        (1040, 130, "vLLM Semantic Router", ("writes config v0.3 (validated)", "reads  x-vsr-selected-model",
                                             "deploy  vllm-sr serve / apply")),
        (60, 540, "Prismyra", ("writes learn spec router block", "reads  /v1/decide answers",
                               "student: LightGBM on CPU")),
        (1040, 540, "your side", ("grader: tests, keys, labels", "floors per task type",
                                  "arms + prices: candidates.json")),
    )
    for x, y, t, lines in blocks:
        d.rect(x, y, 500, 250, WHITE, stroke=LINE, sw=2, shadow=1)
        d.text(x + 24, y + 14, 452, 44, t, size=26, color=INK, bold=True, align="left")
        for j, s in enumerate(lines):
            d.chip(x + 24, y + 74 + j * 54, 452, 42, s, size=16, mono=True)
    for (x1, y1), (x2, y2) in (((560, 255), (620, 350)), ((1040, 255), (980, 350)), ((560, 665), (620, 470)),
                               ((1040, 665), (980, 470))):
        d.arrow([(x1, y1), (x2, y2)], color=DEEP, w=4, start="block")
    return d


# --- 6. a live run, three deployments ------------------------------------------------------------------------------

def live_run():
    d = D("live-run", 1600, 600)
    d.text(40, 24, 1520, 50, "A live run: the policy moved three times, and each move had a reason", size=32,
           color=INK, bold=True)
    d.text(40, 72, 1520, 34, "MMLU-Pro biology · history · math · law, five then seven arms through a billing gateway, routed by "
           "vLLM Semantic Router (docs/verify/v0.5.0-certification-loop.md)", size=17)
    d.rect(80, 250, 1440, 8, LINE, arc=4)
    stages = (
        ("v1", "derive", "sonnet ×3, qwen for history\n0.84 × single-best cost", DEEP),
        ("drift", "Claude unreachable", "gateway usage keys rejected;\n135 attempts reached no arm", AMBER),
        ("v2", "re-derive", "Claude left out: gpt-6.1-terra\neverywhere, 4 confirmed", DEEP),
        ("price ×3", "nothing re-measured", "3 task types move to\ngpt-5.6-terra · 0.79 × cost", BRIGHT),
        ("v3", "redeploy", "router follows the policy\n2 confirmed, 2 consistent", DEEP),
    )
    for i, (tag, head, body, color) in enumerate(stages):
        x = 80 + i * 300
        d.badge(x + 100, 224, 60, str(i + 1), fill=color)
        d.chip(x + 40, 150, 180, 40, tag, fill=WHITE, color=color, size=18)
        d.card(x, 310, 270, 140, head, body, accent=color, size=21, body_size=16)
    d.chip(80, 500, 1440, 44, "then, on a gateway rebuilt with the fix: Claude routed 130/130, and billed spend matched "
           "tokens × the gateway's own rates to a ratio of 1.0004", size=16)
    return d


# --- 7. growing a student ------------------------------------------------------------------------------------------

def student_ops():
    d = D("student-ops", 1600, 800)
    d.text(40, 24, 1520, 50, "A task type moves from the teacher to a student only when the student has earned it",
           size=30, color=INK, bold=True)
    d.text(40, 72, 1520, 34, "The large model is scaffolding. The loop around it is what tierbook adds.", size=19)
    H = 160
    steps = (
        (80, 140, "1  teacher answers", "a large model or a decision\nmodel serves and labels\ntraffic for a while", SLATE),
        (450, 140, "2  student learns", "a classifier on embeddings,\nor a small LLM fine-tuned\non the teacher's labels", DEEP),
        (820, 140, "3  cascades declared", "student if its score >= t,\nteacher otherwise; several\nt are several candidates", DEEP),
        (1190, 140, "4  certify per floor", "chosen on selection,\nchecked on held-out;\nthe floor is yours", BRIGHT),
        (1190, 430, "5  serve on a CPU", "measured throughput is\nthe price: serving work\nmoves the policy", BRIGHT),
        (820, 430, "6  watch fresh traffic", "drift: contradicted?\nprice moved? a better\nstudent this window?", DEEP),
    )
    for x, y, t, b, col in steps:
        d.card(x, y, 330, H, t, b, accent=col, size=23, body_size=17)
    for (x1, y1), (x2, y2) in (((410, 220), (450, 220)), ((780, 220), (820, 220)), ((1150, 220), (1190, 220)),
                               ((1355, 300), (1355, 430)), ((1190, 510), (1150, 510))):
        d.arrow([(x1, y1), (x2, y2)], color=DEEP, w=4)
    d.arrow([(985, 430), (985, 365), (615, 365), (615, 300)], color=MUTED, w=4, dashed=1)
    d.text(630, 370, 340, 30, "next window: refit, re-derive", size=16, color=BODY, align="left")
    d.rect(80, 430, 560, H, AMBER_SOFT, stroke="#F0D9A8", sw=2, arc=16)
    d.text(100, 440, 520, 36, "what the operator declares", size=20, color=AMBER, bold=True, align="left")
    d.text(100, 478, 520, 110, "the floor per task type\nthe teacher's amortisation horizon\nthe thresholds to try\n"
           "the split, alpha and bound", size=17, align="left", valign="top")
    d.chip(80, 640, 1440, 46, "measured here: a fine-tuned 0.8B student reached 0.885 against its teacher's 0.896 at under a "
           "third of the teacher's price; serving work alone made it 2.3x cheaper", size=16)
    d.chip(80, 700, 1440, 46, "alone it missed 0.85 on held-out; its cascade with the teacher was certified at 0.85 at 37% "
           "of the teacher's cost -- the certificate, not the hope, decides the switch", fill=AMBER_SOFT, color=AMBER,
           size=16)
    return d


DIAGRAMS = (architecture, ops_loop, certificate, distillation, interfaces, live_run, student_ops)


def main() -> int:
    IMAGES.mkdir(parents=True, exist_ok=True)
    for make in DIAGRAMS:
        src = make().save()
        out = IMAGES / f"{src.stem}.png"
        subprocess.run(["drawio", "--export", "--format", "png", "--scale", "1.5", "--output", str(out), str(src)],
                       check=True, capture_output=True)
        print(f"wrote {src.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
