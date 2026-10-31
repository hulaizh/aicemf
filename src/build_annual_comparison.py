import json
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "sec_edgar"
TABLES = ROOT / "output" / "tables"
FIGURES = ROOT / "output" / "figures"
SLIDES = ROOT / "slides"
CUTOFF = pd.Timestamp("2026-09-30")
COMPANIES = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "GOOGL": "Alphabet",
    "AMZN": "Amazon",
}
COLORS = {
    "AAPL": "#0072B2",
    "MSFT": "#D55E00",
    "NVDA": "#009E73",
    "GOOGL": "#CC79A7",
    "AMZN": "#E69F00",
}


def annual_fact(facts, filing, metric):
    facts = facts.copy()
    facts["period_end"] = pd.to_datetime(facts["period_end"])
    matches = facts.loc[
        (facts["accession"] == filing["accession"])
        & (facts["period_end"] == filing["report_date"])
        & (facts["form_type"] == "10-K")
        & (facts["unit"] == "USD")
        & (facts["statement_type"] == "IncomeStatement")
    ].copy()
    if metric == "net_income":
        matches = matches.loc[matches["concept"] == "us-gaap:NetIncomeLoss"]
    starts = pd.to_datetime(matches["period_start"], errors="coerce")
    ends = pd.to_datetime(matches["period_end"], errors="coerce")
    matches = matches.loc[(ends - starts).dt.days.between(330, 380)]
    values = matches["numeric_value"].dropna().unique()
    if len(values) != 1:
        raise ValueError(
            f"{filing['ticker']} FY{filing['fiscal_year']} {metric}: "
            f"expected one annual value, found {values.tolist()}"
        )
    if not matches["is_audited"].astype(str).str.lower().eq("true").all():
        raise ValueError(f"Unaudited source row for {filing['ticker']} FY{filing['fiscal_year']}")
    return float(values[0]), ";".join(sorted(matches["concept"].unique()))


def load_company(ticker):
    filings = pd.read_csv(RAW / f"{ticker}_10k_filings.csv")
    filings["ticker"] = ticker
    filings["filing_date"] = pd.to_datetime(filings["filing_date"])
    filings["report_date"] = pd.to_datetime(filings["report_date"])
    filings = filings.loc[
        (filings["form_type"] == "10-K")
        & (filings["filing_date"] <= CUTOFF)
        & (filings["report_date"] <= CUTOFF)
    ].sort_values("fiscal_year", ascending=False)
    selected = filings.head(6).sort_values("fiscal_year")
    if len(selected) != 6:
        raise ValueError(f"{ticker}: six annual source periods required")
    revenue = pd.read_csv(RAW / f"{ticker}_revenue.csv")
    net_income = pd.read_csv(RAW / f"{ticker}_net_income.csv")
    rows = []
    for _, filing in selected.iterrows():
        revenue_value, revenue_concept = annual_fact(revenue, filing, "revenue")
        net_income_value, net_income_concept = annual_fact(net_income, filing, "net_income")
        rows.append({
            "company": COMPANIES[ticker],
            "ticker": ticker,
            "cik": int(filing["cik"]),
            "fiscal_year": int(filing["fiscal_year"]),
            "fiscal_period": filing["fiscal_period"],
            "period_start": filing["period_start"] if "period_start" in filing else "",
            "fiscal_year_end": filing["report_date"].strftime("%Y-%m-%d"),
            "filing_date": filing["filing_date"].strftime("%Y-%m-%d"),
            "form_type": filing["form_type"],
            "revenue_usd": int(revenue_value),
            "net_income_usd": int(net_income_value),
            "revenue_concept": revenue_concept,
            "net_income_concept": net_income_concept,
            "accession": filing["accession"],
            "sec_url": filing["sec_url"],
            "revenue_source_file": f"data/raw/sec_edgar/{ticker}_revenue.csv",
            "net_income_source_file": f"data/raw/sec_edgar/{ticker}_net_income.csv",
        })
    sources = pd.DataFrame(rows).sort_values("fiscal_year")
    sources["previous_fiscal_year"] = sources["fiscal_year"].shift(1)
    sources["previous_revenue_usd"] = sources["revenue_usd"].shift(1)
    sources["revenue_growth_pct"] = (
        sources["revenue_usd"] / sources["previous_revenue_usd"] - 1
    ) * 100
    sources["net_margin_pct"] = sources["net_income_usd"] / sources["revenue_usd"] * 100
    return sources


def reconcile_latest_statements(latest):
    rows = []
    for row in latest.itertuples():
        relative_path = f"data/raw/sec_edgar/{row.ticker}_income_statement_latest.csv"
        statement = pd.read_csv(ROOT / relative_path)
        period_column = f"{row.fiscal_year_end} (FY)"
        base = statement.loc[
            statement["dimension"].astype(str).str.lower().eq("false")
            & statement["accession_number"].eq(row.accession)
        ]
        values = {}
        for metric, concept in [("revenue_usd", "Revenue"), ("net_income_usd", "NetIncome")]:
            matches = base.loc[base["standard_concept"].eq(concept)]
            if len(matches) != 1 or period_column not in statement.columns:
                raise ValueError(f"{row.ticker}: cannot reconcile {metric} to income statement")
            value = int(matches.iloc[0][period_column])
            expected = getattr(row, metric)
            if value != expected:
                raise ValueError(f"{row.ticker}: {metric} statement mismatch: {value} != {expected}")
            values[metric] = value
        rows.append({
            "ticker": row.ticker,
            "fiscal_year": row.fiscal_year,
            "fiscal_year_end": row.fiscal_year_end,
            "accession": row.accession,
            "revenue_usd": values["revenue_usd"],
            "net_income_usd": values["net_income_usd"],
            "revenue_statement_match": True,
            "net_income_statement_match": True,
            "statement_source_file": relative_path,
            "sec_url": row.sec_url,
        })
    return pd.DataFrame(rows)


def write_latex_tables(annual, latest):
    latest_lines = [
        r"\begin{tabular}{@{}llrrr@{}}",
        r"\toprule",
        r"Company & FY end & Revenue & Growth & Margin \\",
        r" & & (\$bn) & (\%) & (\%) \\",
        r"\midrule",
    ]
    for row in latest.itertuples():
        latest_lines.append(
            f"{row.ticker} FY{row.fiscal_year} & {row.fiscal_year_end} & "
            f"{row.revenue_usd / 1e9:,.1f} & {row.revenue_growth_pct:.1f} & "
            f"{row.net_margin_pct:.1f} \\\\"
        )
    latest_lines += [r"\bottomrule", r"\end{tabular}"]
    (TABLES / "latest_fiscal_year_summary.tex").write_text(
        "\n".join(latest_lines) + "\n", encoding="utf-8"
    )

    annual_lines = [
        r"\begin{tabular}{@{}lllrrr@{}}",
        r"\toprule",
        r"Ticker & FY & Fiscal-year end & Revenue (\$bn) & Growth (\%) & Net margin (\%) \\",
        r"\midrule",
    ]
    for ticker in COMPANIES:
        subset = annual.loc[annual["ticker"] == ticker]
        for row in subset.itertuples():
            annual_lines.append(
                f"{row.ticker} & {row.fiscal_year} & {row.fiscal_year_end} & "
                f"{row.revenue_usd / 1e9:,.1f} & {row.revenue_growth_pct:.1f} & "
                f"{row.net_margin_pct:.1f} \\\\"
            )
        if ticker != list(COMPANIES)[-1]:
            annual_lines.append(r"\addlinespace[2pt]")
    annual_lines += [r"\bottomrule", r"\end{tabular}"]
    (TABLES / "annual_comparison.tex").write_text(
        "\n".join(annual_lines) + "\n", encoding="utf-8"
    )

    source_lines = [
        r"\begin{tabular}{@{}llll@{}}",
        r"\toprule",
        r"Ticker & Fiscal-year end & Filed & 10-K accession \\",
        r"\midrule",
    ]
    for row in latest.itertuples():
        source_lines.append(
            f"{row.ticker} & {row.fiscal_year_end} & {row.filing_date} & "
            f"\\href{{{row.sec_url}}}{{{row.accession}}} \\\\"
        )
    source_lines += [r"\bottomrule", r"\end{tabular}"]
    (TABLES / "latest_source_records.tex").write_text(
        "\n".join(source_lines) + "\n", encoding="utf-8"
    )


def make_chart(annual):
    plt.rcParams.update({
        "figure.dpi": 100,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "font.size": 10,
        "axes.labelsize": 10,
        "axes.titlesize": 12,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "lines.linewidth": 2.0,
        "legend.frameon": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=False)
    panels = [
        ("revenue_usd", "Revenue", "USD billions", 1e-9),
        ("revenue_growth_pct", "Year-over-year revenue growth", "Percent", 1),
        ("net_margin_pct", "GAAP net margin", "Percent", 1),
    ]
    for ax, (column, title, ylabel, scale) in zip(axes, panels):
        for ticker, name in COMPANIES.items():
            subset = annual.loc[annual["ticker"] == ticker].sort_values("fiscal_year")
            ax.plot(
                subset["fiscal_year"], subset[column] * scale,
                marker="o", markersize=4.5, color=COLORS[ticker],
                label=f"{name} ({ticker})",
            )
        ax.set_title(title, loc="left", fontweight="bold")
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", color="#D8DDE3", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.set_xticks(range(2021, 2027))
        ax.set_xlim(2020.75, 2026.25)
        if column != "revenue_usd":
            ax.axhline(0, color="#606870", linewidth=0.8)
    axes[-1].set_xlabel("Company fiscal year (year-end dates differ; see table)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=5, bbox_to_anchor=(0.5, 0.955))
    fig.suptitle(
        "Mega-cap technology: annual scale, growth and profitability",
        x=0.08, y=0.995, ha="left", fontsize=16, fontweight="bold",
    )
    fig.text(
        0.08, 0.005,
        "Source: SEC EDGAR 10-K XBRL facts via kimi-datasource. Latest five fiscal years per company; "
        "filings and fiscal years ended by 30 Sep 2026.\nGrowth = current revenue / prior-year revenue - 1; "
        "net margin = NetIncomeLoss / revenue. Fiscal calendars are not aligned.",
        fontsize=8, color="#4B5563",
    )
    fig.subplots_adjust(left=0.08, right=0.98, top=0.90, bottom=0.10, hspace=0.42)
    for suffix in ("png", "pdf"):
        fig.savefig(FIGURES / f"annual_revenue_growth_net_margin.{suffix}")
    plt.close(fig)

    latest = annual.sort_values("fiscal_year").groupby("ticker", sort=False).tail(1)
    latest = latest.set_index("ticker").loc[list(COMPANIES)].reset_index()
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.1))
    for ax, (column, title, _, scale) in zip(axes, panels):
        values = latest[column] * scale
        bars = ax.barh(latest["ticker"], values, color=[COLORS[t] for t in latest["ticker"]], height=0.58)
        ax.invert_yaxis()
        ax.set_title(title, loc="left", fontweight="bold", fontsize=11)
        ax.set_xlabel("USD billions" if column == "revenue_usd" else "Percent")
        ax.set_xlim(min(0, values.min() * 1.1), values.max() * 1.23)
        ax.xaxis.grid(True, color="#D8DDE3", linewidth=0.7)
        ax.set_axisbelow(True)
        labels = [f"{value:,.1f}" for value in values]
        ax.bar_label(bars, labels=labels, padding=4, fontsize=9)
    fig.text(
        0.07, 0.01,
        "Source: SEC EDGAR 10-K XBRL via kimi-datasource. Latest eligible fiscal year per company; year-ends differ.",
        fontsize=8, color="#4B5563",
    )
    fig.subplots_adjust(left=0.07, right=0.98, top=0.86, bottom=0.25, wspace=0.38)
    for suffix in ("png", "pdf"):
        fig.savefig(FIGURES / f"latest_fiscal_year_metrics.{suffix}")
    plt.close(fig)


def html_table(frame, columns, source_links=False):
    parts = ['<div class="table-wrap"><table>', "<thead><tr>"]
    for label, _ in columns:
        parts.append(f"<th scope=\"col\">{label}</th>")
    parts.append("</tr></thead><tbody>")
    for row in frame.itertuples():
        parts.append("<tr>")
        for label, attribute in columns:
            value = getattr(row, attribute)
            if attribute == "revenue_usd":
                text = f"{value / 1e9:,.1f}"
            elif attribute in {"revenue_growth_pct", "net_margin_pct"}:
                text = f"{value:.1f}%"
            elif attribute == "fiscal_year":
                text = f"FY{value}"
            else:
                text = str(value)
            if source_links and attribute == "accession":
                text = f'<a href="{row.sec_url}">{text}</a>'
            parts.append(f"<td>{text}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def make_html(annual, latest, sources, verification):
    latest_columns = [
        ("Company", "company"), ("Ticker", "ticker"), ("Fiscal year", "fiscal_year"),
        ("Fiscal-year end", "fiscal_year_end"), ("Revenue (USD bn)", "revenue_usd"),
        ("YoY growth", "revenue_growth_pct"), ("Net margin", "net_margin_pct"),
    ]
    annual_columns = latest_columns[1:]
    source_columns = [
        ("Ticker", "ticker"), ("Fiscal year", "fiscal_year"),
        ("Fiscal-year end", "fiscal_year_end"), ("Filed", "filing_date"),
        ("Form", "form_type"), ("Accession / SEC source", "accession"),
        ("Revenue concept", "revenue_concept"), ("Net income concept", "net_income_concept"),
    ]
    source_rows = sources.loc[sources["fiscal_year"].isin(annual["fiscal_year"].unique())]
    source_rows = sources.merge(
        annual[["ticker", "fiscal_year"]], on=["ticker", "fiscal_year"], how="inner"
    )
    checks = "".join(f"<li>{item}</li>" for item in verification["checks"])
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Annual revenue, growth and net margin | Mega-cap technology</title>
<style>
:root{{--ink:#17202a;--muted:#5c6670;--paper:#f5f3ee;--surface:#fff;--line:#d6d9dc;--blue:#203e70;--accent:#0072b2;--focus:#9b4d00}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums}}
a{{color:var(--blue);text-underline-offset:3px}}a:focus-visible{{outline:3px solid var(--focus);outline-offset:3px}}.wrap{{max-width:1240px;margin:auto;padding:32px 28px 64px}}
header{{border-top:8px solid var(--blue);padding-top:24px}}.eyebrow{{font-size:.76rem;font-weight:750;letter-spacing:.13em;text-transform:uppercase;color:var(--blue)}}h1{{font-size:clamp(2rem,5vw,4.3rem);line-height:1.02;letter-spacing:-.045em;max-width:950px;margin:.25em 0}}h2{{font-size:1.45rem;line-height:1.2;margin:0 0 14px}}h3{{font-size:1rem;margin:0 0 8px}}p{{max-width:78ch}}.dek{{font-size:1.1rem;color:var(--muted)}}.meta{{display:flex;flex-wrap:wrap;gap:8px 24px;border-block:1px solid var(--line);padding:12px 0;margin:24px 0;color:var(--muted);font-size:.88rem}}
nav{{display:flex;gap:18px;flex-wrap:wrap;margin:20px 0 32px;font-weight:650}}.finding{{background:var(--blue);color:white;padding:24px 28px;margin:28px 0;font-size:1.25rem;max-width:none}}section{{margin-top:44px}}figure{{margin:0;background:var(--surface);border:1px solid var(--line);padding:16px}}figure img{{display:block;width:100%;height:auto}}figcaption{{color:var(--muted);font-size:.85rem;margin-top:10px}}.table-wrap{{overflow-x:auto;background:var(--surface);border:1px solid var(--line)}}table{{border-collapse:collapse;width:100%;font-size:.88rem}}th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th{{background:#e9edf2;color:#26384c;font-size:.76rem;text-transform:uppercase;letter-spacing:.035em}}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}tbody tr:last-child td{{border-bottom:0}}tbody tr:hover{{background:#f3f6f8}}.notes{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:24px;margin-top:24px}}.notes>div{{border-top:3px solid var(--blue);padding-top:12px}}.status{{font-weight:700;color:#135f4b}}details{{margin-top:16px}}summary{{cursor:pointer;font-weight:700;color:var(--blue)}}.downloads{{display:flex;gap:12px;flex-wrap:wrap}}.downloads a{{background:var(--surface);border:1px solid var(--line);padding:8px 12px}}footer{{margin-top:44px;padding-top:16px;border-top:1px solid var(--line);font-size:.82rem;color:var(--muted)}}
@media(max-width:640px){{.wrap{{padding:22px 16px 44px}}.finding{{padding:18px;font-size:1.08rem}}th,td{{padding:8px 10px}}figure{{padding:8px}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
@media print{{body{{background:white}}.wrap{{max-width:none;padding:0}}nav,.downloads{{display:none}}section{{break-inside:avoid}}}}
</style>
</head>
<body><main class="wrap">
<header><div class="eyebrow">Research briefing · SEC annual filings</div><h1>Scale is not growth.<br>Growth is not margin.</h1><p class="dek">Annual revenue, year-over-year revenue growth and GAAP net margin for Apple, Microsoft, NVIDIA, Alphabet and Amazon.</p><div class="meta"><span>Cutoff: 30 September 2026</span><span>Latest five eligible fiscal years per company</span><span>USD; GAAP actuals</span><span class="status">Verified: {verification['annual_rows']} annual rows passed</span></div><nav aria-label="Page sections"><a href="#latest">Latest fiscal years</a><a href="#history">Annual history</a><a href="#sources">Sources &amp; checks</a></nav></header>
<p class="finding">Amazon has the largest latest-year revenue base; NVIDIA leads both latest-year revenue growth and net margin.</p>
<section id="latest"><h2>Latest eligible fiscal year by company</h2><p>Fiscal years are not calendar-aligned. “Latest” means the newest 10-K with both filing date and fiscal-year end on or before the cutoff.</p>{html_table(latest, latest_columns)}<figure><img src="../output/figures/annual_revenue_growth_net_margin.png" alt="Three line charts showing annual revenue, revenue growth, and net margin for the five companies over their latest five fiscal years."><figcaption>Reported USD revenue and calculated growth and margins. Read values in the tables; lines do not imply calendar-aligned observations.</figcaption></figure></section>
<section id="history"><h2>Five-year annual history</h2><p>Revenue is shown in USD billions. Growth uses the preceding fiscal year, including a baseline year retained in the source records. Net margin is NetIncomeLoss divided by revenue.</p>{html_table(annual, annual_columns)}<div class="downloads" aria-label="Data downloads"><a href="../output/tables/annual_comparison.csv">Download annual CSV</a><a href="../output/tables/latest_fiscal_year_summary.csv">Download latest-year CSV</a><a href="../output/tables/source_records.csv">Download source records</a><a href="../report/annual_comparison.pdf">Open two-page report</a></div></section>
<section id="sources"><h2>Sources, definitions and verification</h2><div class="notes"><div><h3>Source of record</h3><p>SEC EDGAR 10-K filings and XBRL facts retrieved through kimi-datasource. Original annual filings are matched by CIK, fiscal year and accession; later comparative duplicates are excluded.</p></div><div><h3>Definitions</h3><p>Revenue uses the reported annual consolidated value. Net margin uses GAAP NetIncomeLoss attributable to parent. Growth = current / prior fiscal-year revenue − 1. No estimates or adjustments.</p></div><div><h3>Comparability</h3><p>Company fiscal years end on different dates and can span 52 or 53 weeks. Latest-year comparisons therefore cover different economic periods.</p></div></div><h3 style="margin-top:28px">Completed checks</h3><ul>{checks}</ul><details><summary>Show retained 10-K source records ({len(source_rows)} annual rows)</summary>{html_table(source_rows, source_columns, source_links=True)}</details></section>
<footer>Generated {verification['generated_date']} from preserved raw SEC extracts. Verification confirms internal reconciliation to retained source records, not independent re-audit. AI-generated analysis; not investment advice.</footer>
</main></body></html>"""
    (SLIDES / "annual_comparison.html").write_text(html, encoding="utf-8")


def main():
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    SLIDES.mkdir(parents=True, exist_ok=True)
    all_sources = pd.concat([load_company(ticker) for ticker in COMPANIES], ignore_index=True)
    annual = all_sources.loc[all_sources["previous_revenue_usd"].notna()].copy()
    annual["previous_fiscal_year"] = annual["previous_fiscal_year"].astype(int)
    annual["previous_revenue_usd"] = annual["previous_revenue_usd"].astype(int)
    annual = annual.sort_values(["ticker", "fiscal_year"], key=lambda s: s.map(list(COMPANIES).index) if s.name == "ticker" else s)
    latest = annual.sort_values("fiscal_year").groupby("ticker", sort=False).tail(1).copy()
    latest["ticker_order"] = latest["ticker"].map({t: i for i, t in enumerate(COMPANIES)})
    latest = latest.sort_values("ticker_order").drop(columns="ticker_order")

    assert len(annual) == 25
    assert len(all_sources) == 30
    assert not annual[["revenue_usd", "revenue_growth_pct", "net_margin_pct"]].isna().any().any()
    assert annual.groupby("ticker").size().eq(5).all()
    assert pd.to_datetime(annual["fiscal_year_end"]).le(CUTOFF).all()
    assert pd.to_datetime(annual["filing_date"]).le(CUTOFF).all()
    for row in annual.itertuples():
        expected_growth = (row.revenue_usd / row.previous_revenue_usd - 1) * 100
        expected_margin = row.net_income_usd / row.revenue_usd * 100
        assert abs(row.revenue_growth_pct - expected_growth) < 1e-10
        assert abs(row.net_margin_pct - expected_margin) < 1e-10

    source_columns = [
        "company", "ticker", "cik", "fiscal_year", "fiscal_period", "fiscal_year_end",
        "filing_date", "form_type", "revenue_usd", "net_income_usd", "revenue_concept",
        "net_income_concept", "accession", "sec_url", "revenue_source_file", "net_income_source_file",
    ]
    annual_columns = [
        "company", "ticker", "fiscal_year", "fiscal_year_end", "revenue_usd",
        "previous_fiscal_year", "previous_revenue_usd", "revenue_growth_pct",
        "net_income_usd", "net_margin_pct", "filing_date", "accession", "sec_url",
    ]
    annual[annual_columns].to_csv(TABLES / "annual_comparison.csv", index=False, float_format="%.8f")
    latest[annual_columns].to_csv(TABLES / "latest_fiscal_year_summary.csv", index=False, float_format="%.8f")
    all_sources[source_columns].to_csv(TABLES / "source_records.csv", index=False)
    write_latex_tables(annual, latest)
    make_chart(annual)
    reconciliation = reconcile_latest_statements(latest)
    reconciliation.to_csv(TABLES / "latest_statement_reconciliation.csv", index=False)
    verification = {
        "status": "passed",
        "generated_date": date.today().isoformat(),
        "cutoff": CUTOFF.strftime("%Y-%m-%d"),
        "annual_rows": len(annual),
        "source_rows": len(all_sources),
        "checks": [
            "25 annual rows: five fiscal years for each of five companies.",
            "30 retained source periods, including each company's prior-year growth baseline.",
            "Revenue and NetIncomeLoss match original 10-K accession, period end, USD unit and annual duration.",
            "All selected fiscal-year end dates and filing dates are on or before 30 September 2026.",
            "Every revenue-growth and net-margin value independently recomputed from retained USD inputs.",
            "Latest-year revenue and net income for all five firms match separate structured income-statement extracts.",
            "No missing revenue, growth or net-margin values in the 25-row annual table.",
        ],
    }
    (TABLES / "verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    make_html(annual, latest, all_sources, verification)
    print(latest[["ticker", "fiscal_year", "fiscal_year_end", "revenue_usd", "revenue_growth_pct", "net_margin_pct"]].to_string(index=False))
    print(f"Verified {len(annual)} annual rows against {len(all_sources)} source periods.")


if __name__ == "__main__":
    main()
