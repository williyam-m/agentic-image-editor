"""An intentionally off-brand board used to exercise Brand DNA."""
import httpx

API = "http://localhost:8787"


def off_brand_spec() -> dict:
    logo = next(a for a in httpx.get(f"{API}/api/brand/assets?category=logo").json())
    return {
        "id": "d_offbrand", "name": "Off-brand test ad", "format": "feed", "width": 1080, "height": 1350,
        "background": "#E53935", "brief": {}, "checks": [], "variant": 0,
        "layers": [
            {"id": "ob_bg", "name": "Background", "kind": "rect", "role": "background", "x": 0, "y": 0, "w": 1080, "h": 1350, "fill": "#E53935"},
            {"id": "ob_h", "name": "Headline", "kind": "text", "role": "headline", "x": 80, "y": 120, "w": 920, "h": 260,
             "text": "The best accounting software, guaranteed!", "font_family": "Inter", "font_weight": "400",
             "font_size": 96, "line_height": 1.1, "color": "#FF9800"},
            {"id": "ob_s", "name": "Subhead", "kind": "text", "role": "subhead", "x": 80, "y": 420, "w": 900, "h": 50,
             "text": "Get 50% off your first 3 months", "font_family": "Inter", "font_weight": "400",
             "font_size": 36, "line_height": 1.2, "color": "#FFCDD2"},
            {"id": "ob_ctab", "name": "CTA button", "kind": "rect", "role": "cta_bg", "x": 80, "y": 520, "w": 300, "h": 72, "fill": "#4CAF50", "radius": 10},
            {"id": "ob_ctal", "name": "CTA label", "kind": "text", "role": "cta_label", "x": 80, "y": 540, "w": 300, "h": 36,
             "text": "Buy now", "font_family": "Barlow", "font_weight": "600", "font_size": 30, "line_height": 1, "color": "#FFFFFF", "align": "center"},
            {"id": "ob_logo", "name": "Xero logo", "kind": "vector", "role": "logo", "x": 860, "y": 1260, "w": 110, "h": 32,
             "fill": "#FF0000", "svg_url": logo["vectorUrl"], "asset_id": "logo-xero", "children": None},
        ],
    }
