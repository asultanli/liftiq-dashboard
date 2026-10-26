"""Clean the LiftIQ workbook, flag bad rows, build a monthly cube and inject it into template.html.

Usage: python3 prep.py [path/to/workbook.xlsx]
Writes index.html next to this script.
"""
import glob
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
KEY = ["date", "offer_id", "publisher_id"]
METRICS = ["clicks", "conversions", "revenue", "payout"]


def find_workbook():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    hits = sorted(glob.glob(str(HERE / "LiftIQ_bi_candidate_dataset*.xlsx")))
    if not hits:
        sys.exit("Workbook not found. Pass its path as the first argument.")
    return Path(hits[0])


def load(path):
    x = pd.ExcelFile(path)
    fct = x.parse("fct_daily_performance")
    adv = x.parse("dim_advertisers")
    off = x.parse("dim_offers")
    pub = x.parse("dim_publishers")
    for df in (fct, adv, off, pub):
        for c in df.select_dtypes("object"):
            df[c] = df[c].str.strip()
    return fct, adv, off, pub


def flag_rows(fct, adv, off, pub):
    """Return a list of reasons per row. An empty list means the row is clean."""
    reasons = [[] for _ in range(len(fct))]

    def add(mask, text):
        for i in fct.index[mask]:
            reasons[i].append(text)

    fct["date"] = pd.to_datetime(fct["date"], errors="coerce")
    add(fct["date"].isna(), "unparseable date")
    add(fct[METRICS].isna().any(axis=1), "null metric")
    add((fct[METRICS] < 0).any(axis=1), "negative metric")
    add(fct["payout"] > fct["revenue"], "payout above revenue")
    add(fct["conversions"] > fct["clicks"], "conversions above clicks")
    add(~fct["advertiser_id"].isin(adv["advertiser_id"]), "advertiser not in dim_advertisers")
    add(~fct["offer_id"].isin(off["offer_id"]), "offer not in dim_offers")
    add(~fct["publisher_id"].isin(pub["publisher_id"]), "publisher not in dim_publishers")
    add(fct.duplicated(KEY, keep=False), "duplicate date x offer x publisher key")
    for idc, col in [("advertiser_id", "account_executive"), ("advertiser_id", "advertiser_name"),
                     ("offer_id", "offer_name"), ("publisher_id", "publisher_name"),
                     ("publisher_id", "publisher_manager")]:
        multi = fct.groupby(idc)[col].transform("nunique") > 1
        add(multi, f"{idc} maps to more than one {col}")
    return ["; ".join(r) for r in reasons]


def build(path):
    fct, adv, off, pub = load(path)
    fct["flag_reason"] = flag_rows(fct, adv, off, pub)
    fct["flag"] = (fct["flag_reason"] != "").astype(int)

    # Clean rows take names and owners from the dimension tables (the source of truth).
    # Flagged rows keep the values the fact table carries, so the conflict stays visible.
    fct = fct.merge(adv.add_suffix("_d").rename(columns={"advertiser_id_d": "advertiser_id"}), on="advertiser_id", how="left")
    fct = fct.merge(off[["offer_id", "offer_name"]].rename(columns={"offer_name": "offer_name_d"}), on="offer_id", how="left")
    fct = fct.merge(pub.add_suffix("_d").rename(columns={"publisher_id_d": "publisher_id"}), on="publisher_id", how="left")
    for col in ["advertiser_name", "vertical", "account_executive", "offer_name", "publisher_name", "publisher_manager"]:
        fct[col] = fct[col + "_d"].where(fct[col + "_d"].notna() & (fct["flag"] == 0), fct[col])

    fct = fct.dropna(subset=["date"])
    fct["month"] = fct["date"].dt.strftime("%Y-%m")
    days = fct.groupby("month")["date"].nunique()
    days_in_month = {m: int(pd.Period(m).days_in_month) for m in days.index}
    partial = {m: int(days[m]) for m in days.index if days[m] != days_in_month[m]}

    dims = ["month", "advertiser_name", "vertical", "account_executive", "offer_name",
            "publisher_name", "publisher_manager", "flag", "flag_reason"]
    cube = fct.groupby(dims, as_index=False)[METRICS].sum()
    cube["revenue"] = cube["revenue"].round(2)
    cube["payout"] = cube["payout"].round(2)

    # Compact encoding: dimension columns become indexes into lookup lists.
    lookups = {c: sorted(cube[c].unique().tolist()) for c in dims if c != "flag"}
    rows = []
    for r in cube.itertuples(index=False):
        rows.append([lookups[c].index(getattr(r, c)) if c != "flag" else int(r.flag) for c in dims]
                    + [int(r.clicks), int(r.conversions), float(r.revenue), float(r.payout)])

    flagged = fct[fct["flag"] == 1]
    qa = {
        "rows": int(len(fct)),
        "flagged_rows": int(len(flagged)),
        "flag_reasons": flagged["flag_reason"].str.split("; ").explode().value_counts().to_dict(),
        "flagged_by_month": flagged.groupby("month")[["revenue", "payout"]].sum().round(2).to_dict("index"),
        "flagged_entities": sorted(flagged["advertiser_name"].unique().tolist()),
        "flagged_dates": sorted(flagged["date"].dt.strftime("%Y-%m-%d").unique().tolist()),
        "partial_months": partial,
    }
    return {
        "dims": dims,
        "metrics": METRICS,
        "lookups": lookups,
        "rows": rows,
        "months": sorted(days.index.tolist()),
        "days": days_in_month,
        "qa": qa,
        "source": path.name,
    }


def stories(path):
    """Numbers behind the "60 seconds with the CEO" block. Clean rows only, monthly $ impact."""
    fct, adv, off, pub = load(path)
    fct["date"] = pd.to_datetime(fct["date"])
    fct = fct[fct["advertiser_id"].isin(adv["advertiser_id"]) & ~fct.duplicated(KEY, keep=False)].copy()
    fct["month"] = fct["date"].dt.strftime("%Y-%m")
    fct["profit"] = fct["revenue"] - fct["payout"]
    months = sorted(fct["month"].unique())
    days = pd.Series({m: pd.Period(m).days_in_month for m in months})
    first = months[0]
    by = lambda d: d.groupby("month")
    ser = lambda s: [round(float(s.get(m, 0)), 2) for m in months]

    # 1. Cobalt: revenue per conversion flat, payout per conversion stepping up on the 1st of each month
    c = by(fct[fct["advertiser_name"] == "Cobalt Mortgage"])[["conversions", "revenue", "payout"]].sum()
    ppc, rpc = c["payout"] / c["conversions"], c["revenue"] / c["conversions"]
    cobalt_loss = -(ppc - ppc[first]) * c["conversions"]
    step = (ppc.iloc[-1] - ppc.iloc[0]) / (len(months) - 1)
    breakeven_months = (rpc.iloc[-1] - ppc.iloc[-1]) / step

    # 2. Growth masking lost volume: Everpeak capped on 1 Apr, Summit cut on 1 May and 1 Jun, Lumen new from 1 Mar
    def run_rate_gap(name, base_months):
        p = by(fct[fct["advertiser_name"] == name])["profit"].sum().reindex(months, fill_value=0)
        rate = p[base_months].sum() / days[base_months].sum()
        gap = p - rate * days
        gap[base_months] = 0
        return gap
    everpeak = run_rate_gap("Everpeak Solar", months[:3])
    summit = run_rate_gap("Summit Tax Advisors", months[:4])
    lumen = by(fct[fct["advertiser_name"] == "Lumen Energy"])["profit"].sum().reindex(months, fill_value=0)
    ep_daily = fct[fct["advertiser_name"] == "Everpeak Solar"].groupby("date")["clicks"].sum()
    ep = by(fct[fct["advertiser_name"] == "Everpeak Solar"])[["conversions", "revenue"]].sum()

    # 3. Publisher pricing: Cascade payout share rising every month; Vertex at ~15% margin on offers others run at ~40%
    k = fct[(fct["publisher_name"] == "Cascade Traffic") & (fct["advertiser_name"] != "Cobalt Mortgage")]
    k = k.groupby(["offer_name", "month"])[["revenue", "payout"]].sum()
    base = k.groupby(level=0).apply(lambda g: 1 - g["payout"].iloc[0] / g["revenue"].iloc[0])
    cascade = ((k["revenue"] - k["payout"]) - k["revenue"] * base.reindex(k.index.get_level_values(0)).values).groupby(level=1).sum()
    cas_mg = by(fct[fct["publisher_name"] == "Cascade Traffic"])[["revenue", "payout"]].sum()
    def vertex_gap(month):
        """Profit Vertex leaves on the table vs other publishers' margin on the same offers."""
        cur = fct[fct["month"] == month].groupby(["offer_name", "publisher_name"])[["revenue", "payout"]].sum()
        total = 0.0
        for offer in cur.index.get_level_values(0).unique():
            g = cur.loc[offer]
            if "Vertex Clicks" in g.index and len(g) > 1:
                v, o = g.loc["Vertex Clicks"], g.drop("Vertex Clicks")
                total += max(0.0, v["revenue"] * ((1 - o["payout"].sum() / o["revenue"].sum()) - (1 - v["payout"] / v["revenue"])))
        return -total
    vertex = pd.Series({m: vertex_gap(m) for m in months})
    vx = fct[fct["publisher_name"] == "Vertex Clicks"]
    vx = vx[vx["advertiser_name"] != "Cobalt Mortgage"]
    others = fct[fct["offer_name"].isin(vx["offer_name"].unique()) & (fct["publisher_name"] != "Vertex Clicks")]

    net = by(fct)["profit"].sum()
    return {
        "months": months,
        "net_profit": ser(net),
        "cobalt": {
            "loss": ser(cobalt_loss), "ppc_first": round(ppc.iloc[0], 2), "ppc_last": round(ppc.iloc[-1], 2),
            "rpc_last": round(rpc.iloc[-1], 2), "margin_first": round(1 - c["payout"].iloc[0] / c["revenue"].iloc[0], 4),
            "margin_last": round(1 - c["payout"].iloc[-1] / c["revenue"].iloc[-1], 4),
            "step": round(step, 2), "months_to_breakeven": round(float(breakeven_months), 1),
        },
        "growth": {
            "everpeak": ser(everpeak), "summit": ser(summit), "lumen": ser(lumen),
            "everpeak_clicks_before": int(ep_daily[: "2025-03-31"].tail(7).mean()),
            "everpeak_clicks_after": int(ep_daily["2025-04-01":].mean()),
            "everpeak_rpc_q1": round(ep["revenue"].iloc[:3].sum() / ep["conversions"].iloc[:3].sum(), 2),
            "everpeak_rpc_last": round(ep["revenue"].iloc[-1] / ep["conversions"].iloc[-1], 2),
        },
        "publishers": {
            "cascade": ser(cascade.reindex(months, fill_value=0)),
            "cascade_margin": [round(1 - r.payout / r.revenue, 4) for r in cas_mg.itertuples()],
            "vertex": ser(vertex),
            "vertex_margin": round(1 - vx["payout"].sum() / vx["revenue"].sum(), 4),
            "others_margin": round(1 - others["payout"].sum() / others["revenue"].sum(), 4),
        },
    }


def main():
    path = find_workbook()
    data = build(path)
    data["stories"] = stories(path)
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    template = (HERE / "template.html").read_text(encoding="utf-8")
    marker = "/*__DATA__*/null"
    if marker not in template:
        sys.exit("Data marker not found in template.html")
    (HERE / "index.html").write_text(template.replace(marker, payload), encoding="utf-8")
    q = data["qa"]
    print(f"{q['rows']} rows, {q['flagged_rows']} flagged -> {len(data['rows'])} cube rows. Wrote index.html")
    for reason, n in q["flag_reasons"].items():
        print(f"  {n:>4}  {reason}")


if __name__ == "__main__":
    main()
