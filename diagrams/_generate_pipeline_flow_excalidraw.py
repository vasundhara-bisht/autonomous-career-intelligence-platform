#!/usr/bin/env python3
"""Generator for pipeline_flow.excalidraw (vertical End-to-End Pipeline Flow)."""
import json
import random
from pathlib import Path

# README-friendly width (~720px export at 1x; scales well on GitHub)
CANVAS_W = 720


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
    stroke="#495057",
    stroke_width=1,
    label=None,
    sublabel=None,
    label_size=18,
    sublabel_size=13,
    extra_lines=None,
):
    rid = _id()
    elements = [
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
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": {"type": 3},
            "seed": _seed(),
            "version": 141,
            "versionNonce": _nonce(),
            "isDeleted": False,
            "boundElements": [],
            "updated": 1,
            "link": None,
            "locked": False,
        }
    ]
    lines = []
    if label:
        lines.append(label)
    if sublabel:
        lines.append(sublabel)
    if extra_lines:
        lines.extend(extra_lines)
    if lines:
        tid = _id()
        line_h = 22 if label else 0
        line_h += 18 * (len(lines) - (1 if label else 0))
        elements.append(
            {
                "id": tid,
                "type": "text",
                "x": x + 12,
                "y": y + (h - line_h) / 2,
                "width": w - 24,
                "height": line_h,
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
                "fontSize": label_size,
                "fontFamily": 2,
                "textAlign": "center",
                "verticalAlign": "middle",
                "containerId": rid,
                "originalText": "\n".join(lines),
                "autoResize": True,
                "lineHeight": 1.2,
            }
        )
        elements[0]["boundElements"] = [{"type": "text", "id": tid}]
    return elements, rid


def text_el(x, y, w, h, content, *, size=16, color="#1e1e1e"):
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
        "textAlign": "center",
        "verticalAlign": "top",
        "containerId": None,
        "originalText": content,
        "autoResize": True,
        "lineHeight": 1.25,
    }


def arrow(x1, y1, x2, y2, *, dashed=False, color="#ADB5BD", label=None, label_offset=(0, 0)):
    ox, oy = min(x1, x2), min(y1, y2)
    elements = [
        {
            "id": _id(),
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
            "points": [[x1 - ox, y1 - oy], [x2 - ox, y2 - oy]],
            "lastCommittedPoint": None,
            "startBinding": None,
            "endBinding": None,
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "elbowed": False,
        }
    ]
    if label:
        lx = (x1 + x2) / 2 + label_offset[0]
        ly = (y1 + y2) / 2 + label_offset[1]
        elements.append(text_el(lx - 75, ly - 10, 150, 22, label, size=11, color=color))
    return elements


def build():
    elements = []

    C_ACQ = ("#E8F0FE", "#4A6FA5")
    C_NEUTRAL = ("#F8F9FA", "#6C757D")
    C_ROUTE = ("#FFF3E0", "#E65100")
    C_AI = ("#D4F4F0", "#0D9488")
    C_OUT = ("#E0F2F1", "#2A9D8F")
    C_DASH = ("#E8F6F4", "#2A9D8F")

    box_w = 500
    box_x = (CANVAS_W - box_w) // 2
    cx = box_x + box_w / 2
    gap = 56
    std_h = 92
    route_h = 128
    dash_h = 108
    ai_h = 96

    elements.append(text_el(40, 28, CANVAS_W - 80, 36, "End-to-End Pipeline Flow", size=26))
    elements.append(
        text_el(
            48,
            64,
            CANVAS_W - 96,
            28,
            "Vertical workflow · optimized for README width",
            size=14,
            color="#495057",
        )
    )

    y = 108
    flow_bottom = 0
    boxes = []

    def add_stage(title, sub, colors, height=std_h, *, stroke_width=1, extra_lines=None):
        nonlocal y, flow_bottom
        els, _ = rect(
            box_x,
            y,
            box_w,
            height,
            bg=colors[0],
            stroke=colors[1],
            stroke_width=stroke_width,
            label=title,
            sublabel=sub,
            label_size=18,
            sublabel_size=13,
            extra_lines=extra_lines,
        )
        elements.extend(els)
        boxes.append(
            {
                "title": title,
                "y": y,
                "h": height,
                "cy": y + height / 2,
                "bottom": y + height,
            }
        )
        flow_bottom = y + height
        y += height + gap

    # Flow column background
    band_top = 100
    band_h = 0  # set after layout

    add_stage("Acquisition", "Job boards · ATS · remote sources", C_ACQ)
    add_stage("Normalization", "Standardize metadata + identity", C_NEUTRAL)

    add_stage(
        "Historical memory routing",
        None,
        C_ROUTE,
        height=route_h,
        extra_lines=[
            "Previously processed",
            "AI-only updates",
            "New jobs",
        ],
    )

    add_stage("Relevance filtering", "Title + geo relevance", C_NEUTRAL)
    add_stage("Deduplication", "Identity · URL · fuzzy match", C_NEUTRAL)
    add_stage("Description enrichment", "Reuse or fetch full text", C_NEUTRAL)
    add_stage("AI scoring", "Semantic fit + explainable reason", C_AI, height=ai_h, stroke_width=2)

    route_box = boxes[2]
    ai_box = boxes[6]

    add_stage("Ranked outputs", "Scored recommendations + exports", C_OUT)
    ranked_box = boxes[7]

    add_stage(
        "Dashboard layer",
        "Analytics · recruiter workflows · filters",
        C_DASH,
        height=dash_h,
        stroke_width=2,
    )
    dash_box = boxes[8]

    band_h = dash_box["bottom"] - band_top + 24
    bg_elements, _ = rect(
        box_x - 24,
        band_top,
        box_w + 48,
        band_h,
        bg="#FAFBFC",
        stroke="#DEE2E6",
        stroke_width=1,
        label=None,
    )

    # Main vertical arrows (center column)
    for i in range(len(boxes) - 1):
        y1 = boxes[i]["bottom"] + 6
        y2 = boxes[i + 1]["y"] - 6
        elements += arrow(cx, y1, cx, y2, color="#CED4DA")

    # Subtle routing branches (right side)
    rx = box_x + box_w + 8
    route_mid = route_box["cy"]
    ai_top = ai_box["y"] + 10
    ranked_mid = ranked_box["cy"]

    elements += arrow(
        rx,
        route_mid - 18,
        rx + 72,
        route_mid - 18,
        dashed=True,
        color="#9E9E9E",
        label="Previously processed",
        label_offset=(20, -14),
    )
    elements += arrow(
        rx + 72,
        route_mid - 18,
        rx + 72,
        ranked_mid,
        dashed=True,
        color="#9E9E9E",
    )
    elements += arrow(
        rx + 72,
        ranked_mid,
        box_x + box_w - 8,
        ranked_mid,
        dashed=True,
        color="#9E9E9E",
    )

    elements += arrow(
        rx,
        route_mid + 18,
        rx + 48,
        route_mid + 18,
        dashed=True,
        color="#9E9E9E",
        label="AI-only updates",
        label_offset=(10, 0),
    )
    elements += arrow(
        rx + 48,
        route_mid + 18,
        rx + 48,
        ai_top,
        dashed=True,
        color="#9E9E9E",
    )
    elements += arrow(
        rx + 48,
        ai_top,
        cx + 8,
        ai_top,
        dashed=True,
        color="#9E9E9E",
    )

    elements.append(
        text_el(
            box_x - 8,
            route_box["y"] + route_h - 28,
            120,
            22,
            "New jobs ↓ full path",
            size=11,
            color="#E65100",
        )
    )

    # Final layer emphasis (user-facing)
    elements.append(
        text_el(
            box_x,
            dash_box["bottom"] + 20,
            box_w,
            24,
            "Final user-facing layer",
            size=12,
            color=C_DASH[1],
        )
    )

    footer_y = dash_box["bottom"] + 52
    elements.append(
        text_el(
            48,
            footer_y,
            CANVAS_W - 96,
            40,
            "Returning jobs skip redundant steps via historical memory.",
            size=12,
            color="#868E96",
        )
    )

    all_elements = bg_elements + elements

    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": all_elements,
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
            "zoom": {"value": 1},
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
    out = Path(__file__).parent / "pipeline_flow.excalidraw"
    data = build()
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    out.chmod(0o644)
    print(f"Wrote {out} ({len(data['elements'])} elements)")


if __name__ == "__main__":
    main()
