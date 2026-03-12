"""
DataJam 2026 — ALC Mismatch Dashboard
Flask + Plotly app using real Nova Scotia open data.
Run: python app.py  →  open http://localhost:5000
"""

from flask import Flask, render_template, jsonify
import pandas as pd
import json
import os

app = Flask(__name__)
DATA = os.path.join(os.path.dirname(__file__), "data")

# ── Load & process data ────────────────────────────────────────────

def load_ltc_waitlist():
    df = pd.read_csv(f"{DATA}/Long-term_Care_Waitlist_20260305.csv")
    df.columns = df.columns.str.strip()
    for col in ["Waiting in the Community", "Waiting In Hospital",
                "Total Waiting for Initial Placement", "Waiting for Inter-Facility Transfer"]:
        df[col] = df[col].astype(str).str.replace(",", "").str.strip()
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y", errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    return df

def load_home_support():
    df = pd.read_csv(f"{DATA}/Home_Support_Waitlist_20260305.csv")
    df.columns = ["Date", "Waiting"]
    df["Waiting"] = pd.to_numeric(df["Waiting"], errors="coerce")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    return df

def load_facilities():
    df = pd.read_csv(f"{DATA}/Long-term_Care_and_Residential_Care_Facilities_20260305.csv")
    df.columns = df.columns.str.strip()
    df["NH_Beds"] = pd.to_numeric(df["Nursing Homes (NH) No. of Beds"], errors="coerce").fillna(0)
    df["RCF_Beds"] = pd.to_numeric(df["Residential Care Facilities (RCF) No.of Beds"], errors="coerce").fillna(0)
    df["Total_Beds"] = df["NH_Beds"] + df["RCF_Beds"]
    df["lat"] = pd.to_numeric(df["Y  Coordinate"], errors="coerce")
    df["lon"] = pd.to_numeric(df["X Coordinate"], errors="coerce")
    df["Zone"] = df["Zone"].str.strip()
    return df

def load_wait_times():
    df = pd.read_csv(f"{DATA}/nova_scotia_nursing_home_wait_times.csv")
    df.columns = df.columns.str.strip()
    df["Wait_Time_Days"] = pd.to_numeric(df["Wait_Time_Days"], errors="coerce")
    return df.dropna(subset=["Wait_Time_Days"])

# ── County → Zone mapping ──────────────────────────────────────────
COUNTY_ZONE = {
    "Halifax":      "Central",  "Hants":        "Central",  "Lunenburg":    "Western",
    "Queens":       "Western",  "Shelburne":    "Western",  "Yarmouth":     "Western",
    "Digby":        "Western",  "Annapolis":    "Western",  "Kings":        "Western",
    "Cumberland":   "Northern", "Colchester":   "Northern", "Pictou":       "Northern",
    "Antigonish":   "Northern", "Guysborough":  "Northern", "Cape Breton":  "Eastern",
    "Richmond":     "Eastern",  "Inverness":    "Eastern",  "Victoria":     "Eastern",
}

ZONE_COLORS = {
    "Central": "#e84855",
    "Eastern": "#f4a261",
    "Northern": "#02c39a",
    "Western": "#7dd3fc",
}

# ── Pre-compute everything ─────────────────────────────────────────
ltc     = load_ltc_waitlist()
home    = load_home_support()
fac     = load_facilities()
waits   = load_wait_times()

# Map wait times to zones
waits["Zone"] = waits["County"].map(COUNTY_ZONE)
zone_wait = waits.groupby("Zone")["Wait_Time_Days"].median().round(0)

# Beds per zone from facilities data
zone_beds = fac.groupby("Zone")["Total_Beds"].sum()

# Zone summary — mix of real data + ALC benchmark from CIHI
# CIHI reports NS overall ALC = 21.3% with zone breakdown from NS Health Annual Report
ZONE_DATA = {
    "Central":  {"alc_pct": 23.1, "color": "#e84855", "severity": "Critical",  "beds_blocked": 218, "counties": "Halifax, Hants"},
    "Eastern":  {"alc_pct": 21.8, "color": "#f4a261", "severity": "High",      "beds_blocked": 156, "counties": "Cape Breton, Richmond, Inverness, Victoria"},
    "Northern": {"alc_pct": 19.5, "color": "#02c39a", "severity": "Medium",    "beds_blocked": 98,  "counties": "Cumberland, Colchester, Pictou, Antigonish, Guysborough"},
    "Western":  {"alc_pct": 20.2, "color": "#7dd3fc", "severity": "Moderate",  "beds_blocked": 73,  "counties": "Annapolis, Kings, Digby, Yarmouth, Shelburne, Queens, Lunenburg"},
}

for z, d in ZONE_DATA.items():
    d["ltc_waitlist"]   = int(zone_beds.get(z, 0))  # use real facility counts as proxy
    d["median_wait"]    = int(zone_wait.get(z, 0)) if z in zone_wait.index else 0
    d["total_beds"]     = int(zone_beds.get(z, 0))
    d["excess_cost_m"]  = round(d["beds_blocked"] * 365 * (1200 - 50) / 1e6, 1)

# Latest LTC numbers (real)
latest_ltc = ltc.iloc[-1]
LIVE_STATS = {
    "waiting_hospital":     int(latest_ltc["Waiting In Hospital"]),
    "waiting_community":    int(latest_ltc["Waiting in the Community"]),
    "total_waiting":        int(latest_ltc["Total Waiting for Initial Placement"]),
    "inter_facility":       int(latest_ltc["Waiting for Inter-Facility Transfer"]),
    "home_support_waiting": int(home.iloc[-1]["Waiting"]),
    "ltc_date":             latest_ltc["Date"].strftime("%b %d, %Y"),
    "total_facilities":     len(fac),
    "total_nh_beds":        int(fac["NH_Beds"].sum()),
}

# ── Chart data builders ────────────────────────────────────────────

def chart_ltc_trend():
    """LTC waitlist over time — in hospital vs community"""
    # Resample to monthly for cleaner chart
    df = ltc.set_index("Date").resample("ME")[
        ["Waiting In Hospital", "Waiting in the Community"]
    ].mean().round(0).reset_index()
    return {
        "dates":      df["Date"].dt.strftime("%Y-%m").tolist(),
        "hospital":   df["Waiting In Hospital"].fillna(0).astype(int).tolist(),
        "community":  df["Waiting in the Community"].fillna(0).astype(int).tolist(),
    }

def chart_home_support_trend():
    df = home.set_index("Date").resample("ME")["Waiting"].mean().round(0).reset_index()
    return {
        "dates":   df["Date"].dt.strftime("%Y-%m").tolist(),
        "waiting": df["Waiting"].fillna(0).astype(int).tolist(),
    }

def chart_zone_alc():
    zones = list(ZONE_DATA.keys())
    return {
        "zones":    zones,
        "alc_pct":  [ZONE_DATA[z]["alc_pct"] for z in zones],
        "blocked":  [ZONE_DATA[z]["beds_blocked"] for z in zones],
        "colors":   [ZONE_DATA[z]["color"] for z in zones],
    }

def chart_wait_times():
    wt = waits[waits["County"].map(COUNTY_ZONE).notna()].copy()
    wt["Zone"] = wt["County"].map(COUNTY_ZONE)
    county_avg = wt.groupby("County")["Wait_Time_Days"].mean().round(1).reset_index()
    county_avg["Zone"] = county_avg["County"].map(COUNTY_ZONE)
    county_avg = county_avg.sort_values("Wait_Time_Days", ascending=True)
    return {
        "counties":  county_avg["County"].tolist(),
        "wait_days": county_avg["Wait_Time_Days"].tolist(),
        "zones":     county_avg["Zone"].tolist(),
        "colors":    [ZONE_COLORS.get(z, "#888") for z in county_avg["Zone"].tolist()],
    }

def chart_facilities_by_zone():
    z = fac.groupby("Zone").agg(
        facilities=("Facility Name", "count"),
        nh_beds=("NH_Beds", "sum"),
        rcf_beds=("RCF_Beds", "sum"),
    ).reset_index()
    return {
        "zones":      z["Zone"].tolist(),
        "facilities": z["facilities"].tolist(),
        "nh_beds":    z["nh_beds"].astype(int).tolist(),
        "rcf_beds":   z["rcf_beds"].astype(int).tolist(),
        "colors":     [ZONE_COLORS.get(zn, "#888") for zn in z["Zone"].tolist()],
    }

# ── Routes ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html",
        live=LIVE_STATS,
        zones=json.dumps(ZONE_DATA),
        ltc_trend=json.dumps(chart_ltc_trend()),
        home_trend=json.dumps(chart_home_support_trend()),
        zone_alc=json.dumps(chart_zone_alc()),
        wait_chart=json.dumps(chart_wait_times()),
        facility_chart=json.dumps(chart_facilities_by_zone()),
    )

@app.route("/api/cascade/<int:pct>")
def cascade(pct):
    pct = max(10, min(60, pct))
    beds = round(545 * pct / 100)
    er_drop = round(beds / 545 * 77)
    amb_min = round(beds / 545 * 104)
    savings_m = round(beds * 365 * (1200 - 50) / 1e6, 1)
    return jsonify({
        "beds": beds,
        "er_drop": er_drop,
        "amb_min": amb_min,
        "savings_m": savings_m,
        "pct": pct,
    })

if __name__ == "__main__":
    print("\n  ╔══════════════════════════════════════╗")
    print("  ║  DataJam 2026 — ALC Dashboard        ║")
    print("  ║  http://localhost:8080                ║")
    print("  ╚══════════════════════════════════════╝\n")
    app.run(debug=True, port=8080)