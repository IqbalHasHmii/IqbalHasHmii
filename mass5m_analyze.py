"""Analysis of the 5-million-strategy search (run mass5m.py first).

    python mass5m_analyze.py                    # the 1-5 minute run
    python mass5m_analyze.py 15,30,60 _htf      # same rules on 15 / 30 / 60 minutes (python mass5m.py 15,30,60)

Periods: P1 2021-11..2023-10 (choose), P2 2023-11..2024-10 (confirm), P3 2024-11..2026-10 (test).
Every selection below uses ONLY P1 and P2. P3 shows how the picks did on data that played no part
in choosing them - that is the number to trust.

Outputs: results/mass5m_summary.txt plus CSVs (mass5m_by_tf, mass5m_40pct, mass5m_top,
mass5m_top_3perweek, mass5m_best_per_rule, mass5m_highest_win).
"""
import os
import sys

import numpy as np
import pandas as pd

from mass5m import ADXS, DOWS, SESSIONS, SLS, TFS, TRENDS, VOLS

if len(sys.argv) > 1:                       # e.g. python mass5m_analyze.py 15,30,60 _htf
    TFS = [int(x) for x in sys.argv[1].split(",")]
TAG = sys.argv[2] if len(sys.argv) > 2 else ""


def out(name):
    return f"results/mass5m{TAG}_{name}"

DIRS = ["both", "buy_only", "sell_only"]
EDGE1, EDGE2 = pd.Timestamp("2023-11-01"), pd.Timestamp("2024-11-01")
lines = []


def say(s=""):
    print(s)
    lines.append(s)


# ----------------------------------------------------------------------------- load
blocks, names, bases, start, end = [], None, {}, None, None
for tf in TFS:
    z = np.load(f"results/mass5m/tf{tf}.npz")
    A = z["A"]                                              # trig, trend, sl, side, per, sess, vol, adx, dow, stat
    if names is None:
        names = list(z["names"])
    assert list(z["names"]) == names
    bases[tf] = z["base"]
    start = min(start or pd.Timestamp(str(z["start"])), pd.Timestamp(str(z["start"])))
    end = max(end or pd.Timestamp(str(z["end"])), pd.Timestamp(str(z["end"])))
    D = np.stack([A[:, :, :, 0] + A[:, :, :, 1], A[:, :, :, 0], A[:, :, :, 1]], axis=3)   # both, buy, sell
    D = np.moveaxis(D, 4, -2)                               # ..., per, stat
    blocks.append(D.reshape(-1, 3, 3))
SHAPE = (len(names), len(TRENDS), len(SLS), 3, len(SESSIONS), len(VOLS), len(ADXS), len(DOWS))
PER_TF = int(np.prod(SHAPE))
X = np.concatenate(blocks)
del blocks
N = X.shape[0]
weeks = np.array([(EDGE1 - start).days / 7, (EDGE2 - EDGE1).days / 7, (end - EDGE2).days / 7])

n = X[:, :, 0]
w = X[:, :, 1]
R = X[:, :, 2]
with np.errstate(invalid="ignore", divide="ignore"):
    win = w / n
    rpt = R / n
n12, w12, R12 = n[:, 0] + n[:, 1], w[:, 0] + w[:, 1], R[:, 0] + R[:, 1]
with np.errstate(invalid="ignore", divide="ignore"):
    p12 = w12 / n12
    t12 = (R12 / n12) / (4 * np.sqrt(np.clip(p12 * (1 - p12), 1e-6, None))) * np.sqrt(n12)
elig = (n[:, 0] >= weeks[0]) & (n[:, 1] >= weeks[1] / 2) & (n[:, 2] >= weeks[2] / 2)   # >= 1 / week in P1
three = elig & (n[:, 0] >= 3 * weeks[0])                                                 # >= 3 / week in P1


def decode(i):
    tf = TFS[i // PER_TF]
    t, tr, sl, dr, se, vo, ad, dw = np.unravel_index(i % PER_TF, SHAPE)
    return {"tf": f"M{tf}", "rule": names[t], "trend": TRENDS[tr], "SL": SLS[sl], "direction": DIRS[dr],
            "session": list(SESSIONS)[se], "volatility": list(VOLS)[vo], "adx": list(ADXS)[ad],
            "days": list(DOWS)[dw]}


def table(ix):
    rows = []
    for i in ix:
        r = decode(i)
        for p, lab in enumerate(("P1", "P2", "P3")):
            r[f"{lab} trades/wk"] = round(float(n[i, p] / weeks[p]), 1)
            r[f"{lab} win%"] = round(float(win[i, p] * 100), 1)
            r[f"{lab} R/trade"] = round(float(rpt[i, p]), 3)
        rows.append(r)
    return pd.DataFrame(rows)


pd.set_option("display.width", 320, "display.max_columns", 40, "display.max_rows", 200)
say(f"Strategies tested: {N:,} ({len(TFS)} timeframes x {PER_TF:,}); {len(names)} entry rules")
say(f"Periods: P1 {start:%Y-%m-%d}..2023-10-31 ({weeks[0]:.0f} wk) choose | P2 2023-11..2024-10 ({weeks[1]:.0f} wk) "
    f"confirm | P3 2024-11..{end:%Y-%m-%d} ({weeks[2]:.0f} wk) test. Every trade 1:3 (break-even win rate 25%).")
say(f"Eligible (>= 1 trade/week in P1, >= 0.5/week in P2 and P3): {elig.sum():,}; with >= 3 trades/week: {three.sum():,}\n")

# ----------------------------------------------------------------------------- baseline per timeframe
say("No-skill win rate at 1:3 (a trade after every candle):")
say(pd.DataFrame({f"M{tf}": [f"{x * 100:.1f}%" for x in bases[tf]] for tf in TFS}, index=SLS).T.to_string())
say()

# ----------------------------------------------------------------------------- 40% club
say("=== The 40%-win question (win = TP hit at 1:3) ===")
rows = []
for lab, base_mask in (("all eligible", elig), (">= 3 trades/week", three)):
    c1 = base_mask & (win[:, 0] >= 0.40)
    c2 = c1 & (win[:, 1] >= 0.40)
    c3 = c2 & (win[:, 2] >= 0.40)
    rows.append({"group": lab, "strategies": int(base_mask.sum()), ">=40% in P1": int(c1.sum()),
                 "and >=40% in P2": int(c2.sum()),
                 "and >=40% in P3 (test)": int(c3.sum()),
                 "P3 avg win% of P1+P2 40% club": round(float(np.nanmean(win[c2, 2])) * 100, 1) if c2.any() else None,
                 "P3 avg R/trade": round(float(np.nanmean(rpt[c2, 2])), 3) if c2.any() else None,
                 "P3 % profitable": round(np.mean(rpt[c2, 2] > 0) * 100) if c2.any() else None})
club = pd.DataFrame(rows)
say(club.to_string(index=False))
c2_all = elig & (win[:, 0] >= 0.40) & (win[:, 1] >= 0.40)
t40 = table(np.flatnonzero(c2_all)[np.argsort(-t12[c2_all])][:200])
t40.to_csv(out("40pct.csv"), index=False)
say("\nBest 15 of the strategies with >= 40% wins in BOTH P1 and P2, and what happened in P3:")
say(t40.head(15).to_string(index=False) if len(t40) else "none")
say()

# ----------------------------------------------------------------------------- per timeframe
rows = []
for k, tf in enumerate(TFS):
    sl_ = slice(k * PER_TF, (k + 1) * PER_TF)
    e = elig[sl_]
    allp = e & (rpt[sl_, 0] > 0) & (rpt[sl_, 1] > 0) & (rpt[sl_, 2] > 0)
    pool = np.flatnonzero(e & (rpt[sl_, 0] > 0) & (rpt[sl_, 1] > 0)) + k * PER_TF
    top = pool[np.argsort(-t12[pool])][:50]
    rows.append({"tf": f"M{tf}", "eligible": int(e.sum()), "% profitable in all 3 periods": round(allp.sum() / max(e.sum(), 1) * 100, 2),
                 "top50 P1+P2 win%": round(np.mean(p12[top]) * 100, 1), "top50 P3 win%": round(np.nanmean(win[top, 2]) * 100, 1),
                 "top50 P3 R/trade": round(np.nanmean(rpt[top, 2]), 3), "top50 % P3 profitable": round(np.mean(rpt[top, 2] > 0) * 100)})
bytf = pd.DataFrame(rows)
bytf.to_csv(out("by_tf.csv"), index=False)
say("=== Per timeframe (top 50 = best P1+P2 t-stat among strategies profitable in P1 and P2) ===")
say(bytf.to_string(index=False))
say()

# ----------------------------------------------------------------------------- best strategies (chosen on P1+P2)
for lab, mask, fn in (("TOP 30 overall (>= 1 trade/week)", elig, "top"),
                      ("TOP 30 with >= 3 trades/week", three, "top_3perweek")):
    pool = np.flatnonzero(mask & (rpt[:, 0] > 0) & (rpt[:, 1] > 0))
    order = pool[np.argsort(-t12[pool])]
    tb = table(order[:300])
    tb.to_csv(out(f"{fn}.csv"), index=False)
    top100 = order[:100]
    say(f"=== {lab}, ranked on P1+P2 only ===")
    say(f"Top 100: P3 profitable {np.mean(rpt[top100, 2] > 0) * 100:.0f}%, P3 avg win {np.nanmean(win[top100, 2]) * 100:.1f}%, "
        f"P3 avg {np.nanmean(rpt[top100, 2]):+.3f}R/trade (P1+P2 avg win {np.mean(p12[top100]) * 100:.1f}%)")
    say(tb.head(30).to_string(index=False))
    say()

# best combination of every entry rule
pool = np.flatnonzero(elig & (rpt[:, 0] > 0) & (rpt[:, 1] > 0))
rule_of = (pool % PER_TF) // (PER_TF // len(names))
best = {}
for i, r_ in zip(pool, rule_of):
    if r_ not in best or t12[i] > t12[best[r_]]:
        best[r_] = i
bp = table(sorted(best.values(), key=lambda i: -t12[i]))
bp.to_csv(out("best_per_rule.csv"), index=False)
say("=== Best combination of each entry rule (chosen on P1+P2), top 25 rules ===")
say(bp.head(25).to_string(index=False))
say(f"Rules with no combination profitable in both P1 and P2: {len(names) - len(best)} of {len(names)}")
say()

# highest win rates (P1+P2, at least 1.5 trades/week over P1+P2)
hw = np.flatnonzero(elig & (n12 >= 1.5 * (weeks[0] + weeks[1])))
order = hw[np.argsort(-p12[hw])][:30]
th = table(order)
th.to_csv(out("highest_win.csv"), index=False)
say("=== Highest P1+P2 win rates (>= 1.5 trades/week), and their P3 ===")
say(th.to_string(index=False))

os.makedirs("results", exist_ok=True)
with open(out("summary.txt"), "w") as f:
    f.write("\n".join(lines) + "\n")
