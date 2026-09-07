"""PrivacyLens AI — session-only public-content privacy awareness tool."""

import html
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import google.generativeai as genai
import streamlit as st


st.set_page_config(
    page_title="PrivacyLens AI | Digital Privacy Intelligence",
    page_icon="🛡️",
    layout="wide",
)


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
def get_api_key() -> str:
    """Read credentials from Streamlit secrets or the environment, never code."""
    try:
        key = st.secrets.get("GOOGLE_API_KEY", "")
        if key:
            return str(key)
    except Exception:
        pass
    return os.getenv("GOOGLE_API_KEY", "")


GOOGLE_API_KEY = get_api_key()
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
MODEL = None
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        MODEL = genai.GenerativeModel(MODEL_NAME)
    except Exception:
        MODEL = None


ANALYSIS_PROMPT = """
You are PrivacyLens AI, an educational privacy assistant. Analyze ONLY the
content explicitly supplied below by the user. It may be pasted content or
visible text extracted from a public URL the user deliberately provided. Never
search the internet, identify a person, infer missing facts, or make claims
about information absent from the supplied content.

Assess proportionate privacy exposure. Use these category names when they
apply: Contact Exposure, Location Exposure, Identity Exposure, Schedule
Exposure, Institution Exposure, Public Links & Profiles. Do not reproduce
complete sensitive values in information_found; describe their type instead.

Return ONLY valid JSON in exactly this shape:
{
  "overall_summary": "short, balanced summary",
  "risk_level": "Low or Medium or High",
  "detected_exposures": [{
    "category": "one supported category name",
    "severity": "Low or Medium or High",
    "information_found": "what is exposed, without restating full sensitive data",
    "why_it_matters": "clear and proportionate explanation",
    "recommendation": "specific practical action based on this content"
  }],
  "positive_observations": ["privacy-conscious observation"],
  "recommendations": ["specific recommendation based on a detected exposure"]
}

Return an empty detected_exposures list when nothing meaningful is present. Do
not exaggerate risk and do not create generic recommendations.
"""

REWRITE_PROMPT = """
You are PrivacyLens AI. Rewrite the supplied text so it is safer to publish,
while preserving the writer's main message and natural tone. Remove or
generalize unnecessary contact details, exact locations, addresses, dates,
travel plans, predictable routines, and other sensitive details. Do not invent
information. Return ONLY the rewritten text.
"""


DEFAULTS = {
    "analysis_history": [],
    "active_result_id": None,
    "safer_rewrites": {},
    "chat_history": {},
    "web_preview": None,
    "theme_preference": "Follow system",
    "analysis_mode": "AI + local context",
    "mask_detected_values": True,
}
for state_key, state_value in DEFAULTS.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = state_value


def apply_style() -> None:
    """Apply the PrivacyLens design system without changing Streamlit behavior."""
    dark_palette = """
    :root {--pl-primary:#4f7cff;--pl-secondary:#a78bfa;--pl-accent:#22d3ee;--pl-bg:#07111f;
    --pl-bg-glow:#0b1d37;--pl-surface:#0d1a2d;--pl-card:#11233b;--pl-card-hover:#162d4a;
    --pl-border:rgba(148,163,184,.18);--pl-text:#eff6ff;--pl-muted:#94a8c5;--pl-success:#34d399;
    --pl-warning:#fbbf24;--pl-danger:#fb7185;--pl-shadow:0 18px 45px rgba(1,8,20,.32);}
    """
    light_palette = """
    :root {--pl-primary:#315ee8;--pl-secondary:#7c4dff;--pl-accent:#0891b2;--pl-bg:#f3f7fd;
    --pl-bg-glow:#e8f1ff;--pl-surface:#ffffff;--pl-card:#ffffff;--pl-card-hover:#f8fbff;
    --pl-border:rgba(49,94,232,.13);--pl-text:#10213e;--pl-muted:#60718d;--pl-success:#0f9f6e;
    --pl-warning:#b77908;--pl-danger:#dc3d58;--pl-shadow:0 18px 38px rgba(45,74,122,.11);}
    """
    preference = st.session_state.theme_preference
    if preference == "Dark":
        palette = dark_palette
    elif preference == "Light":
        palette = light_palette
    else:
        palette = light_palette + "@media (prefers-color-scheme: dark) {" + dark_palette + "}"
    st.markdown(
        f"""<style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono&family=Manrope:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');
        {palette}
        * {{box-sizing:border-box;}}
        html, body, [class*="css"] {{font-family:'Manrope','Segoe UI',sans-serif;}}
        .stApp {{background:radial-gradient(circle at 81% -8%, color-mix(in srgb, var(--pl-primary) 16%, transparent), transparent 30rem),radial-gradient(circle at 8% 15%, color-mix(in srgb, var(--pl-secondary) 11%, transparent), transparent 29rem),var(--pl-bg);color:var(--pl-text);transition:background .35s ease,color .25s ease;}}
        header[data-testid="stHeader"] {{background:transparent;}}
        .block-container {{max-width:1450px;padding:1.45rem 2.5rem 4rem;}}
        #MainMenu, footer {{visibility:hidden;}}
        h1,h2,h3 {{font-family:'Space Grotesk','Manrope',sans-serif!important;color:var(--pl-text)!important;letter-spacing:-.035em;}}
        h1 {{font-size:clamp(2rem,4vw,3.4rem)!important;font-weight:700!important;line-height:1.02!important;}}
        h2 {{font-size:1.65rem!important;}}
        h3 {{font-size:1.1rem!important;letter-spacing:-.02em;}}
        p,li,.stMarkdown {{color:var(--pl-text);}}
        [data-testid="stCaptionContainer"] {{color:var(--pl-muted)!important;}}
        section[data-testid="stSidebar"] > div:first-child {{background:linear-gradient(180deg,color-mix(in srgb,var(--pl-surface) 92%,var(--pl-primary)),var(--pl-surface));border-right:1px solid var(--pl-border);}}
        section[data-testid="stSidebar"] .block-container {{padding:1.3rem .9rem 2rem;}}
        .pl-brand {{display:flex;align-items:center;gap:.78rem;margin:.4rem .3rem 1.25rem;}}
        .pl-logo {{width:2.55rem;height:2.55rem;display:grid;place-items:center;border-radius:.9rem;background:linear-gradient(145deg,var(--pl-primary),var(--pl-secondary));box-shadow:0 10px 25px color-mix(in srgb,var(--pl-primary) 32%,transparent);position:relative;overflow:hidden;}}
        .pl-logo:after {{content:'';position:absolute;width:1.35rem;height:1.55rem;border:2px solid white;border-radius:50% 50% 42% 42%;opacity:.85;}}
        .pl-brand-name {{font-family:'Space Grotesk',sans-serif;font-size:1.14rem;font-weight:700;line-height:1;color:var(--pl-text);}}
        .pl-brand-tag {{font-size:.64rem;letter-spacing:.12em;text-transform:uppercase;color:var(--pl-accent);margin-top:.27rem;}}
        .pl-version {{display:inline-flex;border:1px solid color-mix(in srgb,var(--pl-accent) 38%,transparent);color:var(--pl-accent);border-radius:999px;padding:.24rem .52rem;font-size:.63rem;font-weight:800;letter-spacing:.055em;margin:.15rem .3rem 1rem;}}
        section[data-testid="stSidebar"] [role="radiogroup"] {{gap:.3rem;}}
        section[data-testid="stSidebar"] [data-baseweb="radio"] {{margin:0!important;padding:.62rem .7rem;border:1px solid transparent;border-radius:.65rem;transition:all .2s ease;}}
        section[data-testid="stSidebar"] [data-baseweb="radio"]:hover {{background:color-mix(in srgb,var(--pl-primary) 11%,transparent);transform:translateX(2px);}}
        section[data-testid="stSidebar"] [data-baseweb="radio"]:has(input:checked) {{background:linear-gradient(90deg,color-mix(in srgb,var(--pl-primary) 22%,transparent),color-mix(in srgb,var(--pl-secondary) 12%,transparent));border-color:color-mix(in srgb,var(--pl-primary) 36%,transparent);box-shadow:0 6px 16px color-mix(in srgb,var(--pl-primary) 11%,transparent);}}
        section[data-testid="stSidebar"] [data-baseweb="radio"] > div:first-child {{display:none;}}
        section[data-testid="stSidebar"] [data-baseweb="radio"] label {{font-size:.88rem;font-weight:700;color:var(--pl-text)!important;}}
        .pl-page-kicker {{color:var(--pl-accent);font-size:.7rem;font-weight:800;letter-spacing:.13em;text-transform:uppercase;margin-bottom:.55rem;}}
        .pl-page-intro {{color:var(--pl-muted);font-size:1rem;max-width:48rem;line-height:1.7;margin-top:.15rem;}}
        .pl-hero {{position:relative;overflow:hidden;border:1px solid var(--pl-border);border-radius:1.35rem;padding:clamp(1.8rem,4vw,4rem);margin:.35rem 0 1.5rem;background:linear-gradient(125deg,color-mix(in srgb,var(--pl-card) 90%,var(--pl-primary)),var(--pl-card) 48%,color-mix(in srgb,var(--pl-card) 86%,var(--pl-secondary)));box-shadow:var(--pl-shadow);isolation:isolate;}}
        .pl-hero:before {{content:'';position:absolute;inset:0;background-image:linear-gradient(color-mix(in srgb,var(--pl-accent) 9%,transparent) 1px,transparent 1px),linear-gradient(90deg,color-mix(in srgb,var(--pl-accent) 9%,transparent) 1px,transparent 1px);background-size:36px 36px;mask-image:linear-gradient(90deg,black,transparent 83%);z-index:-1;}}
        .pl-hero:after {{content:'';position:absolute;right:6%;top:15%;width:11rem;height:11rem;border:1px solid color-mix(in srgb,var(--pl-accent) 50%,transparent);border-radius:50%;box-shadow:0 0 0 1.9rem color-mix(in srgb,var(--pl-primary) 10%,transparent),0 0 0 4.2rem color-mix(in srgb,var(--pl-secondary) 7%,transparent);animation:pl-orbit 7s ease-in-out infinite;z-index:-1;}}
        .pl-hero-copy {{max-width:47rem;}}
        .pl-eyebrow {{display:inline-flex;align-items:center;gap:.45rem;color:var(--pl-accent);font-size:.73rem;font-weight:800;text-transform:uppercase;letter-spacing:.13em;}}
        .pl-eyebrow:before {{content:'';width:.43rem;height:.43rem;border-radius:50%;background:var(--pl-success);box-shadow:0 0 0 .28rem color-mix(in srgb,var(--pl-success) 14%,transparent);}}
        .pl-hero h1 {{font-size:clamp(2.45rem,5vw,4.55rem)!important;margin:.65rem 0 .8rem!important;max-width:45rem;}}
        .pl-hero p {{color:var(--pl-muted);font-size:1.05rem;line-height:1.75;max-width:42rem;}}
        .pl-card,.pl-stat,.pl-empty,.pl-source-card,.pl-action-card {{background:linear-gradient(145deg,color-mix(in srgb,var(--pl-card) 96%,white),var(--pl-card));border:1px solid var(--pl-border);border-radius:1rem;box-shadow:var(--pl-shadow);}}
        .pl-card {{padding:1.2rem;height:100%;transition:transform .22s ease,border-color .22s ease,box-shadow .22s ease;}}
        .pl-card:hover,.pl-source-card:hover,.pl-action-card:hover {{transform:translateY(-4px);border-color:color-mix(in srgb,var(--pl-primary) 48%,transparent);box-shadow:0 23px 44px color-mix(in srgb,var(--pl-primary) 14%,transparent);}}
        .pl-card-icon {{width:2.6rem;height:2.6rem;border-radius:.75rem;display:grid;place-items:center;background:color-mix(in srgb,var(--pl-primary) 15%,transparent);color:var(--pl-accent);font-size:1.2rem;margin-bottom:1rem;}}
        .pl-card-title {{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:1rem;margin-bottom:.38rem;color:var(--pl-text);}}
        .pl-card-copy {{font-size:.83rem;line-height:1.6;color:var(--pl-muted);}}
        .pl-section-heading {{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin:1.85rem 0 .8rem;}}
        .pl-section-heading h2 {{margin:0!important;font-size:1.38rem!important;}}
        .pl-section-heading p {{margin:0;color:var(--pl-muted);font-size:.8rem;line-height:1.5;text-align:right;max-width:29rem;}}
        .pl-source-card {{padding:1.05rem 1.1rem;display:flex;align-items:center;gap:.85rem;margin:.8rem 0 1rem;}}
        .pl-source-mark {{flex:0 0 auto;width:2.65rem;height:2.65rem;border-radius:.8rem;display:grid;place-items:center;color:var(--pl-accent);background:color-mix(in srgb,var(--pl-accent) 12%,transparent);border:1px solid color-mix(in srgb,var(--pl-accent) 25%,transparent);font-family:'DM Mono',monospace;font-weight:800;}}
        .pl-source-name {{font-family:'Space Grotesk',sans-serif;font-weight:700;color:var(--pl-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
        .pl-source-meta {{font-size:.75rem;color:var(--pl-muted);margin-top:.18rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
        .pl-meter {{margin:.7rem 0 .2rem;display:flex;align-items:center;gap:.75rem;}}
        .pl-meter-track {{height:.37rem;border-radius:99px;overflow:hidden;background:color-mix(in srgb,var(--pl-muted) 14%,transparent);flex:1;}}
        .pl-meter-fill {{height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--pl-accent),var(--pl-primary),var(--pl-secondary));transition:width .28s ease;}}
        .pl-meter-value {{font-family:'DM Mono',monospace;font-size:.68rem;white-space:nowrap;color:var(--pl-muted);}}
        .pl-stat {{padding:1.05rem 1.15rem;min-height:7.4rem;position:relative;overflow:hidden;}}
        .pl-stat:after {{content:'';position:absolute;right:-1rem;bottom:-1.4rem;width:5rem;height:5rem;border-radius:50%;background:color-mix(in srgb,var(--pl-primary) 10%,transparent);}}
        .pl-stat-label {{color:var(--pl-muted);font-size:.66rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;}}
        .pl-stat-value {{font-family:'Space Grotesk',sans-serif;color:var(--pl-text);font-size:clamp(1.45rem,2vw,2.15rem);font-weight:700;line-height:1.15;margin:.45rem 0 .25rem;}}
        .pl-stat-detail {{color:var(--pl-muted);font-size:.74rem;}}
        .pl-risk-score {{display:grid;place-items:center;min-height:15.4rem;}}
        .pl-ring {{--size:12rem;width:var(--size);height:var(--size);border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--risk) calc(var(--score) * 1%),color-mix(in srgb,var(--risk) 13%,transparent) 0);position:relative;box-shadow:0 0 34px color-mix(in srgb,var(--risk) 25%,transparent);animation:pl-score-in .8s ease both;}}
        .pl-ring:before {{content:'';position:absolute;width:calc(var(--size) - 1.15rem);height:calc(var(--size) - 1.15rem);border-radius:50%;background:var(--pl-card);border:1px solid var(--pl-border);}}
        .pl-ring-content {{position:relative;text-align:center;}}
        .pl-ring-label {{font-size:.62rem;font-weight:800;letter-spacing:.12em;color:var(--pl-muted);}}
        .pl-ring-value {{font-family:'Space Grotesk',sans-serif;font-size:3.3rem;font-weight:700;line-height:1;color:var(--pl-text);}}
        .pl-ring-total {{font-size:.8rem;color:var(--pl-muted);}}
        .pl-badge {{display:inline-flex;align-items:center;gap:.32rem;border-radius:999px;padding:.27rem .58rem;font-size:.67rem;font-weight:800;letter-spacing:.04em;}}
        .pl-badge-low {{background:color-mix(in srgb,var(--pl-success) 15%,transparent);color:var(--pl-success);border:1px solid color-mix(in srgb,var(--pl-success) 28%,transparent);}}
        .pl-badge-medium {{background:color-mix(in srgb,var(--pl-warning) 15%,transparent);color:var(--pl-warning);border:1px solid color-mix(in srgb,var(--pl-warning) 28%,transparent);}}
        .pl-badge-high {{background:color-mix(in srgb,var(--pl-danger) 15%,transparent);color:var(--pl-danger);border:1px solid color-mix(in srgb,var(--pl-danger) 28%,transparent);}}
        .pl-empty {{padding:2.7rem 1.6rem;text-align:center;border-style:dashed;box-shadow:none;}}
        .pl-empty-mark {{width:4.4rem;height:4.4rem;margin:0 auto 1rem;display:grid;place-items:center;border-radius:1.35rem;color:var(--pl-accent);font-size:2rem;background:radial-gradient(circle at 35% 30%,color-mix(in srgb,var(--pl-accent) 29%,transparent),color-mix(in srgb,var(--pl-primary) 9%,transparent));border:1px solid color-mix(in srgb,var(--pl-accent) 25%,transparent);animation:pl-float 4s ease-in-out infinite;}}
        .pl-empty-title {{font-family:'Space Grotesk',sans-serif;font-size:1.18rem;font-weight:700;color:var(--pl-text);}}
        .pl-empty-copy {{max-width:27rem;margin:.45rem auto 0;color:var(--pl-muted);font-size:.86rem;line-height:1.65;}}
        .pl-exposure {{border-left:3px solid var(--risk);padding:1rem 1.1rem;margin:.4rem 0 .8rem;background:color-mix(in srgb,var(--risk) 5%,var(--pl-card));border-radius:.75rem;}}
        .pl-exposure-top {{display:flex;align-items:center;justify-content:space-between;gap:.8rem;}}
        .pl-exposure-category {{font-family:'Space Grotesk',sans-serif;font-weight:700;color:var(--pl-text);}}
        .pl-exposure-copy {{color:var(--pl-muted);font-size:.84rem;line-height:1.58;margin-top:.45rem;}}
        .pl-chart {{padding:1.1rem 1.2rem;}}
        .pl-chart-title {{font-family:'Space Grotesk',sans-serif;font-size:1rem;font-weight:700;margin-bottom:1.1rem;color:var(--pl-text);}}
        .pl-bar-row {{display:grid;grid-template-columns:minmax(7rem,1fr) 3fr 2rem;gap:.7rem;align-items:center;margin:.65rem 0;}}
        .pl-bar-label,.pl-bar-value {{font-size:.74rem;color:var(--pl-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
        .pl-bar-value {{font-family:'DM Mono',monospace;text-align:right;color:var(--pl-text);}}
        .pl-bar-track {{height:.52rem;border-radius:999px;background:color-mix(in srgb,var(--pl-muted) 14%,transparent);overflow:hidden;}}
        .pl-bar-fill {{height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--pl-primary),var(--pl-accent));animation:pl-bar-in .7s ease both;}}
        .pl-action-card {{padding:1rem 1.05rem;margin:.55rem 0;}}
        .pl-action-meta {{font-size:.7rem;color:var(--pl-muted);margin-top:.3rem;}}
        div[data-testid="stButton"] > button,div[data-testid="stDownloadButton"] > button {{border:1px solid color-mix(in srgb,var(--pl-primary) 36%,var(--pl-border));border-radius:.72rem;background:color-mix(in srgb,var(--pl-primary) 9%,var(--pl-card));color:var(--pl-text);font-family:'Manrope',sans-serif;font-weight:800;min-height:2.55rem;transition:transform .2s ease,box-shadow .2s ease,background .2s ease;}}
        div[data-testid="stButton"] > button:hover,div[data-testid="stDownloadButton"] > button:hover {{transform:translateY(-2px);background:color-mix(in srgb,var(--pl-primary) 18%,var(--pl-card));box-shadow:0 10px 18px color-mix(in srgb,var(--pl-primary) 18%,transparent);}}
        div[data-testid="stButton"] > button[kind="primary"] {{background:linear-gradient(120deg,var(--pl-primary),var(--pl-secondary));border-color:transparent;color:white;box-shadow:0 12px 24px color-mix(in srgb,var(--pl-primary) 28%,transparent);}}
        div[data-testid="stButton"] > button[kind="primary"]:hover {{background:linear-gradient(120deg,color-mix(in srgb,var(--pl-primary) 88%,white),color-mix(in srgb,var(--pl-secondary) 88%,white));}}
        .stTextInput input,.stTextArea textarea,[data-baseweb="select"] > div {{background:color-mix(in srgb,var(--pl-surface) 90%,transparent)!important;border:1px solid var(--pl-border)!important;border-radius:.78rem!important;color:var(--pl-text)!important;box-shadow:none!important;transition:border-color .2s ease,box-shadow .2s ease;}}
        .stTextInput input:focus,.stTextArea textarea:focus {{border-color:var(--pl-primary)!important;box-shadow:0 0 0 .2rem color-mix(in srgb,var(--pl-primary) 15%,transparent)!important;}}
        .stTextArea textarea {{font-family:'DM Mono','Consolas',monospace;font-size:.84rem;line-height:1.65;}}
        [data-testid="stRadio"] [role="radiogroup"] {{gap:.42rem;}}
        [data-testid="stRadio"] [data-baseweb="radio"] {{background:color-mix(in srgb,var(--pl-card) 88%,transparent);border:1px solid var(--pl-border);border-radius:.66rem;padding:.45rem .62rem;transition:all .2s ease;}}
        [data-testid="stRadio"] [data-baseweb="radio"]:hover {{border-color:color-mix(in srgb,var(--pl-primary) 45%,transparent);background:color-mix(in srgb,var(--pl-primary) 8%,var(--pl-card));}}
        [data-testid="stRadio"] [data-baseweb="radio"]:has(input:checked) {{border-color:color-mix(in srgb,var(--pl-primary) 55%,transparent);background:linear-gradient(100deg,color-mix(in srgb,var(--pl-primary) 16%,transparent),color-mix(in srgb,var(--pl-secondary) 10%,transparent));}}
        [data-testid="stCheckbox"] {{padding:.25rem .15rem;}}
        [data-testid="stCheckbox"] label {{color:var(--pl-text)!important;font-size:.86rem;font-weight:600;}}
        [data-testid="stCheckbox"] [data-checked="true"] {{background-color:var(--pl-primary)!important;border-color:var(--pl-primary)!important;}}
        [data-testid="stMetric"] {{background:var(--pl-card);border:1px solid var(--pl-border);border-radius:.9rem;padding:.95rem;box-shadow:var(--pl-shadow);}}
        [data-testid="stMetricLabel"] {{color:var(--pl-muted)!important;font-size:.68rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;}}
        [data-testid="stMetricValue"] {{font-family:'Space Grotesk',sans-serif;color:var(--pl-text)!important;}}
        .stTabs [data-baseweb="tab-list"] {{gap:.42rem;border-bottom:1px solid var(--pl-border);padding-bottom:.2rem;overflow-x:auto;}}
        .stTabs [data-baseweb="tab"] {{height:auto;background:transparent!important;border-radius:.65rem .65rem 0 0;padding:.6rem .78rem;color:var(--pl-muted)!important;font-size:.8rem;font-weight:800;white-space:nowrap;}}
        .stTabs [aria-selected="true"] {{color:var(--pl-text)!important;background:color-mix(in srgb,var(--pl-primary) 12%,transparent)!important;}}
        .stTabs [data-baseweb="tab-highlight"] {{background:linear-gradient(90deg,var(--pl-primary),var(--pl-accent))!important;height:2px!important;}}
        [data-testid="stExpander"] {{border:1px solid var(--pl-border)!important;border-radius:.8rem!important;background:var(--pl-card)!important;overflow:hidden;}}
        [data-testid="stExpander"] summary {{font-weight:700;color:var(--pl-text)!important;}}
        [data-testid="stProgress"] > div > div {{background:linear-gradient(90deg,var(--pl-primary),var(--pl-accent))!important;border-radius:999px;}}
        [data-testid="stProgress"] > div {{background:color-mix(in srgb,var(--pl-muted) 14%,transparent)!important;border-radius:999px;}}
        [data-testid="stAlert"] {{border:1px solid var(--pl-border);border-radius:.8rem;background:color-mix(in srgb,var(--pl-card) 88%,transparent);}}
        [data-testid="stDataFrame"] {{border:1px solid var(--pl-border);border-radius:.85rem;overflow:hidden;}}
        .pl-scan {{display:flex;align-items:center;gap:.7rem;padding:.8rem 1rem;margin:.6rem 0;border:1px solid color-mix(in srgb,var(--pl-primary) 28%,transparent);border-radius:.75rem;background:color-mix(in srgb,var(--pl-primary) 8%,transparent);font-size:.8rem;font-weight:700;color:var(--pl-text);}}
        .pl-scan-dots {{display:flex;gap:.18rem;}}
        .pl-scan-dots i {{width:.34rem;height:.34rem;background:var(--pl-accent);border-radius:50%;animation:pl-pulse 1.2s infinite ease-in-out;}}
        .pl-scan-dots i:nth-child(2) {{animation-delay:.14s;}} .pl-scan-dots i:nth-child(3) {{animation-delay:.28s;}}
        @keyframes pl-float {{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-7px)}}}}
        @keyframes pl-orbit {{0%,100%{{transform:translateY(0) rotate(0)}}50%{{transform:translateY(-9px) rotate(8deg)}}}}
        @keyframes pl-score-in {{from{{transform:scale(.84);opacity:.2}}to{{transform:scale(1);opacity:1}}}}
        @keyframes pl-bar-in {{from{{width:0}}}}
        @keyframes pl-pulse {{0%,100%{{transform:scale(.65);opacity:.4}}50%{{transform:scale(1);opacity:1}}}}
        @media (max-width:800px) {{.block-container{{padding:1rem 1rem 3rem;}}.pl-hero{{padding:1.7rem;}}.pl-hero:after{{opacity:.45;right:-3rem;}}.pl-bar-row{{grid-template-columns:6rem 1fr 1.7rem;}}.pl-section-heading{{align-items:flex-start;flex-direction:column;gap:.25rem;}}.pl-section-heading p{{text-align:left;}}}}
        </style>""",
        unsafe_allow_html=True,
    )


apply_style()


# -----------------------------------------------------------------------------
# Presentation helpers — data remains rendered through Streamlit, never HTML.
# -----------------------------------------------------------------------------
def render_page_header(kicker: str, title: str, copy: str) -> None:
    st.markdown(
        f"<div class='pl-page-kicker'>{html.escape(kicker)}</div><h1>{html.escape(title)}</h1>"
        f"<div class='pl-page-intro'>{html.escape(copy)}</div>",
        unsafe_allow_html=True,
    )


def render_empty_state(mark: str, title: str, copy: str) -> None:
    st.markdown(
        f"<div class='pl-empty'><div class='pl-empty-mark'>{mark}</div>"
        f"<div class='pl-empty-title'>{html.escape(title)}</div>"
        f"<div class='pl-empty-copy'>{html.escape(copy)}</div></div>",
        unsafe_allow_html=True,
    )


def render_stat_card(label: str, value: str, detail: str = "") -> None:
    st.markdown(
        f"<div class='pl-stat'><div class='pl-stat-label'>{html.escape(label)}</div>"
        f"<div class='pl-stat-value'>{html.escape(str(value))}</div>"
        f"<div class='pl-stat-detail'>{html.escape(detail)}</div></div>",
        unsafe_allow_html=True,
    )


def render_section_heading(title: str, copy: str = "") -> None:
    """Render a compact, reusable visual hierarchy for page sections."""
    st.markdown(
        f"<div class='pl-section-heading'><h2>{html.escape(title)}</h2>"
        f"<p>{html.escape(copy)}</p></div>",
        unsafe_allow_html=True,
    )


def render_character_meter(length: int, limit: int = 18_000) -> None:
    """Give the text workspace a quiet size indicator without restricting input."""
    fill = min(max(length / limit * 100, 0), 100)
    note = f"{length:,} characters" if length <= limit else f"{length:,} characters · AI uses the first {limit:,}"
    st.markdown(
        f"<div class='pl-meter'><div class='pl-meter-track'><div class='pl-meter-fill' style='width:{fill:.1f}%'></div></div>"
        f"<span class='pl-meter-value'>{html.escape(note)}</span></div>",
        unsafe_allow_html=True,
    )


def render_source_preview(domain: str, title: str, url: str) -> None:
    """Show an intentionally simple source identity without loading external assets."""
    mark = html.escape((domain or "PL")[:2].upper())
    st.markdown(
        f"<div class='pl-source-card'><div class='pl-source-mark'>{mark}</div><div style='min-width:0'>"
        f"<div class='pl-source-name'>{html.escape(title or domain)}</div>"
        f"<div class='pl-source-meta'>{html.escape(url)}</div></div></div>",
        unsafe_allow_html=True,
    )


def render_score_ring(score: int, level: str) -> None:
    colors = {"Low": "var(--pl-success)", "Medium": "var(--pl-warning)", "High": "var(--pl-danger)"}
    color = colors.get(level, "var(--pl-primary)")
    st.markdown(
        f"<div class='pl-risk-score'><div class='pl-ring' style='--score:{max(0, min(score, 100))};--risk:{color}'>"
        f"<div class='pl-ring-content'><div class='pl-ring-label'>Privacy score</div>"
        f"<div class='pl-ring-value'>{score}</div><div class='pl-ring-total'>out of 100</div></div></div></div>",
        unsafe_allow_html=True,
    )


def render_scan_feedback(message: str) -> None:
    st.markdown(
        f"<div class='pl-scan'><span class='pl-scan-dots'><i></i><i></i><i></i></span>{html.escape(message)}</div>",
        unsafe_allow_html=True,
    )


def severity_badge(level: str) -> str:
    value = str(level).title()
    css_class = value.lower() if value in {"Low", "Medium", "High"} else "low"
    return f"<span class='pl-badge pl-badge-{css_class}'>{html.escape(value)} risk</span>"


def render_exposure_card(finding: dict, index: int) -> None:
    severity = str(finding.get("severity", "Low")).title()
    color = {"Low": "var(--pl-success)", "Medium": "var(--pl-warning)", "High": "var(--pl-danger)"}.get(severity, "var(--pl-primary)")
    category = html.escape(str(finding.get("category", "Privacy exposure")))
    found = html.escape(str(finding.get("information_found", "No details available.")))
    st.markdown(
        f"<div class='pl-exposure' style='--risk:{color}'><div class='pl-exposure-top'>"
        f"<span class='pl-exposure-category'>{category}</span>{severity_badge(severity)}</div>"
        f"<div class='pl-exposure-copy'>{found}</div></div>",
        unsafe_allow_html=True,
    )
    with st.expander(f"Explore guidance for {finding.get('category', 'this exposure')}", expanded=False):
        st.markdown("**Why it may matter**")
        st.write(finding.get("why_it_matters", "No additional context available."))
        st.markdown("**Suggested action**")
        st.write(finding.get("recommendation", "No action provided."))


def render_bar_chart(title: str, values: dict[str, int]) -> None:
    if not values:
        return
    maximum = max(values.values()) or 1
    rows = "".join(
        f"<div class='pl-bar-row'><span class='pl-bar-label'>{html.escape(label)}</span><div class='pl-bar-track'>"
        f"<div class='pl-bar-fill' style='width:{round(value / maximum * 100)}%'></div></div>"
        f"<span class='pl-bar-value'>{value}</span></div>"
        for label, value in values.items()
    )
    st.markdown(f"<div class='pl-card pl-chart'><div class='pl-chart-title'>{html.escape(title)}</div>{rows}</div>", unsafe_allow_html=True)


def set_chat_prompt(widget_key: str, prompt: str) -> None:
    """Set an example question before Streamlit re-instantiates its input."""
    st.session_state[widget_key] = prompt


def navigate_to(page_name: str) -> None:
    st.session_state["main-navigation"] = page_name


# -----------------------------------------------------------------------------
# Local detection and risk scoring
# -----------------------------------------------------------------------------
def unique_nonempty(matches: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in matches if item.strip()))


def detect_sensitive_patterns(text: str) -> dict[str, list[str]]:
    """Run common privacy checks locally before optional AI context is sent."""
    patterns = {
        "Email Address": re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text),
        "Phone Number": re.findall(r"(?<!\w)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,5}\)?[-.\s]?)?\d{5,10}(?!\w)", text),
        "URL / Public Link": re.findall(r"(?:https?://|www\.)[^\s<]+", text),
        "Possible Username / Handle": re.findall(r"(?<!\w)@[A-Za-z0-9_]{2,}", text),
        "Possible Street Address": re.findall(
            r"\b\d{1,5}\s+(?:[A-Za-z0-9.'-]+\s+){0,4}(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Lane|Ln\.?|Drive|Dr\.?|Boulevard|Blvd\.?)\b",
            text,
            flags=re.IGNORECASE,
        ),
        "Possible Schedule / Date": re.findall(
            r"\b(?:\d{1,2}:\d{2}\s*(?:a\.m\.|p\.m\.|am|pm)?|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)?)\b",
            text,
            flags=re.IGNORECASE,
        ),
    }
    return {name: unique_nonempty(found) for name, found in patterns.items() if found}


LOCAL_CATEGORY_INFO = {
    "Email Address": ("Contact Exposure", "Low", "Consider using a contact form or a dedicated public email address."),
    "Phone Number": ("Contact Exposure", "Medium", "Remove the number or use a controlled business contact channel."),
    "URL / Public Link": ("Public Links & Profiles", "Low", "Check that linked public profiles reveal only what you intend."),
    "Possible Username / Handle": ("Public Links & Profiles", "Low", "Confirm the handle does not connect to more personal accounts than intended."),
    "Possible Street Address": ("Location Exposure", "High", "Generalize the address to a city, region, or meeting area where possible."),
    "Possible Schedule / Date": ("Schedule Exposure", "Medium", "Avoid publishing precise routine times or dates until they are no longer actionable."),
}


def local_exposures(patterns: dict[str, list[str]]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for pattern_name, matches in patterns.items():
        category, severity, recommendation = LOCAL_CATEGORY_INFO[pattern_name]
        entry = grouped.setdefault(
            category,
            {
                "category": category,
                "severity": severity,
                "information_found": [],
                "why_it_matters": "This information can make a public profile easier to contact, locate, or connect across services.",
                "recommendation": recommendation,
            },
        )
        entry["information_found"].append(f"{len(matches)} {pattern_name.lower()} pattern(s) detected locally")
        if severity == "High" or (severity == "Medium" and entry["severity"] == "Low"):
            entry["severity"] = severity
    for entry in grouped.values():
        entry["information_found"] = "; ".join(entry["information_found"])
    return list(grouped.values())


def local_only_result(patterns: dict[str, list[str]], reason: str = "") -> dict:
    exposures = local_exposures(patterns)
    if exposures:
        summary = "Local pattern detection found details worth reviewing before public sharing."
        recommendations = list(dict.fromkeys(item["recommendation"] for item in exposures))
    else:
        summary = "Local pattern detection did not find common contact, link, address, or schedule patterns."
        recommendations = []
    if reason:
        summary = f"{summary} {reason}"
    return {
        "overall_summary": summary,
        "risk_level": "Low",
        "detected_exposures": exposures,
        "positive_observations": [],
        "recommendations": recommendations,
    }


def parse_ai_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw).strip()
    if not raw.startswith("{"):
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            raw = match.group(0)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("AI response was not a JSON object")
    parsed.setdefault("overall_summary", "No summary available.")
    parsed.setdefault("detected_exposures", [])
    parsed.setdefault("positive_observations", [])
    parsed.setdefault("recommendations", [])
    return parsed


def calculate_risk_score(patterns: dict[str, list[str]], ai_result: dict) -> int:
    score = 0
    weights = {
        "Email Address": 15, "Phone Number": 25, "URL / Public Link": 5,
        "Possible Username / Handle": 5, "Possible Street Address": 30,
        "Possible Schedule / Date": 15,
    }
    for category, matches in patterns.items():
        score += weights.get(category, 5) + min(5 * max(len(matches) - 1, 0), 10)
    severity_weights = {"Low": 8, "Medium": 16, "High": 25}
    for exposure in ai_result.get("detected_exposures", []):
        score += severity_weights.get(str(exposure.get("severity", "Low")).title(), 8)
    return min(score, 100)


def score_to_level(score: int) -> str:
    return "Low" if score <= 30 else "Medium" if score <= 60 else "High"


def combine_exposures(ai_result: dict, patterns: dict[str, list[str]]) -> list[dict]:
    findings = [item for item in ai_result.get("detected_exposures", []) if isinstance(item, dict)]
    represented = {str(item.get("category", "")).lower() for item in findings}
    for item in local_exposures(patterns):
        if item["category"].lower() not in represented:
            findings.append(item)
    return findings


def run_analysis(content: str, source_type: str, domain: str = "Manual content", title: str = "") -> dict:
    """Only called by explicit Analyze buttons; never as part of a page preview."""
    patterns = detect_sensitive_patterns(content)
    ai_enabled = st.session_state.analysis_mode == "AI + local context" and MODEL is not None
    ai_status = "Local pattern analysis"
    if ai_enabled:
        try:
            prompt = f"Source type: {source_type}\nDomain: {domain}\n\nCONTENT:\n{content[:18000]}"
            ai_result = parse_ai_json(MODEL.generate_content(ANALYSIS_PROMPT + "\n\n" + prompt).text)
            ai_status = "AI context + local patterns"
        except Exception as exc:
            ai_result = local_only_result(patterns, "AI context could not be completed, so these are local findings only.")
            ai_status = f"Local pattern analysis (AI unavailable: {type(exc).__name__})"
    else:
        reason = "AI context is disabled in Settings." if st.session_state.analysis_mode == "Local patterns only" else "Add a Gemini API key to enable contextual AI analysis."
        ai_result = local_only_result(patterns, reason)
    score = calculate_risk_score(patterns, ai_result)
    source_label = title or (f"{source_type} — {domain}" if domain != "Manual content" else source_type)
    return {
        "id": f"source-{time.time_ns()}", "source_type": source_type,
        "source_label": source_label, "domain": domain, "title": title,
        "content": content, "content_length": len(content), "local_patterns": patterns,
        "ai_result": ai_result, "exposures": combine_exposures(ai_result, patterns),
        "risk_score": score, "risk_level": score_to_level(score), "ai_status": ai_status,
        "analyzed_at": time.strftime("%Y-%m-%d %H:%M"),
    }


def save_result(result: dict) -> None:
    st.session_state.analysis_history.append(result)
    st.session_state.active_result_id = result["id"]
    st.session_state.safer_rewrites[result["id"]] = ""
    st.session_state.chat_history[result["id"]] = []


def get_active_result() -> dict | None:
    for result in reversed(st.session_state.analysis_history):
        if result["id"] == st.session_state.active_result_id:
            return result
    return None


def clear_session_history() -> None:
    st.session_state.analysis_history = []
    st.session_state.active_result_id = None
    st.session_state.safer_rewrites = {}
    st.session_state.chat_history = {}
    st.session_state.web_preview = None


def clear_manual_text() -> None:
    """Widget callback: clear text before Streamlit instantiates the field."""
    st.session_state["manual-text-input"] = ""


def load_sample_text(content: str) -> None:
    """Populate the analyzer with a clearly labelled demo example."""
    st.session_state["manual-text-input"] = content


# -----------------------------------------------------------------------------
# Public webpage retrieval — public HTML only, with no bypass behavior
# -----------------------------------------------------------------------------
class PublicPageError(Exception):
    pass


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_public_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PublicPageError("Enter a complete public URL beginning with http:// or https://.")
    if parsed.username or parsed.password:
        raise PublicPageError("URLs containing login credentials are not supported.")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".local"):
        raise PublicPageError("Local, private, and internal addresses cannot be analyzed.")
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PublicPageError("The website domain could not be resolved. Check the URL and try again.") from exc
    for address in addresses:
        if not ipaddress.ip_address(address[4][0]).is_global:
            raise PublicPageError("Local, private, and internal addresses cannot be analyzed.")
    return parsed


class VisibleTextExtractor(HTMLParser):
    """Dependency-free visible-text extractor that removes common page chrome."""
    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe", "form", "template", "nav", "footer", "aside"}
    BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "tr"}
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    BOILERPLATE_HINTS = {"nav", "menu", "footer", "header", "sidebar", "cookie", "banner", "modal", "advert", "social-share"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.hidden_stack: list[bool] = []
        self.in_title = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_text = " ".join(value or "" for _, value in attrs).lower()
        hidden = any(self.hidden_stack) or tag in self.SKIP_TAGS or "aria-hidden=true" in attr_text or any(item in attr_text for item in self.BOILERPLATE_HINTS)
        if tag in self.VOID_TAGS:
            if not hidden and tag == "br":
                self.parts.append("\n")
            return
        self.hidden_stack.append(hidden)
        if tag == "title":
            self.in_title += 1
        if not hidden and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title" and self.in_title:
            self.in_title -= 1
        if self.hidden_stack:
            self.hidden_stack.pop()
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
            return
        if not any(self.hidden_stack):
            self.parts.append(data)

    def text(self) -> str:
        seen, lines = set(), []
        for line in "".join(self.parts).splitlines():
            clean = re.sub(r"\s+", " ", html.unescape(line)).strip()
            if clean and clean not in seen:
                seen.add(clean)
                lines.append(clean)
        return "\n".join(lines)

    def title(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.title_parts)).strip()


@st.cache_data(ttl=600, show_spinner=False)
def fetch_public_page(url: str) -> dict:
    """Fetch public HTML once per cache period; never send it to AI automatically."""
    current_url = url.strip()
    opener = urllib.request.build_opener(NoRedirectHandler())
    max_bytes = 2_000_000
    for _ in range(4):
        validate_public_url(current_url)
        request = urllib.request.Request(
            current_url,
            headers={"User-Agent": "PrivacyLensAI/1.0 (public content privacy review)", "Accept": "text/html,application/xhtml+xml"},
        )
        try:
            response = opener.open(request, timeout=12)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400 and exc.headers.get("Location"):
                current_url = urllib.parse.urljoin(current_url, exc.headers["Location"])
                continue
            if exc.code in {401, 403}:
                raise PublicPageError("This page is restricted or login-protected, so PrivacyLens did not access it.") from exc
            if exc.code in {429, 451}:
                raise PublicPageError("This website cannot be accessed right now. PrivacyLens will not bypass its restrictions.") from exc
            raise PublicPageError(f"The website returned HTTP {exc.code}. Try another public page.") from exc
        except urllib.error.URLError as exc:
            raise PublicPageError(f"The public page could not be reached ({getattr(exc, 'reason', 'network error')}).") from exc
        except TimeoutError as exc:
            raise PublicPageError("The public page timed out. Please try again later.") from exc
        if response.headers.get_content_type().lower() not in {"text/html", "application/xhtml+xml"}:
            raise PublicPageError("This URL is not an HTML webpage with readable public content.")
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise PublicPageError("This page is too large to review safely. Try a shorter public page.")
        document = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        extractor = VisibleTextExtractor()
        extractor.feed(document)
        text = extractor.text().strip()
        if len(text) < 20:
            raise PublicPageError("No meaningful visible text could be extracted from this public page.")
        parsed = urllib.parse.urlparse(current_url)
        return {
            "url": current_url, "domain": parsed.netloc,
            "title": extractor.title() or parsed.netloc, "text": text[:30000],
            "extracted_characters": len(text), "status": "Public page accessed successfully",
        }
    raise PublicPageError("Too many redirects. PrivacyLens did not continue to the final page.")


# -----------------------------------------------------------------------------
# Results helpers
# -----------------------------------------------------------------------------
def mask_value(value: str, category: str) -> str:
    if not st.session_state.mask_detected_values:
        return value
    if category == "Email Address" and "@" in value:
        user, host = value.split("@", 1)
        return f"{user[:1]}•••@{host}"
    if category == "URL / Public Link":
        parsed = urllib.parse.urlparse(value if "://" in value else f"https://{value}")
        return f"{parsed.netloc}/•••" if parsed.netloc else "•••"
    if category == "Possible Username / Handle":
        return f"{value[:2]}•••"
    if category in {"Phone Number", "Possible Street Address"}:
        return "••• masked •••"
    return value


def category_breakdown(results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        for finding in result.get("exposures", []):
            category = str(finding.get("category", "Identity Exposure"))
            counts[category] = counts.get(category, 0) + 1
    return counts


def generate_safer_rewrite(result: dict, privacy_level: str = "Balanced") -> str:
    if MODEL is None:
        raise RuntimeError("Add GOOGLE_API_KEY to Streamlit secrets to enable AI rewrites.")
    intensity = {
        "Minimal changes": "Keep wording close to the original; remove only clearly unnecessary sensitive details.",
        "Balanced": "Balance natural tone and meaning with sensible removal or generalization of unnecessary personal detail.",
        "Maximum privacy": "Strongly generalize nonessential identifying, location, schedule, and contact detail while retaining the core message.",
    }.get(privacy_level, "Balance natural tone and meaning with sensible privacy improvements.")
    return MODEL.generate_content(REWRITE_PROMPT + f"\n\nREWRITE INTENSITY: {intensity}\n\nCONTENT:\n" + result["content"][:18000]).text.strip()


def ask_privacy_question(result: dict, question: str) -> str:
    if MODEL is None:
        raise RuntimeError("Add GOOGLE_API_KEY to Streamlit secrets to use Ask PrivacyLens AI.")
    context = {
        "source_type": result["source_type"], "domain": result["domain"],
        "risk_score": result["risk_score"], "risk_level": result["risk_level"],
        "exposures": result["exposures"],
    }
    prompt = f"""You are PrivacyLens AI. Answer only about the user-supplied content and analysis below. Be clear and educational. Do not search for or identify anyone.

ANALYSIS: {json.dumps(context, indent=2)}
CONTENT: {result['content'][:8000]}
QUESTION: {question}"""
    return MODEL.generate_content(prompt).text.strip()


def build_download_text(result: dict) -> str:
    bar = "-" * 58
    ai = result["ai_result"]
    parts = [
        "PRIVACYLENS AI — DIGITAL PRIVACY REPORT", bar,
        f"SOURCE: {result['source_label']}", f"SOURCE TYPE: {result['source_type']}",
        f"DOMAIN: {result['domain']}", f"ANALYZED: {result['analyzed_at']}",
        f"PRIVACY RISK SCORE: {result['risk_score']}/100 ({result['risk_level']})",
        f"ANALYSIS MODE: {result['ai_status']}", "", "SUMMARY", bar,
        ai.get("overall_summary", "No summary available."), "", "LOCALLY DETECTED PATTERN COUNTS", bar,
    ]
    patterns = result.get("local_patterns", {})
    parts.extend([f"- {name}: {len(values)}" for name, values in patterns.items()] or ["None detected."])
    parts.extend(["", "POTENTIAL EXPOSURES", bar])
    if result["exposures"]:
        for number, finding in enumerate(result["exposures"], start=1):
            parts.extend([
                f"{number}. {finding.get('category', 'Unknown')} ({finding.get('severity', 'Low')})",
                f"   Found: {finding.get('information_found', '')}",
                f"   Why it matters: {finding.get('why_it_matters', '')}",
                f"   Suggested action: {finding.get('recommendation', '')}",
            ])
    else:
        parts.append("No meaningful exposures were identified.")
    parts.extend(["", "PRIVACY NOTE", bar, "This session-only educational report analyzes content voluntarily supplied to PrivacyLens AI. It does not search for people, build profiles, or access private content."])
    return "\n".join(parts)


def render_result_dashboard_legacy(result: dict) -> None:
    """Reusable dashboard retaining the original analysis, rewrite, Q&A, and report."""
    ai, exposures, score = result["ai_result"], result["exposures"], result["risk_score"]
    st.divider()
    st.subheader("Privacy analysis results")
    st.caption(f"{result['source_label']} · {result['analyzed_at']} · {result['ai_status']}")
    overview, detected, risk_tab, recommendations, rewrite_tab, ask_tab = st.tabs(
        ["📊 Overview", "🔍 Detected exposure", "⚠️ Risk analysis", "🛡️ Recommendations", "✨ Safer rewrite", "💬 Ask PrivacyLens AI"]
    )
    with overview:
        st.subheader("Public content summary")
        one, two, three, four = st.columns(4)
        one.metric("Privacy risk score", f"{score}/100")
        two.metric("Risk level", result["risk_level"])
        three.metric("Potential exposures", len(exposures))
        four.metric("Content reviewed", f"{result['content_length']:,} chars")
        st.progress(score / 100)
        one, two, three = st.columns(3)
        one.write(f"**Type:** {result['source_type']}")
        two.write(f"**Domain:** {result['domain']}")
        three.write(f"**Source:** {result['source_label']}")
        st.markdown("#### PrivacyLens summary")
        with st.container(border=True):
            st.write(ai.get("overall_summary", "No summary available."))
        if ai.get("positive_observations"):
            st.markdown("#### Good privacy practices detected")
            for item in ai["positive_observations"]:
                st.success(item)
        breakdown = category_breakdown([result])
        if breakdown:
            st.markdown("#### Exposure categories")
            columns = st.columns(min(len(breakdown), 3))
            for index, (category, count) in enumerate(breakdown.items()):
                columns[index % len(columns)].metric(category, count)
    with detected:
        st.subheader("Information detected in this source")
        st.caption("Pattern values are masked by default and stay in this browser session only.")
        patterns = result["local_patterns"]
        if patterns:
            st.markdown("#### Local pattern detection")
            for category, matches in patterns.items():
                with st.expander(f"{category} ({len(matches)} found)"):
                    for match in matches:
                        st.code(mask_value(match, category))
        else:
            st.info("No common contact, link, address, or schedule patterns were detected locally.")
        st.markdown("#### Contextual privacy exposure")
        if exposures:
            for finding in exposures:
                with st.container(border=True):
                    st.markdown(f"**{finding.get('category', 'Unknown')}**")
                    st.caption(f"Severity: {finding.get('severity', 'Low')}")
                    st.write(finding.get("information_found", ""))
        else:
            st.success("No major contextual privacy exposure was identified in this content.")
    with risk_tab:
        st.subheader("Why these details may matter")
        if exposures:
            for finding in exposures:
                with st.expander(f"{finding.get('category', 'Unknown')} — {finding.get('severity', 'Low')} risk", expanded=True):
                    st.markdown("**Why it may matter**")
                    st.write(finding.get("why_it_matters", ""))
                    st.markdown("**Suggested action**")
                    st.write(finding.get("recommendation", ""))
        else:
            st.success("No significant contextual privacy risks were identified.")
    with recommendations:
        st.subheader("Privacy recommendations")
        if ai.get("recommendations"):
            for number, item in enumerate(ai["recommendations"], start=1):
                with st.container(border=True):
                    st.write(f"**{number}. {item}**")
        else:
            st.info("No source-specific recommendations were generated.")
        st.markdown("#### Quick privacy checklist")
        for item in [
            "Avoid posting passwords, IDs, or account credentials.",
            "Share only the location precision the context needs.",
            "Avoid publishing future travel and predictable routines.",
            "Review linked public profiles before sharing them.",
        ]:
            st.checkbox(item, key=f"check-{result['id']}-{item}")
    with rewrite_tab:
        st.subheader("Generate a more privacy-conscious version")
        st.write("The rewrite is generated only after you request it and preserves the main message while reducing unnecessary personal detail.")
        if st.button("✨ Generate safer version", key=f"rewrite-{result['id']}", type="primary"):
            with st.spinner("Creating a safer version…"):
                try:
                    st.session_state.safer_rewrites[result["id"]] = generate_safer_rewrite(result)
                except Exception as exc:
                    st.error(f"Could not generate a rewrite: {exc}")
        rewrite = st.session_state.safer_rewrites.get(result["id"], "")
        if rewrite:
            left, right = st.columns(2)
            with left:
                st.markdown("**Original**")
                st.text_area("Original content", result["content"], height=220, disabled=True, key=f"original-{result['id']}")
            with right:
                st.markdown("**Privacy-conscious rewrite**")
                st.text_area("Safer version", rewrite, height=220, key=f"safer-{result['id']}")
            st.download_button("⬇️ Download safer rewrite (.txt)", rewrite, "privacy_conscious_rewrite.txt", "text/plain", key=f"download-rewrite-{result['id']}")
    with ask_tab:
        st.subheader("Ask PrivacyLens AI")
        st.write("Ask a follow-up question about this analysis. Answers remain limited to the content you supplied.")
        question = st.text_area("Your question", height=100, key=f"question-{result['id']}")
        if st.button("💬 Ask PrivacyLens AI", key=f"ask-{result['id']}", type="primary"):
            if not question.strip():
                st.warning("Type a question first.")
            else:
                with st.spinner("PrivacyLens AI is thinking…"):
                    try:
                        answer = ask_privacy_question(result, question.strip())
                        st.session_state.chat_history[result["id"]].append({"question": question.strip(), "answer": answer})
                    except Exception as exc:
                        st.error(f"Could not answer that question: {exc}")
        for item in reversed(st.session_state.chat_history.get(result["id"], [])):
            with st.container(border=True):
                st.markdown(f"**You:** {item['question']}")
                st.markdown(f"**PrivacyLens AI:** {item['answer']}")
    st.download_button(
        "⬇️ Download privacy analysis report (.txt)", build_download_text(result),
        "digital_footprint_privacy_report.txt", "text/plain", use_container_width=True,
        key=f"download-report-{result['id']}",
    )


def render_result_dashboard(result: dict) -> None:
    """Render analysis findings in the premium PrivacyLens intelligence workspace."""
    ai, exposures, score = result["ai_result"], result["exposures"], result["risk_score"]
    render_page_header(
        "Analysis complete",
        "Your privacy intelligence report",
        f"{result['source_label']} · analyzed {result['analyzed_at']} · {result['ai_status']}",
    )

    score_column, insight_column = st.columns([1.05, 2.15], gap="large")
    with score_column:
        render_score_ring(score, result["risk_level"])
        st.markdown(f"<div style='text-align:center;margin-top:-.8rem'>{severity_badge(result['risk_level'])}</div>", unsafe_allow_html=True)
    with insight_column:
        a, b, c = st.columns(3)
        with a:
            render_stat_card("Risk level", result["risk_level"], "Current content exposure")
        with b:
            render_stat_card("Potential exposures", str(len(exposures)), "Areas worth reviewing")
        with c:
            render_stat_card("Analysis mode", "AI + local" if result["ai_status"].startswith("AI") else "Local scan", result["ai_status"])
        st.markdown(
            f"<div class='pl-card' style='margin-top:1rem'><div class='pl-stat-label'>PrivacyLens summary</div>"
            f"<div style='font-size:1rem;line-height:1.72;margin-top:.55rem'>{html.escape(str(ai.get('overall_summary', 'No summary available.')))}</div>"
            f"<div class='pl-action-meta' style='margin-top:.75rem'>{result['content_length']:,} characters reviewed · {html.escape(result['source_type'])}</div></div>",
            unsafe_allow_html=True,
        )

    overview, detected, risk_tab, recommendations, rewrite_tab, ask_tab = st.tabs(
        ["Overview", "Detected exposure", "Risk guidance", "Action plan", "Safer rewrite", "Ask PrivacyLens"]
    )
    with overview:
        summary_col, chart_col = st.columns([1.1, 1], gap="large")
        with summary_col:
            render_section_heading("At a glance", "A compact view of this source and its analysis boundary.")
            st.markdown(
                "<div class='pl-card'><div class='pl-stat-label'>Source context</div>"
                f"<div style='margin-top:.75rem;line-height:1.9'><b>Type:</b> {html.escape(result['source_type'])}<br>"
                f"<b>Domain:</b> {html.escape(result['domain'])}<br><b>Analysis:</b> {html.escape(result['ai_status'])}</div></div>",
                unsafe_allow_html=True,
            )
            if ai.get("positive_observations"):
                st.markdown("### Already doing well")
                for item in ai["positive_observations"]:
                    st.success(item)
        with chart_col:
            breakdown = category_breakdown([result])
            if breakdown:
                render_bar_chart("Exposure breakdown", breakdown)
            else:
                render_empty_state("⌁", "No category signals yet", "The analysis did not identify a privacy exposure category in this source.")

    with detected:
        render_section_heading("Detected information", "Review what was found before deciding what to change.")
        st.caption("Detected values are masked by default and stay in this browser session only.")
        local_col, contextual_col = st.columns([.95, 1.35], gap="large")
        with local_col:
            st.markdown("#### Local pattern scan")
            patterns = result["local_patterns"]
            if patterns:
                for category, matches in patterns.items():
                    with st.expander(f"{category} · {len(matches)} found"):
                        for match in matches:
                            st.code(mask_value(match, category), language=None)
            else:
                render_empty_state("◌", "Nothing common found", "No common contact, link, address, or schedule patterns were detected locally.")
        with contextual_col:
            st.markdown("#### Contextual exposure")
            if exposures:
                for index, finding in enumerate(exposures, start=1):
                    render_exposure_card(finding, index)
            else:
                render_empty_state("✓", "Looking good", "No major contextual privacy exposure was identified in this content.")

    with risk_tab:
        render_section_heading("What to consider", "Each signal is explained with proportionate, practical guidance.")
        if exposures:
            for index, finding in enumerate(exposures, start=1):
                render_exposure_card(finding, index)
        else:
            render_empty_state("✦", "No elevated risks detected", "This source did not produce significant contextual privacy risks to investigate.")

    with recommendations:
        render_section_heading("Privacy action plan", "Track small privacy improvements for this source in the current session.")
        source_recommendations = ai.get("recommendations", [])
        if source_recommendations:
            complete_count = 0
            for number, item in enumerate(source_recommendations, start=1):
                item_key = f"recommendation-{result['id']}-{number}"
                st.markdown(
                    f"<div class='pl-action-card'><div class='pl-stat-label'>Recommended action {number:02d}</div>"
                    f"<div style='margin-top:.38rem;font-weight:700;line-height:1.55'>{html.escape(str(item))}</div></div>",
                    unsafe_allow_html=True,
                )
                if st.checkbox("Mark complete", key=item_key):
                    complete_count += 1
            st.progress(complete_count / len(source_recommendations))
            st.caption(f"{complete_count} of {len(source_recommendations)} recommended actions completed in this session.")
        else:
            render_empty_state("✓", "No tailored actions needed", "No source-specific recommendations were generated from the current findings.")
        render_section_heading("Everyday privacy checklist", "Helpful habits that apply even when this source is low risk.")
        for item in [
            "Avoid posting passwords, IDs, or account credentials.",
            "Share only the location precision the context needs.",
            "Avoid publishing future travel and predictable routines.",
            "Review linked public profiles before sharing them.",
        ]:
            st.checkbox(item, key=f"check-{result['id']}-{item}")

    with rewrite_tab:
        render_section_heading("Privacy-conscious rewrite", "Keep the message while generalizing detail you do not need to publish.")
        st.caption("Choose a level of privacy protection, then request a rewrite. The original text is sent to Gemini only when you choose Generate.")
        rewrite_level = st.radio(
            "Rewrite style",
            ["Minimal changes", "Balanced", "Maximum privacy"],
            horizontal=True,
            key=f"rewrite-style-{result['id']}",
            label_visibility="collapsed",
        )
        if st.button("Generate safer version", key=f"rewrite-{result['id']}", type="primary", use_container_width=True):
            render_scan_feedback("Understanding context and reducing unnecessary exposure…")
            with st.spinner("Creating your privacy-conscious version…"):
                try:
                    st.session_state.safer_rewrites[result["id"]] = generate_safer_rewrite(result, rewrite_level)
                except Exception as exc:
                    st.error(f"Could not generate a rewrite: {exc}")
        rewrite = st.session_state.safer_rewrites.get(result["id"], "")
        if rewrite:
            left, right = st.columns(2, gap="large")
            with left:
                st.markdown("#### Original content")
                st.text_area("Original content", result["content"], height=250, disabled=True, key=f"original-{result['id']}", label_visibility="collapsed")
            with right:
                st.markdown("#### Privacy-conscious version")
                st.text_area("Safer version", rewrite, height=250, key=f"safer-{result['id']}", label_visibility="collapsed")
            st.caption("Use the copy control on the rewrite below, or download a text file for your records.")
            st.code(rewrite, language=None)
            st.download_button("Download safer rewrite (.txt)", rewrite, "privacy_conscious_rewrite.txt", "text/plain", key=f"download-rewrite-{result['id']}")
        else:
            render_empty_state("⌁", "Your safer version will appear here", "Select a rewrite style to preserve the right balance of voice and privacy.")

    with ask_tab:
        render_section_heading("Ask PrivacyLens AI", "Explore the findings without expanding beyond the content in this session.")
        st.caption("Answers stay limited to the content and findings in this session.")
        question_key = f"question-{result['id']}"
        example_left, example_middle, example_right = st.columns(3)
        examples = [
            "What creates the biggest privacy risk?",
            "How can I reduce my exposure?",
            "Explain this in simpler language.",
        ]
        for column, prompt in zip([example_left, example_middle, example_right], examples):
            with column:
                st.button(prompt, key=f"prompt-{result['id']}-{prompt}", on_click=set_chat_prompt, args=(question_key, prompt), use_container_width=True)
        question = st.text_area("Your question", height=105, key=question_key, placeholder="Ask about a finding, score, or recommended next step.")
        if st.button("Ask PrivacyLens AI", key=f"ask-{result['id']}", type="primary"):
            if not question.strip():
                st.warning("Type a question first.")
            else:
                render_scan_feedback("Reviewing the analysis with your question in mind…")
                with st.spinner("PrivacyLens AI is thinking…"):
                    try:
                        answer = ask_privacy_question(result, question.strip())
                        st.session_state.chat_history[result["id"]].append({"question": question.strip(), "answer": answer})
                    except Exception as exc:
                        st.error(f"Could not answer that question: {exc}")
        for item in st.session_state.chat_history.get(result["id"], []):
            with st.chat_message("user"):
                st.write(item["question"])
            with st.chat_message("assistant", avatar="🛡️"):
                st.write(item["answer"])

    st.download_button(
        "Download privacy analysis report (.txt)",
        build_download_text(result),
        "digital_footprint_privacy_report.txt",
        "text/plain",
        use_container_width=True,
        key=f"download-report-{result['id']}",
    )


# -----------------------------------------------------------------------------
# Sidebar navigation
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        "<div class='pl-brand'><div class='pl-logo'></div><div><div class='pl-brand-name'>PrivacyLens AI</div>"
        "<div class='pl-brand-tag'>Privacy intelligence</div></div></div>"
        "<div class='pl-version'>AI PRIVACY INTELLIGENCE · v2.0</div>",
        unsafe_allow_html=True,
    )
    st.caption("Your private workspace for reviewing content you intentionally share.")
    page = st.radio(
        "Main navigation",
        ["🏠 Home", "📝 Text Analyzer", "🌐 Public Footprint", "📊 Privacy Snapshot", "🧹 Cleanup Plan", "⚙️ Settings", "ℹ️ How It Works"],
        key="main-navigation",
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown("<div class='pl-stat-label'>Privacy boundary</div>", unsafe_allow_html=True)
    st.caption("Analyze only content you own or may review. PrivacyLens never searches for people, accesses private accounts, or builds hidden profiles.")
    st.markdown(f"<div class='pl-version'>SESSION SOURCES · {len(st.session_state.analysis_history)}</div>", unsafe_allow_html=True)
    if st.session_state.analysis_history and st.button("🧹 Clear session history", use_container_width=True):
        clear_session_history()
        st.rerun()


# -----------------------------------------------------------------------------
# Pages
# -----------------------------------------------------------------------------
if page == "🏠 Home":
    st.markdown(
        "<section class='pl-hero'><div class='pl-hero-copy'><div class='pl-eyebrow'>Private by design</div>"
        "<h1>See what your public content reveals—before the internet does.</h1>"
        "<p>PrivacyLens AI turns content you intentionally provide into practical, proportionate privacy guidance."
        " No people-searching. No hidden profiles. Just clarity, on your terms.</p></div></section>",
        unsafe_allow_html=True,
    )
    primary_action, secondary_action, spacer = st.columns([1.15, 1.25, 2.6])
    with primary_action:
        st.button("Analyze my content", type="primary", use_container_width=True, on_click=navigate_to, args=("📝 Text Analyzer",))
    with secondary_action:
        st.button("Review public content", use_container_width=True, on_click=navigate_to, args=("🌐 Public Footprint",))
    st.markdown("<div style='height:.9rem'></div>", unsafe_allow_html=True)
    one, two, three = st.columns(3, gap="large")
    with one:
        st.markdown("<div class='pl-card'><div class='pl-card-icon'>⌁</div><div class='pl-card-title'>Analyze content</div><div class='pl-card-copy'>Check posts, bios, portfolio copy, and messages before you share them publicly.</div></div>", unsafe_allow_html=True)
    with two:
        st.markdown("<div class='pl-card'><div class='pl-card-icon'>◉</div><div class='pl-card-title'>Review a public page</div><div class='pl-card-copy'>Preview a single public webpage or paste profile content before you choose to analyze it.</div></div>", unsafe_allow_html=True)
    with three:
        st.markdown("<div class='pl-card'><div class='pl-card-icon'>✦</div><div class='pl-card-title'>Act on real findings</div><div class='pl-card-copy'>Compare session-only sources and build a focused cleanup plan grounded in evidence.</div></div>", unsafe_allow_html=True)
    st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)
    st.markdown("### A calm, deliberate workflow")
    workflow_a, workflow_b, workflow_c, workflow_d = st.columns(4)
    for column, number, heading, copy in [
        (workflow_a, "01", "Provide", "Paste content or request a public-page preview."),
        (workflow_b, "02", "Review", "Confirm what will be analyzed before AI context is used."),
        (workflow_c, "03", "Understand", "See patterns, score, and proportionate risk guidance."),
        (workflow_d, "04", "Improve", "Use practical actions or a safer rewrite when useful."),
    ]:
        with column:
            st.markdown(f"<div class='pl-stat'><div class='pl-stat-label'>{number}</div><div class='pl-card-title' style='margin-top:.6rem'>{heading}</div><div class='pl-card-copy'>{copy}</div></div>", unsafe_allow_html=True)
    st.info("PrivacyLens analyzes only content you own or have permission to review. It does not search for people, bypass sign-ins, or access private content.")

elif page == "📝 Text Analyzer":
    render_page_header(
        "Content workspace",
        "Understand your content before you share it",
        "Paste a draft, bio, portfolio section, or message. Local checks run first; AI context starts only after you choose Analyze.",
    )
    workspace, preview_panel = st.columns([1.35, .9], gap="large")
    with workspace:
        st.markdown("### Your content")
        st.caption("Start from a sample or paste content you own or are authorized to review.")
        samples = [
            ("High exposure", "Contains contact detail, a specific address, and a future plan.", "Reach me at dev@example.com or +1 555 014 2869. I will be away next Tuesday at 8:30am, but you can drop the documents at 42 Cedar Street."),
            ("Moderate exposure", "Contains a public handle and a predictable schedule.", "I share design ideas at @northstudiolab and host a live session every Friday at 7pm."),
            ("Low exposure", "A public update with minimal personal detail.", "I am excited to share that I am working on a new creative project. More details coming soon."),
        ]
        sample_columns = st.columns(3)
        for column, (name, copy, content) in zip(sample_columns, samples):
            with column:
                tone = "High" if name.startswith("High") else "Medium" if name.startswith("Moderate") else "Low"
                st.markdown(f"<div class='pl-card' style='padding:.9rem'><div class='pl-card-title'>{html.escape(name)}</div><div class='pl-card-copy'>{html.escape(copy)}</div><div style='margin-top:.65rem'>{severity_badge(tone)}</div></div>", unsafe_allow_html=True)
                st.button("Use sample", key=f"sample-{name}", on_click=load_sample_text, args=(content,), use_container_width=True)
        text = st.text_area(
            "Paste text to analyze", height=310, key="manual-text-input",
            placeholder="Example: I will be away next week. Email me at hello@example.com for updates.",
        )
        text_length = len(text)
        render_character_meter(text_length)
        st.caption("Content stays in this browser session unless you download a report.")
        st.radio(
            "Analysis depth",
            ["AI + local context", "Local patterns only"],
            key="analysis_mode",
            horizontal=True,
            help="AI context uses Gemini only after you select Analyze. Local pattern checks always run in this browser session.",
        )
        analyze_col, clear_col = st.columns([3, 1])
        with analyze_col:
            analyze_clicked = st.button("Analyze privacy risk", type="primary", use_container_width=True)
        with clear_col:
            st.button("Clear", use_container_width=True, on_click=clear_manual_text)
    with preview_panel:
        st.markdown("### Privacy analysis preview")
        current_result = get_active_result()
        if current_result and current_result["source_type"] == "Pasted text":
            render_score_ring(current_result["risk_score"], current_result["risk_level"])
            st.markdown(f"<div style='text-align:center'>{severity_badge(current_result['risk_level'])}</div><div class='pl-empty-copy'>The latest analysis is ready below with exposures and practical next steps.</div>", unsafe_allow_html=True)
        else:
            render_empty_state("⌁", "Ready when you are", "Paste content to see what it may reveal. Your privacy insights will appear here after analysis.")
    if analyze_clicked:
        if not text.strip():
            st.warning("Paste some text before starting the analysis.")
        else:
            render_scan_feedback("Detecting exposed information, understanding context, and scoring privacy risk…")
            with st.spinner("PrivacyLens is analyzing the text…"):
                save_result(run_analysis(text.strip(), "Pasted text"))
            st.success("Analysis complete. It has been added to this session's privacy snapshot.")
    result = get_active_result()
    if result and result["source_type"] == "Pasted text":
        render_result_dashboard(result)

elif page == "🌐 Public Footprint":
    render_page_header(
        "Public footprint",
        "Review public content deliberately",
        "Preview an accessible public page or paste a public profile you own or may review. You always confirm before analysis begins.",
    )
    st.info("Analyze only public content you own or have permission to analyze. PrivacyLens will not search for people, access private accounts, bypass logins, CAPTCHAs, paywalls, or website security controls.")
    webpage_tab, profile_tab = st.tabs(["Public webpage", "Public profile content"])
    with webpage_tab:
        st.markdown("### 01 · Enter a public URL")
        st.caption("PrivacyLens only retrieves normally accessible HTML and blocks internal, local, credentialed, and restricted destinations.")
        url = st.text_input("Public webpage URL", placeholder="https://example.com/about", key="public-url-input")
        preview_col, clear_col = st.columns([3, 1])
        with preview_col:
            preview_clicked = st.button("Retrieve public content preview", type="primary", use_container_width=True)
        with clear_col:
            clear_preview_clicked = st.button("Clear preview", use_container_width=True)
        if clear_preview_clicked:
            st.session_state.web_preview = None
            st.rerun()
        if preview_clicked:
            if not url.strip():
                st.warning("Enter a public webpage URL first.")
            else:
                render_scan_feedback("Checking a public page and extracting only readable visible text…")
                with st.spinner("Retrieving public page content…"):
                    try:
                        st.session_state.web_preview = fetch_public_page(url.strip())
                    except PublicPageError as exc:
                        st.session_state.web_preview = None
                        st.error(str(exc))
                    except Exception:
                        st.session_state.web_preview = None
                        st.error("The public page could not be processed safely. Check the URL and try again.")
        preview = st.session_state.web_preview
        if preview:
            st.markdown("### 02 · Review the extracted content")
            st.caption(f"Previewed URL: {preview['url']}")
            render_source_preview(preview["domain"], preview["title"], preview["url"])
            one, two, three, four = st.columns(4)
            with one:
                render_stat_card("Access", "Ready", "Public content retrieved")
            with two:
                render_stat_card("Domain", preview["domain"], "Requested destination")
            title = preview["title"]
            with three:
                render_stat_card("Page title", title[:25] + ("…" if len(title) > 25 else ""), "Extracted from visible HTML")
            with four:
                render_stat_card("Text extracted", f"{preview['extracted_characters']:,}", "Characters available")
            st.caption("This extracted text is held temporarily in the browser session. Review it below; no Gemini request has been made yet.")
            st.text_area("Text that will be analyzed", preview["text"], height=300, disabled=True, key=f"web-preview-{hash(preview['url'])}")
            if preview["extracted_characters"] > len(preview["text"]):
                st.caption("For performance, the review is limited to the first 30,000 extracted characters. AI analysis uses up to 18,000 characters.")
            if url.strip() != preview["url"]:
                st.warning("The URL field has changed. Retrieve a fresh preview before analyzing it.")
            elif st.button("03 · Analyze this public content", type="primary", use_container_width=True):
                render_scan_feedback("Analyzing the public content you explicitly approved…")
                with st.spinner("Analyzing the public content you approved…"):
                    save_result(run_analysis(preview["text"], "Public webpage", preview["domain"], preview["title"]))
                st.success("Public content analysis complete and added to this session's snapshot.")
    with profile_tab:
        st.markdown("### Review a public profile")
        st.caption("Paste public content you own or have permission to analyze, such as a social bio, portfolio About section, creator bio, or public profile description.")
        profile_content = st.text_area(
            "Paste public content you own or have permission to analyze", height=260,
            placeholder="Paste a public bio, portfolio section, or profile description here…",
            key="profile-content-input",
        )
        if st.button("🔍 Analyze public profile content", type="primary"):
            if not profile_content.strip():
                st.warning("Paste public content before starting the analysis.")
            else:
                render_scan_feedback("Detecting common exposure patterns and reviewing context…")
                with st.spinner("Analyzing the public profile content…"):
                    save_result(run_analysis(profile_content.strip(), "Public profile content"))
                st.success("Profile analysis complete and added to this session's snapshot.")
    result = get_active_result()
    if result and result["source_type"] in {"Public webpage", "Public profile content"}:
        render_result_dashboard(result)

elif page == "📊 Privacy Snapshot":
    render_page_header(
        "Session intelligence",
        "Your public privacy snapshot",
        "Compare only the sources analyzed in this browser session. Nothing is permanently stored by default.",
    )
    history = st.session_state.analysis_history
    if not history:
        render_empty_state("◌", "No sources analyzed yet", "Run an analysis on text, a public webpage, or profile content to build your session-only privacy snapshot.")
    else:
        breakdown = category_breakdown(history)
        average = round(sum(item["risk_score"] for item in history) / len(history))
        highest_category = max(breakdown, key=breakdown.get) if breakdown else "No exposure category detected"
        highest_score = max(item["risk_score"] for item in history)
        one, two, three, four = st.columns(4)
        with one:
            render_stat_card("Sources analyzed", str(len(history)), "Current browser session")
        with two:
            render_stat_card("Average risk", f"{average}/100", "Across all sources")
        with three:
            render_stat_card("Highest risk", f"{highest_score}/100", "Highest source score")
        with four:
            render_stat_card("Top category", highest_category, "Most frequent exposure")
        st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
        chart_col, categories_col = st.columns(2, gap="large")
        with chart_col:
            render_bar_chart("Source risk comparison", {item["source_label"]: item["risk_score"] for item in history})
        with categories_col:
            if breakdown:
                render_bar_chart("Exposure overview", breakdown)
            else:
                render_empty_state("✓", "No exposure categories", "The sources in this session did not generate any privacy exposure categories.")
        st.markdown("### Source comparison")
        comparison = [{
            "Source": item["source_label"], "Type": item["source_type"], "Domain": item["domain"],
            "Risk score": item["risk_score"], "Risk level": item["risk_level"],
            "Main exposure": item["exposures"][0].get("category", "None detected") if item["exposures"] else "None detected",
        } for item in history]
        st.dataframe(comparison, hide_index=True, use_container_width=True)
        st.markdown("### Analysis timeline")
        st.caption("Newest analysis first · all activity is session-only.")
        for item in reversed(history):
            st.markdown(
                f"<div class='pl-action-card'><div class='pl-exposure-top'><div class='pl-exposure-category'>{html.escape(item['source_label'])}</div>"
                f"{severity_badge(item['risk_level'])}</div><div class='pl-action-meta'>{html.escape(item['analyzed_at'])} · "
                f"{html.escape(item['source_type'])} · {item['risk_score']}/100</div></div>",
                unsafe_allow_html=True,
            )

elif page == "🧹 Cleanup Plan":
    render_page_header(
        "Action center",
        "Your privacy cleanup plan",
        "Prioritized actions below are based only on findings from the sources in this session. Check off progress as you work.",
    )
    history = st.session_state.analysis_history
    if not history:
        render_empty_state("☷", "Your plan will appear here", "Analyze one or more sources to generate a tailored, session-only action plan.")
    else:
        priorities, seen = {"High": [], "Medium": [], "Low": []}, set()
        for result in history:
            for finding in result.get("exposures", []):
                recommendation = str(finding.get("recommendation", "")).strip()
                category = str(finding.get("category", "Privacy exposure"))
                severity = str(finding.get("severity", "Low")).title()
                marker = (category, recommendation)
                if recommendation and marker not in seen:
                    seen.add(marker)
                    priorities[severity if severity in priorities else "Low"].append((category, recommendation, result["source_label"]))
        actions = [(level, category, recommendation, source) for level in ("High", "Medium", "Low") for category, recommendation, source in priorities[level]]
        if actions:
            completed = sum(st.session_state.get(f"cleanup-action-{index}", False) for index in range(len(actions)))
            header_left, header_right = st.columns([3, 1])
            with header_left:
                st.markdown("### Privacy action progress")
                st.caption(f"{completed} of {len(actions)} privacy actions completed in this session.")
            with header_right:
                st.markdown(f"<div style='padding-top:.35rem;text-align:right'>{severity_badge('High' if any(level == 'High' for level, *_ in actions) else 'Medium' if any(level == 'Medium' for level, *_ in actions) else 'Low')}</div>", unsafe_allow_html=True)
            st.progress(completed / len(actions))
        any_actions = False
        action_index = 0
        for level, heading in [("High", "High priority"), ("Medium", "Recommended"), ("Low", "Optional improvement")]:
            if priorities[level]:
                any_actions = True
                st.markdown(f"### {heading}")
                for category, recommendation, source in priorities[level]:
                    st.markdown(
                        f"<div class='pl-action-card' style='border-left:3px solid {'var(--pl-danger)' if level == 'High' else 'var(--pl-warning)' if level == 'Medium' else 'var(--pl-success)'}'>"
                        f"<div class='pl-exposure-top'><div class='pl-exposure-category'>{html.escape(category)}</div>{severity_badge(level)}</div>"
                        f"<div style='margin-top:.45rem;line-height:1.58'>{html.escape(recommendation)}</div>"
                        f"<div class='pl-action-meta'>Based on: {html.escape(source)}</div></div>",
                        unsafe_allow_html=True,
                    )
                    st.checkbox("Mark action complete", key=f"cleanup-action-{action_index}")
                    action_index += 1
        if not any_actions:
            render_empty_state("✓", "Nothing urgent to clean up", "No source-specific cleanup actions are needed from the findings in this session.")

elif page == "⚙️ Settings":
    render_page_header(
        "Workspace controls",
        "Settings tailored to this session",
        "Choose how PrivacyLens looks and how it handles the content you intentionally analyze. These controls apply only to this browser session.",
    )
    old_theme = st.session_state.theme_preference
    appearance_tab, analysis_tab, privacy_tab = st.tabs(["Appearance", "Analysis", "Privacy & session"])
    with appearance_tab:
        st.markdown("### Choose your workspace mood")
        st.caption("Each palette is designed independently for contrast, readability, and focus.")
        st.radio("Interface theme", ["Follow system", "Light", "Dark"], key="theme_preference", horizontal=True, label_visibility="collapsed")
        previews = st.columns(3)
        for column, name, copy, accent in [
            (previews[0], "System", "Match your device preference automatically.", "var(--pl-accent)"),
            (previews[1], "Light", "Soft blue-greys and elevated white surfaces.", "var(--pl-primary)"),
            (previews[2], "Dark", "Deep navy layers with cyan and violet signals.", "var(--pl-secondary)"),
        ]:
            with column:
                st.markdown(f"<div class='pl-card' style='border-top:3px solid {accent}'><div class='pl-card-title'>{name}</div><div class='pl-card-copy'>{copy}</div></div>", unsafe_allow_html=True)
    with analysis_tab:
        st.markdown("### Analysis depth")
        st.radio("Analysis mode", ["AI + local context", "Local patterns only"], key="analysis_mode", horizontal=True)
        st.markdown("<div class='pl-card'><div class='pl-card-title'>AI + local context</div><div class='pl-card-copy'>Uses local pattern checks and, when configured, Gemini for contextual educational guidance. No external search is performed.</div></div>", unsafe_allow_html=True)
        if not GOOGLE_API_KEY:
            st.warning("Gemini context, safer rewrites, and follow-up answers are unavailable until GOOGLE_API_KEY is added to Streamlit secrets or the environment. Local pattern detection remains available.")
        elif MODEL is None:
            st.warning("A Gemini key was found, but the configured model could not be initialized. Check GEMINI_MODEL and the installed Gemini SDK.")
        else:
            st.success(f"Gemini contextual analysis is available through {MODEL_NAME}.")
    with privacy_tab:
        st.markdown("### Privacy controls")
        st.checkbox("Mask detected pattern values in results", key="mask_detected_values")
        st.caption("Masked values are safer to view on screen. Content and results remain in the active browser session unless you download a report.")
        st.markdown("### Session history")
        st.markdown(f"<div class='pl-card'><div class='pl-stat-value'>{len(st.session_state.analysis_history)}</div><div class='pl-card-copy'>source(s) stored temporarily in the active browser session.</div></div>", unsafe_allow_html=True)
        if st.button("Delete all session-only history"):
            clear_session_history()
            st.success("Session-only analysis history has been deleted.")
    if st.session_state.theme_preference != old_theme:
        st.rerun()

elif page == "ℹ️ How It Works":
    render_page_header(
        "A clear boundary",
        "How PrivacyLens works",
        "A deliberate workflow for understanding the privacy signals in content you choose to provide—without people-searching or hidden data collection.",
    )
    render_section_heading("The analysis pipeline", "Five small steps. You stay in control at every one.")
    steps = [
        ("01", "Provide", "Paste text you own, or request a preview of a public webpage you are allowed to review."),
        ("02", "Preview", "For webpages, readable visible text is extracted while common page chrome is removed."),
        ("03", "Confirm", "Review the exact extracted text and explicitly select Analyze when you are ready."),
        ("04", "Understand", "Local checks run first. Gemini adds contextual educational guidance only when enabled."),
        ("05", "Act", "Use the score, targeted recommendations, cleanup plan, or safer rewrite in this session."),
    ]
    step_columns = st.columns(5, gap="small")
    for column, (number, title, copy) in zip(step_columns, steps):
        with column:
            st.markdown(
                f"<div class='pl-stat' style='min-height:11.8rem'><div class='pl-stat-label'>{number}</div>"
                f"<div class='pl-card-title' style='margin-top:.65rem'>{html.escape(title)}</div>"
                f"<div class='pl-card-copy'>{html.escape(copy)}</div></div>",
                unsafe_allow_html=True,
            )
    render_section_heading("Privacy boundaries", "The product is designed to make its limits visible, not hidden in fine print.")
    boundary_left, boundary_right = st.columns(2, gap="large")
    with boundary_left:
        st.markdown(
            "<div class='pl-card'><div class='pl-card-icon'>✓</div><div class='pl-card-title'>What PrivacyLens does</div>"
            "<div class='pl-card-copy'>It analyzes content you intentionally provide, highlights common patterns locally, and can use Gemini for contextual privacy guidance when you enable it.</div></div>",
            unsafe_allow_html=True,
        )
    with boundary_right:
        st.markdown(
            "<div class='pl-card'><div class='pl-card-icon'>⌁</div><div class='pl-card-title'>What PrivacyLens never does</div>"
            "<div class='pl-card-copy'>It does not search for people, build hidden profiles, access private accounts, or bypass sign-ins, CAPTCHAs, paywalls, and other website controls.</div></div>",
            unsafe_allow_html=True,
        )
    render_section_heading("Public webpage support", "Public HTML only—accessed normally and with clear limits.")
    st.markdown(
        "<div class='pl-card'><div class='pl-card-copy' style='font-size:.92rem'>PrivacyLens supports normally accessible public HTML pages. "
        "It blocks local and private addresses, credentialed URLs, non-HTML files, restricted pages, oversized pages, excessive redirects, and pages without meaningful visible text. "
        "Results remain in the active browser session unless you choose to download a report.</div></div>",
        unsafe_allow_html=True,
    )
