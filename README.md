# LiftIQ BI dashboard

A month over month performance dashboard for LiftIQ, built from `LiftIQ_bi_candidate_dataset (1).xlsx`. It is a single static HTML file. No server, no internet, no build step.

## How to run

Just look at it: open `index.html` in any browser. It works offline.

Rebuild it from the workbook (needs Python 3 with pandas and openpyxl). The workbook is not in this repo. Put `LiftIQ_bi_candidate_dataset (1).xlsx` (any file matching `LiftIQ_bi_candidate_dataset*.xlsx`) in this folder first, then run:

```bash
python3 prep.py
```

`prep.py` finds the workbook in this folder, or takes a path to it as its first argument. You only need it to rebuild: the data is already baked into `index.html`. It cleans and flags the data, builds a monthly cube (month x advertiser x offer x publisher, with vertical, AE, publisher manager, clicks, conversions, revenue, payout and a flag), works out the numbers behind the CEO block, and injects everything as JSON into `template.html` to write `index.html`. The page itself is plain JavaScript and SVG with no libraries.

| File | What it is |
|---|---|
| `prep.py` | Cleaning, flagging, aggregation, CEO story numbers |
| `template.html` | Page layout, charts and calculations |
| `index.html` | Generated output. This is the dashboard. |
| `claude_code_session.md` | The Claude Code session log, including my corrections and redirections |

## What is on the page

1. **60 seconds with the CEO**: three findings with the $ impact per month.
2. **KPI tiles**: revenue, profit, margin and conversions for the selected month vs the prior month.
3. **Trends**: revenue and profit by month, and margin % by month. Each chart title states the takeaway.
4. **What moved profit**: profit change by advertiser, offer, publisher, vertical, AE or publisher manager, with status flags (New, Stopped, Revenue drop, Growing, Margin eroding). A full sortable table sits underneath, collapsed.
5. **Margin heatmap**: advertiser x publisher. The number is the margin in the selected month, and the colour is the change vs January.
6. **Methodology**: collapsed. Covers data handling, formulas and what each control does.

Controls: a month selector, a **Per day** toggle that divides by days in the month (so February is not penalised), and, inside Methodology, a toggle to include the flagged rows.

## Data handling decisions

- **One bad block of rows is excluded by default.** 14 rows for "Green Roof Solar" (advertiser 111, offer 9015), all dated 27 April 2025. The advertiser and offer are missing from the dim tables, the advertiser maps to three different AEs, and 11 of the rows are duplicates on date x offer x publisher. There is no way to tell which duplicate is right, so the whole block is flagged. It adds $24.9K revenue and $6.9K profit to April. Including it changes April revenue MoM from -5.9% to -2.8% and profit MoM from -9.5% to -6.9%. The toggle in Methodology adds it back.
- **Everything else was clean.** There were no nulls, no negative values, no payout above revenue, no conversions above clicks, and no missing days. Names, verticals and owners matched the dim tables on every other row. `prep.py` still runs all of these checks on every rebuild and flags anything that fails.
- **Names and owners come from the dim tables** for clean rows, since those are the source of truth.
- **Formulas.** Profit = revenue - payout. Margin = sum(profit) / sum(revenue) over whatever is in view, never an average of row margins. MoM % = (current - prior) / prior. Margin changes are shown in percentage points.
- **"Margin eroding" baseline.** This flag compares against January. Anything that started later (for example Lumen) is compared with its first active month instead, and the label names that month.
- **Limits.** There are only six months of data and no prior year, so seasonality cannot be measured directly. The per-day view and comparisons within a vertical help, but cannot prove it.

All June vs May KPIs and the top five advertiser profit changes were recalculated directly in pandas from the raw sheet. They match the dashboard to the cent.

## Three points for the CEO

**1. Cobalt Mortgage's margin is being given away to publishers. -$39.9K profit in June, and it grows every month.**
Cobalt still pays us about $95 per lead. We now pay publishers $84 per lead, up from $52 in January. The payout rose by about $6 on the 1st of every month, on all four publishers at once, while the price Cobalt pays did not move. Margin fell from 44.9% to 12.2%. At this pace payout passes revenue around August, after which every Cobalt lead loses money. Cobalt alone explains the whole network margin decline: without Cobalt, network margin went up slightly from January to June. Action: freeze Cobalt payouts now, find out who approved the monthly increases, and roll back toward the January rate.

**2. Flat revenue hides lost clients. -$43.8K a month from Everpeak and Summit, covered by one new advertiser.**
Everpeak Solar was capped overnight on 1 April, from about 377 clicks a day to exactly 60, and its price per lead then fell from $125 to $56. That is about $27K a month of lost profit. Summit Tax Advisors cut volume in two steps, on 1 May and 1 June, with price and margin unchanged. That is about $17K a month and is most likely a post-tax-season budget cut, not a lost client, but we have no 2024 data to prove it. Lumen Energy, new in March, now earns $38K a month and covers almost all of it. Total revenue looks flat (+2% since January), but profit is down 12%. Action: AEs get the reason and a restart date from Everpeak and Summit this week, and check whether Everpeak's solar budget simply moved to Lumen (same AE, same vertical).

**3. Cascade Traffic is quietly raising its price. Vertex Clicks is the biggest margin opportunity.**
On every offer it runs, Cascade's share of revenue rises each month, while the advertisers pay the same. Its margin fell from 42% to 14%, costing $4.6K in June and more every month. This is why BlueHarbor and Everpeak look bad only with Cascade. Separately, Vertex Clicks earns us 15% on BlueHarbor, Northwind and Summit, where other publishers earn 40% on the same offers. That is not a loss, because it has been flat all year. It is up to $21K a month of upside if we can get the same volume at network rates, which we do not know yet. Action: reset Cascade to January rates now. Then test Vertex by renegotiating its rate, or moving a slice of its volume to Apex and Meridian, and see whether the volume holds.

## What I would build next and why

1. **A payout rate alert.** Two of the three stories are payout rates drifting up month after month without anyone noticing. A daily check on payout per conversion by offer x publisher, with an alert when it moves more than a few percent, would have caught Cobalt in February instead of June.
2. **Daily and weekly views with change detection.** Everpeak, Summit and Cobalt all changed on a specific day, which monthly totals blur. A daily chart per advertiser that marks step changes automatically would point straight to the date and the cause.
3. **A profit bridge.** A waterfall that splits each month's profit change into volume, price per lead, payout rate and mix (new and lost advertisers). That turns "profit is down" into "why" in one chart, and is how the CEO points above were built by hand.
4. **Prior-year data and targets.** Loading 2024 would settle the Summit seasonality question. Adding budgets or targets per AE would show what is on plan and what is not, not just what changed.
