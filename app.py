# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import requests
import re
import time
from math import ceil

st.set_page_config(page_title="Completor EAN • Bing", layout="wide")
TARGET_HDR = "GTIN, UPC, EAN, or ISBN"

# ── helpers ───────────────────────────────────────────────────────────────────
def ean13_ok(code: str) -> bool:
    s = re.sub(r"\D", "", str(code))
    if len(s) != 13: return False
    d = [int(c) for c in s]
    chk = (10 - (sum(d[i]*(1 if i%2==0 else 3) for i in range(12)) % 10)) % 10
    return chk == d[12]

def pick_ean(text: str) -> str:
    if not text: return ""
    cands = re.findall(r"\b\d{13}\b", text)
    for c in cands:
        if ean13_ok(c):
            return c
    return ""

def bing_search_first_ean(query: str, api_key: str, mkt: str="ro-RO", count:int=10) -> str:
    url = "https://api.bing.microsoft.com/v7.0/search"
    params = {"q": query, "count": count, "textDecorations": "false",
              "textFormat": "Raw", "mkt": mkt}
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=12)
    except requests.RequestException:
        return ""
    if r.status_code != 200:
        return ""
    data = r.json()
    items = (data.get("webPages", {}) or {}).get("value", []) or []
    for it in items:
        txt = " ".join([it.get("name",""), it.get("snippet",""), it.get("url","")])
        code = pick_ean(txt)
        if code:
            return code
    return ""

# ── load secrets ──────────────────────────────────────────────────────────────
api_key = st.secrets["BING_API_KEY"]
mkt = st.secrets.get("BING_MKT", "ro-RO")
qps = int(st.secrets.get("QPS", 3))
delay = 1.0 / max(1, qps)

# ── test API key ──────────────────────────────────────────────────────────────
st.subheader("🔑 Test conexiune Bing API")
r = requests.get(
    "https://api.bing.microsoft.com/v7.0/search",
    headers={"Ocp-Apim-Subscription-Key": api_key},
    params={"q": "test", "count": 1, "mkt": mkt}
)
if r.status_code == 200:
    st.success("Cheia API funcționează.")
else:
    st.error(f"Eroare Bing API (status {r.status_code}).")
    st.stop()

# ── UI principal ──────────────────────────────────────────────────────────────
st.title("Completare EAN automat din web (Bing API)")

f = st.file_uploader("Încarcă CSV-ul", type=["csv"])
if not f:
    st.stop()

df = pd.read_csv(f, dtype=str, keep_default_na=False)
if TARGET_HDR not in df.columns:
    st.error(f"Lipsește coloana exactă: {TARGET_HDR}")
    st.stop()

sku_col = "SKU" if "SKU" in df.columns else df.columns[0]
name_col = "Name" if "Name" in df.columns else None

rows_total = len(df)
todo_idx = [i for i,v in enumerate(df[TARGET_HDR].astype(str)) if not str(v).strip()]
st.write(f"Rânduri totale: {rows_total} • De completat: {len(todo_idx)}")

# contoare locale (Bing nu expune usage în răspuns)
q_total = 0
q_hits = 0
q_miss = 0

progress = st.progress(0.0)
status = st.empty()
metrics = st.empty()
preview_slot = st.empty()

batch_size = 20
batches = ceil(len(todo_idx) / batch_size)

filled_rows_preview = []  # pentru afișarea primelor 10 rezultate găsite

processed = 0
for b in range(batches):
    idx_batch = todo_idx[b*batch_size : (b+1)*batch_size]
    for i in idx_batch:
        if str(df.at[i, TARGET_HDR]).strip():
            processed += 1
            continue
        sku = str(df.at[i, sku_col]).strip()
        name = str(df.at[i, name_col]).strip() if name_col else ""
        q = f"{sku} {name}".strip()
        q_total += 1
        code = bing_search_first_ean(q, api_key, mkt=mkt)
        if code:
            df.at[i, TARGET_HDR] = code
            q_hits += 1
            if len(filled_rows_preview) < 10:
                filled_rows_preview.append({
                    "SKU": sku,
                    "Name": name,
                    TARGET_HDR: code
                })
        else:
            q_miss += 1

        processed += 1
        progress.progress(min(1.0, processed / max(1, len(todo_idx))))
        # metrice live + estimare cost (5 USD / 1000 căutări)
        est_cost = (q_total / 1000.0) * 5.0
        metrics.markdown(
            f"**Interogări:** {q_total} • **Găsite:** {q_hits} • **Negăsite:** {q_miss} • "
            f"**Cost estimat:** ~${est_cost:0.2f}"
        )
        time.sleep(delay)
    status.write(f"Lot {b+1}/{batches} procesat.")

# preview primele 10 rezultate găsite
if filled_rows_preview:
    st.subheader("Primele 10 potriviri găsite")
    st.dataframe(pd.DataFrame(filled_rows_preview))
else:
    st.info("Nu s-au găsit potriviri în primele loturi sau codurile sunt deja completate.")

st.success("Procesare terminată.")
st.download_button(
    "Descarcă CSV completat",
    data=df.to_csv(index=False, encoding="utf-8-sig"),
    file_name="products_with_ean.csv",
    mime="text/csv",
)
