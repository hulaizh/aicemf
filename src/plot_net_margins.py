import csv
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
COMPANIES = [
    ("Apple", "AAPL", "aapl_sp_fy2025_ratios.csv"),
    ("Microsoft", "MSFT", "msft_sp_fy2025_ratios.csv"),
    ("Alphabet (Google)", "GOOGL", "googl_sp_fy2025_ratios.csv"),
]


def load_net_margin(ticker, filename):
    path = ROOT / "data" / "raw" / filename
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["ticker"] == ticker
            and row["data_item_name"] == "Net Income Margin %"
            and row["fiscal_year"] == "2025"
            and row["period_type"] == "Annual"
        ]
    if len(rows) != 1:
        raise ValueError(f"Expected one FY2025 net-margin row for {ticker}; found {len(rows)}")
    row = rows[0]
    if row["unit_type"] != "Actual" or not row["data_item_value"]:
        raise ValueError(f"Missing or non-actual net margin for {ticker}")
    return float(row["data_item_value"]), row["period_end_date"]


results = [(name, ticker, *load_net_margin(ticker, filename)) for name, ticker, filename in COMPANIES]
names = [f"{name} ({ticker})" for name, ticker, _, _ in results]
margins = [margin for _, _, margin, _ in results]

plt.rcParams.update({
    "figure.figsize": (8, 4.5),
    "figure.dpi": 100,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "font.size": 10,
    "axes.labelsize": 10,
    "axes.titlesize": 12,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "lines.linewidth": 1.8,
    "legend.frameon": False,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

fig, ax = plt.subplots(figsize=(8, 4.5))
bars = ax.barh(names, margins, color="#4C72B0", height=0.56)
ax.invert_yaxis()
ax.set_title("FY2025 Net Income Margin: Apple, Microsoft, and Alphabet")
ax.set_xlabel("Net income margin (%)")
ax.set_xlim(0, max(margins) * 1.18)
ax.set_xticks(range(0, 41, 10))
ax.xaxis.grid(True, color="#D9D9D9", linewidth=0.7)
ax.set_axisbelow(True)
ax.bar_label(bars, labels=[f"{value:.1f}%" for value in margins], padding=5)

fig.subplots_adjust(left=0.23, right=0.96, top=0.85, bottom=0.25)
fig.text(
    0.23,
    0.09,
    "Source: S&P Capital IQ via kimi-datasource; standardized FY2025 actuals.\n"
    "Fiscal year-ends: Apple 27 Sep 2025; Microsoft 30 Jun 2025; Alphabet 31 Dec 2025.",
    fontsize=8,
    color="#444444",
)

output_path = ROOT / "output" / "figures" / "fy2025_peer_net_margins.png"
output_path.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(output_path, dpi=300, bbox_inches="tight")
plt.close(fig)

for name, ticker, margin, period_end in results:
    print(f"{name} ({ticker}): {margin:.4f}% (FY2025, ended {period_end})")
print(f"Saved figure: {output_path}")
