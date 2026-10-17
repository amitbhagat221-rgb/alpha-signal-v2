"""Mockup v5 chapters: a prologue, an India framework, a global and geopolitical framework, and a synthesis track.
Every chapter has at least one chart or diagram and a history block. Written prose carries no figures except years;
figures in charts, tables and 'where it stands' boxes come from the database (core.py, data2.json)."""
import json
from pathlib import Path
from core import *          # noqa: F401,F403
import charts as C

D2 = json.loads(Path(__file__).with_name("data2.json").read_text())
T10 = f'{T["value"]:.2f}%'
REC = D2["records"]
def feed(v): return f'<span class="mono feedv">{v}</span>'
def P(*ps): return "".join(f"<p>{p}</p>" for p in ps)
def Lst(*items): return '<ul class="pts">' + "".join(f"<li>{i}</li>" for i in items) + "</ul>"
def fig(svg, cap): return f'<div class="fig">{svg}<div class="fig-cap">{cap}</div></div>'
def stand(*rows): return '<div class="seeit"><div class="seeit-h">Where it stands now</div>' + "".join(f'<div class="seeit-r">{r}</div>' for r in rows) + "</div>"
def history(title, rows, note=""):
    body = "".join(f"<tr><td>{a}</td><td><b>{E(b)}</b><div class='tiny-t'>{c}</div></td><td class='tiny-t'>{d}</td></tr>" for a, b, c, d in rows)
    return (f'<div class="histblock"><div class="hb-h">History · {E(title)}</div><table class="hist-t"><thead><tr><th>When</th><th>What happened</th><th>Lesson</th></tr></thead>'
            f'<tbody>{body}</tbody></table>{f"<div class=fig-cap>{note}</div>" if note else ""}</div>')
NOFEED = '<span class="nf">no feed yet</span>'
STALE = '<span class="nf">stale</span>'
def ch_link(cid, label): return f'<a class="chlink" href="#{cid}">{E(label)}</a>'

EPIS = {e["label"]: e for e in D2["episodes"]}
EPI_BANDS = [("2015-08-11", "2016-02-29", "Yuan deval"), ("2018-01-15", "2018-10-31", "Oil + IL&FS"), ("2020-02-15", "2020-04-30", "Covid"),
             ("2022-02-15", "2022-06-30", "Ukraine + Fed"), ("2026-02-27", "2026-10-16", "Iran war")]
EV = {e["name"]: e for e in D2["events"]}
def evline(name):
    e = EV[name]; return f'{feed(f"{e["day0"]:+.1f}%")} on the day, {feed(f"{e["min10"]:+.1f}%")} at worst within ten sessions, {feed(f"{e["d30"]:+.1f}%")} after thirty'

def mo(series):   # [['YYYY-MM', v]] -> [['YYYY-MM-01', v]]
    return [[k + "-01", v] for k, v in series]
def yo(k):        # dict month->yoy -> chart series
    return [[m + "-01", v] for m, v in sorted(D2["yoy"][k].items())]

SECT_LABEL = {"bank_nifty": "Banks", "nifty_psubank": "PSU banks", "nifty_auto": "Autos", "nifty_fmcg": "FMCG", "nifty_it": "IT", "nifty_pharma": "Pharma",
              "nifty_metal": "Metals", "nifty_energy": "Energy", "nifty_infra": "Infra", "nifty_realty": "Realty", "nifty_media": "Media", "gold": "Gold", "usdinr": "USD/INR"}

CH = []   # each: dict(id, track, title, mins, hook, body, history, today, sowhat, indicators, deeper, deeper_label)

# ═════════════════════════════ PROLOGUE ═════════════════════════════
CH.append(dict(id="pro", track="Prologue", title="Three variables, two frameworks", mins="three",
    hook=P("Strip Indian equity returns of company noise and most of the common movement traces back to three variables: the oil price, US real "
           "yields and the dollar, and the pace of domestic flows. The first two arrive from outside India; the third is built at home. That is why "
           "this course has two frameworks, an Indian one and a global and geopolitical one, and a short synthesis that joins them."),
    body=fig(C.stacked(
        C.line_panel(D2["w_brent_crude"], label="Brent, $ a barrel", color="#d97706", episodes=EPI_BANDS, h=130, show_years=False),
        C.line_panel(D2["w_us_10y"], label="US ten-year yield, %", color="var(--blue)", episodes=EPI_BANDS, h=130, fmt="{:.1f}", show_years=False),
        C.line_panel(D2["w_nifty50"], label="Nifty 50", color="var(--accent)", episodes=EPI_BANDS, h=150)),
        "Weekly closes since mid-2015, one axis per panel. Shaded: the five stress episodes this course keeps returning to. Every shaded Nifty drawdown "
        "lines up with a move in at least one of the two outside variables.") +
         P("<b>The India framework</b> covers what is built at home: the national balance sheet, growth engines, inflation, the RBI's three levers, "
           "the oil and rupee chain as India experiences it, flows and positioning, fiscal policy and politics, and a decade of Indian drawdowns.",
           "<b>The global and geopolitical framework</b> covers what arrives from outside: how six economies reach India, the dollar and US rates, oil "
           "and the Gulf's chokepoints, China as the world's price-setter, Europe and Japan, Russia and the sanctions era, and conflict on India's own "
           "borders.",
           "<b>The synthesis</b> combines both into a regime view, works through the current shock end to end, and sets out the daily routine."),
    history=history("how the three variables took turns", [
        ("1991", "Oil and remittances", "The Gulf war spiked oil and stopped Gulf remittances; India ran out of reserves.", "Oil plus a thin external buffer is India's oldest crisis recipe."),
        ("2013", "US rates", "A Fed taper hint pulled foreign money out of India's bonds and the rupee broke.", "US rates matter most when India's external gap is wide."),
        ("2020–21", "Domestic flows arrive", "Retail investors opened accounts in record numbers and monthly fund flows took off.", "A structural domestic buyer changes how deep sell-offs go."),
        ("2022", "All three at once", "Oil spiked, the Fed hiked fastest in decades, domestic funds absorbed record foreign selling.", "The market fell, but far less than the flows would once have implied."),
    ]),
    today=stand(f"Brent {feed(fmt(B['value']))}, {feed(sign(B['chg_63']))} over three months; US ten-year {feed(T10)}, sample high {feed('5.31%')} on 2026-10-05.",
                f"Foreign {feed(rupee(F20['FII']))}, domestic {feed(rupee(F20['DII']))} over twenty sessions."),
    sowhat="Two of the three variables are adverse at once and domestic flows are the buffer. Start with whichever track explains the variable you understand least.",
    indicators=[("Brent", feed(fmt(B["value"]))), ("US ten-year", feed(T10)), ("FII / DII, 20 sessions", feed(f'{rupee(F20["FII"])} / {rupee(F20["DII"])}'))],
    deeper="world", deeper_label="The world, economy by economy"))

# ═════════════════════════════ INDIA FRAMEWORK ═════════════════════════════
CH.append(dict(id="in-1", track="India", title="India's balance sheet: savings, the fiscal draw and the external gap", mins="five",
    hook=P("Investment equals domestic saving plus foreign saving. In India the government takes the first and largest claim on domestic saving, "
           "and the external gap is whatever is left to fund. Most Indian macro stress shows up at the boundary between the two."),
    body='''<div class="flow4"><div><b>Households save</b><span>deposits, funds, insurance, gold, property</span></div><div class="arr">→</div>
         <div><b>Intermediaries pool</b><span>banks lend; funds and insurers buy shares and bonds</span></div><div class="arr">→</div>
         <div><b>Claims on saving</b><span>government first, then companies and households</span></div><div class="arr">→</div>
         <div><b>External gap</b><span>funded by FDI, portfolio flows, loans, NRI deposits</span></div></div>''' +
         Lst("<b>Household net financial savings have thinned.</b> Gross saving into financial assets is healthy, but household borrowing for housing "
             "and consumption rose faster after the pandemic, so the net surplus fell to multi-decade lows. A thinner household surplus leaves more of "
             "investment to be funded from abroad.",
             "<b>The composition moved towards markets.</b> Systematic plans and insurance-linked products carry a larger share of flows, which is why "
             "domestic institutions can now absorb foreign selling.",
             "<b>The sovereign claim is large and sticky.</b> Centre and states together absorb a large share of financial savings. Banks must hold "
             "government paper; insurers and pension funds are natural long-end buyers. State borrowing now rivals the centre's.",
             "<b>The external funding mix has worsened.</b> Net direct investment weakened as repatriation and outward investment rose, so the gap "
             "leans on portfolio money, part of it passive bond-index money since India joined global bond indices in 2024.") +
         fig(C.line_panel([[d, g] for d, g, n in D2["w_gold_vs_nifty"]], label="Gold in rupees, indexed to 100 in mid-2015", color="#d97706", h=140, show_years=False) +
             C.line_panel([[d, n] for d, g, n in D2["w_gold_vs_nifty"]], label="Nifty 50, indexed to 100 in mid-2015", color="var(--accent)", h=150),
             "The household's two big financial choices, weekly since mid-2015. Gold in rupees benefits twice in a crisis: from the dollar gold price and "
             "from a weaker rupee. That is part of why Indian households never fully left it."),
    history=history("the balance sheet under stress", [
        ("1991", "Balance-of-payments crisis", "Reserves fell to a few weeks of imports; India pledged gold and devalued.", "The external account is the binding constraint, not growth."),
        ("2003", "FRBM Act", "A legal glide path for the fiscal deficit.", "Fiscal anchors are credible until a shock tests them; it was suspended in 2008."),
        ("2008–09", "Stimulus and slippage", "The deficit widened sharply to fight the global crisis.", "Slippage funded growth then fed the inflation of 2010–13."),
        ("2013", "Fragile Five", "A wide current-account gap met a US taper; the rupee fell to a record.", "A wide gap funded by hot money is the vulnerable configuration."),
        ("2020–23", "Household balance-sheet shift", "Savings moved to markets while borrowing jumped; net financial savings thinned.", "Domestic flows got stronger even as the household cushion got thinner."),
    ]),
    today=stand(f"Domestic institutions {feed(rupee(F20['DII']))} against foreign {feed(rupee(F20['FII']))} over twenty sessions.",
                "The news desk reports reserves falling and a higher cash reserve requirement: the external defence is draining domestic liquidity."),
    sowhat="Thin household net savings and weak direct investment mean the external gap is funded by the most volatile money. That is why an oil shock bites harder this cycle than the headline current-account number suggests.",
    indicators=[("FII / DII flows", feed(f'{rupee(F20["FII"])} / {rupee(F20["DII"])}')), ("Forex reserves, weekly", NOFEED), ("Net FDI, quarterly", NOFEED), ("Household savings, annual", NOFEED)],
    deeper="plumbing", deeper_label="The plumbing, in detail"))

CH.append(dict(id="in-2", track="India", title="Growth: which engine is accelerating", mins="four",
    hook=P("Headline GDP growth is the least useful growth number for equities. Sector returns follow whichever demand component is accelerating, and "
           "in this cycle the components have moved far apart."),
    body=fig(C.stacked(
        C.line_panel(yo("iip_capital_goods"), label="IIP capital goods, year on year %", color="var(--accent)", h=120, fmt="{:.0f}", ref=0, show_years=False),
        C.line_panel(yo("iip_consumer_durables"), label="IIP consumer durables, year on year %", color="#d97706", h=120, fmt="{:.0f}", ref=0, show_years=False),
        C.line_panel(yo("iip_manufacturing"), label="IIP manufacturing, year on year %", color="var(--blue)", h=130, fmt="{:.0f}", ref=0)),
        "Monthly, from our feeds. Capital goods has run hottest, the footprint of public and incentive-led investment; consumer durables swings with "
        "festive stocking and credit.") +
         P("Public capex carried the post-pandemic recovery. The intended hand-off, public spending filling order books until private balance sheets "
           "and utilisation justified new capacity, has happened only where incentives point: electronics, power equipment and transmission, "
           "renewables, defence.",
           "Consumption is bifurcated: premium and urban-affluent demand has held up, mass and rural demand has lagged, which is why staples volumes "
           "disappointed while premium autos and travel did well. The 2025 income-tax and GST cuts targeted the mass segment; fuel and rates now work "
           "against them.",
           "Services exports stabilise the external account but have slowed; goods exports face US tariffs, with electronics the incentive-driven "
           "exception."),
    history=history("India's capex cycles", [
        ("2003–08", "The private capex boom", "Infrastructure, power and metals capacity built on cheap credit and strong global demand.", "Booms financed by bank debt end in bad loans."),
        ("2011–19", "The twin balance-sheet problem", "Over-leveraged companies and loaded banks; stalled projects; the bad-loan clean-up and the bankruptcy code of 2016.", "Repair takes most of a decade and suppresses private capex throughout."),
        ("2019", "Corporate tax cut", "A large cut in the corporate tax rate to revive investment.", "Tax cuts lift profits faster than they lift capex."),
        ("2020–", "The state steps in", "Public capex raised sharply and kept high; incentive schemes for manufacturing.", "Public capex can fill order books but cannot force private capex."),
    ]),
    today=stand(f"Capital goods {feed(sign(MP['iip_capital_goods']['yoy']))} in {MP['iip_capital_goods']['month']}, decelerating from {feed(sign(MP['iip_capital_goods']['prev']))}; consumer durables {feed(sign(MP['iip_consumer_durables']['yoy']))}.",
                f"Imports {feed(sign(MP['india_imports']['yoy']))} against exports {feed(sign(MP['india_exports']['yoy']))} in {MP['india_exports']['month']}."),
    sowhat="The capex complex still has momentum but is decelerating from a very high pace; consumption faces an income squeeze from fuel and rates. Expect dispersion within the index to widen.",
    indicators=[("IIP capital goods", feed(sign(MP["iip_capital_goods"]["yoy"]))), ("IIP consumer durables", feed(sign(MP["iip_consumer_durables"]["yoy"]))), ("GST and e-way bills", NOFEED), ("Capital-goods order inflows", NOFEED)],
    deeper="engines", deeper_label="The five engines, in detail"))

cpi_old = yo("india_cpi_index"); cpi_new = yo("cpi_general")
CH.append(dict(id="in-3", track="India", title="Inflation: a supply-shock basket, and what the RBI reacts to", mins="four",
    hook=P("Indian headline inflation is dominated by components monetary policy cannot touch: food, which swings with the monsoon, and fuel, whose "
           "pass-through is administered. The data and the policy reaction both follow from that."),
    body=fig(C.line_panel(cpi_old + cpi_new, label="CPI inflation, year on year %", color="var(--red)", h=170, fmt="{:.0f}", ref=4,
                          markers=[("2025-04-01", "series rebased: gap")]),
             "Monthly. Dashed line: the RBI's four percent target. The break in 2025 is the CPI rebasing; the old and new series do not overlap in our "
             "feed, so year-on-year inflation is missing for most of 2025.") +
         Lst("<b>Food is the volatility, core is the signal.</b> Food is still the largest group in the basket, and most of its variance is supply-driven. "
             "The MPC looks through food shocks it judges temporary and reacts when they leak into core and household expectations.",
             "<b>Fuel pass-through is lagged and stepwise.</b> Retail fuel follows excise decisions and the oil companies' under-recoveries, not Brent in "
             "real time, so an oil shock reaches CPI late and in jumps, and part of it is absorbed fiscally.",
             "<b>The rule is forward-looking.</b> A four percent target with a two-point band, acting on the projection several quarters out and giving "
             "weight to the rupee. October's hike came before fuel reached the index."),
    history=history("India's inflation regimes", [
        ("2009–13", "The double-digit years", "Food and stimulus-driven inflation ran high for years; real deposit rates turned negative.", "Persistent inflation pushed households into gold and property."),
        ("2014–16", "Inflation targeting adopted", "An expert committee recommended CPI targeting; the formal framework and a six-member MPC followed in 2016.", "A credible target lowered inflation expectations within a few years."),
        ("2019–20", "Onion and vegetable spikes", "Headline jumped on vegetables while core stayed soft; the MPC largely looked through.", "Supply spikes in food rarely change policy on their own."),
        ("2022", "War and the global spike", "Oil, food and edible oils surged; the RBI hiked, starting between meetings.", "When food and fuel spike together, the RBI acts fast."),
        ("2025–26", "From multi-year lows to a turn", "Inflation fell to multi-year lows and the RBI cut; the oil shock reversed the direction.", "Low starting inflation buys time, but not against a currency shock."),
    ]),
    today=stand(f"Headline {feed(sign(MP['cpi_general']['yoy']))} in {MP['cpi_general']['month']} (from {feed(sign(MP['cpi_general']['prev']))}); food {feed(sign(MP['cpi_food_beverages']['yoy']))}; housing and fuel {feed(sign(MP['cpi_housing_fuel']['yoy']))}.",
                "Core CPI is not in our feeds yet, so whether pressure is broadening is still unanswered."),
    sowhat="Prints should rise over the next two months as fuel catches up, which a hiking RBI partly prices. The risk is broadening into core, which would extend the cycle.",
    indicators=[("CPI headline", feed(sign(MP["cpi_general"]["yoy"]))), ("CPI food", feed(sign(MP["cpi_food_beverages"]["yoy"]))), ("Core CPI", NOFEED), ("Household inflation expectations", NOFEED), ("Monsoon and reservoirs", NOFEED)],
    deeper="lesson3", deeper_label="Worked lesson: a CPI release"))

CH.append(dict(id="in-4", track="India", title="The RBI: rates, liquidity and the rupee are one decision", mins="five",
    hook=P("The RBI runs three levers at once, the policy rate, system liquidity and the exchange rate, and in a currency defence they become a single "
           "decision. Reading it through the repo rate alone misses most of what it does."),
    body=fig(C.diagram_levers(), "Each lever works through more than one channel; the links show the main ones.") +
         P("<b>Transmission depends on loan pricing.</b> Retail and small-business floating loans have been linked to an external benchmark, usually the "
           "repo, since 2019, and reprice within a quarter; corporate loans on internal benchmarks reprice slowly; deposits lag both. In a hiking cycle "
           "banks with externally linked books and granular deposits see margins expand first; wholesale-funded lenders see costs rise first.",
           "<b>Liquidity can tighten on its own.</b> A higher cash reserve requirement, unsterilised dollar sales and slow government spending drain "
           "rupee liquidity and lift the overnight rate within the corridor. October used both the rate and liquidity.",
           "<b>The rupee is managed for speed.</b> The RBI leans against disorderly moves with spot and forwards and, since late 2024, has tolerated "
           "more depreciation, partly because the real effective rate had become rich.") +
         fig(rate_svg(D["money_rate_hist"]), f"Money-market rate, monthly, our feed: the 2022 hiking cycle, the 2025 cuts, and a series that ends in {MR['date'][:7]}, before October's hike."),
    history=history("RBI regimes and turning points", [
        ("2013", "The rupee defence", "A new governor raised rates, curbed gold imports and opened a dollar deposit swap for non-residents.", "Administrative measures buy time that rates alone cannot."),
        ("2016", "Flexible inflation targeting", "The MPC replaced the governor's sole discretion.", "Read the committee's statement and votes, not just the decision."),
        ("2019", "External-benchmark lending", "Floating retail loans moved to an external benchmark.", "Transmission to households became fast; to companies it stayed slow."),
        ("2020", "Pandemic easing", "Rates cut to record lows and liquidity flooded in.", "Easy liquidity inflated valuations more than earnings."),
        ("2022", "The fast hikes", "A hike between meetings, then a series of large moves.", "The RBI moves fast when food and fuel spike together."),
        ("2025–26", "Cuts, then a turn", "Cuts through 2025 as inflation fell; a hike plus liquidity tightening in October.", "A first move in a new direction is the regime signal."),
    ]),
    today=stand("October: the first repo hike after the 2025 easing, a higher cash reserve requirement, a dollar window for oil companies, tighter hedging rules. (News desk.)",
                f"Our money-market series: {feed(str(MR['value']) + '%')} in {MR['date'][:7]}, {STALE}."),
    sowhat="Prefer lenders with low-cost deposits and externally linked books over wholesale-funded NBFCs and housing financiers. The next statement's stance and vote split tell you whether October was insurance or a cycle.",
    indicators=[("Repo decisions", NOFEED), ("Call rate", f'{feed(str(MR["value"]) + "%")} {STALE}'), ("System liquidity", NOFEED), ("RBI forward book", NOFEED), ("Ten-year G-sec", NOFEED)],
    deeper="referees", deeper_label="The referees"))

op = D2["oil_playbook"]
oil_rows = sorted(((SECT_LABEL[k], v["rel"], v["t"]) for k, v in op["rows"].items() if k != "usdinr"), key=lambda r: -r[1])
CH.append(dict(id="in-5", track="India", title="Oil and the rupee: the twin-deficit chain, as India lives it", mins="five",
    hook=P("An oil shock hits India through five channels at once: the current account, the rupee, inflation, the fiscal and corporate margins. The "
           "question is who absorbs it: consumers through pump prices, the government through excise and subsidies, or the state oil companies through "
           "under-recoveries."),
    body=fig(C.stacked(
        C.line_panel(D2["w_brent_crude"], label="Brent, $ a barrel", color="#d97706", episodes=EPI_BANDS, h=140, show_years=False),
        C.line_panel(D2["w_usdinr"], label="USD/INR (up = weaker rupee)", color="var(--red)", episodes=EPI_BANDS, h=150, fmt="{:.0f}")),
        f"Weekly since mid-2015. The rupee has weakened from {feed(D2['usdinr_2015'])} to {feed(fmt(U['value']))} over the period, with its fastest falls in "
        f"2018 and 2022, both oil years. Its record, {feed('96.88')}, came on 2026-07-24.") +
         P("The external leg: oil is the swing item in the import bill; services exports and remittances, India's two structural surpluses, cover a "
           "normal oil bill but not a spike. The gap leans on portfolio money, and the RBI's defence tightens domestic liquidity.",
           "The fiscal leg: an excise cut shields CPI at the cost of revenue; gas-linked fertiliser subsidies rise automatically; frozen retail prices push "
           "losses onto the oil companies, which is quasi-fiscal; windfall taxes on producers claw some back.",
           "Which sectors have actually done well when oil rose fast? Our own history answers, with an important caveat below.") +
         fig(C.hbars(oil_rows, title=f"Sector return against the Nifty over three-month windows when Brent rose more than a quarter ({len(op['months'])} months since 2016)"),
             "Bars in full colour clear |t| ≥ 2.5. <b>Caveat:</b> most of these windows are demand-led oil recoveries (2016, mid-2020 to early 2021), when "
             "metals, PSU banks and realty rallied with the cycle. Only 2022 and 2026 are supply shocks. The one result that fits both kinds is FMCG "
             "lagging: input costs rise faster than staples companies can pass them on."),
    history=history("India's oil shocks", [
        ("1973, 1979", "The two oil shocks", "Import bills ballooned and inflation surged; India borrowed from the IMF in 1981.", "India's oil vulnerability is structural, not cyclical."),
        ("1990–91", "The Gulf war", "Oil spiked and Gulf remittances stopped; the balance-of-payments crisis followed.", "Oil plus a thin buffer is the classic Indian crisis."),
        ("2008", "Oil at its peak", "Oil marketing losses were funded with oil bonds; the deficit widened.", "Quasi-fiscal tricks shift the cost forward, they don't remove it."),
        ("2014–16", "The windfall", "Oil collapsed; the government raised excise and pocketed much of the gain.", "Falling oil is India's best macro tailwind."),
        ("2018", "Oil and the rupee", f"Rupee {feed(f'+{EPIS['2018']['usdinr_chg']}%')} weaker over the episode, Nifty drawdown {feed(f'{EPIS['2018']['nifty_mdd']}%')}.", "Oil and liquidity stress compound each other."),
        ("2022", "War", f"Brent {feed(f'+{EPIS['2022']['brent_chg']}%')}, Nifty drawdown {feed(f'{EPIS['2022']['nifty_mdd']}%')}, US ten-year {feed(f'+{EPIS['2022']['us10y_bps']:.0f} bps')}.", "Oil and US rates together is the worst pairing for India."),
    ], "Figures for 2018 and 2022 are computed from our database over each episode window."),
    today=stand(f"Brent {feed(fmt(B['value']))}, {feed(sign(B['chg_63']))} over three months: a supply shock, the kind the playbook above has least data on.",
                f"USD/INR {feed(fmt(U['value']))}, {feed(sign(U['chg_63']))} over three months. The rupee is being held, so the pressure shows up in liquidity and rates."),
    sowhat="Oil consumers (aviation, paints, OMCs, autos) and wholesale-funded borrowers lose on every link; staples lag in every kind of oil shock. Exporters gain only if the RBI lets the rupee go.",
    indicators=[("Brent", feed(fmt(B["value"]))), ("USD/INR", feed(fmt(U["value"]))), ("Trade balance", f'imports {feed(sign(MP["india_imports"]["yoy"]))}'), ("Forex reserves", NOFEED), ("Retail fuel and excise", NOFEED)],
    deeper="twin", deeper_label="The twin deficits: toolkit and history"))

pb = D2["pos_buckets"]
CH.append(dict(id="in-6", track="India", title="Flows and positioning: what the data actually says", mins="four",
    hook=P("Daily FII and DII numbers are the most quoted and most over-read data in Indian markets. Our own history since 2022 also overturns one "
           "piece of folklore: a crowded foreign short has not reliably been followed by a rally."),
    body=(
         fig(C.stacked(
            C.line_panel(D2["w_fii_long"], label="FII long share of index futures, %", color="#d97706", h=140, fmt="{:.0f}", ref=FII["median"], show_years=False),
            C.line_panel(D2["w_nifty_pos"], label="Nifty 50", color="var(--accent)", h=140)),
            f"Weekly since 2022. Dashed line: the median long share, {feed(str(FII['median']) + '%')}. Today: {feed(str(FII['value']) + '%')}, the "
            f"{feed(str(int(FII['pctile'])) + 'th')} percentile.") +
         fig(C.buckets([(f"Crowded short (≤ {pb['q15']}%)", pb["low"]["mean"], pb["low"]["hit"], pb["low"]["n"]),
                        ("Normal", pb["mid"]["mean"], pb["mid"]["hit"], pb["mid"]["n"]),
                        (f"Crowded long (≥ {pb['q85']}%)", pb["high"]["mean"], pb["high"]["hit"], pb["high"]["n"])],
                       title="Nifty return over the next twenty sessions, by foreign futures positioning, since 2022"),
             "Overlapping windows, so the day counts overstate the independent evidence. Crowded longs have preceded weaker months. Crowded shorts have "
             "not preceded better-than-normal months, although the market rose more often than not.") +
         P("<b>Ownership has shifted.</b> Domestic institutions now own roughly as much of listed India as foreigners, after a decade in which foreign "
           "ownership drifted down and domestic fund assets compounded. Persistent foreign selling meets a structural buyer.",
           "<b>Foreign flows are driven mostly from outside</b>: US real yields, the dollar, emerging-market allocation and India's valuation premium. "
           "That is why they can persist through good domestic data.",
           "<b>The risk is a domestic flow stall.</b> A long drawdown that pushes recent investors into losses, or higher deposit rates, could slow "
           "monthly inflows and remove the buffer. The monthly fund-flow data deserves more attention than the daily FII print.")),
    history=history("who owns India", [
        ("1992–93", "Foreign portfolio investors allowed in", "The opening that created the FII-led market.", "For two decades, foreign flows set the direction."),
        ("2003–07", "The FII bull market", "Heavy foreign inflows drove a long rally.", "Flow-driven rallies reverse when the flows do."),
        ("2008", "The exit", "Foreign investors sold heavily; the market more than halved.", "Without a domestic buyer, drawdowns were brutal."),
        ("2013", "The bond exit", "Foreign selling of Indian bonds broke the rupee.", "Debt flows matter for the currency as much as equity flows."),
        ("2020–21", "The retail wave", "Record new accounts and monthly fund flows.", "The domestic buyer arrived."),
        ("2022", "Record foreign selling absorbed", "Foreigners sold at a record pace; domestic funds bought almost all of it.", "The market fell far less than the flows implied."),
    ]),
    today=stand(f"Twenty sessions: foreign {feed(rupee(F20['FII']))}, domestic {feed(rupee(F20['DII']))}. Long share {feed(str(FII['value']) + '%')}."),
    sowhat="Foreign selling is heavy and positioning is bearish, but our data does not support betting on a short-covering rally. The cushion is the domestic buyer, so watch monthly fund inflows.",
    indicators=[("FII long share", feed(f'{FII["value"]}%')), ("FII / DII cash", feed(f'{rupee(F20["FII"])} / {rupee(F20["DII"])}')), ("Monthly equity fund inflows", NOFEED), ("FPI debt flows", NOFEED)],
    deeper="lesson7", deeper_label="Worked lesson: flows"))

ele = EV["Election result"]; dem = EV["Demonetisation"]
CH.append(dict(id="in-7", track="India", title="Fiscal policy and political economy: what changes earnings", mins="five",
    hook=P("For equities the Budget matters through four lines: capex, borrowing, taxes and subsidies. Political economy matters through whether those "
           "lines are predictable."),
    body=fig(C.diagram_budget(), "The four Budget lines and the parts of the market each one moves.") +
         P("This government's revealed preferences have been consistent across majority and coalition terms: protect public capex, keep the deficit "
           "on a declining path and anchor it to debt, deliver relief through tax cuts and direct transfers rather than new entitlements, and use "
           "incentive schemes rather than broad subsidies for manufacturing.",
           "The oil shock tests that ordering. An excise cut and higher fertiliser subsidies widen the deficit; historically the headline target is "
           "protected by slowing other spending, and capex execution is the easiest line to slow quietly. States are the bigger source of slippage: "
           "their borrowing rivals the centre's, and election-year transfers are common.") +
         fig(C.event_study([ele, dem, EV["Covid lockdown"], EV["IL&FS default"]], highlight="Election result",
                           title="Nifty around four domestic shocks, indexed to 100 the day before"),
             f"The 2024 election result (amber): {evline('Election result')}. Political shocks without a policy change faded within weeks; demonetisation and "
             f"the IL&FS default, which changed the economics, did not ({evline('Demonetisation')} for demonetisation)."),
    history=history("fiscal and political turning points", [
        ("1991", "Liberalisation", "Licences scrapped, tariffs cut, the rupee devalued, after the crisis.", "India's big reforms have come out of crises."),
        ("2003", "FRBM Act", "A legal deficit glide path.", "Anchors hold until a shock; then they are rewritten."),
        ("2014", "A single-party majority", "The first in three decades.", "Majorities make big reforms possible: GST, the bankruptcy code."),
        ("2016–17", "Demonetisation and GST", "A cash shock, then a messy switch to a national tax.", "Formalisation helped listed companies at the informal sector's expense."),
        ("2019", "Corporate tax cut", "A large rate cut; the market jumped on the day.", "Supply-side policy is rewarded quickly by the market."),
        ("2024", "Coalition government", "The ruling party lost its single-party majority.", "Reforms get harder; spending tilts to allies' states."),
        ("2025", "Consumption push", "Income-tax relief and fewer GST slabs.", "The government chose consumers over capex at the margin."),
    ]),
    today=stand("The GST Council approved easier compliance with no rate changes; Cabinet approved a small-business fund and a logistics authority. (News desk.)",
                "Next Budget: February 2027. Uttar Pradesh votes in early 2027."),
    sowhat="Policy-backed sectors carry support through a weak quarter, but watch monthly capex execution: a quiet slowdown would be the first sign the oil bill is being paid at their expense.",
    indicators=[("Centre's capex execution", NOFEED), ("Fiscal deficit, monthly", NOFEED), ("GST collections", NOFEED), ("Fuel excise changes", NOFEED)],
    deeper="politics", deeper_label="The political economy, in detail"))

ep_rows = "".join(f"<tr><td class='mono'>{e['label']}</td><td>{E(e['name'])}</td><td class='num mono'>{e['nifty_mdd']:+.1f}%</td><td class='num mono'>{e['brent_chg']:+.1f}%</td>"
                  f"<td class='num mono'>{e['usdinr_chg']:+.1f}%</td><td class='num mono'>{e['us10y_bps']:+.0f}</td><td class='num mono'>{e['vix_peak']:.0f}</td></tr>" for e in D2["episodes"])
CH.append(dict(id="in-8", track="India", title="A decade of Indian drawdowns, and what caused each", mins="four",
    hook=P("Every Indian drawdown in our data since 2015 has a cause you can name, and most of them came from outside India. Laying them side by side "
           "is the fastest way to calibrate how bad the current one is."),
    body=fig(C.line_panel(D2["w_drawdown"], label="Nifty 50, distance from its previous high, %", color="var(--red)", area=True, h=190, fmt="{:.0f}", episodes=EPI_BANDS),
             "Weekly. Each dip is the market's distance from its running high; the shaded windows are the named episodes.") +
         f'''<div class="fig"><table class="b-table"><thead><tr><th>Episode</th><th></th><th class="num">Nifty worst</th><th class="num">Brent</th><th class="num">USD/INR</th><th class="num">US 10y, bps</th><th class="num">VIX peak</th></tr></thead><tbody>{ep_rows}</tbody></table>
         <div class="fig-cap">Computed from our database over each episode window. "Nifty worst" is the deepest fall from a prior high inside the window.</div></div>''' +
         P("Three patterns stand out. The deepest falls came from global shocks, the pandemic above all, with India's own events in the middle of "
           "the range. Oil-and-dollar episodes, 2018 and 2022, produced drawdowns in a narrow band and recovered when the external pressure eased. "
           "And the current episode, so far, sits inside that band, with an unusually calm fear gauge for the size of the oil move."),
    history=history("the episodes in one line each", [
        ("2015–16", "China and commodities", "A yuan devaluation and a commodity rout hit every emerging market.", "Global growth scares hit India through flows and metals."),
        ("2016", "Demonetisation", "A domestic cash shock.", "Domestic shocks hit small caps and consumption hardest."),
        ("2018", "Oil, rupee, IL&FS", "Oil, a falling rupee and a lender's default together.", "Liquidity stress turns a correction into a small-cap bear market."),
        ("2020", "Covid", "The deepest and fastest fall, then the fastest recovery.", "Liquidity can repair a crash quickly."),
        ("2022", "Ukraine and the Fed", "Oil, food and the fastest US hiking in decades.", "Domestic flows capped the damage."),
        ("2024", "Election and carry unwind", "Two sharp one-day shocks inside a rising market.", "Event shocks inside a bull market fade fast."),
        ("2026", "The Iran war", "US–Israeli strikes from 28 February, Hormuz closed, an oil supply shock, a hiking RBI, record US yields.", "So far, a drawdown in the 2018 range."),
    ]),
    today=stand(f"Nifty {feed(fmt(REC['nifty50']['last']))}, against a high of {feed(fmt(REC['nifty50']['max']))} on {REC['nifty50']['max_date']}.",
                f"Worst fall inside the 2026 window so far: {feed(f'{EPIS['2026']['nifty_mdd']}%')}; VIX peak {feed(EPIS['2026']['vix_peak'])}."),
    sowhat="The current drawdown is in the 2018 range, not the 2020 one. History says the turn comes when the external pressure eases, so watch oil and the rupee, not the growth data.",
    indicators=[("Nifty distance from high", feed(f'{(REC["nifty50"]["last"] / REC["nifty50"]["max"] - 1) * 100:+.1f}%')), ("India VIX", feed(fmt(REC["india_vix"]["last"]))), ("Breadth", NOFEED)],
    deeper="data", deeper_label="The data room"))

# ═════════════════════════════ GLOBAL & GEOPOLITICAL FRAMEWORK ═════════════════════════════
CH.append(dict(id="gl-1", track="Global", title="How the world reaches India", mins="four",
    hook=P("Six outside economies matter for Indian markets, and they arrive through only five channels: rates and the dollar, commodity prices, trade "
           "and tariffs, capital flows, and energy supply. Knowing the channel tells you which Indian sectors will feel a foreign event, and how fast."),
    body=fig(C.diagram_world(), "The main links only. A single foreign event usually travels through two or three channels at once.") +
         P("Speed differs by channel. Rates and capital flows move within days, through the rupee and foreign selling. Commodity prices reach margins "
           "within a quarter. Trade and tariffs take quarters to show up in exporters' revenue. Energy supply shocks are the exception: they hit prices "
           "the same day and the fiscal for months.",
           "India's own position has changed. It is now large enough that global allocators treat it as a standalone market rather than a slice of "
           "emerging Asia, which makes its valuation premium more sensitive to global rates and less to regional contagion. Its foreign policy of "
           "strategic autonomy, buying from Russia, partnering with the US, competing with China, keeps it exposed to sanctions risk from several "
           "directions at once."),
    history=history("India's integration with the world", [
        ("1991", "Opening", "Trade and investment liberalisation after the crisis.", "From then on, global shocks reach India directly."),
        ("2001", "China joins the WTO", "The start of China as the world's factory.", "China, not the US, sets the price of most manufactured goods India competes with."),
        ("2008", "The global crisis", "Contagion through flows within weeks.", "Financial integration means global panics arrive fast."),
        ("2018", "The US–China trade war", "Tariffs and the first supply-chain shifts.", "Trade wars create both risk and a China+1 opportunity for India."),
        ("2024", "Bond-index inclusion", "Indian government bonds joined global bond indices.", "A new, stickier channel of foreign money, and a new path for contagion."),
        ("2025", "US tariffs on India", "Broad tariffs plus a penalty tied to Russian crude purchases.", "Strategic autonomy has a price in market access."),
    ]),
    today=stand(f"Rates and dollar: US ten-year {feed(T10)}. Energy supply: Brent {feed(fmt(B['value']))}. Trade: US talks stalled.",
                "Capital flows: foreign investors net sellers over twenty sessions. Commodity prices: copper still beating gold."),
    sowhat="Today three of the five channels are adverse at once: rates, energy supply and trade. That combination, not any single one, is what makes this shock serious.",
    indicators=[("US ten-year", feed(T10)), ("Brent", feed(fmt(B["value"]))), ("Copper against gold, six months", feed(sign(RN["cg_6m"]))), ("Dollar index", NOFEED)],
    deeper="world", deeper_label="The world cards"))

usp = D2["us_playbook"]
us_rows = sorted(((SECT_LABEL[k], v["rel"], v["t"]) for k, v in usp["rows"].items()), key=lambda r: -r[1])
CH.append(dict(id="gl-2", track="Global", title="The dollar and US rates: pricing the India premium", mins="five",
    hook=P("India's valuation premium over other emerging markets behaves like a long-duration asset, priced off the global discount rate set in the US "
           "Treasury market. US real yields therefore matter to Indian multiples even when Indian earnings do not change."),
    body=fig(C.line_panel(D2["w_us_10y"], label="US ten-year Treasury yield, %", color="var(--blue)", episodes=EPI_BANDS, h=180, fmt="{:.1f}",
                          markers=[("2022-03-16", "Fed starts hiking"), ("2020-03-09", "record low")]),
             f"Weekly since mid-2015. From a record low of {feed(str(REC['us_10y']['min']) + '%')} in March 2020 to {feed(str(REC['us_10y']['max']) + '%')} on {REC['us_10y']['max_date']}.") +
         P("Three channels, fastest first: portfolio flows and the rupee, as higher US yields raise the hurdle for emerging-market allocations; multiples, "
           "as a higher global risk-free rate compresses the premium on long-duration growth stocks; and trade and services, through tariffs, technology "
           "budgets and visa costs.",
           "Today's move looks more like term premium and inflation compensation than a growth signal: an oil-driven inflation scare plus heavy issuance. "
           "Term-premium rises tend to persist and to coincide with a strong dollar.") +
         fig(C.hbars(us_rows, title=f"Sector return against the Nifty over three-month windows when the US ten-year rose more than three-quarters of a point ({len(usp['months'])} months)"),
             f"In those windows the Nifty itself moved {feed(sign(usp['nifty_abs']))} on average and the rupee weakened {feed(sign(usp['usdinr']))}. Metals is the only "
             f"sector that clears |t| ≥ 2.5, and it overlaps heavily with reflation; treat the rest as noise."),
    history=history("US rate shocks and India", [
        ("1994", "The bond massacre", "A surprise Fed tightening crashed bond markets and preceded the Mexican crisis.", "Fast US hikes break the weakest emerging markets first."),
        ("2013", "The taper tantrum", "A hint of slower bond buying; India among the Fragile Five.", "India is vulnerable when its external gap is wide."),
        ("2015–18", "The slow hiking cycle", "Gradual hikes and a stronger dollar; the rupee fell in 2018.", "Slow cycles hurt through the currency, not a crash."),
        ("2022", "The fastest hikes in decades", f"US ten-year {feed(f'+{EPIS['2022']['us10y_bps']:.0f} bps')} in the first half; record foreign selling of India.", "Domestic flows now soften even severe US shocks."),
        ("2026", "Term premium and oil", f"The ten-year reached the high of our sample, {feed(str(REC['us_10y']['max']) + '%')}.", "Long yields rising on inflation fear is worse for India than on growth."),
    ]),
    today=stand(f"US ten-year {feed(T10)}, {feed(sign(T['chg_63']))} over three months. US–India talks stalled; new US sanctions on Iranian crude cover two Indian firms. (News desk.)"),
    sowhat="While the US ten-year stays near its highs, expect foreign underweighting and pressure on the most richly valued large caps. IT, software and asset managers are the most exposed in our industry map.",
    indicators=[("US ten-year", feed(T10)), ("US real yield", NOFEED), ("Dollar index", NOFEED), ("Fed funds path", NOFEED)],
    deeper="us", deeper_label="The US card"))

CH.append(dict(id="gl-3", track="Global", title="Oil and the Gulf: chokepoints and war premiums", mins="five",
    hook=P("Most of India's crude passes through two narrow stretches of water: the Strait of Hormuz and, for cargoes from the west, the Bab-el-Mandeb at "
           "the mouth of the Red Sea. Geopolitics enters India's economy mostly through those two points."),
    body=fig(C.diagram_chokepoints(), "Red: the two chokepoints that matter most for India. Re-routing around the Cape adds weeks and freight cost.") +
         fig(C.line_panel(D2["w_brent_crude"], label="Brent, $ a barrel", color="#d97706", h=180,
                          markers=[("2016-11-30", "OPEC+ deal"), ("2019-09-16", "Abqaiq"), ("2020-04-21", "price war, Covid"), ("2022-02-24", "Ukraine"), ("2023-11-19", "Red Sea attacks")]),
             f"Weekly since mid-2015. Range: {feed(fmt(REC['brent_crude']['min']))} on {REC['brent_crude']['min_date']} to {feed(fmt(REC['brent_crude']['max']))} on {REC['brent_crude']['max_date']}.") +
         P("Two kinds of oil rise need different readings. A <b>demand-led</b> rise comes with global growth, and Indian cyclicals can rise with it. A "
           "<b>supply-led</b> rise, from a war, sanctions or a blocked route, is a pure tax on India. The war premium in a supply shock fades when "
           "the route reopens, often abruptly, which is why oil after the Abqaiq attack round-tripped within weeks while 2022 lasted months.",
           "OPEC+ policy is the slow variable underneath: since 2016 Saudi Arabia and Russia have coordinated supply, and the group's spare capacity "
           "decides how much of a disruption can be offset."),
    history=history("oil shocks and the Gulf", [
        ("1973", "Arab oil embargo", "Prices quadrupled.", "Supply shocks reprice oil in weeks and last years."),
        ("1979", "Iranian revolution", "A second shock; global stagflation.", "Two shocks close together are the stagflation recipe."),
        ("1990", "Iraq invades Kuwait", "Prices doubled; India's crisis followed.", "Gulf wars hit India twice: oil and remittances."),
        ("2008", "The supercycle peak", "Demand-led spike, then collapse in the crisis.", "Demand-led peaks end with demand."),
        ("2019", "Abqaiq attack", f"A drone strike on Saudi processing; Nifty {evline('Abqaiq attack')}.", "Quickly repaired supply shocks fade within weeks."),
        ("2022", "Russia invades Ukraine", f"Nifty {evline('Russia invades Ukraine')}.", "Sanctions-driven shocks last as long as the sanctions."),
        ("2023–24", "Red Sea attacks", "Shipping re-routed around the Cape; freight costs jumped.", "Chokepoint risk shows up in freight before it shows up in crude."),
        ("2026", "The Iran war closes Hormuz", f"US–Israeli strikes began on 28 February; Iran closed the strait; a ceasefire from April collapsed in July. Brent {feed(sign(EPIS['2026']['brent_chg']))} over the war so far.", "A Hormuz closure is the tail risk India's oil-security planning exists for, and it has now happened."),
    ], "Nifty reactions are computed from our database: index level relative to the close before the event."),
    today=stand(f"Brent {feed(fmt(B['value']))}. Gulf shipping attacks continue despite emergency stock releases; the Hormuz route is closed. (News desk.)"),
    sowhat="Treat the current rise as supply-led: there is no cyclical upside for India in it. The single most important signpost for Indian equities right now is the Hormuz route reopening.",
    indicators=[("Brent", feed(fmt(B["value"]))), ("Freight index", NOFEED), ("OPEC+ spare capacity", NOFEED), ("India's crude import mix", NOFEED)],
    deeper="shock", deeper_label="The shock walk-through"))

CH.append(dict(id="gl-4", track="Global", title="China: the price-setter and the rival", mins="four",
    hook=P("China matters to India in two opposite ways. It sets the world price of most manufactured goods and metals, which squeezes Indian "
           "producers, and it is the strategic rival whose supply chains India hopes to capture."),
    body=fig(C.stacked(
        C.line_panel(D2["w_cg"], label="Copper against gold (×1000), a global growth gauge", color="#d97706", h=140, fmt="{:.2f}", show_years=False, markers=[("2015-08-11", "yuan devaluation")]),
        C.line_panel(D2["w_nifty_metal"], label="Nifty Metal", color="var(--accent)", h=150)),
        "Weekly since mid-2015. Copper against gold tracks Chinese and global industrial demand; Indian metal stocks follow it closely.") +
         P("Since its property bust began in 2021, China has kept producing more than it consumes and exported the surplus at low prices: steel, "
           "chemicals, solar equipment, increasingly cars. For India that means a price ceiling on its own producers and a stream of anti-dumping "
           "cases. Stimulus comes in measured doses, and export controls on rare earths and other critical materials are now a regular tool.",
           "The rivalry runs alongside. After the 2020 border clash India restricted Chinese investment and banned Chinese apps, yet still depends on "
           "Chinese components for electronics, solar and pharmaceuticals. China+1 brings orders to India; dependence on Chinese inputs caps how much "
           "value stays."),
    history=history("China and India's markets", [
        ("2001", "China joins the WTO", "The factory of the world begins.", "Indian manufacturing competes against Chinese scale."),
        ("2008–09", "China's stimulus", "A credit-fuelled building boom drives a commodity supercycle.", "Chinese credit is the commodity cycle."),
        ("2015", "Yuan devaluation", f"Nifty {evline('Yuan devaluation')}.", "A China growth scare hits India through flows and metals."),
        ("2018", "US–China trade war", "Tariffs and the first China+1 shifts.", "India gains orders slowly, not in a rush."),
        ("2020", "Galwan and the decoupling", "Border clash; curbs on Chinese investment and apps.", "Geopolitics sets the limits of economic integration."),
        ("2021–", "Property bust and overcapacity", "Deflationary exports flood global markets.", "Chinese deflation is India's import price ceiling."),
        ("2025", "Rare-earth controls", "Export curbs on critical materials and magnets.", "Supply-chain dependence is a lever China will use."),
    ]),
    today=stand(f"Copper against gold {feed(sign(RN['cg_6m']))} over six months: markets still read global growth as firm.",
                "India joined a US-led group on industrial overcapacity. (News desk.)"),
    sowhat="Metals and chemicals live under the Chinese price ceiling; electronics and pharma depend on Chinese inputs. Anti-dumping duties are the policy cushion, and China's export controls are the tail risk.",
    indicators=[("Copper against gold", feed(sign(RN["cg_6m"]))), ("China producer prices", NOFEED), ("China factory surveys", NOFEED), ("Indian anti-dumping cases", "regulatory feed")],
    deeper="world", deeper_label="The China card"))

ycu = EV["Yen carry unwind"]
CH.append(dict(id="gl-5", track="Global", title="Europe and Japan: energy, carbon and the carry trade", mins="four",
    hook=P("Europe reaches India slowly, through export demand, energy prices and carbon rules. Japan reaches it suddenly, through the yen carry trade, "
           "which can make every risky asset fall on the same day."),
    body=fig(C.line_panel(D2["w_india_vix"], label="India VIX", color="var(--red)", h=170, fmt="{:.0f}",
                          markers=[("2020-03-24", "Covid"), ("2022-02-24", "Ukraine"), ("2024-06-04", "election"), ("2024-08-05", "carry unwind")]),
             f"Weekly since mid-2015. The record, {feed(fmt(REC['india_vix']['max']))}, came on {REC['india_vix']['max_date']}. The yen unwind of 2024 produced one of the "
             f"sharpest one-day jumps in the fear gauge outside a crisis.") +
         P("<b>Japan.</b> For decades near-zero Japanese rates let investors borrow yen and buy higher-yielding assets everywhere. When Japanese rates rise "
           f"or the yen jumps, those positions unwind together. In August 2024, days after a Bank of Japan hike, it happened: Nifty {evline('Yen carry unwind')}, "
           f"and the VIX jumped {feed(f'{ycu["vix_chg"]:+.0f}%')} in a day. The Bank of Japan ended negative rates in 2024 and is raising slowly; each hike "
           "is a small carry-trade risk.",
           "<b>Europe.</b> Since the 2022 gas crisis European energy has been dearer than in the US or Asia, which helps Indian chemical exporters "
           "compete with European plants. The carbon border tax on steel, aluminium, cement and fertiliser entered its paying phase in 2026, a direct "
           "cost for Indian metal exporters. Germany's 2025 decision to borrow more for defence and infrastructure is a modest demand tailwind for "
           "Indian engineering suppliers."),
    history=history("Europe and Japan", [
        ("2010–12", "Euro debt crisis", "Sovereign stress, bank funding fears, a global risk-off.", "European crises reach India through global risk appetite."),
        ("2016", "Brexit vote", f"Nifty {evline('Brexit vote')}.", "Political shocks in rich countries fade quickly in India."),
        ("2022", "Europe's energy crisis", "Gas prices spiked; European heavy industry lost competitiveness.", "Dear European energy is a tailwind for Indian chemicals."),
        ("2024", "The yen carry unwind", f"Nifty {evline('Yen carry unwind')}.", "Carry unwinds are violent and brief."),
        ("2026", "Carbon border tax bites", "EU importers start paying for embedded carbon.", "Carbon rules are a new, permanent trade cost."),
    ]),
    today=stand(f"India VIX {feed(fmt(V['value']))}, the {feed(str(int(D['vix_pctile_3y'])) + 'th')} percentile of three years: calm for the size of the oil shock."),
    sowhat="Japan is the source of sudden, indiscriminate sell-offs; treat them as liquidity events, not information. Europe is a slow-moving factor for chemicals, metals and engineering exporters.",
    indicators=[("India VIX", feed(fmt(V["value"]))), ("Yen against the dollar", NOFEED), ("European gas price", NOFEED), ("Japanese bond yields", NOFEED)],
    deeper="world", deeper_label="The Europe and Japan cards"))

CH.append(dict(id="gl-6", track="Global", title="Russia, sanctions and India's balancing act", mins="four",
    hook=P("India's foreign policy rests on strategic autonomy: buying Russian crude and weapons, deepening ties with the US, competing with China, and "
           "staying close to the Gulf. Each relationship has a market price, and sanctions are how the bill arrives."),
    body='''<div class="fig"><div class="bal4">
      <div><b>United States</b><span>Technology, capital, the largest export market, defence partnership. <em>Lever over India:</em> tariffs, sanctions, visas.</span></div>
      <div><b>Russia</b><span>Discounted crude since 2022, legacy defence supplies. <em>Cost:</em> exposure to US and European sanctions.</span></div>
      <div><b>The Gulf</b><span>Most of India's oil and gas, millions of Indian workers, sovereign-fund investment. <em>Risk:</em> war in the region.</span></div>
      <div><b>China</b><span>Inputs for electronics, solar and pharma; the border; the rival. <em>Risk:</em> export controls, border clashes.</span></div>
    </div><div class="fig-cap">India's four key relationships and the lever each partner holds.</div></div>''' +
         P("After the 2022 invasion of Ukraine, India became one of the largest buyers of discounted Russian crude, paying in a mix of currencies. That "
           "lowered the average cost of India's oil and helped hold inflation down, a real macro gain.",
           "The bill arrived in 2025. The US imposed a penalty tariff on Indian goods linked to the Russian purchases and sanctioned Russia's largest oil "
           "companies, which made the discounted barrel harder to buy and finance. In 2026 new US sanctions on Iranian oil named Indian firms too. "
           "Strategic autonomy now carries a measurable cost in market access for exporters and in sanctions risk for refiners and banks.",
           "The market impact is sectoral, not systemic: refiners' crude costs and export margins, exporters' tariff exposure, and banks' compliance risk "
           "on trade finance."),
    history=history("India between the blocs", [
        ("1971", "The Indo-Soviet treaty", "A strategic tie that shaped defence procurement for decades.", "Defence dependence is slow to unwind."),
        ("1998", "Nuclear tests and sanctions", "US and others imposed sanctions; they faded within a few years.", "Sanctions on India have historically been short-lived."),
        ("2008", "The US civil nuclear deal", "India's integration into the global nuclear order.", "The US relationship is strategic, not transactional, over the long run."),
        ("2022", "Discounted Russian crude", "India's crude basket shifted sharply towards Russia.", "Geopolitical flexibility can lower India's oil bill."),
        ("2025", "The penalty tariff and oil sanctions", "US tariffs tied to Russian purchases; sanctions on Russia's oil majors.", "The discount comes with a bill."),
    ]),
    today=stand("US–India trade talks have hit a plateau; India is reassessing the interim deal and pushing deals with Europe and others. (News desk.)"),
    sowhat="Sanctions risk is a sector story: refiners, exporters to the US and banks financing sanctioned trade. Watch the US talks and any change in Russian crude flows.",
    indicators=[("Russian share of India's crude imports", NOFEED), ("US tariff rate on Indian goods", NOFEED), ("Sanctions designations involving Indian firms", "news desk")],
    deeper="world", deeper_label="The Gulf and Russia card"))

geo = [EV[n] for n in ["Surgical strikes", "Pulwama attack", "Balakot strike", "Galwan clash", "Pahalgam attack", "Operation Sindoor"]]
glob_ev = [EV[n] for n in ["Russia invades Ukraine", "Abqaiq attack", "Hamas attack on Israel", "Yen carry unwind", "Yuan devaluation", "Brexit vote"]]
geo_avg30 = sum(e["d30"] for e in geo) / len(geo); geo_avg0 = sum(e["day0"] for e in geo) / len(geo)
CH.append(dict(id="gl-7", track="Global", title="Conflict on India's borders: what markets have done", mins="four",
    hook=P("Every few years a border crisis with Pakistan or China dominates the news and the market dips. Our data since 2016 shows a consistent "
           "pattern: the dip is small and short, unless the conflict touches oil or foreign flows."),
    body=fig(C.event_study(geo, highlight="Operation Sindoor", title="Nifty around six India–Pakistan and India–China events, indexed to 100 the day before"),
             f"Grey: each event. Purple: the average, {feed(f'{geo_avg0:+.1f}%')} on the day and {feed(f'{geo_avg30:+.1f}%')} after thirty sessions. Amber: Operation "
             f"Sindoor in 2025. The surgical strikes of 2016 are the outlier, because demonetisation and the US election followed within weeks.") +
         fig(C.event_study(glob_ev, highlight="Russia invades Ukraine", title="For comparison: Nifty around six global shocks"),
             f"Global shocks that hit oil or flows cut deeper: the Ukraine invasion, {evline('Russia invades Ukraine')}.") +
         P("Why are border shocks short-lived for markets? India's borders do not sit on a major oil route, the conflicts have stayed limited, and foreign "
           "investors price India's political stability higher than the risk of escalation. The exception would be a conflict that closes airspace or "
           "shipping lanes for long, raises defence spending sharply at the cost of capex, or triggers foreign selling. None of the recent episodes did."),
    history=history("India's border conflicts", [
        ("1962", "War with China", "A defeat that shaped defence policy for decades.", "The China border is the long-run strategic risk."),
        ("1965, 1971", "Wars with Pakistan", "Before modern markets; heavy fiscal cost.", "Full wars are fiscal events."),
        ("1999", "Kargil", "A limited conflict in the mountains; markets fell then recovered as it stayed contained.", "Containment is what markets price."),
        ("2001–02", "Parliament attack and the standoff", "A long military mobilisation.", "Prolonged standoffs weigh on sentiment more than single strikes."),
        ("2008", "Mumbai attacks", "Terror in the financial capital during the global crisis.", "Terror attacks rarely move the market beyond days."),
        ("2016–25", "Strikes and clashes", f"Surgical strikes, Balakot, Galwan, Pahalgam, Sindoor: average Nifty {feed(f'{geo_avg30:+.1f}%')} thirty sessions later.", "Border shocks fade unless they hit oil or flows."),
    ], "The 2016–25 figures are computed from our database."),
    today=stand("No active border escalation in the news desk's themes; the live geopolitical risk is in the Gulf, not on India's borders."),
    sowhat="Fade market dips on contained border events; respect shocks that move oil, shipping or foreign flows. Defence is the sector that benefits on a multi-year view.",
    indicators=[("India VIX", feed(fmt(V["value"]))), ("Defence budget and orders", NOFEED), ("Border news", "news desk")],
    deeper="history", deeper_label="History that still bites"))

# ═════════════════════ v5.1: technology and hot spots (web-checked 2026-10-17) ═════════════════════
D3 = json.loads(Path(__file__).with_name("data3.json").read_text())
EV3 = {e["name"]: e for e in D3["events3"]}
def ev3(name):
    e = EV3[name]; return f'{feed(f"{e["day0"]:+.1f}%")} on the day, {feed(f"{e["d30"]:+.1f}%")} after thirty sessions'
def sources(items, checked="2026-10-17"):
    return (f'<div class="srcbox"><div class="hb-h">Sources · web-checked {checked}</div><ul class="tight">'
            + "".join(f'<li><a href="{u}" target="_blank" rel="noopener">{E(t)}</a></li>' for t, u in items) + "</ul></div>")
EXTERNAL_ROWS = []
def external(rows, checked="2026-10-17"):
    """Figures from the web, not from our feeds: shown in their own box with source and date."""
    EXTERNAL_ROWS.extend({"reading": a, "value": b, "source": src, "url": u, "checked": checked} for a, b, src, u in rows)
    body = "".join(f"<tr><td>{E(a)}</td><td class='num mono'>{E(b)}</td><td class='tiny-t'><a href='{u}' target='_blank' rel='noopener'>{E(src)}</a></td></tr>" for a, b, src, u in rows)
    return (f'<div class="extbox"><div class="hb-h">Latest external readings · web-checked {checked} · not yet a feed</div>'
            f'<table class="ind-t"><tbody>{body}</tbody></table></div>')

BL = D3["basket_last"]
CH.append(dict(id="gl-8", track="Global", title="Technology, AI and the chip cycle", mins="six",
    hook=P("The AI build-out is the largest corporate investment cycle since the telecom boom of the late 1990s. It reaches markets through three "
           "places: the earnings and credit of a handful of US companies, the Korea–Taiwan chip chain, and the demand for power and data centres. "
           "India sits on both sides of it: a beneficiary in electronics, power equipment, data centres and AI servers, and a potential loser in IT "
           "services."),
    body=fig(C.diagram_ai_chain(), "Left: the global chain. Right: India's position at each layer.") +
         fig(C.stacked(
            C.line_panel(D3["basket_build"], label="India AI build-out basket (equal weight)", color="var(--green)", h=130, fmt="{:.0f}", ref=100, show_years=False),
            C.line_panel(D3["basket_it"], label="Indian IT services basket (equal weight)", color="var(--red)", h=130, fmt="{:.0f}", ref=100, show_years=False,
                         markers=[("2025-01-27", "DeepSeek")]),
            C.line_panel(D3["basket_nifty"], label="Nifty 50", color="var(--accent)", h=130, fmt="{:.0f}", ref=100)),
            f"Weekly, indexed to 100 on {D3['basket_start']}, from our own price data. Build-out: {', '.join(D3['build_members'])}. IT services: "
            f"{', '.join(D3['it_members'])}. Bonus-issue days neutralised; Siemens left out because its 2025 demerger breaks the raw series. A hand-picked, "
            f"illustrative basket, not a factor. Today: build-out {feed(BL['build'])}, IT services {feed(BL['it'])}, Nifty {feed(BL['nifty'])}.") +
         P("<b>The spending and its funding.</b> The largest US cloud companies are spending at a pace that now rivals their operating cash flow, and a "
           "growing share is borrowed. Credit stress has appeared first at the weaker end: specialist AI cloud providers whose bonds trade at distressed "
           "yields, and project debt tied to individual data centres. The big platforms remain investment grade. For India the link is indirect but "
           "real: AI-related bond issuance adds to the supply pressure behind record US yields (chapter on US rates), and a credit wobble in AI would hit "
           "global risk appetite and foreign flows.",
           "<b>The chip chain.</b> Leading-edge logic chips are made almost entirely in Taiwan and high-bandwidth memory mostly in Korea, which makes "
           "Korea's monthly export data one of the earliest public readings of AI demand. US export controls decide which chips China can buy; China's "
           "controls on rare earths and magnets decide what the rest of the world can build. Both are now permanent bargaining chips.",
           "<b>India's two-sided exposure.</b> AI coding and automation tools press on the hours IT clients pay for, which is why the largest IT firms "
           "report muted demand and the IT basket has gone sideways since 2023. On the other side, the build-out needs servers, transformers, switchgear, "
           "transmission lines and data-centre capacity, and India's semiconductor mission now has assembly and test plants running, with the first "
           "wafer fab still under construction.") +
         external([
            ("South Korea total exports, September 2026", "$120.9 bn, +83.5% y/y", "Korea Times, 2026-10-01", "https://www.koreatimes.co.kr/economy/20261001/koreas-sept-exports-hit-record-1209-bil-on-robust-chip-sales"),
            ("South Korea chip exports, September 2026", "$60.3 bn, about +263% y/y", "KED Global / Digital Today", "https://www.kedglobal.com/economy/newsView/ked202610010001"),
            ("Big US cloud capex, 2026 estimates", "roughly $600–800 bn", "MIT Technology Review; HB Capital", "https://www.technologyreview.com/2026/09/15/1144028/ai-infrastructure-boom-investment-bubble-risk/"),
            ("Share of AI capex funded by debt", "about a third", "Axios, 2026-10-16", "https://axios.com/2026/10/16/wall-street-limit-ai-spending-debt"),
            ("Micron's Sanand assembly and test plant", "inaugurated 28 Feb 2026, shipping", "Zetwerk; IT Voice", "https://www.zetwerk.com/blog/india-semiconductor-manufacturing-2026/"),
            ("Tata–PSMC fab, Dholera", "first output: late 2026 to 2028, sources differ", "Khaleej Times; Anantam", "https://www.khaleejtimes.com/supplements/indias-semiconductor-ambitions-grow-as-chip-manufacturing-investment-accelerates"),
         ]),
    history=history("technology cycles and Indian markets", [
        ("1998–2000", "Y2K and the dot-com boom", "Indian IT's first global boom, then the bust.", "Technology booms overbuild; Indian IT survived by moving to outsourcing."),
        ("2000–02", "The telecom capex bust", "Fibre and network capacity built on debt went unused for years.", "Debt-funded infrastructure booms end in write-offs, even when the technology wins."),
        ("2017–18", "The memory supercycle", "Korea's exports surged on memory prices, then fell sharply.", "Memory is the most cyclical part of the chip chain; Korea's data turns first."),
        ("2020–21", "The chip shortage", "Car makers worldwide, India's included, idled lines for lack of chips.", "Supply-chain concentration becomes a production risk overnight."),
        ("2022", "US export controls", "Sweeping limits on advanced chips and tools for China.", "Technology became an instrument of geopolitics."),
        ("2023–24", "The generative-AI boom", "Chip designers and cloud spending surged.", "The market rewards the picks-and-shovels first."),
        ("2025", "The DeepSeek shock", f"A cheap Chinese model briefly shook AI stocks; Nifty IT {ev3('DeepSeek shock (Nifty IT)')}.", "Fears of cheaper AI hit IT services as much as chip makers."),
        ("2026", "Records and credit stress", "Korea's chip exports hit records while AI debt markets showed strain.", "The boom and its funding risk are rising together."),
    ]),
    today=stand(f"Nifty IT jumped {feed(sign(D['movers'][0]['chg']))} on 2026-10-16, the most unusual move of the day, on easing AI-disruption fears. (News desk.)",
                "Korea's September exports were a record, led by chips; US cloud capex is increasingly debt-funded and bank lenders are pulling back. (Web, 2026-10-16.)"),
    sowhat="Keep the two Indian AI trades apart: the build-out (power equipment, electronics, data centres, AI servers) has the momentum; IT services carry disruption risk that a single good day does not remove. An AI credit event would hit both through foreign flows.",
    indicators=[("Nifty IT", feed(fmt(next(m for m in D["movers"] if m["id"] == "nifty_it")["value"]))), ("Korea monthly exports", NOFEED), ("Semiconductor index (SOX)", NOFEED),
                ("Memory-chip contract prices", NOFEED), ("US cloud capex guidance, quarterly", NOFEED), ("AI credit spreads", NOFEED), ("India electronics exports", NOFEED)],
    deeper="world", deeper_label="The world cards", extra=sources([
        ("Korea Times: September exports record", "https://www.koreatimes.co.kr/economy/20261001/koreas-sept-exports-hit-record-1209-bil-on-robust-chip-sales"),
        ("KED Global: chip exports record", "https://www.kedglobal.com/economy/newsView/ked202610010001"),
        ("Axios: banks pull back from AI debt", "https://axios.com/2026/10/16/wall-street-limit-ai-spending-debt"),
        ("MIT Technology Review: what must happen for AI's bet to pay off", "https://www.technologyreview.com/2026/09/15/1144028/ai-infrastructure-boom-investment-bubble-risk/"),
        ("Naked Capitalism: CoreWeave and AI credit", "https://nakedcapitalism.com/2026/10/coreweave-stock-price-credit-market-nvidia-ai.html"),
        ("Zetwerk: India semiconductor manufacturing 2026", "https://www.zetwerk.com/blog/india-semiconductor-manufacturing-2026/"),
        ("Khaleej Times: India's chip ambitions", "https://www.khaleejtimes.com/supplements/indias-semiconductor-ambitions-grow-as-chip-manufacturing-investment-accelerates"),
        ("Export controls landscape 2026 (single source, verify)", "https://casrai.org/wp/?p=2848"),
    ])))

HOT_ROWS = [("Iran war and Hormuz", "escalating"), ("Russia–Ukraine", "elevated"), ("Taiwan Strait", "elevated"), ("South China Sea", "elevated"),
            ("Korean peninsula", "elevated"), ("India's borders", "calm")]
HOT_COLS = ["Oil and gas", "Shipping and freight", "Chips and supply chains", "Global risk appetite", "Sanctions and trade", "India directly"]
HOT_CELLS = {(0, 0): "high", (0, 1): "high", (0, 3): "med", (0, 4): "med", (0, 5): "high",
             (1, 0): "med", (1, 3): "low", (1, 4): "high", (1, 5): "med",
             (2, 2): "high", (2, 3): "high", (2, 4): "med", (2, 5): "low",
             (3, 1): "med", (3, 2): "low", (3, 3): "low", (3, 4): "low",
             (4, 2): "low", (4, 3): "low",
             (5, 3): "low", (5, 5): "med"}

def hotcard(name, trend, status, channel, exposed, signposts, memory, src):
    tcls = {"escalating": "t-esc", "elevated": "t-elv", "easing": "t-eas", "calm": "t-calm"}[trend]
    return (f'<div class="hot"><div class="hot-h"><b>{E(name)}</b><span class="{tcls}">{E(trend)}</span></div>'
            f'<div class="hot-r"><span class="rl">Status</span><span>{status}</span></div>'
            f'<div class="hot-r"><span class="rl">Channel into India</span><span>{E(channel)}</span></div>'
            f'<div class="hot-r"><span class="rl">Most exposed</span><span>{" ".join(f"<span class=\'ind x\'>{E(x)}</span>" for x in exposed)}</span></div>'
            f'<div class="hot-r"><span class="rl">Signposts</span><span>{E(signposts)}</span></div>'
            f'<div class="hot-r"><span class="rl">Market memory</span><span>{memory}</span></div>'
            f'<div class="hot-src">{src}</div></div>')
def s1(t, u): return f'<a href="{u}" target="_blank" rel="noopener">{E(t)}</a>'

IRAN_RUNGS = [("Talks fail; strikes on Iran begin", "28 February: US and Israeli strikes; Iran retaliates across the region"),
              ("Hormuz closed", "Iran attacks shipping and closes the strait; Brent jumps by half in three weeks"),
              ("US campaign and naval blockade", "March to April: air campaign to reopen the strait, then a blockade"),
              ("Ceasefire and talks", "April to June: a pause, then a memorandum of understanding; Brent back near prewar"),
              ("Truce collapses", "July: ships attacked, the truce declared over; flows partly restored under escorts"),
              ("Tanker war escalates", "October: strikes on more than a dozen ships, mines; Brent back near its spring high"),
              ("Gulf export infrastructure hit", "Tail risk: attacks on Gulf states' terminals or a long, total closure")]
TAIWAN_RUNGS = [("Grey-zone pressure", "Air incursions across the median line, coast-guard incidents"),
                ("Large live-fire drills", "Multi-sea exercises and new legal measures; October 12–20 drills under way"),
                ("Quarantine or inspection regime", "Coast-guard checks on shipping to Taiwan"),
                ("Blockade", "Shipping to Taiwan halted; chip supply disrupted"),
                ("Armed conflict", "Global technology supply shock; US–China escalation")]

CH.append(dict(id="gl-9", track="Global", title="Hot spots: the conflicts that can move markets", mins="six",
    hook=P("Six live conflicts matter for Indian markets this autumn. One is a hot war already moving oil every day; the others are pressure points "
           "whose escalation would hit oil, shipping, chips or global risk appetite. This chapter is the one part of the framework refreshed every week."),
    body=fig(C.heat_matrix(HOT_ROWS, HOT_COLS, HOT_CELLS, title="Which conflict reaches India through which channel, this week"),
             "Our assessment, refreshed weekly from the news desk and a web check. High: already moving that channel or would move it sharply on escalation. "
             "Trend is the direction over the past month.") +
         fig(C.line_panel(D3["brent_2026"], label="Brent through the Iran war, $ a barrel", color="#d97706", h=190, fmt="{:.0f}",
                          markers=[("2026-02-28", "war begins"), ("2026-04-08", "ceasefire"), ("2026-06-17", "MoU"), ("2026-07-07", "truce collapses"), ("2026-10-11", "tanker war")]),
             f"Weekly, from our feed; event dates web-checked. Nifty on the first trading day of the war: {ev3('Iran war begins')}; on the ceasefire: {ev3('Ceasefire announced')}.") +
         fig(C.ladder(IRAN_RUNGS, 5, title="Iran war: the escalation ladder"), "Each rung up has meant a higher war premium in oil; the ceasefire rung shows how fast it can come out.") +
         fig(C.ladder(TAIWAN_RUNGS, 1, title="Taiwan Strait: the escalation ladder"), "The rung that would matter for markets is the third: any formal control of shipping to Taiwan.") +
         '<div class="hots">' +
         hotcard("Iran war and Hormuz", "escalating",
                 "US–Israeli strikes since 28 February; a spring ceasefire collapsed in July; Iran stepped up attacks on tankers in October and claims a supertanker hit a mine on 17 October.",
                 "Oil and LPG prices, the rupee, the current account and the fiscal; freight; Gulf remittances; Indian firms named in Iran sanctions.",
                 ["Aviation", "Oil marketing", "Paints", "FMCG", "Logistics"], "A ceasefire that holds; escort convoys restoring flows; any strike on Gulf export terminals.",
                 f"Nifty around the war's phases: start {ev3('Iran war begins')}; ceasefire {ev3('Ceasefire announced')}. {ch_link('gl-3', 'Oil and the Gulf')}",
                 s1("CNN, 2026-10-11", "https://www.cnn.com/2026/10/11/middleeast/iran-hormuz-oil-analysis-intl") + " · " + s1("Britannica: 2026 Iran war", "https://www.britannica.com/event/2026-Iran-war") + " · " + s1("CRS: US conflict with Iran", "https://www.congress.gov/crs-product/R48887")) +
         hotcard("Russia–Ukraine", "elevated",
                 "A US-announced 'energy ceasefire' on 11 October that neither side has confirmed; strikes continue. The US eased sanctions on Russian diesel; the EU approved its largest package since 2022; trilateral talks proposed for late October.",
                 "Russian crude and diesel supply to India, sanctions risk for refiners and banks, fertiliser and edible-oil prices, defence supplies.",
                 ["Oil & Gas", "Banks", "Chemicals & Specialty"], "Confirmation of the energy ceasefire; the late-October talks; any change in US sanctions on Russian oil.",
                 f"The 2022 invasion: Nifty {evline('Russia invades Ukraine')}. {ch_link('gl-6', 'Russia and sanctions')}",
                 s1("Axios, 2026-10-11", "https://www.axios.com/2026/10/11/trump-russia-ukraine-energy-ceasefire-zelensky") + " · " + s1("Al Jazeera, 2026-10-13", "https://www.aljazeera.com/economy/2026/10/13/trump-insists-energy-ceasefire-holds-as-ukraine-reports-new-russian-strikes")) +
         hotcard("Taiwan Strait", "elevated",
                 "Chinese live-fire drills across several seas from 12 to 20 October; a revised Chinese defence-mobilisation law in force since 1 October; a US official says investors overprice the risk of conflict.",
                 "Leading-edge chips for every Indian electronics and auto maker, global risk appetite, US–China escalation; India could also gain China+1 orders.",
                 ["Consumer Durables", "Automobiles", "IT Services & ITeS"], "Any quarantine or inspection of shipping to Taiwan; US–Japan missile deployments near Taiwan; TSMC guidance.",
                 "No Taiwan crisis in our data window has moved the Nifty measurably, and we hold no Taiwan or chip index to test the channel properly.",
                 s1("AEI/ISW, 2026-10-16", "https://www.aei.org/commentary/china-taiwan-update-october-16-2026/") + " · " + s1("CNBC, 2026-10-09", "https://www.cnbc.com/2026/10/09/taiwan-trump-china-militia-boat-tsmc-.html")) +
         hotcard("South China Sea", "elevated",
                 "Repeated China–Philippines confrontations, including a violent boarding at Second Thomas Shoal in July and harassment near Thitu in early October.",
                 "Shipping lanes to East Asia for Indian exports, US–China escalation risk.",
                 ["Logistics & Transport"], "Any incident invoking the US–Philippines defence treaty; ASEAN talks on a code of conduct.",
                 "No measurable Nifty reaction to past incidents.",
                 s1("China-Global South, 2026-10-05", "https://chinaglobalsouth.com/2026/10/05/philippines-china-harassment-south-china-sea/") + " · " + s1("ACLED", "https://acleddata.com/expert-comment/are-tensions-south-china-sea-rising")) +
         hotcard("Korean peninsula", "elevated",
                 "North Korea's fourth launch in a month on 12 October, roughly its sixteenth round this year; a border mine blast in September; talk of a Kim–Trump summit.",
                 "Korea makes most of the world's high-bandwidth memory; a crisis would hit the AI chip chain and Asian risk appetite.",
                 ["Consumer Durables", "IT Services & ITeS"], "A summit announcement, a nuclear test, or incidents on the border.",
                 "Missile tests have not moved Indian markets.",
                 s1("Reuters via Daily Maverick, 2026-10-12", "https://www.dailymaverick.co.za/article/2026-10-12-north-korea-fires-missiles-days-after-south-koreas-hypersonic-test.md")) +
         hotcard("India's borders", "calm",
                 "No active escalation with Pakistan or China since the May 2025 conflict and ceasefire.",
                 "Defence spending and orders; brief risk-off on an incident.",
                 ["Defence & Aerospace"], "Terror attacks, Line of Control incidents, border talks with China.",
                 f"Six border events since 2016: average Nifty {feed(f'{geo_avg30:+.1f}%')} thirty sessions later. {ch_link('gl-7', 'Conflict on India’s borders')}",
                 "News desk; our event studies") +
         '</div>' +
         P("<b>How to use this chapter.</b> Read the heat matrix for which channel each conflict uses, then the cards for what would move it. A conflict "
           "that touches oil or chips matters more for India than one that does not, however loud the headlines."),
    history=history("how geopolitical shocks have moved markets", [
        ("1973", "Arab–Israeli war and embargo", "The template for an oil-supply war shock.", "Oil wars reprice energy for years, not days."),
        ("1990–91", "Gulf war", "Oil doubled, then fell as the war ended quickly.", "Markets bottom when the war's outcome becomes clear."),
        ("2003", "Iraq invasion", "Markets rallied once the invasion began.", "Uncertainty before a war often costs more than the war."),
        ("2014", "Crimea", "Sanctions began; limited market effect outside Russia.", "Sanctions shocks are slow and regional at first."),
        ("2022", "Ukraine invasion", f"Nifty {evline('Russia invades Ukraine')}.", "A war that hits energy and food goes global."),
        ("2026", "Iran war", f"Nifty at the start {ev3('Iran war begins')}; Brent {feed(sign(EPIS['2026']['brent_chg']))} over the war so far.", "Hormuz is the one chokepoint that turns a regional war into a global oil shock."),
    ]),
    today=stand("Most important this week: tanker attacks and mines in Hormuz, Brent back near its spring high, and the unconfirmed Russia–Ukraine energy ceasefire.",
                "Updated weekly; refreshed the same day if the news desk flags a major escalation."),
    sowhat="Only the Iran war is moving Indian markets today. Taiwan and Korea are the tail risks that would matter most through chips; Russia–Ukraine matters through sanctions on crude. Size hedges to oil, not to headlines.",
    indicators=[("Brent", feed(fmt(B["value"]))), ("Hormuz tanker transits", NOFEED), ("Geopolitical risk index", NOFEED), ("Freight rates", NOFEED), ("News desk themes", "weekly")],
    deeper="history", deeper_label="History that still bites", extra=sources([
        ("CNN: Iran tries to regain its stranglehold on shipping (2026-10-11)", "https://www.cnn.com/2026/10/11/middleeast/iran-hormuz-oil-analysis-intl"),
        ("CNBC: crude exports through Hormuz hit prewar levels (2026-09-30)", "https://www.cnbc.com/2026/09/30/iran-war-strait-hormuz-gulf-oil-fuel.html"),
        ("Al Jazeera live blog (2026-10-17), IRGC mine claim, unverified", "https://www.aljazeera.com/news/liveblog/2026/10/17/draft-2"),
        ("Britannica: 2026 Iran war", "https://www.britannica.com/event/2026-Iran-war"),
        ("Congressional Research Service: US conflict with Iran", "https://www.congress.gov/crs-product/R48887"),
        ("AEI/ISW: China & Taiwan update (2026-10-16)", "https://www.aei.org/commentary/china-taiwan-update-october-16-2026/"),
        ("Taiwan News: live-fire drills condemned", "https://www.taiwannews.com.tw/news/6456147"),
        ("Axios: Russia–Ukraine energy ceasefire (2026-10-11)", "https://www.axios.com/2026/10/11/trump-russia-ukraine-energy-ceasefire-zelensky"),
        ("Critical Threats: Russian offensive assessment (2026-10-12)", "https://www.criticalthreats.org/analysis/russian-offensive-campaign-assessment-october-12-2026"),
        ("China-Global South: South China Sea harassment (2026-10-05)", "https://chinaglobalsouth.com/2026/10/05/philippines-china-harassment-south-china-sea/"),
        ("Daily Maverick (Reuters): North Korea missile launch (2026-10-12)", "https://www.dailymaverick.co.za/article/2026-10-12-north-korea-fires-missiles-days-after-south-koreas-hypersonic-test.md"),
    ])))

# ═════════════════════════════ SYNTHESIS ═════════════════════════════
mini_q = quadrant_svg(trail, "India growth and inflation quadrant")
reg_row = RT[RN["regime"]]
reg_bars = sorted(((n, reg_row[s]["rel"], reg_row[s]["t"]) for s, n in SECT), key=lambda r: -r[1])
CH.append(dict(id="sy-1", track="Synthesis", title="Regimes: combining both frameworks", mins="four",
    hook=P("The India and global frameworks meet in one question: are growth and inflation accelerating or decelerating? The answer names the regime, "
           "and the regime organises everything else."),
    body=f'<div class="fig"><div class="seeit-two"><div>{mini_q}</div><div><p class="b-p" style="font-size:15px">India: <b>{india_quad}</b>. Over the three months to {now_m}, IIP growth {feed(sign(now_x, " pp", 1))}, CPI inflation {feed(sign(now_y, " pp", 1))}. Market-implied regime: {RN["regime"]} (copper against gold {feed(sign(RN["cg_6m"]))}, Brent {feed(sign(RN["brent_yoy"]))} year on year). Data and markets agree.</p></div></div><div class="fig-cap">Official trail since 2026; the CPI rebasing leaves a gap in 2025.</div></div>' +
         fig(C.hbars(reg_bars, title=f"Sector return against the Nifty in the month after a {RN['regime'].lower()} reading, since 2016"),
             f"The strongest of the {n_cells} regime-by-sector cells has |t| {feed(f'{best_t:.1f}')}; a fair bar for {n_cells} tests is about {feed(f'{bonf:.1f}')}. "
             "These are priors, not signals, and none is in the model.") +
         P("Two caveats specific to now. This reflation is supply-led, worse for oil consumers than a demand-led one. And the most likely next regime is "
           "stagflation: inflation still rising on fuel pass-through while higher rates start to slow activity. The global inputs (US yields, oil) and "
           "the Indian ones (RBI, fiscal) both point that way."),
    history=history("India's regimes since 2015", [
        ("2015–16", "Deflation", "Commodity collapse, falling inflation, a growth scare.", "Bonds and defensives did best."),
        ("2017", "Goldilocks", "Low inflation, GST transition over, flows strong.", "Broad rally, small caps led."),
        ("2018", "Stagflation", "Oil and the rupee pushed inflation up while credit froze.", "Small caps fell hardest."),
        ("2021", "Reflation", "Reopening growth, commodity prices rising.", "Metals and cyclicals led."),
        ("2022", "Stagflation", "War inflation and hikes.", "Energy and banks held up; tech fell."),
        ("2026", "Reflation, turning", "Supply-led oil inflation with growth still firm.", "The turn to stagflation is the risk."),
    ], "Regime labels for past years are qualitative summaries, not computed; the bar chart above is computed."),
    today="", sowhat="Lean towards commodity and capex exposure over defensives and gold while the regime holds, sized as a weak prior; watch the September IIP and October CPI for the turn.",
    indicators=[("India regime", feed(india_quad)), ("Market-implied", feed(RN["regime"])), ("US regime", NOFEED)],
    deeper="playbook", deeper_label="The playbook"))

e26 = EPIS["2026"]; e18 = EPIS["2018"]; e22 = EPIS["2022"]
cmp_rows = "".join(f"<tr><td class='mono'>{lab}</td><td class='num mono'>{e['brent_chg']:+.1f}%</td><td class='num mono'>{e['usdinr_chg']:+.1f}%</td><td class='num mono'>{e['us10y_bps']:+.0f}</td><td class='num mono'>{e['nifty_mdd']:+.1f}%</td><td class='num mono'>{e['vix_peak']:.0f}</td></tr>"
                   for lab, e in (("2018", e18), ("2022", e22), ("2026", e26)))
CH.append(dict(id="sy-2", track="Synthesis", title="Case study: the 2026 oil shock, end to end", mins="five",
    hook=P("The current episode runs through both frameworks. Read in sequence, it also tells you what to watch for the turn."),
    body=fig(C.stacked(
        C.line_panel([p for p in D2["w_brent_crude"] if p[0] >= "2025-10-01"], label="Brent", color="#d97706", h=110, show_years=False),
        C.line_panel([p for p in D2["w_usdinr"] if p[0] >= "2025-10-01"], label="USD/INR", color="var(--red)", h=110, fmt="{:.1f}", show_years=False),
        C.line_panel([p for p in D2["w_us_10y"] if p[0] >= "2025-10-01"], label="US ten-year, %", color="var(--blue)", h=110, fmt="{:.2f}", show_years=False),
        C.line_panel([p for p in D2["w_nifty50"] if p[0] >= "2025-10-01"], label="Nifty 50", color="var(--accent)", h=130)),
        "The last twelve months, weekly: oil and US yields rising together, the rupee peaking in July and then held by the RBI, the Nifty off its January high.") +
         '<ol class="story">' + "".join(f"<li><b>{a}</b> {b}</li>" for a, b in [
            ("Global: a war in the Gulf.", f"US–Israeli strikes on Iran from 28 February; Iran closes Hormuz; a spring ceasefire collapses in July and tanker attacks escalate in October. Brent {feed(fmt(B['value']))}. {ch_link('gl-9', 'Hot spots')}"),
            ("Global: US yields at their high.", f"Term premium and inflation fear push the ten-year to {feed(T10)}. {ch_link('gl-2', 'The dollar and US rates')}"),
            ("India: who absorbs it.", f"Oil companies and airlines first; then the excise-versus-deficit choice and fertiliser subsidies. {ch_link('in-7', 'Fiscal policy')}"),
            ("India: the external gap.", f"Imports far outpace exports; the gap leans on portfolio money. {ch_link('in-1', 'The balance sheet')}"),
            ("India: inflation projection.", f"Headline {feed(sign(MP['cpi_general']['yoy']))} and turning up, fuel still to come. {ch_link('in-3', 'Inflation')}"),
            ("India: the RBI turns.", f"A hike, a higher cash reserve requirement, rupee defences. {ch_link('in-4', 'The RBI')}"),
            ("Both: flows.", f"Foreign {feed(rupee(F20['FII']))}, domestic {feed(rupee(F20['DII']))} over twenty sessions. {ch_link('in-6', 'Flows')}"),
            ("Both: the regime.", f"Supply-led reflation, stagflation the likely next state. {ch_link('sy-1', 'Regimes')}"),
         ]) + "</ol>" +
         f'''<div class="fig"><table class="b-table"><thead><tr><th>Episode</th><th class="num">Brent</th><th class="num">USD/INR</th><th class="num">US 10y, bps</th><th class="num">Nifty worst</th><th class="num">VIX peak</th></tr></thead><tbody>{cmp_rows}</tbody></table>
         <div class="fig-cap">Computed over each episode window. 2026 has the biggest oil move of the three, the smallest rupee move (because it is being defended) and the calmest fear gauge.</div></div>''',
    history=history("how the comparable episodes ended", [
        ("2013", "Ended with administrative measures", "Rate defence, gold curbs and the deposit swap stabilised the rupee within months.", "Policy ingenuity can end a currency crisis before oil falls."),
        ("2018", "Ended with oil", "Oil fell sharply late in the year; the rupee and market recovered.", "The external variable turned first."),
        ("2022", "Ended with oil and peak hawkishness", "Oil eased from its spike and the market bottomed before the Fed stopped hiking.", "Markets bottom on the second derivative, not the level."),
    ]),
    today="", sowhat="The base case is a grinding squeeze with wide dispersion. The turn comes from the oil route and the rupee, not domestic data; foreign positioning is bearish but, on our data, not a reliable rally trigger.",
    indicators=[("Brent", feed(fmt(B["value"]))), ("USD/INR", feed(fmt(U["value"]))), ("US ten-year", feed(T10)), ("RBI stance", "next meeting")],
    deeper="shock", deeper_label="The full shock walk-through"))

CH.append(dict(id="sy-3", track="Synthesis", title="The daily read: a five-minute routine, and the traps", mins="two",
    hook=P("The brief answers the same questions in the same order every day, so that changes stand out."),
    body='<ol class="routine">' + "".join(f"<li><b>{a}</b><span>{b}</span></li>" for a, b in [
        ("Verdict.", "Has the one-line state of play changed? If not, the rest is confirmation."),
        ("The four lights.", "Oil, US rates and the dollar, flows and positioning, the RBI. A light changing colour is the event; the level is context."),
        ("Unusual moves.", "Ranked against each series' own volatility, with the industries each move helps or hurts from the 38 industry pages."),
        ("Winners and losers.", "The sector map implied by the regime and house view. Check it against your book."),
        ("What's coming.", "Releases and meetings that could change a light."),
    ]) + "</ol>" +
         P("<b>The traps.</b> Reading a single day of flows. Treating an expected decision as news. Confusing a level with a change. Over-fitting the regime "
           "or oil tables, which are priors with weak statistics. And trading folklore: our own data says a crowded foreign short is not a reliable "
           "rally signal."),
    history="", today="", sowhat="The brief is a monitoring tool, not a signal: its job is to tell you which chapter's mechanism is driving the market this week.",
    indicators=[], deeper="today", deeper_label="Open today's brief"))
