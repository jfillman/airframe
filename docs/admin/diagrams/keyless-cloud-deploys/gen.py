#!/usr/bin/env python3
"""Hangar-skinned diagram-design SVGs for the keyless cloud deploy explainer.

Emits one standalone HTML per diagram (for repo docs and the skill's checkers) plus fragments/<slug>.svg for the
artifact. Tokens: ~/.diagram-design/profiles/hangar.md (light values; the page remaps them for dark mode).
"""
import html, math, os, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
os.makedirs(os.path.join(OUT, "fragments"), exist_ok=True)

PAPER, INK, MUT, SOFT, ACC, LINK = "#f2efe9", "#1b1f24", "#5b6570", "#838b93", "#b9791f", "#2e7ba6"
SANS = "'Geist', system-ui, sans-serif"
MONO = "'Geist Mono', ui-monospace, monospace"
SERIF = "'Instrument Serif', serif"
KIND = {  # fill, stroke, dash, tag color
    "focal": ("rgba(185,121,31,0.08)", ACC, None, ACC),
    "backend": ("#ffffff", INK, None, INK),
    "store": ("rgba(27,31,36,0.05)", MUT, None, MUT),
    "external": ("rgba(27,31,36,0.03)", "rgba(27,31,36,0.30)", None, MUT),
    "input": ("rgba(91,101,112,0.10)", SOFT, None, SOFT),
    "security": ("rgba(185,121,31,0.05)", "rgba(185,121,31,0.50)", "4,4", ACC),
}


def esc(s):
    return html.escape(s, quote=True)


def mono_w(text, size=8):
    return int(math.ceil((len(text) * size * 0.62 + 8) / 4.0) * 4)


class SVG:
    def __init__(self, slug, w, h, title, desc):
        self.slug, self.w, self.h, self.title, self.desc = slug, w, h, title, desc
        self.zones, self.arrows, self.labels, self.nodes, self.top = [], [], [], [], []

    # ---- primitives -------------------------------------------------------------------------------------
    def zone(self, x, y, w, h, label, kind="plain", label_x=None):
        if kind == "security":
            fill, stroke, dash, lc = "rgba(185,121,31,0.05)", "rgba(185,121,31,0.50)", ' stroke-dasharray="4,4"', ACC
        else:
            fill, stroke, dash, lc = "rgba(27,31,36,0.02)", "rgba(27,31,36,0.20)", "", MUT
        self.zones.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1"{dash}/>'
            f'<text x="{label_x if label_x is not None else x + 12}" y="{y + 18}" fill="{lc}" font-size="8" font-weight="500" font-family="{MONO}" '
            f'letter-spacing="0.14em">{esc(label)}</text>')

    def node(self, x, y, w, h, kind, tag, name, sub=None, sub2=None):
        fill, stroke, dash, tc = KIND[kind]
        d = f' stroke-dasharray="{dash}"' if dash else ""
        cx = x + w / 2
        tw = mono_w(tag, 7) if tag else 0
        s = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{PAPER}"/>',
             f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1"{d}/>']
        if tag:
            s.append(f'<rect x="{x + 8}" y="{y + 6}" width="{tw}" height="12" rx="2" fill="transparent" stroke="{tc}" '
                     f'stroke-opacity="0.5" stroke-width="0.8"/>'
                     f'<text x="{x + 8 + tw / 2}" y="{y + 15}" fill="{tc}" font-size="7" font-family="{MONO}" '
                     f'text-anchor="middle" letter-spacing="0.08em">{esc(tag)}</text>')
        lines = [l for l in (sub, sub2) if l]
        top = y + (h - 12 - 14 * len(lines)) / 2 + 10 + (6 if tag else 0)
        s.append(f'<text x="{cx}" y="{top}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" '
                 f'text-anchor="middle">{esc(name)}</text>')
        for i, l in enumerate(lines):
            s.append(f'<text x="{cx}" y="{top + 16 + 13 * i}" fill="{MUT}" font-size="9" font-family="{MONO}" '
                     f'text-anchor="middle">{esc(l)}</text>')
        self.nodes.append("".join(s))

    def diamond(self, cx, cy, hw, hh, line1, line2=None, kind="backend"):
        fill, stroke, _, _ = KIND[kind]
        pts = f"{cx},{cy - hh} {cx + hw},{cy} {cx},{cy + hh} {cx - hw},{cy}"
        s = [f'<polygon points="{pts}" fill="{PAPER}"/>',
             f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>']
        if line2:
            s.append(f'<text x="{cx}" y="{cy - 3}" fill="{INK}" font-size="11" font-weight="600" font-family="{SANS}" text-anchor="middle">{esc(line1)}</text>'
                     f'<text x="{cx}" y="{cy + 12}" fill="{INK}" font-size="11" font-weight="600" font-family="{SANS}" text-anchor="middle">{esc(line2)}</text>')
        else:
            s.append(f'<text x="{cx}" y="{cy + 4}" fill="{INK}" font-size="11" font-weight="600" font-family="{SANS}" text-anchor="middle">{esc(line1)}</text>')
        self.nodes.append("".join(s))

    def oval(self, x, y, w, h, name, kind="backend", sub=None):
        fill, stroke, _, _ = KIND[kind]
        s = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="20" fill="{PAPER}"/>',
             f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="20" fill="{fill}" stroke="{stroke}" stroke-width="1"/>']
        ty = y + h / 2 + (4 if not sub else -2)
        s.append(f'<text x="{x + w / 2}" y="{ty}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{esc(name)}</text>')
        if sub:
            s.append(f'<text x="{x + w / 2}" y="{ty + 14}" fill="{MUT}" font-size="9" font-family="{MONO}" text-anchor="middle">{esc(sub)}</text>')
        self.nodes.append("".join(s))

    def arrow(self, pts, color="muted", dashed=False, r=8):
        stroke, marker = {"muted": (MUT, "arrow"), "accent": (ACC, "arrow-accent"), "link": (LINK, "arrow-link")}[color]
        d = f"M{pts[0][0]},{pts[0][1]}"
        for i in range(1, len(pts) - 1):
            (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
            sx0, sy0 = (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0)
            sx1, sy1 = (x2 > x1) - (x2 < x1), (y2 > y1) - (y2 < y1)
            ax, ay = x1 - sx0 * r, y1 - sy0 * r
            bx, by = x1 + sx1 * r, y1 + sy1 * r
            sweep = 1 if (sx0 * sy1 - sy0 * sx1) > 0 else 0
            d += f" L{ax},{ay} A{r},{r} 0 0 {sweep} {bx},{by}"
        d += f" L{pts[-1][0]},{pts[-1][1]}"
        da = ' stroke-dasharray="5,4"' if dashed else ""
        self.arrows.append(f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="1.2"{da} marker-end="url(#{marker})"/>')

    def line(self, x1, y1, x2, y2, stroke="rgba(27,31,36,0.20)", dash="3,3", width=1):
        self.zones.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}" stroke-dasharray="{dash}"/>')

    def label_h(self, cx, y_line, text, color=SOFT):
        """Label above a horizontal segment: mask bottom 6px above the stroke."""
        w = mono_w(text)
        self.labels.append(f'<rect x="{cx - w / 2}" y="{y_line - 18}" width="{w}" height="12" rx="2" fill="{PAPER}"/>'
                           f'<text x="{cx}" y="{y_line - 9}" fill="{color}" font-size="8" font-family="{MONO}" '
                           f'text-anchor="middle" letter-spacing="0.06em">{esc(text)}</text>')

    def label_v(self, x_line, cy, text, color=SOFT, side="right"):
        """Label beside a vertical segment, 8px clear of the stroke."""
        w = mono_w(text)
        x = x_line + 8 if side == "right" else x_line - 8 - w
        self.labels.append(f'<rect x="{x}" y="{cy - 6}" width="{w}" height="12" rx="2" fill="{PAPER}"/>'
                           f'<text x="{x + w / 2}" y="{cy + 3}" fill="{color}" font-size="8" font-family="{MONO}" '
                           f'text-anchor="middle" letter-spacing="0.06em">{esc(text)}</text>')

    def dot(self, x, y):
        self.top.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{INK}"/>')

    def callout(self, x, y, text, anchor="start"):
        self.top.append(f'<text x="{x}" y="{y}" fill="{MUT}" font-size="16" font-family="{SERIF}" font-style="italic" text-anchor="{anchor}">{esc(text)}</text>')

    def raw(self, s, layer="top"):
        getattr(self, layer).append(s)

    def legend(self, y, items):
        out = [f'<line x1="24" y1="{y - 20}" x2="{self.w - 24}" y2="{y - 20}" stroke="rgba(27,31,36,0.12)" stroke-width="0.8"/>',
               f'<text x="24" y="{y}" fill="{MUT}" font-size="8" font-weight="500" font-family="{MONO}" letter-spacing="0.14em">LEGEND</text>']
        x = 96
        for kind, text in items:
            if kind in KIND:
                fill, stroke, dash, _ = KIND[kind]
                d = f' stroke-dasharray="{dash}"' if dash else ""
                out.append(f'<rect x="{x}" y="{y - 8}" width="16" height="12" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1"{d}/>')
            elif kind.startswith("line-"):
                c = {"line-muted": MUT, "line-accent": ACC, "line-link": LINK, "line-dash": MUT, "line-link-dash": LINK}[kind]
                d = ' stroke-dasharray="5,4"' if kind.endswith("dash") else ""
                out.append(f'<line x1="{x}" y1="{y - 2}" x2="{x + 20}" y2="{y - 2}" stroke="{c}" stroke-width="1.2"{d}/>')
            elif kind == "dot-accent":
                out.append(f'<circle cx="{x + 8}" cy="{y - 2}" r="6" fill="{ACC}"/>')
            elif kind == "dot":
                out.append(f'<circle cx="{x + 8}" cy="{y - 2}" r="4" fill="{INK}"/>')
            out.append(f'<text x="{x + 24}" y="{y + 1}" fill="{MUT}" font-size="8" font-family="{MONO}">{esc(text)}</text>')
            x += 24 + int(len(text) * 8 * 0.62) + 28
        self.top.extend(out)

    def svg(self):
        defs = ('<defs>'
                f'<marker id="arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{MUT}"/></marker>'
                f'<marker id="arrow-accent" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{ACC}"/></marker>'
                f'<marker id="arrow-link" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="{LINK}"/></marker>'
                '</defs>')
        body = "".join(self.zones + self.arrows + self.labels + self.nodes + self.top)
        return (f'<svg viewBox="0 0 {self.w} {self.h}" style="min-width:{self.w}px" xmlns="http://www.w3.org/2000/svg" role="img" '
                f'aria-labelledby="{self.slug}-title {self.slug}-desc"><title id="{self.slug}-title">{esc(self.title)}</title>'
                f'<desc id="{self.slug}-desc">{esc(self.desc)}</desc>{defs}<rect width="100%" height="100%" fill="{PAPER}"/>{body}</svg>')


# =========================================================================================================
# 1. Before: two stored keys
# =========================================================================================================
def fig_before():
    g = SVG("fed-before", 1000, 392, "Before: two long-lived AWS keys",
            "Each AWS identity was an IAM user whose access key was stored in Infisical, copied into a Kubernetes Secret and readable by every pod that mounted it.")
    for row, y, sec, sub_sec, cons, sub_cons, lbl in (
            (1, 64, "app-secrets", "Secret · app-<app>-cicd", "Every pipeline step", "build · test · deploy", "MOUNTED"),
            (2, 232, "provider-aws-creds", "Secret · crossplane-system", "Crossplane AWS providers", "provider-aws-*", "READ")):
        my = y + 32
        g.arrow([(220, my), (286, my)]); g.label_h(253, my, "SYNCED")
        g.arrow([(470, my), (536, my)]); g.label_h(503, my, lbl)
        g.arrow([(740, my), (806, my)], color="accent"); g.label_h(773, my, "ACCESS KEY", ACC)
        g.node(40, y, 180, 64, "store", "VAULT", "Infisical", "app project" if row == 1 else "platform project")
        g.node(290, y, 180, 64, "store", "SECRET", sec, sub_sec)
        g.node(540, y, 200, 64, "backend", "PODS", cons, sub_cons)
    g.node(810, 64, 150, 232, "focal", "IAM USERS", "AWS account", "glidepath-deployer", "hangar-crossplane")
    g.callout(40, 176, "A copy of each key sat in three places, and anyone who could read one")
    g.callout(40, 200, "could use it from anywhere, for every app, until someone deleted it.")
    g.legend(364, [("store", "stored copy"), ("backend", "workload"), ("focal", "long-lived identity"), ("line-accent", "the access key")])
    return g


# =========================================================================================================
# 2. How a token becomes AWS access (sequence)
# =========================================================================================================
def fig_sequence():
    g = SVG("fed-sequence", 1000, 516, "Exchanging a ServiceAccount token for AWS access",
            "A deploy pod receives a signed token from the kiac-dev API server, presents it to AWS STS, which checks it against the published keys and returns a one-hour session the pod uses to update its Lambda function.")
    xs = [112, 304, 500, 696, 888]
    for x in xs:
        g.line(x, 76, x, 460)
    # messages
    g.arrow([(xs[1] - 4, 124), (xs[0] + 4, 124)]); g.label_h((xs[0] + xs[1]) / 2, 124, "SIGNED TOKEN")
    g.arrow([(xs[0] + 4, 172), (xs[3] - 4, 172)], color="link"); g.label_h(400, 172, "TOKEN + ROLE", LINK)
    g.arrow([(xs[3] - 4, 220), (xs[2] + 4, 220)], color="link"); g.label_h((xs[2] + xs[3]) / 2, 220, "GET KEYS", LINK)
    g.arrow([(xs[2] + 4, 260), (xs[3] - 4, 260)], dashed=True); g.label_h((xs[2] + xs[3]) / 2, 260, "PUBLIC KEYS")
    g.arrow([(xs[3] + 4, 300), (xs[3] + 44, 300), (xs[3] + 44, 332), (xs[3] + 8, 332)])
    g.label_v(xs[3] + 44, 316, "CHECK CLAIMS")
    g.arrow([(xs[3] - 4, 380), (xs[0] + 4, 380)], color="accent"); g.label_h(400, 380, "1-HOUR SESSION", ACC)
    g.arrow([(xs[0] + 4, 428), (xs[4] - 4, 428)], color="link"); g.label_h(592, 428, "UPDATE CODE", LINK)
    # actors
    g.node(xs[0] - 88, 24, 176, 52, "backend", None, "Deploy step pod", "glidepath-cloud-deployer")
    g.node(xs[1] - 88, 24, 176, 52, "backend", None, "kiac-dev API server", "the issuer: signs tokens")
    g.node(xs[2] - 88, 24, 176, 52, "external", None, "hangarplatform.dev", "/oidc/kiac-dev")
    g.node(xs[3] - 88, 24, 176, 52, "focal", None, "AWS STS", "sts.amazonaws.com")
    g.node(xs[4] - 88, 24, 176, 52, "external", None, "Lambda + ECR", "this function only")
    for i, y in enumerate((124, 172, 220, 260, 316, 380, 428), 1):
        g.raw(f'<circle cx="24" cy="{y}" r="8" fill="{PAPER}" stroke="{SOFT}" stroke-width="0.8"/>'
              f'<text x="24" y="{y + 3}" fill="{MUT}" font-size="8" font-weight="500" font-family="{MONO}" text-anchor="middle">{i}</text>')
    g.legend(492, [("line-muted", "inside Kubernetes"), ("line-link", "call to AWS or the web"), ("line-dash", "reply"), ("line-accent", "the credential")])
    return g


# =========================================================================================================
# 3. The trust chain (architecture)
# =========================================================================================================
def fig_trust():
    g = SVG("fed-trust", 1000, 488, "The trust chain behind keyless deploys",
            "kiac-dev publishes its token-signing keys on hangarplatform.dev; an IAM identity provider trusts them, so Crossplane and each app's deploy step can assume their own IAM roles, and every role Crossplane creates sits inside a permissions boundary.")
    g.zone(24, 40, 288, 384, "KIAC-DEV CLUSTER")
    g.zone(336, 40, 192, 384, "PUBLIC WEB")
    g.zone(552, 40, 424, 384, "AWS ACCOUNT 700017004810")
    g.zone(564, 288, 400, 124, "PERMISSIONS BOUNDARY", kind="security", label_x=692)
    # arrows
    g.arrow([(288, 102), (364, 102)], dashed=True); g.label_h(326, 102, "PUBLISH")
    g.arrow([(512, 102), (572, 102)], color="link", dashed=True); g.label_h(542, 102, "KEYS", LINK)
    g.arrow([(672, 132), (672, 192)]); g.label_v(672, 162, "VERIFIES")
    g.arrow([(288, 226), (572, 226)], color="link"); g.label_h(430, 226, "ASSUME ROLE", LINK)
    g.arrow([(288, 362), (572, 362)], color="accent"); g.label_h(430, 362, "ASSUME ROLE", ACC)
    g.arrow([(672, 256), (672, 332)]); g.label_v(672, 276, "CREATES")
    g.arrow([(796, 226), (868, 226), (868, 332)]); g.label_h(832, 226, "CREATES")
    # nodes
    g.node(48, 72, 240, 60, "backend", "ISSUER", "kiac-dev API server", "signs ServiceAccount tokens")
    g.node(48, 196, 240, 60, "backend", "PODS", "Crossplane AWS providers", "SA provider-aws-*")
    g.node(48, 332, 240, 60, "backend", "PODS", "Deploy step · bootstrap Job", "SA glidepath-cloud-deployer")
    g.node(368, 72, 144, 60, "external", "STATIC", "Published keys", "/oidc/kiac-dev")
    g.node(576, 72, 200, 60, "external", "IAM", "Identity provider", "trusts the issuer")
    g.node(576, 196, 220, 60, "backend", "ROLE", "hangar-crossplane-kiac-dev", "builds the infrastructure")
    g.node(576, 336, 192, 60, "focal", "ROLE", "glidepath-deploy-<fn>", "this repo · this function")
    g.node(784, 336, 168, 60, "store", "ROLE", "<fn>-exec", "runs the function")
    g.legend(460, [("backend", "workload or role"), ("external", "public / AWS service"), ("security", "boundary"),
                   ("line-link", "web identity"), ("line-dash", "keys flow")])
    return g


# =========================================================================================================
# 4. Guardrails (layer stack)
# =========================================================================================================
def fig_layers():
    g = SVG("fed-layers", 1000, 536, "Six guardrails around a keyless deploy",
            "Six independent checks stand between a pipeline step and AWS, from the admission policy that decides who may run as the deploy ServiceAccount down to Crossplane's own policy, which cannot create a role without the permissions boundary.")
    rows = [("01", "Admission policy", "who may run as glidepath-cloud-deployer", "plain"),
            ("02", "Short-lived token", "1 hour · audience sts.amazonaws.com · bound to the pod", "plain"),
            ("03", "Trust policy", "this issuer · this audience · this ServiceAccount", "plain"),
            ("04", "Role policy", "this repository · this function · no deletes", "plain"),
            ("05", "Permissions boundary", "the most any role Crossplane creates can ever do", "focal"),
            ("06", "Crossplane's own policy", "can't create or extend a role without the boundary", "plain")]
    x, w, h, y0 = 160, 800, 64, 40
    g.raw(f'<rect x="{x}" y="{y0}" width="{w}" height="{h * 6}" rx="6" fill="{PAPER}" stroke="{MUT}" stroke-width="1"/>', "zones")
    for i, (idx, name, note, kind) in enumerate(rows):
        y = y0 + h * i
        if kind == "focal":
            g.raw(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="rgba(185,121,31,0.08)" stroke="{ACC}" stroke-width="1"/>')
        elif i:
            g.raw(f'<line x1="{x}" y1="{y}" x2="{x + w}" y2="{y}" stroke="rgba(27,31,36,0.12)" stroke-width="1"/>', "zones")
        c = ACC if kind == "focal" else MUT
        g.raw(f'<text x="{x + 20}" y="{y + 37}" fill="{c}" font-size="9" font-weight="500" font-family="{MONO}" letter-spacing="0.18em">{idx}</text>'
              f'<text x="{x + 64}" y="{y + 38}" fill="{INK}" font-size="15" font-weight="600" font-family="{SANS}">{esc(name)}</text>'
              f'<text x="{x + w - 20}" y="{y + 37}" fill="{MUT}" font-size="10" font-family="{MONO}" text-anchor="end">{esc(note)}</text>')
    # side brackets: where each check runs
    for (y1, y2, text) in ((y0 + 8, y0 + h * 2 - 8, "KUBERNETES"), (y0 + h * 2 + 8, y0 + h * 6 - 8, "AWS IAM")):
        g.raw(f'<line x1="140" y1="{y1}" x2="140" y2="{y2}" stroke="rgba(27,31,36,0.30)" stroke-width="1"/>'
              f'<line x1="136" y1="{y1}" x2="140" y2="{y1}" stroke="rgba(27,31,36,0.30)" stroke-width="1"/>'
              f'<line x1="136" y1="{y2}" x2="140" y2="{y2}" stroke="rgba(27,31,36,0.30)" stroke-width="1"/>'
              f'<text x="128" y="{(y1 + y2) / 2 + 3}" fill="{MUT}" font-size="8" font-weight="500" font-family="{MONO}" letter-spacing="0.14em" text-anchor="end">{text}</text>')
    g.raw(f'<line x1="56" y1="{y0 + h * 6 + 20}" x2="56" y2="{y0 + h * 6 + 44}" stroke="{MUT}" stroke-width="1.2" marker-end="url(#arrow)"/>'
          f'<text x="72" y="{y0 + h * 6 + 36}" fill="{MUT}" font-size="8" font-weight="500" font-family="{MONO}" letter-spacing="0.14em">A DEPLOY PASSES EVERY LAYER, TOP TO BOTTOM</text>')
    g.legend(520, [("backend", "guardrail"), ("focal", "the one added to close an escalation path")])
    return g


# =========================================================================================================
# 5. The deploy step's credential decision (flowchart)
# =========================================================================================================
def fig_flow():
    # Phase 4 (2026-10-16): no stored-key fallback. Each failed check stops the deploy with its own fix.
    g = SVG("fed-flow", 1000, 456, "How the deploy step gets its AWS access",
            "The deploy step checks three things in order: the account ConfigMap is in the namespace, its token belongs to glidepath-cloud-deployer, and STS accepts the function's role. When all hold it assumes glidepath-deploy-<function> with no stored key; when one fails the deploy stops with an error naming that piece.")
    # arrows first
    g.arrow([(500, 64), (500, 92)])
    g.arrow([(500, 184), (500, 212)]); g.label_v(500, 198, "YES")
    g.arrow([(500, 304), (500, 332)]); g.label_v(500, 318, "YES")
    g.arrow([(620, 376), (692, 376)], color="accent"); g.label_h(656, 376, "YES", ACC)
    for y in (140, 260, 376):
        g.arrow([(380, y), (304, y)]); g.label_h(342, y, "NO")
    # shapes
    g.oval(380, 24, 240, 40, "Deploy step starts")
    g.diamond(500, 140, 120, 44, "Account ConfigMap", "in the namespace?")
    g.diamond(500, 260, 120, 44, "Token belongs to", "glidepath-cloud-deployer?")
    g.diamond(500, 376, 120, 44, "STS accepts", "the role?")
    g.node(696, 348, 264, 56, "focal", None, "Assume glidepath-deploy-<fn>", "no stored key")
    g.oval(56, 118, 244, 44, "Deploy fails", sub="error names clusters.yaml")
    g.oval(56, 238, 244, 44, "Deploy fails", sub="error names taskRunSpecs")
    g.oval(56, 354, 244, 44, "Deploy fails", sub="error names the deploy Role")
    return g


# =========================================================================================================
# 6. The incident (timeline)
# =========================================================================================================
def fig_incident():
    g = SVG("fed-incident", 1000, 372, "Incident: smoke-fn's function deleted and re-created",
            "Timeline of 16 October 2026 UTC: the federation switch merged at 17:05, the deploy role appeared at 17:16 and the Lambda function, URL and permission were deleted a second later, the function came back from the placeholder at 17:22, and the fix merged at 17:27.")
    x0, x1, t0, t1 = 60, 940, 0, 35  # minutes after 17:00
    px = lambda m: x0 + (m - t0) * (x1 - x0) / (t1 - t0)
    base = 196
    g.raw(f'<line x1="{x0}" y1="{base}" x2="{x1}" y2="{base}" stroke="{INK}" stroke-width="1"/>', "zones")
    for m in range(0, 36, 5):
        x = px(m)
        g.raw(f'<line x1="{x}" y1="{base - 4}" x2="{x}" y2="{base + 4}" stroke="{INK}" stroke-width="1"/>'
              f'<text x="{x}" y="{base + 20}" fill="{SOFT}" font-size="8" font-family="{MONO}" text-anchor="middle" letter-spacing="0.06em">17:{m:02d}</text>', "zones")
    events = [  # minute, above?, major?, title, line1, line2
        (5 + 22 / 60, True, False, "17:05 · switch merged", "registry names the account", "(gitops-cluster-dev#102)"),
        (16 + 30 / 60, False, True, "17:16 · function deleted", "deploy role created; 1 s later", "function, URL, permission gone"),
        (22 + 45 / 60, True, False, "17:22 · function back", "re-created from the placeholder", "new Function URL"),
        (27 + 30 / 60, False, True, "17:27 · fix merged", "never drop what exists", "(airframe#90, v0.3.144)"),
    ]
    for m, above, major, title, l1, l2 in events:
        x = px(m)
        r = 6 if major else 4
        c = ACC if major else INK
        if above:
            g.raw(f'<line x1="{x}" y1="{base - r}" x2="{x}" y2="{base - 52}" stroke="rgba(27,31,36,0.30)" stroke-width="1"/>', "zones")
            ty = base - 100
        else:
            g.raw(f'<line x1="{x}" y1="{base + r}" x2="{x}" y2="{base + 44}" stroke="rgba(27,31,36,0.30)" stroke-width="1"/>', "zones")
            ty = base + 64
        g.raw(f'<circle cx="{x}" cy="{base}" r="{r}" fill="{c}"/>'
              f'<text x="{x}" y="{ty}" fill="{INK}" font-size="12" font-weight="600" font-family="{SANS}" text-anchor="middle">{esc(title)}</text>'
              f'<text x="{x}" y="{ty + 16}" fill="{MUT}" font-size="9" font-family="{MONO}" text-anchor="middle">{esc(l1)}</text>'
              f'<text x="{x}" y="{ty + 29}" fill="{MUT}" font-size="9" font-family="{MONO}" text-anchor="middle">{esc(l2)}</text>')
    g.legend(352, [("dot", "event"), ("dot-accent", "damage and fix")])
    return g


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Geist',system-ui,sans-serif;background:#f2efe9;color:#1b1f24;padding:2.5rem 2rem}}
.frame{{max-width:1080px;margin:0 auto}}
.eyebrow{{font-family:'Geist Mono',ui-monospace,monospace;font-size:.66rem;font-weight:500;letter-spacing:.18em;text-transform:uppercase;color:#5b6570;margin-bottom:.5rem}}
h1{{font-family:'Instrument Serif',serif;font-size:clamp(1.5rem,2.4vw + .75rem,2rem);font-weight:400;letter-spacing:-.02em;line-height:1.15;margin-bottom:1.25rem}}
.diagram-container{{width:100%;overflow-x:auto}}
svg{{width:100%;display:block}}
@media print{{.diagram-container{{overflow-x:visible}} svg{{min-width:0 !important}}}}
</style>
</head>
<body><div class="frame"><p class="eyebrow">Hangar · keyless cloud deploys</p><h1>{title}</h1>
<div class="diagram-container">{svg}</div></div></body></html>
"""

if __name__ == "__main__":
    figs = [("01-before", fig_before()), ("02-token-exchange", fig_sequence()), ("03-trust-chain", fig_trust()),
            ("04-guardrails", fig_layers()), ("05-deploy-credentials", fig_flow()), ("06-incident", fig_incident())]
    for name, g in figs:
        s = g.svg()
        open(os.path.join(OUT, "fragments", f"{g.slug}.svg"), "w").write(s)
        open(os.path.join(OUT, f"{name}.html"), "w").write(PAGE.format(title=esc(g.title), svg=s))
        print("wrote", name, g.slug)
