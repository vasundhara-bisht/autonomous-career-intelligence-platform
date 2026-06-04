#!/usr/bin/env python3
"""One-off generator for architecture_overview.excalidraw (not part of app runtime)."""
import json
import random
from pathlib import Path

CANVAS_W, CANVAS_H = 1600, 900


def _id():
    return format(random.randint(0, 2**64 - 1), "x")[2:18]


def _seed():
    return random.randint(1, 2**31 - 1)


def _nonce():
    return random.randint(1, 2**31 - 1)


def rect(
    x,
    y,
    w,
    h,
    *,
    bg="#ffffff",
    stroke="#1e1e1e",
    stroke_width=2,
    stroke_style="solid",
    roughness=0,
    label=None,
    label_size=14,
    label_bold=False,
    sublabel=None,
    sublabel_size=11,
    roundness=3,
):
    rid = _id()
    elements = []
    elements.append(
        {
            "id": rid,
            "type": "rectangle",
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "angle": 0,
            "strokeColor": stroke,
            "backgroundColor": bg,
            "fillStyle": "solid",
            "strokeWidth": stroke_width,
            "strokeStyle": stroke_style,
            "roughness": roughness,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": {"type": roundness},
            "seed": _seed(),
            "version": 141,
            "versionNonce": _nonce(),
            "isDeleted": False,
            "boundElements": [],
            "updated": 1,
            "link": None,
            "locked": False,
        }
    )
    bound = []
    lines = []
    if label:
        lines.append(label)
    if sublabel:
        lines.append(sublabel)
    if lines:
        tid = _id()
        text_h = (22 if label else 0) + (18 if sublabel else 0)
        ty = y + (h - text_h) / 2
        elements.append(
            {
                "id": tid,
                "type": "text",
                "x": x + 8,
                "y": ty,
                "width": w - 16,
                "height": text_h or 20,
                "angle": 0,
                "strokeColor": stroke,
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "roughness": 0,
                "opacity": 100,
                "groupIds": [],
                "frameId": None,
                "roundness": None,
                "seed": _seed(),
                "version": 141,
                "versionNonce": _nonce(),
                "isDeleted": False,
                "boundElements": None,
                "updated": 1,
                "link": None,
                "locked": False,
                "text": "\n".join(lines),
                "fontSize": label_size if label else sublabel_size,
                "fontFamily": 2,
                "textAlign": "center",
                "verticalAlign": "middle",
                "containerId": rid,
                "originalText": "\n".join(lines),
                "autoResize": True,
                "lineHeight": 1.2,
            }
        )
        bound.append({"type": "text", "id": tid})
    elements[0]["boundElements"] = bound
    return elements


def text_el(x, y, w, h, content, *, size=20, bold_center=True, color="#1e1e1e"):
    return {
        "id": _id(),
        "type": "text",
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": color,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": _seed(),
        "version": 141,
        "versionNonce": _nonce(),
        "isDeleted": False,
        "boundElements": None,
        "updated": 1,
        "link": None,
        "locked": False,
        "text": content,
        "fontSize": size,
        "fontFamily": 2,
        "textAlign": "center" if bold_center else "left",
        "verticalAlign": "top",
        "containerId": None,
        "originalText": content,
        "autoResize": True,
        "lineHeight": 1.25,
    }


def arrow(
    x1,
    y1,
    x2,
    y2,
    *,
    dashed=False,
    color="#495057",
    label=None,
):
    ox = min(x1, x2)
    oy = min(y1, y2)
    p1 = [x1 - ox, y1 - oy]
    p2 = [x2 - ox, y2 - oy]
    elements = []
    aid = _id()
    elements.append(
        {
            "id": aid,
            "type": "arrow",
            "x": ox,
            "y": oy,
            "width": max(abs(x2 - x1), 1),
            "height": max(abs(y2 - y1), 1),
            "angle": 0,
            "strokeColor": color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "dashed" if dashed else "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": {"type": 2},
            "seed": _seed(),
            "version": 141,
            "versionNonce": _nonce(),
            "isDeleted": False,
            "boundElements": None,
            "updated": 1,
            "link": None,
            "locked": False,
            "points": [p1, p2],
            "lastCommittedPoint": None,
            "startBinding": None,
            "endBinding": None,
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "elbowed": False,
        }
    )
    if label:
        elements.append(
            text_el(
                (x1 + x2) / 2 - 80,
                (y1 + y2) / 2 - 28,
                160,
                24,
                label,
                size=12,
                bold_center=True,
                color=color,
            )
        )
    return elements


def build():
    elements = []
    # Colors
    C_SOURCE_BG = "#E8F0FE"
    C_SOURCE_STROKE = "#4A6FA5"
    C_PIPE_BG = "#F8F9FA"
    C_PIPE_STROKE = "#343A40"
    C_ROUTE_BG = "#FFF3E0"
    C_AI_BG = "#D4F4F0"
    C_AI_STROKE = "#0D9488"
    C_MEM_BG = "#FFF8E1"
    C_MEM_STROKE = "#B8860B"
    C_OUT_BG = "#E0F2F1"
    C_OUT_STROKE = "#2A9D8F"
    C_CTRL_BG = "#E9ECEF"

    # Title
    elements.append(
        text_el(200, 18, 1200, 40, "Autonomous Career Intelligence Platform", size=32)
    )
    elements.append(
        text_el(450, 58, 700, 28, "Collect → Organize → Score → Recommend", size=18, color="#495057")
    )

    # --- L1 Sources ---
    elements += rect(
        28,
        108,
        224,
        418,
        bg="#FAFBFC",
        stroke=C_SOURCE_STROKE,
        stroke_width=1,
        label="Hiring channels",
        label_size=16,
    )
    sources = [
        ("LinkedIn", "Query orchestration"),
        ("Instahyre", "Feed sessions"),
        ("Greenhouse", "Company boards"),
        ("Lever", "Company boards"),
        ("WeWorkRemotely", "Remote listings"),
    ]
    sy = 148
    for title, sub in sources:
        elements += rect(
            48,
            sy,
            184,
            52,
            bg=C_SOURCE_BG,
            stroke=C_SOURCE_STROKE,
            label=title,
            sublabel=sub,
            label_size=15,
            sublabel_size=11,
        )
        sy += 62

    # Acquisition control
    elements += rect(
        48,
        448,
        184,
        58,
        bg=C_CTRL_BG,
        stroke="#6C757D",
        label="Run governance",
        sublabel="MAX_RUNS · JSON catalogs",
        label_size=14,
        sublabel_size=10,
    )

    # --- Pipeline hero ---
    elements += rect(
        268,
        108,
        754,
        408,
        bg=C_PIPE_BG,
        stroke=C_PIPE_STROKE,
        stroke_width=2,
        label="Career intelligence pipeline",
        label_size=18,
    )
    elements.append(
        text_el(
            900,
            118,
            110,
            40,
            "main.py",
            size=11,
            bold_center=True,
            color="#868E96",
        )
    )
    elements.append(
        text_el(
            290,
            468,
            400,
            22,
            "Operational run summaries (Stage 1 · identity · batches)",
            size=11,
            bold_center=False,
            color="#868E96",
        )
    )

    chips = [
        ("Normalize", "Standardize fields", C_PIPE_BG, C_PIPE_STROKE),
        ("Historical routing", "New · AI · Done", C_ROUTE_BG, "#E65100"),
        ("Stage 1 filter", "PM relevance", C_PIPE_BG, C_PIPE_STROKE),
        ("Dedup", "V2 · URL · fuzzy", C_PIPE_BG, C_PIPE_STROKE),
        ("Descriptions", "Reuse or fetch", C_PIPE_BG, C_PIPE_STROKE),
        ("AI scoring", "Fit + reason", C_AI_BG, C_AI_STROKE),
        ("Export & rank", "Session output", C_PIPE_BG, C_PIPE_STROKE),
    ]
    cx, cy, cw, ch = 288, 188, 88, 118
    gap = 8
    chip_centers = []
    for i, (title, sub, bg, stroke) in enumerate(chips):
        x = cx + i * (cw + gap)
        elements += rect(
            x,
            cy,
            cw,
            ch,
            bg=bg,
            stroke=stroke,
            stroke_width=2 if title == "AI scoring" else 1,
            label=title,
            sublabel=sub,
            label_size=12,
            sublabel_size=10,
        )
        chip_centers.append((x + cw / 2, cy + ch / 2))
    # Inter-chip flow arrows
    for i in range(len(chip_centers) - 1):
        x1 = chip_centers[i][0] + cw / 2
        x2 = chip_centers[i + 1][0] - cw / 2
        y = cy + ch / 2
        elements += arrow(x1, y, x2, y, color="#ADB5BD")

    # --- Memory band ---
    elements += rect(
        268,
        532,
        754,
        118,
        bg="#FFFBF0",
        stroke=C_MEM_STROKE,
        stroke_width=1,
        label="Career memory (CSV)",
        label_size=15,
    )
    mem_boxes = [
        ("Historical jobs", "Run memory · routing"),
        ("Description store", "Full text cache"),
        ("Recruiter CRM", "Contacts · outreach"),
    ]
    mx = 288
    mw = 228
    mg = 14
    mem_centers = []
    for title, sub in mem_boxes:
        elements += rect(
            mx,
            568,
            mw,
            64,
            bg=C_MEM_BG,
            stroke=C_MEM_STROKE,
            label=title,
            sublabel=sub,
            label_size=13,
            sublabel_size=10,
        )
        mem_centers.append((mx + mw / 2, 600))
        mx += mw + mg

    # --- Outputs ---
    elements += rect(
        1058,
        148,
        214,
        96,
        bg=C_OUT_BG,
        stroke=C_OUT_STROKE,
        label="Ranked recommendations",
        sublabel="jobs.csv · score · reason",
        label_size=14,
        sublabel_size=11,
    )
    elements += rect(
        1058,
        268,
        214,
        200,
        bg=C_OUT_BG,
        stroke=C_OUT_STROKE,
        label="Streamlit dashboard",
        sublabel="Filters · charts · recruiters",
        label_size=14,
        sublabel_size=11,
    )
    elements.append(
        text_el(
            1070,
            340,
            190,
            110,
            "• Location & source filters\n• AI score + reason\n• Job listings table\n• Recruiter CRM view",
            size=11,
            bold_center=False,
            color="#495057",
        )
    )

    # --- Main arrows ---
    # Sources → pipeline (to Normalize)
    elements += arrow(232, 280, 268, 250, color=C_SOURCE_STROKE)
    elements += arrow(232, 478, 268, 420, color="#6C757D")

    # Pipeline → outputs
    elements += arrow(1022, 250, 1058, 200, color=C_OUT_STROKE)
    elements += arrow(1022, 320, 1058, 330, color=C_OUT_STROKE)

    # Memory ↔ pipeline (solid feedback)
    elements += arrow(640, 532, 640, 516, color=C_MEM_STROKE)
    elements += arrow(500, 516, 500, 532, color=C_MEM_STROKE)
    elements += arrow(880, 516, 880, 532, color=C_MEM_STROKE)
    elements.append(
        text_el(600, 518, 120, 20, "Incremental memory", size=11, color=C_MEM_STROKE)
    )

    # CRM path to dashboard
    elements += arrow(980, 600, 1100, 468, color=C_MEM_STROKE, label="Recruiter path")

    # Dashed shortcuts
    # Historical jobs (first mem box) → AI scoring chip (index 5)
    hist_c = mem_centers[0]
    ai_c = chip_centers[5]
    elements += arrow(
        hist_c[0],
        hist_c[1] + 20,
        ai_c[0] - 20,
        ai_c[1] + 40,
        dashed=True,
        color="#9E9E9E",
        label="Needs AI only",
    )
    # Historical → Export chip (index 6)
    exp_c = chip_centers[6]
    elements += arrow(
        hist_c[0] + 40,
        hist_c[1] + 10,
        exp_c[0],
        exp_c[1] + 50,
        dashed=True,
        color="#9E9E9E",
        label="Fully processed",
    )

    # Legend footer
    elements.append(
        text_el(
            40,
            680,
            1520,
            48,
            "Python pipeline · Playwright (LinkedIn, Instahyre) · OpenAI batch scoring · CSV memory · Streamlit dashboard",
            size=12,
            bold_center=True,
            color="#868E96",
        )
    )
    elements.append(
        text_el(
            40,
            720,
            400,
            24,
            "Candidate profile drives AI fit + explainable reason",
            size=11,
            bold_center=False,
            color="#868E96",
        )
    )

    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {
            "gridSize": 20,
            "viewBackgroundColor": "#ffffff",
            "currentItemStrokeColor": "#1e1e1e",
            "currentItemBackgroundColor": "transparent",
            "currentItemFillStyle": "solid",
            "currentItemStrokeWidth": 2,
            "currentItemRoughness": 0,
            "currentItemOpacity": 100,
            "currentItemFontFamily": 2,
            "currentItemFontSize": 16,
            "currentItemTextAlign": "left",
            "currentItemStartArrowhead": None,
            "currentItemEndArrowhead": "arrow",
            "zoom": {"value": 0.75},
            "scrollX": 0,
            "scrollY": 0,
            "theme": "light",
            "viewModeEnabled": False,
            "zenModeEnabled": False,
            "exportWithDarkMode": False,
            "exportBackground": True,
            "exportScale": 1,
            "objectsSnapModeEnabled": False,
        },
        "files": {},
    }


def main():
    out = Path(__file__).parent / "architecture_overview.excalidraw"
    data = build()
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {out} ({len(data['elements'])} elements)")


if __name__ == "__main__":
    main()
