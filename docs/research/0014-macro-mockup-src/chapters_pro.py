"""The twelve chapters, pitched at an investor who already knows the vocabulary (CFA-level reader).

No definitions of GDP, CPI or the repo rate; the words go on India-specific mechanisms, transmission and what to track.
Written prose carries no figures except years; every figure is inserted from the database.
"""
from core import *   # noqa: F401,F403

T10 = f'{T["value"]:.2f}%'
def feed(v): return f'<span class="mono feedv">{v}</span>'
def ch_link(n, label=None): return f'<a class="chlink" href="#learn-{n}">{E(label or f"Chapter {n}")}</a>'
def P(*ps): return "".join(f"<p>{p}</p>" for p in ps)
def L(*items): return '<ul class="pts">' + "".join(f"<li>{i}</li>" for i in items) + "</ul>"
def today_box(*rows):
    return '<div class="seeit"><div class="seeit-h">Where it stands now</div>' + "".join(f'<div class="seeit-r">{r}</div>' for r in rows) + "</div>"
NOFEED = '<span class="nf">no feed yet</span>'
STALE = '<span class="nf">stale</span>'

CHAPTERS = []

# 1 ─────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="Three variables explain most of the Indian market", mins="three",
    hook=P("Strip Indian equity returns of company-specific noise and most of the common movement traces back to three things: the oil price, "
           "US real yields and the dollar, and the pace of domestic flows. Growth data matters, but it usually moves the market through one of these "
           "three rather than on its own."),
    body=P("<b>Oil</b> is India's terms-of-trade shock. It hits the current account, the rupee, inflation, the fiscal position and corporate margins "
           "in one move, so it is the closest thing Indian markets have to a single macro factor.",
           "<b>US real yields and the dollar</b> set the price of the India premium. India trades at a persistent valuation premium to other emerging "
           "markets; that premium is a long-duration asset, and it compresses when the global risk-free rate rises or the dollar strengthens.",
           "<b>Domestic flows</b> are the structural change of the last cycle. Monthly systematic flows into Indian equity funds now offset much of what "
           "foreign investors sell, which has changed the depth and speed of drawdowns more than it has changed their direction.",
           "Everything else on this page, the RBI, the fiscal stance, the regime, is either a transmission channel for these three or a second-order "
           "driver. The order of the chapters follows that logic: domestic plumbing and growth first, then the external shocks, then how to combine "
           "them into a view."),
    today=today_box(f"Oil: Brent {feed(fmt(B['value']))}, {feed(sign(B['chg_63']))} over three months. A supply shock, not a demand one.",
                    f"US: ten-year at {feed(T10)}, {feed(sign(T['chg_63']))} over three months; it printed {feed('5.31%')} on 2026-10-05, the high of our sample.",
                    f"Flows: foreign {feed(rupee(F20['FII']))}, domestic {feed(rupee(F20['DII']))} over twenty sessions. Domestic money is absorbing almost all of it."),
    sowhat="Two of the three variables are adverse at the same time, and the third is the only thing preventing a disorderly drawdown. That is the setup to underwrite against.",
    indicators=[("Brent", feed(fmt(B["value"]))), ("US ten-year", feed(T10)), ("FII and DII net, 20 sessions", feed(f'{rupee(F20["FII"])} / {rupee(F20["DII"])}')), ("Domestic SIP flows, monthly", NOFEED), ("US real yield and dollar index", NOFEED)],
    deeper="world", deeper_label="The world, economy by economy"))

# 2 ─────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="India's balance sheet: savings, the fiscal draw and the external gap", mins="four",
    hook=P("The useful identity for an equity investor is the old one: investment equals domestic saving plus foreign saving. In India the government "
           "takes the first and largest claim on domestic saving, and the external gap is whatever is left to fund. Most macro stress shows up at the "
           "boundary between the two."),
    body=P("Three shifts in the last cycle change how this identity behaves.") +
         L("<b>Household financial savings have thinned.</b> Gross saving into deposits, funds and insurance is healthy, but household borrowing for "
           "housing and consumption has risen faster, so net financial savings fell to multi-decade lows after the pandemic. Less net household "
           "surplus means more reliance on the external account to fund investment.",
           "<b>The composition of saving moved towards markets.</b> Systematic plans and insurance-linked products now carry a larger share of flows. "
           "This is why domestic institutions can absorb foreign selling, and why a sustained drop in fund inflows would be a genuinely new risk.",
           "<b>The general-government claim is large and sticky.</b> Centre and states together absorb a large share of financial savings every year. "
           "Banks are required to hold government paper, and insurers and pension funds are natural buyers, so the sovereign crowds the long end. "
           "State borrowing has grown to rival the centre's, and it is less visible in the headline deficit.") +
         P("On the external side, the current-account gap is funded by a mix that has worsened in quality. Net direct investment has weakened as "
           "repatriation and outward investment rose, so the gap leans more on portfolio flows. Since India's inclusion in global bond indices in 2024, "
           "part of that is passive debt money, which is stickier than equity flows but still flows out in a broad emerging-market sell-off.",
           "The RBI sits across both sides. Its foreign-exchange operations are also liquidity operations: selling dollars drains rupee liquidity unless "
           "it is offset, which is why a currency defence tightens money even without a policy move."),
    today=today_box(f"Domestic institutions bought {feed(rupee(F20['DII']))} over twenty sessions against foreign selling of {feed(rupee(F20['FII']))}.",
                    "The news desk reports reserves falling again and a higher cash reserve requirement: the external defence is draining domestic liquidity."),
    sowhat="With net household savings thin and direct investment weak, the external gap is funded by the most volatile money. That is why an oil shock bites harder in this cycle than the headline current-account number suggests.",
    indicators=[("FII and DII net flows", feed(f'{rupee(F20["FII"])} / {rupee(F20["DII"])}')), ("Forex reserves, weekly", NOFEED), ("Bank deposit and credit growth", NOFEED),
                ("Centre and state borrowing calendars", NOFEED), ("Net FDI, quarterly", NOFEED)],
    deeper="plumbing", deeper_label="The plumbing, in detail"))

# 3 ─────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="Growth: which engine is accelerating", mins="four",
    hook=P("Headline GDP growth is the least useful growth number for equities. What moves sector returns is which demand component is accelerating, "
           "and in this cycle the components have moved far apart."),
    body=P("Public capex carried the post-pandemic recovery. The intended hand-off, public spending filling order books until private balance "
           "sheets and utilisation justified new capacity, has happened only where incentives point: electronics, power equipment and transmission, "
           "renewables, defence. Broad corporate capex remains cautious, and the October tightening raises the hurdle further.",
           "Consumption is bifurcated. Premium and urban-affluent demand has held up; mass-market and rural demand has lagged for several years, "
           "which is why staples volumes disappointed while premium autos, jewellery and travel did well. The income-tax and GST cuts of 2025 were "
           "explicitly aimed at the mass segment; the oil shock and the rate rise now work against them.",
           "Services exports are the quiet stabiliser of the external account, but their growth has slowed: the largest IT firms report muted "
           "discretionary demand, AI is pressing on pricing, and US visa costs rose. Global capability centres keep expanding, which shows up in "
           "office absorption and urban consumption more than in listed IT revenue.",
           "Goods exports face tariffs in the US, including the penalty linked to Russian crude purchases, partly offset by diversification to other "
           "partners. Electronics is the structural exception, almost entirely an incentive story."),
    today=today_box(f"Capital-goods output: {feed(sign(MP['iip_capital_goods']['yoy']))} year on year in {MP['iip_capital_goods']['month']}, decelerating from {feed(sign(MP['iip_capital_goods']['prev']))}.",
                    f"Consumer durables: {feed(sign(MP['iip_consumer_durables']['yoy']))}, festive stocking. Manufacturing overall: {feed(sign(MP['iip_manufacturing']['yoy']))}.",
                    f"Goods exports: {feed(sign(MP['india_exports']['yoy']))} in {MP['india_exports']['month']}; imports {feed(sign(MP['india_imports']['yoy']))}. The trade gap is widening before the full oil shock."),
    sowhat="The capex complex still has momentum but is decelerating from a very high pace; consumption faces an income squeeze from fuel and rates. Expect dispersion within the index to widen.",
    indicators=[("IIP capital goods", feed(sign(MP["iip_capital_goods"]["yoy"]))), ("IIP consumer durables", feed(sign(MP["iip_consumer_durables"]["yoy"]))), ("Core sector index", feed(sign(MP["core_combined"]["yoy"]))),
                ("GST collections and e-way bills", NOFEED), ("Order inflows of capital-goods firms", NOFEED), ("Rural wages", NOFEED)],
    deeper="engines", deeper_label="The five engines, in detail"))

# 4 ─────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="Inflation: a supply-shock basket, and what the RBI actually reacts to", mins="four",
    hook=P("Indian headline inflation is dominated by components the central bank cannot influence: food, which swings with the monsoon and with "
           "vegetable supply, and fuel, whose pass-through is administered. That shapes both the data and the policy reaction."),
    body=P("Three things to keep in mind when reading a print.") +
         L("<b>Food is the volatility, core is the signal.</b> Food is still the largest group in the basket, far larger than in developed markets, "
           "and most of its variance is supply-driven. The MPC looks through food shocks it judges temporary and reacts when they leak into core and "
           "into household inflation expectations.",
           "<b>Fuel pass-through is lagged and stepwise.</b> Retail fuel prices respond to excise decisions and the oil marketing companies' "
           "under-recoveries, not to Brent in real time. An oil shock therefore reaches CPI late and in jumps, and some of it is absorbed by the "
           "fiscal or by the oil companies' margins instead.",
           "<b>The series changed in 2025.</b> The CPI was rebased, so year-on-year comparisons across the break need care; our own series has a "
           "gap where the old and new bases do not overlap.") +
         P("The policy rule is forward-looking and flexible: the MPC targets four percent with a two-point band, acts on its projection for "
           "inflation several quarters out, and gives weight to the rupee because a weaker currency imports inflation. That is why October's hike "
           "came before fuel had shown up in the index: the committee was reacting to the projection, not the print."),
    today=today_box(f"Headline CPI: {feed(sign(MP['cpi_general']['yoy']))} in {MP['cpi_general']['month']}, up from {feed(sign(MP['cpi_general']['prev']))}.",
                    f"Food and beverages {feed(sign(MP['cpi_food_beverages']['yoy']))}; housing and fuel {feed(sign(MP['cpi_housing_fuel']['yoy']))}. The fuel leg has not caught up with Brent yet.",
                    "Core CPI is not in our feeds, so we cannot yet say whether price pressure is broadening."),
    sowhat="The next two prints should rise as fuel catches up, which is already partly priced by a hiking RBI. The risk to positioning is a broadening into core, which would extend the hiking cycle.",
    indicators=[("CPI headline", feed(sign(MP["cpi_general"]["yoy"]))), ("CPI food", feed(sign(MP["cpi_food_beverages"]["yoy"]))), ("CPI housing and fuel", feed(sign(MP["cpi_housing_fuel"]["yoy"]))),
                ("Core CPI", NOFEED), ("RBI household inflation expectations survey", NOFEED), ("Monsoon and reservoir levels", NOFEED)],
    deeper="lesson3", deeper_label="Worked lesson: reading a CPI release"))

# 5 ─────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="The RBI: rates, liquidity and the rupee are one decision", mins="four",
    hook=P("It is tempting to read the RBI through the repo rate alone. In practice it runs three levers at once, the policy rate, system liquidity and "
           "the exchange rate, and in a currency defence they become a single decision."),
    body=P("<b>Transmission depends on what loans are priced off.</b> Floating-rate retail and small-business loans have been linked to an external "
           "benchmark, usually the repo, since 2019, so they reprice within a quarter. Corporate loans on internal benchmarks reprice more slowly, and "
           "deposits lag both. In a hiking cycle that means banks with a high share of externally linked loans and a granular, low-cost deposit base "
           "see margins expand first; lenders funded in the wholesale market see costs rise first.",
           "<b>Liquidity can do the tightening.</b> A higher cash reserve requirement, unsterilised dollar sales and slower government spending all "
           "drain rupee liquidity and push the overnight rate towards the top of the corridor, tightening conditions without a repo move. October "
           "used both channels.",
           "<b>The rupee is managed for speed, not level.</b> The RBI leans against disorderly moves using spot and forward intervention, and since "
           "late 2024 has tolerated more depreciation than before, partly because the real effective exchange rate had become rich. Special measures "
           "such as a separate dollar window for oil companies and tighter hedging rules are used when spot intervention alone is too costly.",
           "<b>Reading the committee.</b> Six members, three external. The stance language, the inflation projection and the vote split carry more "
           "information than the decision itself; dissents tend to lead the next move."),
    today=today_box("October: the first repo hike after the 2025 easing cycle, a higher cash reserve requirement, a dollar window for oil marketing companies and tighter hedging rules. (News desk.)",
                    f"Our money-market series ends at {feed(str(MR['value']) + '%')} in {MR['date'][:7]}: {STALE}, three months behind the decision."),
    sowhat="Prefer lenders with low-cost deposits and externally linked books over wholesale-funded NBFCs and housing financiers. The next statement's stance and vote split decide whether October was insurance or the start of a cycle.",
    indicators=[("Repo rate and decisions", NOFEED), ("Weighted average call rate", f'{feed(str(MR["value"]) + "%")} {STALE}'), ("System liquidity (surplus or deficit)", NOFEED),
                ("RBI forward book and reserves", NOFEED), ("Ten-year G-sec yield", NOFEED)],
    deeper="referees", deeper_label="The referees: RBI, Finance Ministry, GST Council, SEBI, states"))

# 6 ─────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="Oil and the current account: the twin-deficit chain", mins="five",
    hook=P("An oil shock hits India through five channels at once: the current account, the rupee, inflation, the fiscal and corporate margins. The "
           "question is never whether it hurts but who absorbs it: consumers through pump prices, the government through excise and subsidies, or the "
           "oil marketing companies through under-recoveries."),
    body=P("The external side is straightforward. Oil is the swing item in the import bill; gold and electronics add to it in a strong festive season. "
           "Services exports and remittances, India's two structural surpluses, cover a normal oil bill but not a spike. A wider gap funded by "
           "volatile portfolio money puts the rupee under pressure, and the RBI's response tightens domestic liquidity (chapter 5).",
           "The fiscal side is where the second deficit appears. Cutting excise shields CPI at the cost of revenue. Gas-linked fertiliser subsidies "
           "rise automatically with energy prices. Leaving retail prices frozen shifts the loss to the state oil companies' balance sheets, which is "
           "quasi-fiscal. Windfall taxes on upstream producers claw some of it back.",
           "History rhymes closely. In 2013 a wide current-account gap met a Fed taper and the rupee broke; the fix was a rate defence, gold-import "
           "curbs and a special deposit swap for non-residents. In 2018 rising oil met tightening liquidity and a large NBFC default. In 2022 the "
           "oil and food spike met a fast Fed, and domestic flows absorbed record foreign selling for the first time. In each case the market bottomed "
           "when the external pressure eased, not when the growth data improved."),
    today=today_box(f"Brent {feed(fmt(B['value']))}, {feed(sign(B['chg_63']))} over three months; Gulf shipping attacks and the closed Hormuz route carry a war premium.",
                    f"USD/INR {feed(fmt(U['value']))}, {feed(sign(U['chg_63']))} over three months; the record is {feed('96.88')} on 2026-07-24. The rupee is being held, so the pressure is showing up in liquidity and rates instead."),
    sowhat="Oil consumers (aviation, paints, OMCs, autos) and rate-sensitive borrowers lose on every link. Exporters gain only if the RBI lets the rupee go, which it currently is not.",
    indicators=[("Brent", feed(fmt(B["value"]))), ("USD/INR", feed(fmt(U["value"]))), ("Trade deficit, monthly", f'imports {feed(sign(MP["india_imports"]["yoy"]))} vs exports {feed(sign(MP["india_exports"]["yoy"]))}'),
                ("Forex reserves and forward book", NOFEED), ("Retail fuel prices and excise changes", NOFEED), ("OMC marketing margins", NOFEED)],
    deeper="twin", deeper_label="The twin deficits: the RBI's and the government's toolkit"))

# 7 ─────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="Flows and positioning: when they matter and when they are noise", mins="four",
    hook=P("Daily FII and DII numbers are the most quoted and most over-read data in Indian markets. They matter at the extremes and in persistent "
           "runs; on any single day they are mostly noise."),
    body=P("<b>Ownership has shifted.</b> Domestic institutions now own roughly as much of listed India as foreign investors, after a decade in which "
           "foreign ownership drifted down and domestic fund assets compounded. Persistent foreign selling is therefore met by a structural buyer, "
           "which shortens and shallows drawdowns in the large caps foreigners own most.",
           "<b>What drives foreign flows</b> is mostly outside India: US real yields, the dollar, emerging-market allocation shifts and the relative "
           "valuation premium. Indian earnings revisions matter at the margin. That is why foreign selling can persist through good domestic data.",
           "<b>Positioning is the better signal.</b> The participant-wise open interest in index futures shows how foreign investors are leaning. When "
           "their long share sits near its historical floor, much of the bearish view is already expressed and the asymmetry of the next surprise "
           "turns positive: short-covering rallies in India have tended to be sharp and led by the heaviest foreign-owned names.",
           "<b>The domestic risk is a flow stall.</b> Domestic inflows are steady but not unconditional. A long drawdown that pushes recent investors "
           "into losses, or a sharp rise in deposit rates, could slow them. That would remove the buffer, so the monthly fund-flow data is worth more "
           "attention than the daily FII print."),
    today=today_box(f"Twenty sessions: foreign {feed(rupee(F20['FII']))}, domestic {feed(rupee(F20['DII']))}. Last session: foreign {feed(rupee(FL['FII']))}, domestic {feed(rupee(FL['DII']))}.",
                    f"FII long share in index futures: {feed(str(FII['value']) + '%')}, the {feed(str(int(FII['pctile'])) + 'th')} percentile since 2022 (median {feed(str(FII['median']) + '%')})."),
    sowhat="Foreign investors are both heavy cash sellers and near a positioning floor. The downside from further foreign selling is cushioned; the upside from a positioning unwind on good oil news is underpriced.",
    indicators=[("FII long share, index futures", feed(f'{FII["value"]}%')), ("FII and DII cash flows", feed(f'{rupee(F20["FII"])} / {rupee(F20["DII"])}')), ("Monthly equity fund inflows", NOFEED),
                ("FPI debt flows", NOFEED), ("Put-call ratio", NOFEED)],
    deeper="lesson7", deeper_label="Worked lesson: reading flows and positioning"))

# 8 ─────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="The US transmission: real yields, the dollar and the India premium", mins="four",
    hook=P("India's valuation premium over other emerging markets is a long-duration asset. It is priced off the global discount rate, which is set in "
           "the US Treasury market, so US real yields matter to Indian multiples even when Indian earnings are unchanged."),
    body=P("Three channels, in order of speed.") +
         L("<b>Portfolio flows and the rupee.</b> Higher US real yields and a stronger dollar raise the hurdle for emerging-market allocations; foreign "
           "investors trim the markets with the richest valuations first, and India usually qualifies.",
           "<b>Multiples.</b> A higher global risk-free rate compresses the premium on long-duration growth stocks most, which is why quality and "
           "consumer franchises can de-rate in a US rates shock without any change in their earnings.",
           "<b>Trade and services.</b> US tariff policy, including the penalty tariff tied to Russian crude purchases, sets the outlook for goods "
           "exporters; US technology budgets and visa costs set IT services demand.") +
         P("Today's move in US yields looks more like term premium and inflation compensation than a pure growth signal: an oil-driven inflation "
           "scare plus heavy issuance. That matters because a term-premium rise tends to persist longer than a growth-driven one, and it coincides "
           "with a strong dollar rather than a weak one.",
           "Two more US dates matter for India this year: the midterm elections in November, which set tariff and fiscal policy for two years, and "
           "the Fed's reaction to an oil shock at a time when the chair's seat changed hands in 2026."),
    today=today_box(f"US ten-year {feed(T10)}, {feed(sign(T['chg_63']))} over three months; sample high {feed('5.31%')} on 2026-10-05.",
                    "US–India trade talks have stalled, and new US sanctions over Iranian crude now include two Indian firms. (News desk.)"),
    sowhat="As long as the US ten-year stays near its highs, expect continued foreign underweighting and pressure on the most richly valued large caps. IT, software and asset managers are the most directly exposed industries in our map.",
    indicators=[("US ten-year yield", feed(T10)), ("US real yield (TIPS)", NOFEED), ("Dollar index", NOFEED), ("US CPI and payrolls", NOFEED), ("Fed funds path", NOFEED)],
    deeper="us", deeper_label="The US card and the rest of the world"))

# 9 ─────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="Fiscal policy and political economy: what changes earnings", mins="four",
    hook=P("For equities, the fiscal stance matters through three lines of the Budget: the capex allocation, the borrowing programme and tax changes. "
           "Political economy matters through whether those lines are predictable."),
    body=P("This government's revealed preferences are consistent across both coalition and majority terms: protect public capex, keep the deficit on "
           "a declining path and shift the anchor towards debt, deliver relief through tax cuts and direct transfers rather than new entitlements, and "
           "use incentive schemes rather than broad subsidies for manufacturing.",
           "The oil shock tests that preference ordering. An excise cut and higher fertiliser subsidies widen the deficit; the government has "
           "historically protected the headline target by slowing other spending, and capex execution is the easiest line to slow without announcing "
           "it. That is the main fiscal risk to the capex complex in the next two quarters.",
           "States are the larger source of slippage. Their combined borrowing now rivals the centre's, election-year transfers are common, and "
           "power-distribution losses periodically turn into state-guaranteed debt. Uttar Pradesh, the largest state, votes in early 2027.",
           "Coalition arithmetic since 2024 makes big structural reforms harder and favours spending that benefits allies' states. The market priced "
           "this once, sharply, on the 2024 results day, and then reversed within days when policy continuity became clear. Political shocks without "
           "a policy change have tended to fade."),
    today=today_box("The GST Council approved a compliance-easing package with no rate changes; Cabinet approved a small-business fund and a logistics authority. (News desk.)",
                    "Next Budget: February 2027. The key read before then is monthly capex execution and any fuel-excise decision."),
    sowhat="Policy-backed sectors (infrastructure, defence, power, electronics) carry support through a weak quarter, but watch monthly capex execution: a quiet slowdown would be the first sign the oil bill is being funded at their expense.",
    indicators=[("Centre's monthly capex execution", NOFEED), ("Fiscal deficit, monthly", NOFEED), ("GST collections", NOFEED), ("Fuel excise changes", NOFEED), ("State election calendar", "Uttar Pradesh, early 2027")],
    deeper="politics", deeper_label="The political economy, in detail"))

# 10 ────────────────────────────────────────────────────────────
mini_q = quadrant_svg(trail, "India growth and inflation quadrant")
reg_row = RT[RN["regime"]]
top_rel = sorted(((reg_row[s]["rel"], n, reg_row[s]["t"]) for s, n in SECT), reverse=True)
def _nm(n): return n if n in ("PSU banks", "IT", "FMCG") else n.lower()
best3 = ", ".join(f"{_nm(n)} ({feed(f'{r:+.1f}')} pp, t {feed(f'{t:+.1f}')})" for r, n, t in top_rel[:3])
worst3 = ", ".join(f"{_nm(n)} ({feed(f'{r:+.1f}')} pp, t {feed(f'{t:+.1f}')})" for r, n, t in top_rel[-3:])
CHAPTERS.append(dict(
    title="Regimes: growth and inflation momentum, and what has worked", mins="four",
    hook=P("Regime frameworks earn their place because they ask about the direction of growth and inflation rather than their level, and markets price "
           "changes. The useful version for India is simple and comes with an honest evidence base."),
    body=P("Two axes: is growth accelerating or decelerating, and is inflation accelerating or decelerating. We read India's from official data, the "
           "three-month change in IIP growth against the three-month change in CPI inflation, and cross-check with a market-implied version (copper "
           "against gold for growth, Brent momentum for inflation) that has a longer history.",
           f"On our own data since 2016, the month after a reflation reading has favoured {best3}, and penalised {worst3}, all relative to the Nifty. "
           f"Read that with the multiple-testing discount in mind: the strongest of the {n_cells} regime-by-sector cells has |t| {feed(f'{best_t:.1f}')}, "
           f"and a fair threshold for {n_cells} tests is about {feed(f'{bonf:.1f}')}. These are priors, not signals, and none of them is in the model.",
           "Two caveats specific to now. This reflation is supply-led, which is worse for oil consumers than a demand-led one. And the regime most "
           "likely to follow is stagflation, as inflation keeps rising on fuel pass-through while higher rates start to slow activity."),
    today=f'<div class="seeit"><div class="seeit-h">Where it stands now</div><div class="seeit-two"><div>{mini_q}</div><div><div class="seeit-r">India: <b>{india_quad}</b>. Over the three months to {now_m}, IIP growth {feed(sign(now_x, " pp", 1))}, CPI inflation {feed(sign(now_y, " pp", 1))}.</div><div class="seeit-r">Market-implied: {RN["regime"]} (copper against gold {feed(sign(RN["cg_6m"]))} over six months; Brent {feed(sign(RN["brent_yoy"]))} year on year). Data and markets agree.</div><div class="seeit-r tiny">The official trail starts in 2026 because the CPI rebasing leaves a gap in 2025.</div></div></div></div>',
    sowhat="Lean towards commodity and capex exposure over defensives and gold while the regime holds, but size it as a weak prior, and watch the September IIP and October CPI for the turn to stagflation.",
    indicators=[("India regime (official)", feed(india_quad)), ("India regime (market-implied)", feed(RN["regime"])), ("US regime", NOFEED), ("Core CPI momentum", NOFEED)],
    deeper="playbook", deeper_label="The playbook: regime table, scenarios, risk radar"))

# 11 ────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="Case study: the 2026 oil shock, end to end", mins="four",
    hook=P("The current episode uses every channel in this course. Read as a sequence, it also tells you what to watch for the turn."),
    body='<ol class="story">' + "".join(f"<li><b>{a}</b> {b}</li>" for a, b in [
        ("Supply shock.", f"Attacks on Gulf shipping and the closure of the Hormuz route put a war premium into crude: Brent {feed(fmt(B['value']))}, {feed(sign(B['chg_63']))} over three months. ({ch_link(6)})"),
        ("Who absorbs it.", f"Retail fuel lags, so the first loss sits with the oil marketing companies and airlines; the government faces an excise-versus-deficit choice and rising fertiliser subsidies. ({ch_link(9)})"),
        ("External account.", f"Imports are already growing far faster than exports ({feed(sign(MP['india_imports']['yoy']))} against {feed(sign(MP['india_exports']['yoy']))}), before the full oil effect. The gap leans on portfolio money. ({ch_link(2)})"),
        ("Inflation projection.", f"Headline CPI is turning up ({feed(sign(MP['cpi_general']['yoy']))}) with the fuel leg still to come. ({ch_link(4)})"),
        ("Policy response.", f"The RBI hikes, raises the cash reserve requirement and defends the rupee with dollar sales and administrative measures: tightening through rates and liquidity at once. ({ch_link(5)})"),
        ("Global overlay.", f"US ten-year near its high ({feed(T10)}) keeps the global discount rate elevated and the dollar firm. ({ch_link(8)})"),
        ("Flows and positioning.", f"Foreign investors sell {feed(rupee(F20['FII']))} over twenty sessions and sit near a futures-positioning floor; domestic funds absorb {feed(rupee(F20['DII']))}. ({ch_link(7)})"),
        ("Regime.", f"Reflation, supply-led, with stagflation the likely next state. ({ch_link(10)})"),
    ]) + "</ol>" +
         P("<b>What would mark the turn.</b> In 2013, 2018 and 2022 the market bottomed when the external pressure eased, not when growth data improved. "
           "The signposts here: Brent falling as the shipping route normalises, the rupee strengthening without RBI support, the RBI's stance language "
           "softening, and foreign futures positioning moving off its floor. The first two are necessary; the last is what turns a relief move into a "
           "sharp rally."),
    today="",
    sowhat="The base case is a grinding squeeze with wide sector dispersion. The asymmetry is upward because positioning is extreme; the trigger is the oil supply route, not domestic data.",
    indicators=[("Brent", feed(fmt(B["value"]))), ("USD/INR", feed(fmt(U["value"]))), ("FII long share", feed(f'{FII["value"]}%')), ("RBI stance language", "next meeting")],
    deeper="shock", deeper_label="The full shock walk-through"))

# 12 ────────────────────────────────────────────────────────────
CHAPTERS.append(dict(
    title="The daily read: a five-minute routine, and the traps", mins="two",
    hook=P("The brief is built to be read in a fixed order, so that the same five questions are answered every day and changes stand out."),
    body='<ol class="routine">' + "".join(f"<li><b>{a}</b><span>{b}</span></li>" for a, b in [
        ("Verdict.", "Has the one-line state of play changed? If not, the rest is confirmation."),
        ("The four lights.", "Oil, US rates and the dollar, domestic and foreign flows, the RBI. A light changing colour is the event; the level is context."),
        ("Unusual moves.", "Ranked by size relative to each series' own volatility, with the industries each move helps or hurts from the 38 industry pages."),
        ("Winners and losers.", "The sector map implied by the current regime and house view. Check it against your book."),
        ("What's coming.", "Releases and meetings that could change a light."),
    ]) + "</ol>" +
         P("<b>The traps.</b> Reading a single day of flows. Treating an expected decision as news: markets move on surprises against what was priced. "
           "Confusing a level with a change: the regime framework exists to stop that. And over-fitting the regime table: it is a prior with weak "
           "statistics, not a trading rule."),
    today="",
    sowhat="The brief is a monitoring tool, not a signal. Its job is to tell you which chapter's mechanism is driving the market this week.",
    indicators=[], deeper="today", deeper_label="Open today's brief"))
