"""Macro mockup v2: the same computed data (core.py), with the prose written out in full.

Rule kept: hand-written prose carries no figures except years and calendar words; every figure on the page
is inserted from the database by core.py.
"""
from core import *   # noqa: F401,F403  (data, helpers, CSS)

T10 = f'{T["value"]:.2f}%'

# ═══════════════════════════ building blocks ═══════════════════════════

def card(num, title, speed, ask, *blocks):
    return (f'<section class="card"><div class="q"><span class="num">{num}</span><h2>{E(title)}</h2>'
            f'<span class="speed">{E(speed)}</span></div><div class="ask">{E(ask)}</div>{"".join(blocks)}</section>')

def breath(t):  return f'<div class="breath"><b>In one breath.</b> {t}</div>'
def para(t):    return f'<p>{t}</p>'
def h3(t):      return f'<h3 class="sub">{E(t)}</h3>'
def analogy(t): return f'<div class="analogy"><b>Analogy.</b> {t}</div>'
def sowhat(t):  return f'<div class="sowhat"><b>So what for the stock</b>{t}</div>'
def note(t):    return f'<div class="tiny" style="margin-top:8px">{t}</div>'

def steps(items):
    return '<ol class="steps">' + "".join(f'<li><b>{E(a)}</b><div>{b}</div></li>' for a, b in items) + "</ol>"

def table(head, rows, cls="", extra_rows=""):
    return (f'<table class="{cls}"><thead><tr>' + "".join(f"<th>{E(h)}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + extra_rows + "</tbody></table>")

def watch(rows):
    return h3("Signals to watch") + table(["Signal", "What it tells you", "Reading now"], rows, "watch")

def lk(word):
    cls = {"likely": "lk-l", "possible": "lk-p", "unlikely": "lk-u"}.get(word.split()[0].rstrip(","), "lk-p")
    return f'<b class="{cls}">{E(word)}</b>'

def feed(v):    return f'<span class="mono">{v}</span>'
NOFEED = '<span class="nf">no feed yet</span>'

def ichips(names, cls="m"):
    return " ".join(f'<span class="ind {cls}">{E(n)}</span>' for n in names)

def rev_ind(ind_id, direction):
    return sorted({r["industry"] for r in REV.get(ind_id, []) if r["direction"] == direction})

# ═══════════════════════════ MAP ═══════════════════════════

M0 = card("M0", "India on one page", "the big picture", "If you read only one card, read this one.",
    breath("India is a large, young economy that runs mostly on its own households' spending. It imports most of its energy, so oil is its "
           "weak spot. It earns dollars from services and from workers abroad, so it can usually pay the bill. More and more of its savings "
           "now flow into the stock market every month."),
    steps([
        ("It runs on home demand.", "Household spending is the largest part of the economy by a wide margin. Exports matter far less than in East "
         "Asian economies. That shelters India from a global slowdown, but not from global money: when foreign investors leave, Indian markets "
         "fall even if Indian demand is fine."),
        ("Oil and the dollar are its two pressure points.", "India imports most of the crude it uses, plus a lot of gold and electronics. So it "
         "runs a current-account deficit, and foreign money has to fill the gap. A costly barrel or a strong dollar squeezes that gap from both "
         "sides at once."),
        ("Services and remittances are its cushion.", "Software, consulting and the global capability centres earn dollars every month, and India "
         "receives more money from workers abroad than any other country. Together they pay for a large share of the oil bill. That is why a "
         "normal oil price is manageable and a shock is not."),
        ("The state has been the main investor.", "Since the pandemic the government has spent heavily on roads, railways, power and defence "
         "while many private companies waited. Whether private companies now take over that role is the central question of this cycle."),
        ("Inflation is about food.", "Food is a large part of what a typical Indian household buys, far more than in rich countries. So the "
         "monsoon is a macro variable, and the RBI watches vegetable prices as closely as oil."),
        ("The RBI manages two things.", "It targets inflation, but it also manages the rupee. It rarely lets the currency fall freely and prefers "
         "to spend its reserves to slow a slide. Defending the rupee has side effects: it drains cash from banks and can force rates up."),
        ("Savings are moving into markets.", "Indian households used to keep their savings in gold, property and bank deposits. Since the "
         "pandemic a steady stream goes into mutual funds every month through systematic investment plans. That domestic money now often "
         "absorbs foreign selling, which changes how deep a sell-off can go."),
        ("Growth is priced richly.", "India has been among the fastest-growing large economies for years, and its stock market usually trades "
         "at a premium to other emerging markets. Good news is partly in the price; disappointments are punished."),
    ]),
    analogy("India is a big joint family that earns most of its income at home, runs its kitchen on imported gas, and has relatives abroad who "
            "send money home every month. In a normal year the remittances pay the gas bill. In a year the gas price doubles, the family "
            "dips into savings and borrows, and the neighbours start asking whether it can pay."),
    sowhat("Three questions explain most of what Indian markets do in any month: what oil is doing, what the US is doing to the dollar and "
           "yields, and whether domestic money is still coming in. The rest of this page is a deeper answer to those three."))

M1 = card("M1", "The plumbing", "India · how money flows", "Where does India's money come from, where does it go, and where can the pipes burst?",
    breath("Households save, banks and funds pool those savings, the government and companies borrow them, and foreign money fills whatever is "
           "left over. The RBI sits on top and controls the price, the volume and the exchange rate of the money in the pipes."),
    '''<div class="pipe">
      <div class="st"><h4>Households save</h4><ul><li>Bank deposits</li><li>Monthly investment plans into mutual funds</li><li>Insurance and pension funds</li><li>Gold and property</li></ul></div>
      <div class="st"><h4>Banks and markets pool it</h4><ul><li>Banks turn deposits into loans</li><li>Funds buy shares and bonds: these are the DIIs</li><li>Insurers buy long government bonds</li></ul></div>
      <div class="st"><h4>It becomes spending</h4><ul><li>The government borrows first, for its deficit</li><li>Companies borrow for plants and working capital</li><li>Households borrow for homes, cars and phones</li></ul></div>
      <div class="st"><h4>The world closes the loop</h4><ul><li>The current-account deficit is the shortfall</li><li>FDI fills it slowly and stays</li><li>FIIs fill it quickly and can leave</li><li>If they fall short, reserves drop and the rupee weakens</li></ul></div>
    </div>''',
    steps([
        ("Households save, and how they save is changing.", "Indian households save a large share of what they earn. For generations that went "
         "into gold, land and bank deposits. Since the pandemic a growing share goes into mutual funds through monthly plans, which arrive "
         "whatever the headlines say. At the same time households have borrowed more for homes and consumption, so their net financial "
         "savings have thinned. Less spare saving means more reliance on foreign money to fund investment."),
        ("Banks and funds turn savings into loans and bond purchases.", "Banks lend to companies and households. Mutual funds, insurers and "
         "pension funds buy shares and bonds; together they are the domestic institutional investors. Banks are also required by rule to hold "
         "a slice of their deposits in government bonds, which gives the government a captive buyer."),
        ("The government borrows first.", "The centre and the states together borrow a large part of the country's financial savings every year to "
         "fund their deficits. When they borrow more, they compete with companies for the same pool, and borrowing costs rise for everyone. "
         "Economists call that crowding out. It is why the size of the deficit matters to a stock investor."),
        ("The world fills the gap.", "India invests more than it saves. The difference shows up as a current-account deficit, and it has to be "
         "financed from abroad. Foreign direct investment builds factories and rarely leaves. Foreign portfolio investors buy listed shares and "
         "bonds and can sell in a day. Loans from abroad and deposits from Indians living overseas make up the rest. When these flows fall "
         "short, the RBI sells dollars from its reserves and the rupee slides."),
        ("The RBI controls the valves.", "It sets the price of money through the policy rate. It sets the volume through the cash banks must park "
         "with it and through buying or selling bonds. It sets the pace of the rupee by buying or selling dollars. These valves are connected: "
         "when the RBI sells dollars to defend the rupee, it takes rupees out of the banking system at the same time, so a currency defence "
         "tightens money even without a rate change."),
    ]),
    f'<div class="loop"><b>FIIs and DIIs sit inside this loop, not beside it.</b> FII money arrives when the gap needs filling and leaves when '
    f'US yields rise or the rupee looks weak. DII money is Indian savings arriving every month. Over the last twenty sessions FIIs sold '
    f'{feed(rupee(F20["FII"]))} and DIIs bought {feed(rupee(F20["DII"]))}: almost a mirror image.</div>',
    h3("Where the pipes burst"),
    para("The plumbing has failed in recognisable ways. In 2013 foreign money left faster than the gap could be closed and the rupee crashed. "
         "In 2018 a large lender that borrowed short and lent long ran out of funding, and credit to property and autos froze for a year. In 2022 "
         "foreign investors sold heavily as US rates rose, and domestic funds stepped in for the first time on a large scale. Each failure starts "
         "at a different pipe, but each shows up first in the same three places: the rupee, short-term interest rates and bank shares."),
    watch([
        ("FII and DII cash flows", "Whether foreign money is leaving and whether domestic money is catching it",
         f'FII {feed(rupee(F20["FII"]))}, DII {feed(rupee(F20["DII"]))} over 20 sessions'),
        ("Monthly mutual-fund inflows", "Whether households are still sending savings to the market", NOFEED),
        ("Bank credit and deposit growth", "Whether banks have enough deposits to fund the loans they are making", NOFEED),
        ("Government borrowing calendar", "How much savings the state will take before companies get their turn", NOFEED),
        ("Forex reserves", "How much ammunition the RBI has to defend the rupee", NOFEED + " · the news desk says they fell again"),
        ("Money-market rate", "The price of overnight money between banks", f'{feed(str(MR["value"]) + "%")} in {MR["date"][:7]} <span class="nf">stale</span>'),
    ]),
    analogy("A joint family's money. The elders save; the family account lends to the younger members starting businesses; one cousin, the "
            "government, always borrows first and borrows big; and when the family spends more than it earns, it borrows from the neighbours, "
            "who can ask for their money back at the worst possible moment."),
    sowhat("When the plumbing is under strain, the pain shows first in the rupee and in the stocks foreign investors own most heavily: the large "
           "private banks, IT and the biggest large caps. Domestic money cushions the market but rarely lifts it on its own. Lenders that fund "
           "themselves with short-term wholesale money are the first to crack when the pipes tighten."))

TOOLS_RBI = [
    ("Raise the policy rate", "Makes rupee assets pay more and slows borrowing, so demand for imports cools", "Slower growth, costlier loans, weaker bank and property shares", "Yes, in October"),
    ("Sell dollars from reserves", "Meets the demand for dollars directly and slows the rupee's fall", "Reserves are finite, and every dollar sold drains rupees from banks", "Yes, reserves are falling"),
    ("Raise banks' cash reserve rule", "Locks more bank deposits at the RBI, draining money that could chase dollars", "Squeezes bank margins and loan growth", "Yes, in October"),
    ("A separate dollar window for oil companies", "Lets state oil firms buy dollars away from the open market, so their big orders do not push the rupee down", "Moves the pressure onto the RBI's own balance sheet", "Yes, now and in 2013"),
    ("Special deposit schemes for Indians abroad", "Pulls in dollars at attractive rates when foreign money is scarce", "Expensive, and the money has to be repaid", "Not yet; used in 1998, 2000 and 2013"),
    ("Curb gold imports", "Cuts one of the biggest items in the import bill", "Smuggling rises, jewellers suffer", "Not yet; used in 2013"),
    ("Tighten currency-hedging rules", "Stops speculators betting on a weaker rupee", "Makes hedging harder for genuine importers and exporters", "Yes, in October"),
]
TOOLS_GOV = [
    ("Cut fuel excise duty", "Keeps pump prices from rising as fast as crude", "Loses tax revenue, widens the fiscal deficit"),
    ("Let state oil companies absorb losses", "Holds pump prices without touching the budget, for a while", "Hurts the oil companies' profits and balance sheets"),
    ("Tax windfall profits of oil producers", "Takes back some of the gain upstream producers make", "Hurts upstream oil shares and future investment"),
    ("Buy discounted crude from sanctioned sellers", "Lowers the average cost of a barrel", "Sanction and tariff risk from the US"),
]
HIST_TWIN = [
    ("2013", "Rising, high", "Record low after the Fed's taper hint", "Hiked, curbed gold, special deposit scheme", "Sold bonds and shares heavily"),
    ("2018", "Rising", "Fell steadily through the year", "Hiked twice", "Sold, then a lender's default froze credit"),
    ("2022", "Spiked after the Ukraine war", "Fell to a then-record low", "Hiked fast, starting between meetings", "Record selling, absorbed by domestic funds"),
    ("Now", f'Brent {feed(fmt(B["value"]))}, {feed(sign(B["chg_63"]))} in three months', f'{feed(fmt(U["value"]))}; record {feed("96.88")} on 2026-07-24', "Hiked in October and added rupee defences", f'{feed(rupee(F20["FII"]))} in 20 sessions'),
]
M2 = card("M2", "The twin deficits and the rupee", "India · the chain that matters most", "Why do the oil price, the rupee, inflation and RBI rates move together, and how does it end?",
    breath("A costly barrel widens the gap foreign money has to fill. The rupee weakens, imports get dearer, inflation rises, and the RBI has to "
           "choose between defending growth and defending the currency. The government faces its own version of the same choice."),
    '<div class="chain"><span class="n hot">Oil jumps</span><span class="a">›</span><span class="n hot">Import bill rises</span><span class="a">›</span><span class="n">Current-account gap widens</span><span class="a">›</span><span class="n hot">Rupee weakens</span><span class="a">›</span><span class="n">Imported inflation</span><span class="a">›</span><span class="n hot">RBI hikes and sells dollars</span><span class="a">›</span><span class="n">Reserves fall, loans dearer</span><span class="a">›</span><span class="n hot">FIIs sell</span></div>',
    steps([
        ("Oil jumps.", "India buys most of its crude abroad and pays in dollars. A higher price is effectively a tax paid to foreign producers, and "
         "it arrives every single day."),
        ("The import bill and the gap widen.", "Exports do not rise to match, so the current-account deficit gets bigger. Gold and electronics "
         "imports add to it, and a strong festive season makes it worse."),
        ("The rupee weakens.", "More dollars are needed than are coming in. Importers rush to buy dollars before the rupee falls further, "
         "exporters wait to sell theirs, and the move feeds on itself."),
        ("Inflation rises, twice.", "Fuel, fertiliser and freight get dearer directly, and a weaker rupee makes every other import dearer too. "
         "Fuel prices are partly set by the government, so the pass-through comes in steps rather than all at once."),
        ("The RBI responds.", "It raises rates to cool demand and make rupee assets more attractive, and it sells dollars to slow the slide. Both "
         "tighten money for the whole economy."),
        ("Foreign investors move first.", "They watch the same chain. A weaker rupee eats into their returns, so they sell before the chain plays "
         "out, which pushes the rupee down further. Domestic funds usually buy what they sell."),
    ]),
    h3("What the RBI can do, and what each tool costs"),
    table(["Tool", "How it works", "What it costs", "Used now?"], TOOLS_RBI),
    h3("What the government can do: the second deficit"),
    para("The government's main tool is fuel tax. Cutting it shields pump prices and inflation, but the lost revenue widens the fiscal deficit. "
         "That is the second deficit in \"twin deficits\": an oil shock widens the gap with the world and the gap in the budget at the same time."),
    table(["Tool", "How it helps", "What it costs"], TOOLS_GOV),
    h3("How it ends"),
    para("There are three exits. The good one: oil falls back, usually because the supply problem is fixed. The slow one: higher rates and prices "
         "cool demand until imports shrink and the gap closes, at the cost of a growth slowdown. The bad one: reserves run low before either "
         "happens, the rupee drops sharply, and the RBI is forced into large rate rises. India has had all three; the 1991 crisis was the bad exit "
         "in its most extreme form."),
    h3("History rhymes"),
    table(["Episode", "Oil", "Rupee", "RBI", "Foreign investors"], HIST_TWIN),
    analogy("A family that cooks on imported gas. When the cylinder price doubles, the monthly budget breaks, savings run down, and the bank "
            "charges more on the next loan because the family suddenly looks riskier. The family can cut back, borrow, or sell the jewellery, "
            "and each choice hurts somewhere."),
    sowhat("Every link in this chain is lit today. It decides when to own exporters, who earn in dollars and gain from a weaker rupee, and when to "
           "own rate-sensitive borrowers such as property developers, shadow banks and auto makers, who lose on every link. Oil marketing "
           "companies and airlines sit at the sharpest end."))

ENGINES2 = [
    ("Consumption", "the largest engine by far",
     "Jobs and wages, rural income from the monsoon and crop prices, cheap credit, tax cuts that leave money in pockets, festivals and weddings.",
     "Food inflation, rate rises, weak rains, a jobs scare in the cities, a squeeze on unsecured lending.",
     "Through the sales of companies that sell to households: two-wheelers and cars, consumer staples, paints, retail, hotels, airlines, and the "
     "lenders who finance them. Premium and mass-market demand have moved differently for several years: the top end has been strong, the "
     "bottom end weak.",
     "Festive demand is strong and led by premium goods. Rural demand is clouded by weak rains. The income-tax and goods and services tax cuts of "
     "the past year help; the October rate rise and higher fuel prices hurt.",
     gauge("iip_consumer_durables"), ["Automobiles", "FMCG", "Consumer Durables", "Retail", "Hospitality & Hotels", "NBFCs / Finance"]),
    ("Government capex", "the engine the state controls directly",
     "Budget allocations, strong tax collection, a government that has chosen public investment as its main growth lever.",
     "A fiscal squeeze, an election year when execution slows, a fuel-subsidy bill or tax cut that eats the budget.",
     "Through order books: construction and engineering firms, capital-goods makers, cement and steel, defence manufacturers, railway "
     "suppliers. Orders show up in company announcements months before revenue, so order inflows are the leading indicator.",
     "Still high, and still the main support for heavy industry. The oil shock is the threat: if fuel tax is cut to shield pump prices, the "
     "money has to come from somewhere, and capex is the easiest line to slow quietly.",
     gauge("iip_capital_goods", "capital-goods output is the closest proxy we hold"), ["Construction & Engineering", "Capital Goods & Industrial Machinery", "Cement", "Iron & Steel", "Defence & Aerospace"]),
    ("Private capex", "the engine that decides whether a boom lasts",
     "Full factories, visible demand, cheap credit, production-linked incentives, confidence that policy will not change.",
     "Rate rises, tariff or policy uncertainty, a demand scare, a weak global outlook.",
     "Through the same order books as government capex, plus bank loan growth to companies. Capex announcements and capacity use lead it; "
     "company commentary in results calls is the earliest signal.",
     "Busy where incentives point: electronics, power equipment, renewables, defence. Broad corporate capex stays cautious, and costlier money "
     "will not help. This is the engine everyone hoped would take the baton from the government, and it has not fully done so yet.",
     gauge("iip_manufacturing", "manufacturing output as a proxy; no capex feed yet"), ["Capital Goods & Industrial Machinery", "Power T&D", "Banks", "Industrial Services & Misc"]),
    ("Services exports", "India's quiet dollar earner",
     "Technology budgets in the US and Europe, a weaker rupee, more global firms setting up capability centres in India.",
     "A US slowdown, visa restrictions, AI tools that cut the hours clients pay for, a strong rupee.",
     "Through IT services and software companies, and indirectly through office property and consumption in the big tech cities. IT stocks "
     "react to US data and to the guidance of the largest firms each quarter.",
     "The largest IT firm reported muted demand, a steep new US fee on work visas added worry, and AI is pressing on pricing. Capability "
     "centres keep growing. A weaker rupee helps margins.",
     '<div class="gauge nofeed">no feed for services exports · Nifty IT is the market proxy (see the pulse)</div>', ["IT Services & ITeS", "Software Products & SaaS", "REITs"]),
    ("Goods exports", "engineering goods, pharma, chemicals, textiles, phones",
     "Global demand, a competitive rupee, trade deals that cut tariffs, supply chains moving out of China.",
     "Tariffs, freight shocks, a strong rupee, cheap Chinese competition.",
     "Through exporters' revenue and margins: pharma, chemicals, auto components, textiles, electronics assemblers. Phones have become one of "
     "the largest export lines in a few years, almost entirely thanks to the incentive schemes.",
     "US trade talks have hit a plateau, and the US penalty tariff linked to India's Russian oil purchases hangs over exporters. India is pushing "
     "deals with Europe and others. Attacks on Gulf shipping add freight cost and delay.",
     gauge("india_exports"), ["Pharmaceuticals", "Chemicals & Specialty", "Auto Components", "Consumer Durables"]),
]
eng2 = "".join(f'''<div class="eng"><h4>{E(n)} <span class="eng-size">{E(size)}</span></h4>
<div class="eng-row"><span class="tag-h">drives it</span>{E(dr)}</div><div class="eng-row"><span class="tag-x">kills it</span>{E(kl)}</div>
<div class="eng-row"><span class="tag-b">how it reaches stocks</span>{E(how)}</div>
<div class="eng-row"><span class="tag-m">where it stands</span>{E(now)}</div>{g}<div class="eng-inds">{ichips(inds)}</div></div>''' for n, size, dr, kl, how, now, g, inds in ENGINES2)
M3 = card("M3", "The engines", "India · what makes it grow", "What drives each engine, what stops it, how it reaches stocks, and where each one stands today.",
    breath("Five engines pull the economy: household consumption, government investment, private investment, services exports and goods "
           "exports. They rarely all run at once, and the market rewards the industries attached to whichever engine is speeding up."),
    f'<div class="eng-grid">{eng2}</div>',
    h3("How the engines pass the baton"),
    para("After the pandemic the government carried growth with heavy public investment while consumers recovered and companies waited. The plan "
         "was a hand-off: public capex would fill order books, factories would fill up, and private companies would start building. That hand-off "
         "has happened only in pockets. Consumption has split in two, with the well-off spending freely and the mass market struggling, which the "
         "income-tax and goods and services tax cuts of the past year were meant to fix. Exports were the hoped-for third leg and have run into "
         "tariffs. The oil shock now hits the two engines that were meant to accelerate next: consumption, through prices and rates, and private "
         "capex, through costlier money."),
    note("The gauge under each card comes from our feeds and updates on its own. The words above it are refreshed quarterly. The chips list the "
         "industry pages that ride each engine."),
    sowhat("Ask which engine is speeding up, not how fast the economy is growing. In a quarter where government capex accelerates and consumption "
           "slows, construction and capital-goods stocks can rise while consumer stocks fall, even with the same headline growth number."))

REF2 = [
    ("Reserve Bank of India", "The policy rate, banks' cash rules, liquidity, the rupee through its reserves, the rules for banks and lenders.",
     "A monetary policy committee of six sets the rate, three from the RBI and three from outside, with the governor holding the casting vote. "
     "It reacts to where it expects inflation to be a year or so out, not to this month's print. It cares about the rupee's speed more than its "
     "level, and it prefers small, signalled steps over surprises.",
     "Read the statement for changes in wording: the stance, the inflation forecast and the vote split. A dissent is often the first sign of the "
     "next move. The governor's press conference matters as much as the decision.",
     "Under the governor appointed in late 2024 the RBI cut rates through 2025 as inflation fell to multi-year lows. In October it reversed course: "
     "its first rate rise in years, plus a higher cash reserve rule, a dollar window for state oil firms and tighter hedging rules.",
     "Another rate rise", "likely while oil stays above a hundred and the rupee is under pressure", "A pause while oil is still high would surprise the market and lift rate-sensitive stocks."),
    ("Finance Ministry and the Budget", "Taxes, spending, government borrowing, fuel excise duty, the sale of state companies.",
     "Protects capital spending above almost everything else. Has moved its fiscal target toward a debt anchor rather than a yearly number. Cuts "
     "fuel excise in oil shocks to shield pump prices, and prefers tax relief for the middle class over big new welfare schemes.",
     "The February Budget sets the year: capex, the deficit, borrowing and tax changes. Between budgets, watch excise decisions on fuel and the "
     "monthly tax-collection numbers.",
     "Raised the income-tax exemption sharply in the 2025 Budget and cut goods and services tax rates to fewer slabs later that year, both meant to "
     "lift consumption.",
     "Fuel-duty relief", "possible if crude stays high; a capex cut before the Budget is unlikely", "A cut in the capex target would hit construction and capital-goods stocks hard."),
    ("GST Council", "Indirect tax rates and rules, decided by the centre and all the states together.",
     "Moves by consensus and slowly. Prefers rule changes to rate changes, and avoids anything that cuts states' revenue without compensation.",
     "Watch the agenda before each meeting: rate changes on specific goods move individual industries overnight.",
     "Approved a big round of easier rules with no rate changes: faster refunds, simpler filing for small sellers, export status for contract "
     "manufacturing.",
     "Rate changes", "unlikely in the near term", "A surprise rate cut on a mass-market item would lift that industry's stocks."),
    ("SEBI", "Market rules, derivatives, disclosures, fund rules, foreign investor registration.",
     "Tightens when retail speculation runs hot, consults before it acts, and phases big changes in over months.",
     "Consultation papers signal the direction months ahead. Final rules usually soften the draft.",
     "Tightened derivatives rules in late 2024. A new round of derivatives rules is due next.",
     "Tighter derivatives rules", "likely", "Hits exchange, broker and depository earnings; matters little to the wider economy."),
    ("The states", "Their own budgets, power distribution companies, stamp duty on property, fuel and liquor taxes.",
     "Spend on welfare before elections. State borrowing is now about as large as the centre's. Power-distribution losses are the chronic weak spot.",
     "Watch state budgets and election manifestos for cash-transfer promises, and power-distribution dues for the health of power companies.",
     "Several states face elections in the coming year, and Uttar Pradesh, the largest, votes in early 2027.",
     "New welfare promises", "likely ahead of state polls", "Large promises in a big state widen its deficit and can lift consumption locally."),
]
ref2 = "".join(f'''<div class="ref"><h4>{E(n)}</h4>
<div class="ref-row"><span class="rl">Controls</span><span>{E(c)}</span></div>
<div class="ref-row"><span class="rl">How it behaves</span><span>{E(b)}</span></div>
<div class="ref-row"><span class="rl">How to read it</span><span>{E(rd)}</span></div>
<div class="ref-row"><span class="rl">Latest</span><span>{E(now)}</span></div>
<div class="ref-row"><span class="rl">Next move</span><span><b>{E(mv)}</b>: {lk(lkw)}</span></div>
<div class="ref-row"><span class="rl">Would surprise</span><span>{E(sur)}</span></div></div>''' for n, c, b, rd, now, mv, lkw, sur in REF2)
M4 = card("M4", "The referees", "India · who sets the rules", "Who controls what, how each one usually behaves, how to read their signals, and what they will likely do next.",
    breath("Five referees shape the macro game: the RBI sets the price of money, the Finance Ministry sets taxes and spending, the GST Council sets "
           "indirect taxes, SEBI sets market rules, and the states run their own budgets. Each has a recognisable way of reacting."),
    f'<div class="ref-grid">{ref2}</div>',
    sowhat("The market moves on surprises, not decisions. Knowing a referee's usual reaction lets you tell a surprise from a decision that was "
           "already priced in. When the RBI does what it signalled, rate-sensitive stocks barely move; when it does more, they fall hard."))

TRACK = [
    ("Infrastructure", "Build roads, rail, ports and power at scale", "Public capex raised sharply since 2020 and kept high", "Construction, capital goods, cement, steel"),
    ("Manufacturing", "Production-linked incentives and self-reliance", "Worked best in phones and electronics, slower elsewhere", "Electronics assemblers, defence, select chemicals"),
    ("Fiscal discipline", "Bring the deficit down after Covid", "Deficit cut from its pandemic peak; target moved toward a debt anchor", "Banks and bond holders, through lower yields"),
    ("Taxes", "Simpler taxes, relief for the middle class", "Big income-tax relief in 2025; fewer goods and services tax slabs", "Consumer companies"),
    ("Welfare", "Direct transfers, free grain, housing", "Large and growing, delivered digitally", "Mass-market consumption, rural demand"),
    ("Labour and land", "Modernise old laws", "Labour codes brought into force; land reform shelved", "Manufacturers, slowly"),
    ("Trade", "Selective openness, protect strategic industries", "New trade deals with several partners; duties on cheap Chinese goods; US deal stalled", "Exporters, import-competing industries"),
]
M5 = card("M5", "The political economy", "India · what the government wants and does", "What this government says it wants, what it has actually done, how coalition politics changes that, and what follows.",
    breath("A government that believes growth comes from public investment, manufacturing and digital delivery of welfare, now governing with "
           "allies. It tends to protect capex and fiscal credibility, and to deliver relief through tax cuts and transfers rather than big new "
           "spending schemes."),
    h3("Who governs and how"),
    para("A coalition led by the BJP has governed since 2014 and is in its third term. Since the 2024 election it relies on allies for a majority, "
         "chiefly two regional parties from Andhra Pradesh and Bihar. The alliance's strong result in the Bihar election in late 2025 steadied "
         "the coalition. Allies with state-level priorities pull spending toward their states and make reforms that hurt their voters harder "
         "to pass."),
    h3("What it says it wants, and the record"),
    table(["Area", "Stated aim", "What happened", "Market winners"], TRACK),
    h3("How politics moves markets"),
    para("Indian markets price political risk in bursts. The clearest recent example is the 2024 election result: the market fell sharply on the "
         "day the ruling party lost its single-party majority, then recovered within days when it became clear policy would continue. State "
         "elections matter less to the index but more to specific industries: cash-transfer promises lift local consumption and widen state "
         "deficits; power-sector promises hurt power-distribution finances. Policy continuity is the asset the market pays for; uncertainty about "
         "it is what gets sold."),
    h3("Likely next, with reasons"),
    table(["Policy", "Likelihood", "Why"], [
        ("Capex stays the top budget priority", lk("likely"), "It is the government's core growth belief and the easiest lever it controls."),
        ("Welfare promises before state elections", lk("likely"), "Every major party has used cash transfers to win state polls."),
        ("Fiscal slippage from fuel subsidies or tax cuts", lk("possible"), "Depends on how long oil stays high; the government has protected its deficit target before."),
        ("A US trade deal this year", lk("possible"), "Talks have stalled, and US sanctions on Indian firms over Iranian oil complicate them."),
        ("A land-acquisition overhaul", lk("unlikely"), "Politically costly and opposed by allies."),
    ]),
    note("Neutral by rule: stated aims, the track record and likelihoods with reasons. Never a view on who is right or how to vote."),
    sowhat("Industries tied to the government's stated priorities, such as infrastructure, defence, electronics manufacturing and power, carry "
           "policy support that survives a weak quarter. Industries that depend on a policy the coalition finds hard to deliver should not be "
           "priced as if it will happen."))

HIST2 = [
    ("1991", "The balance-of-payments crisis", "Oil spiked during the Gulf war, remittances from the Gulf stopped, and India ran out of foreign currency; it pledged its gold to pay for imports.",
     "The crisis forced the reforms that opened the economy: the rupee was devalued, licences scrapped, foreign investment allowed.", "Reserves and the current account are the real constraint. Watch them every time oil spikes.", "strong"),
    ("2008", "The global credit freeze", "Foreign investors pulled money out of every emerging market at once. The rupee fell and Indian shares more than halved from their peak.",
     "The RBI cut rates hard and flooded the system with money; the government spent. India recovered faster than most.", "In a global panic India falls with the world first and recovers on domestic demand later.", "weak"),
    ("2013", "The taper tantrum", "A hint that the Fed would slow its bond buying sent foreign money out of Indian bonds. With high inflation and a wide current-account gap, India was named one of the most fragile economies.",
     "A new governor raised rates, curbed gold imports and opened a special deposit scheme for Indians abroad that pulled in dollars fast.", "A wide current-account deficit plus tighter US money is India's most dangerous mix.", "strong"),
    ("2016", "Demonetisation", "Most of the cash in circulation was cancelled overnight. The informal economy and rural demand took the hit.",
     "Digital payments jumped; formal, listed companies gained share from informal rivals over the following years.", "Policy shocks hurt the informal economy first; listed companies often gain share afterwards.", "weak"),
    ("2017", "The goods and services tax", "A single national tax replaced a tangle of state and central taxes. The switch-over was messy for small firms.",
     "After a few painful quarters, tax collection rose and more business moved into the formal economy.", "Structural reforms cost a few quarters before they pay.", "weak"),
    ("2018", "IL&FS", "A large infrastructure lender defaulted. Shadow banks that funded themselves with short-term money could no longer borrow, and credit to property and autos froze.",
     "The government took over the lender; the RBI tightened rules for shadow banks. Several lenders failed over the next two years.", "Watch lenders that live on short-term wholesale borrowing whenever rates rise.", "medium"),
    ("2020", "Covid", "A sharp crash in the spring, then one of the strongest rallies on record, fuelled by cheap money and a wave of new retail investors.",
     "The RBI cut rates to record lows and pumped in liquidity; the government focused on capex and free grain rather than cash handouts.", "Central-bank liquidity moves valuations more than earnings in the short run.", "weak"),
    ("2022", "The inflation spike", "The Ukraine war sent oil and food prices up. US rates rose fast and foreign investors sold Indian shares heavily.",
     "The RBI raised rates quickly, starting between scheduled meetings. Domestic funds absorbed the foreign selling.", "Domestic monthly-investment money now offsets foreign selling. You can see it again in today's flows.", "strong"),
    ("2024", "The election-result shock", "The ruling party lost its single-party majority. The market fell sharply on results day.",
     "Within days it was clear the coalition would continue the same policies, and the market recovered fully.", "The market sells policy uncertainty, then buys continuity. Political shocks without policy change fade fast.", "medium"),
]
hist2 = "".join(f'''<div class="hist2"><div class="hy mono">{y}</div><div><div class="h2t">{E(t)} <span class="rhyme rh-{rh}">rhymes with today: {rh}</span></div>
<div><b>What happened.</b> {E(w)}</div><div><b>What policy did.</b> {E(p)}</div><div class="hl"><b>Lesson for today.</b> {E(l)}</div></div></div>''' for y, t, w, p, l, rh in HIST2)
M6 = card("M6", "History that still bites", "India · nine episodes", "Which past episodes explain how the market reacts today, and how closely does each one rhyme with now?",
    breath("Most of what Indian markets do in a crisis has happened before. The 2013 and 2022 episodes, an oil or dollar shock meeting a wide "
           "current-account gap, rhyme most closely with today."),
    hist2,
    sowhat("When today's chain matches a past episode, the past episode is the best guide to which stocks fell first and which recovered first. "
           "In 2013 and 2022 the rupee and bank shares led the fall, exporters held up, and the recovery started when the oil or dollar pressure "
           "eased, not when growth data improved."))

WORLD = [
    ("W1", "United States", "The economy whose rates and dollar move Indian markets most.",
     "The Trump administration, in its second term since 2025: tariffs as a standing tool, an America-first industrial policy, large deficits, and open pressure on the Fed for lower rates. The Fed chair's seat changed hands in 2026, and the midterm elections come in November 2026.",
     "The world's largest economy and the issuer of the world's reserve currency. When US interest rates rise, money everywhere becomes more expensive and flows back to the US. The bond market has pushed the long-term yield to the highest level in our records this month, which means investors expect inflation and heavy government borrowing to keep rates high.",
     [("Tariffs stay a bargaining tool", "likely"), ("A trade deal with India this year", "possible"), ("Long yields fall back soon", "unlikely while oil stays high")],
     ["High US yields pull foreign money home, so FIIs sell Indian shares and bonds.", "A strong dollar weakens the rupee and raises the cost of oil in rupees.",
      "US technology budgets and visa rules set demand for Indian IT services; a steep new work-visa fee in 2025 raised costs.", "US tariffs, including a penalty linked to India's Russian oil purchases, set the outlook for exporters."],
     rev_ind("us_10y", "down"), rev_ind("usdinr", "up"),
     [("US 10-year yield", f'{feed(T10)}, {feed(sign(T["chg_63"]))} in three months'), ("US inflation and jobs", NOFEED), ("Fed policy rate", NOFEED), ("Dollar index", NOFEED)]),
    ("W2", "China", "The price-setter for the world's factory goods.",
     "Led by Xi Jinping, with the Communist Party firmly in control of economic policy. Priorities: technological self-reliance, manufacturing strength and stability over fast consumer-led growth.",
     "A property bust since 2021 has hurt household wealth and confidence. Factories keep producing more than China consumes, so it exports the surplus at low prices, which pushes down global prices for steel, chemicals, solar panels and much more. Stimulus comes in measured doses rather than one big push. Export controls on rare earths and other materials are now a regular tool.",
     [("Factory overcapacity continues", "likely"), ("A large consumer stimulus", "unlikely"), ("New export controls on critical materials", "possible")],
     ["Cheap Chinese exports set the ceiling for prices of Indian metals, chemicals and many manufactured goods.", "China's demand sets global prices for copper, iron ore and coal, which matter to Indian miners and steel makers.",
      "Supply chains leaving China bring orders to Indian electronics, pharma and chemicals firms.", "Rare-earth and component export controls can stall Indian auto and electronics production."],
     ["Iron & Steel", "Chemicals & Specialty", "Mining & Minerals", "Paper, Wood & Forest Products"], ["Consumer Durables", "Pharmaceuticals", "Auto Components"],
     [("Copper against gold", f'{feed(sign(RN["cg_6m"]))} in six months'), ("China producer prices", NOFEED), ("China factory surveys", NOFEED)]),
    ("W3", "Europe", "A large export market and the setter of carbon rules.",
     "Centrist governments under pressure from the populist right in several countries. The European Central Bank cut rates through 2024 and 2025. Germany loosened its borrowing limits in 2025 to spend more on defence and infrastructure.",
     "Growth is slow. Energy prices are higher than in the US or Asia since the 2022 gas crisis, which has made European chemical and heavy industry less competitive. A carbon border tax on imports of steel, aluminium, cement and fertiliser entered its paying phase in 2026.",
     [("A trade deal with India", "possible"), ("European rate cuts continue", "possible"), ("Carbon rules widen to more goods", "likely over time")],
     ["European demand drives orders for Indian engineering goods, chemicals, textiles and pharma.", "European gas prices decide whether European chemical plants can compete with Indian ones.",
      "The carbon border tax raises costs for Indian steel and aluminium exporters.", "German defence and infrastructure spending can pull in Indian capital-goods and defence suppliers."],
     ["Iron & Steel", "Mining & Minerals"], ["Chemicals & Specialty", "Pharmaceuticals", "Auto Components", "Capital Goods & Industrial Machinery"],
     [("European gas price", NOFEED), ("Euro area factory surveys", NOFEED)]),
    ("W4", "Japan", "The source of the world's cheapest borrowing, and of sudden sell-offs.",
     "A prime minister who took office in late 2025 favouring fiscal support. The Bank of Japan ended negative interest rates in 2024 and has been raising them slowly since.",
     "For decades Japan's near-zero rates let investors borrow yen cheaply and buy higher-yielding assets everywhere, including Indian shares. When Japanese rates rise or the yen jumps, those trades unwind at once. That is what happened in August 2024, when markets around the world fell sharply in a day. Japan is also one of the largest sources of foreign direct investment in India.",
     [("The Bank of Japan raises rates again", "possible"), ("A sudden carry-trade unwind", "possible, unpredictable in timing")],
     ["A yen-funded trade unwinding sells everything risky at once, including Indian shares, regardless of Indian news.", "Japanese companies invest directly in Indian autos, electronics and infrastructure."],
     [], ["Automobiles", "Auto Components"],
     [("Yen against the dollar", NOFEED), ("Japanese government bond yields", NOFEED)]),
    ("W5", "The Gulf and Russia", "The oil, the shipping route and the workers.",
     "Gulf monarchies that are among India's largest suppliers of oil and gas and home to millions of Indian workers. Russia, under Vladimir Putin, has been India's largest crude supplier since 2022 at a discount, under sanctions pressure.",
     "Attacks on Gulf shipping and the closure of the Hormuz sea route have put a war premium in oil prices. US sanctions on Russia's largest oil companies in 2025 and a US penalty tariff on India over its Russian purchases made the discounted barrel harder to buy. New US sanctions on Iranian oil now also cover Indian firms.",
     [("The war premium stays while Hormuz is disrupted", "likely"), ("Russian crude flows to India shrink further", "possible"), ("A negotiated reopening of the route", "possible")],
     ["The price of every barrel India imports, and so the current account, the rupee and inflation.", "Remittances from Indian workers in the Gulf, the largest single source of money sent home.",
      "Gulf sovereign funds are large investors in Indian infrastructure, renewables and listed companies.", "Freight costs and delivery times for Indian exports through the Red Sea and the Gulf."],
     rev_ind("brent_crude", "down"), rev_ind("brent_crude", "mixed"),
     [("Brent crude", f'{feed(fmt(B["value"]))}, {feed(sign(B["chg_63"]))} in three months'), ("Remittances", NOFEED), ("Container freight", NOFEED)]),
]
def world_card(num, name, sub, lead, econ, guesses, channels, hurt, both, w):
    exposed = ""
    if hurt:
        exposed += '<div><span class="tag-x">most exposed</span>' + ichips(hurt, "x") + "</div>"
    if both:
        exposed += '<div style="margin-top:4px"><span class="tag-m">exposed both ways or helped</span>' + ichips(both, "m") + "</div>"
    return card(num, name, "the world", sub,
        f'''<dl class="fields">
          <dt>Who leads, and the leaning</dt><dd>{E(lead)}</dd>
          <dt>The economy in a paragraph</dt><dd>{E(econ)}</dd>
          <dt>Policy guesses</dt><dd>{"<br>".join(f"{E(g)}: {lk(l)}" for g, l in guesses)}</dd>
          <dt>Channels into India</dt><dd><ul class="tight">{"".join(f"<li>{E(c)}</li>" for c in channels)}</ul></dd>
          <dt>Indian industries exposed</dt><dd>{exposed}<div class="tiny">From the reverse dial index where a feed exists; otherwise from the industry pages.</div></dd>
          <dt>What to watch</dt><dd>{"<br>".join(f"{E(a)}: {b}" for a, b in w)}</dd>
        </dl>''')
WORLD_HTML = "".join(world_card(*w) for w in WORLD)

W6 = card("W6", "How a global shock reaches an Indian stock", "the world · walk-through", "Take today's shock, the Gulf oil disruption, and follow it from a tanker to a share price.",
    breath("A disruption in the Gulf becomes a higher pump price, a weaker rupee, a rate rise and a foreign sell-off, in that order, and each step "
           "has its own winners and losers on the Indian market."),
    steps([
        ("The shipping route closes.", f"Attacks on Gulf shipping and the closure of the Hormuz route remove supply. Brent is at {feed(fmt(B['value']))}, "
         f"{feed(sign(B['chg_63']))} in three months. Card W5."),
        ("India's oil companies feel it first.", "State oil marketing companies buy crude at the new price but sell petrol and diesel at prices the "
         "government watches closely, so their margins shrink before anyone else's. Airlines pay more for fuel at once. Upstream producers gain "
         "unless the government taxes the windfall. Industry pages: Oil & Gas, Aviation."),
        ("The government chooses.", "Either pump prices rise, which feeds inflation, or fuel taxes are cut, which widens the deficit. Card M4, "
         "Finance Ministry."),
        ("Inflation picks it up.", f"Fuel, freight and fertiliser costs flow into prices with a lag. CPI was {feed(sign(cpi_h['yoy']))} in "
         f"{cpi_h['month']}, up from {feed(sign(cpi_h['prev']))}. Lesson 3."),
        ("The rupee and the RBI respond.", "The import bill widens the current-account gap, the rupee comes under pressure, and the RBI raises "
         "rates and sells dollars. That happened in October. Card M2."),
        ("Foreign investors sell.", f"FIIs sold {feed(rupee(F20['FII']))} over twenty sessions and hold only {feed(str(FII['value']) + '%')} of "
         "their index futures long. Domestic funds bought almost as much. The clock's market gauges."),
        ("The stock market sorts the winners and losers.", "Paints, airlines, autos and consumer staples lose on input costs and rates. Property "
         "and shadow banks lose on rates. IT and pharma exporters gain from a weaker rupee. Upstream oil gains on price. The pulse shows which "
         "industries each day's move helps or hurts."),
    ]),
    sowhat("Every step of this chain has a feed or a news theme behind it on this page. When the shock eases, the same chain runs in reverse, and "
           "the stocks that fell first, the rate-sensitive and oil-consuming ones, usually recover first."))

MAP = M0 + M1 + M2 + M3 + M4 + M5 + M6 + WORLD_HTML + W6

# ═══════════════════════════ CLOCK ═══════════════════════════

C1 = card("C1", "The regime quadrants", "weekly · computed", "Is growth speeding up or slowing down, and is inflation rising or falling?",
    breath("India's growth and inflation are both rising, which puts it in the reflation quadrant. That is the quadrant where central banks "
           "tighten, and the RBI already has."),
    f'''<div class="clock2">
      <div class="qbox"><h4>India</h4><div class="qv">{india_quad}</div>
        <div class="tiny">x: change over three months in IIP growth (three-month average) · y: change over three months in CPI inflation. Latest {now_m}: growth {sign(now_x, " pp", 1)}, inflation {sign(now_y, " pp", 1)}. Trail since {trail[0][0]}.</div>
        {quadrant_svg(trail, "India growth and inflation quadrant")}
        <div class="tiny">The CPI series changed base in 2025: year-on-year inflation is missing from 2025-04 to 2025-12, so the trail starts in 2026.</div></div>
      <div class="qbox"><h4>United States</h4>
        <div class="nofeed-box"><b>no feed</b><div>US CPI and industrial production are not in the database yet (plan 0028, feeds phase: FRED through the host door).</div><div>What we do hold: the US 10-year yield at <b class="mono">{T10}</b>, {sign(T["chg_63"])} in three months, which says the bond market is pricing tighter money.</div></div></div>
    </div>''',
    h3("How to read the quadrant"),
    para("The quadrant does not ask whether growth or inflation is high. It asks which way each one is moving, because markets price change, not "
         "levels. Goldilocks, growth speeding up with inflation cooling, is the best quadrant for shares and bonds together. Reflation, both "
         "speeding up, is good for companies' revenue but brings rate rises. Stagflation, growth slowing while inflation rises, is the worst for "
         "almost everything except cash and gold. Deflation, both slowing, is bad for profits but good for bonds, because rate cuts follow."),
    h3("Why the dot is where it is"),
    para("Industrial output has been accelerating for several months, helped by capital goods and consumer durables production ahead of the festive "
         "season. Inflation has turned up from very low levels, first through food and now through fuel. Both readings come from the latest prints "
         "we hold, for August; the oil shock that intensified in September and October is not in them yet."),
    h3("What would move the dot next"),
    table(["Next print", "What to look for", "Which way it pushes"], [
        ("CPI for September and October", "Fuel and transport prices catching up with crude", "Up the inflation axis: toward reflation or stagflation"),
        ("IIP for September", "Whether factories slowed as rates rose and festive stocking ended", "Left on the growth axis: toward stagflation if it slows"),
        ("Core-sector output", "Steel, cement and power, the heavy-industry heartbeat", "Confirms or contradicts the IIP signal a month earlier"),
    ]),
    para("The worry is the move from reflation to stagflation: inflation still rising from oil while growth starts to slow from higher rates. That "
         "is the path to watch over the next two or three prints."),
    sowhat("Our market-implied regime, built from copper against gold and Brent's momentum, also says reflation. When the data and the markets "
           "agree, the regime is more trustworthy. The playbook tab shows what sectors have done in this regime in our own history."))

C2 = card("C2", "The rate cycle and liquidity", "weekly", "Is the RBI hiking, holding or cutting, and is money getting tighter or looser?",
    breath("After cutting rates through 2025, the RBI turned in October: its first rate rise in years, plus measures that drain cash from banks. "
           "Money is getting tighter on two fronts at once, through the rate and through liquidity."),
    f'''<div class="clock2">
      <div><div class="tiny" style="margin-bottom:4px">Money-market rate, monthly, our feed</div>{rate_svg(D["money_rate_hist"])}
        <div class="ex" style="border-left-color:var(--red);background:var(--red-bg)"><b>Stale feed.</b> Our series ends in {MR["date"][:7]} at {MR["value"]}%. The news desk reports the RBI raised its key rate in October and raised banks' cash reserve rule. The feeds phase adds the repo-rate history so the clock never lags a decision again.</div></div>
      <div>{table(["Liquidity gauge", "Reading", "What it means"], [
        ("Money-market rate", f'{feed(str(MR["value"]) + "%")} <span class="nf">stale, {MR["date"][:7]}</span>', "The price of overnight money; it follows the policy rate"),
        ("Banks' cash reserve rule", "raised in October <span class='nf'>news desk</span>", "Locks more deposits at the RBI; less money to lend"),
        ("RBI dollar sales", "reserves fell again <span class='nf'>news desk</span>", "Every dollar sold drains rupees from banks"),
        ("Bank credit growth", NOFEED, "Whether tighter money is slowing lending yet"),
        ("10-year G-sec yield", NOFEED + " · we hold only an ETF price", "The long-term cost of money for the government and companies"),
        ("Fed policy rate", NOFEED, "The US half of the rate cycle"),
      ])}</div>
    </div>''',
    h3("How to read the rate cycle"),
    para("Rate cycles are long. Central banks move in small steps and rarely reverse quickly, so the first move in a new direction matters more "
         "than any later one: it tells you the regime has changed. A first rise after a run of cuts, like October's, is rare and usually comes "
         "only when the central bank sees a threat it cannot ignore, here the rupee and imported inflation. The question now is whether it was a "
         "one-off insurance move or the start of a series. The wording of the next statement and the vote split will tell you."),
    h3("Who feels tighter money first"),
    steps([
        ("Lenders that borrow short.", "Shadow banks and housing finance companies that fund themselves in the money market pay more within weeks."),
        ("Banks, in two directions.", "Loans reprice upward, which helps margins at first; the higher cash reserve rule and slower loan growth "
         "hurt. Banks with cheap, sticky deposits come out ahead."),
        ("Borrowers and buyers.", "Home buyers, car buyers and companies with heavy debt see their costs rise over the following quarters."),
        ("Valuations.", "Higher rates lower the value of future profits, which hits richly priced growth stocks hardest."),
    ]),
    sowhat("In a tightening cycle, prefer lenders with cheap deposits over lenders that borrow in the market, and companies with net cash over "
           "companies with heavy debt. The industry pages for Banks, NBFCs, Real Estate Developers and Automobiles each list the rate as one of "
           "their dials."))

C3 = card("C3", "Market gauges: what is priced in", "daily · added", "The data says where the economy is. Markets say where they think it is going, and how scared they are.",
    breath("Foreign investors are selling shares and sitting near their most bearish futures position since 2022, while domestic funds buy and "
           "the fear gauge stays moderate. The market is stressed, not panicking."),
    f'''<div class="gauges">
      <div class="g"><div class="l">FII index-futures long share</div><div class="v">{FII["value"]}%</div><div class="s">{FII["pctile"]:.0f}th percentile since 2022 · median {FII["median"]}% · range {FII["min"]}–{FII["max"]}% · {FII["ago_20"]}% twenty sessions ago</div><div class="meter2"><i style="left:{FII["pctile"]}%"></i></div><div class="tiny">left = crowded short, right = crowded long</div></div>
      <div class="g"><div class="l">India VIX</div><div class="v">{V["value"]:.1f}</div><div class="s">{D["vix_pctile_3y"]:.0f}th percentile of three years · {sign(V["chg_21"])} in a month</div><div class="meter2"><i style="left:{100 - D["vix_pctile_3y"]}%"></i></div><div class="tiny">left = fear, right = calm</div></div>
      <div class="g"><div class="l">Copper against gold, six months</div><div class="v">{sign(RN["cg_6m"])}</div><div class="s">copper outrunning gold means markets expect growth</div></div>
      <div class="g"><div class="l">Brent, year on year</div><div class="v">{sign(RN["brent_yoy"])}</div><div class="s">{sign(RN["brent_yoy_3m_ago"])} three months ago: inflation pressure is building</div></div>
    </div>
    <div style="margin-top:14px"><div class="legend2"><span><i style="background:#d97706"></i>FII net</span><span><i style="background:var(--accent)"></i>DII net</span><span class="tiny">daily cash market, ₹ crore, last 60 sessions; latest {FL["date"]}: FII {rupee(FL["FII"])} · DII {rupee(FL["DII"])}</span></div>{flows_svg(D["flows_series"])}</div>
    <div style="margin-top:8px"><div class="tiny">FII index-futures long share, last 250 sessions (dashed line = median since 2022)</div>{spark(D["fii_long_series"], "v", ref=FII["median"])}</div>''',
    h3("How to read each gauge"),
    steps([
        ("FII index-futures long share.", "Foreign investors hold both long and short positions in Nifty futures. The share that is long tells you "
         "how they are betting on the index. Folklore says a crowded short is fuel for a rally. Our data since 2022 disagrees: crowded shorts "
         "were not followed by better-than-normal months, while crowded longs were followed by weaker ones. Treat the extreme short as a sign "
         "of stress, not a buy signal."),
        ("FII and DII cash flows.", "The bars show who bought and who sold Indian shares each day. Since the pandemic the two have often been "
         "mirror images: foreign money sells, domestic monthly-investment money buys. A day when foreign investors buy after a long selling run "
         "is worth noting, but one day is not a trend. Lesson 7 explains how not to over-read them."),
        ("India VIX.", "The price of protection on the Nifty, in volatility terms. It rises when investors pay up for insurance. A middling VIX "
         "during heavy foreign selling means the market is absorbing the selling without panic."),
        ("Copper against gold.", "Copper goes into wires, buildings and machines, so it rises when growth looks strong. Gold rises when investors "
         "want safety. Copper beating gold means markets still expect growth."),
        ("Brent, year on year.", "How much more oil costs than a year ago. A rising year-on-year number is what feeds through into inflation over "
         "the following months."),
    ]),
    sowhat("Gauges tell you what is already priced in. When the data is bad but positioning is extremely bearish, the next surprise is more likely "
           "to push prices up than down, but our positioning data does not back that up for crowded shorts. Respect the domestic buyer, not the short."))

C4 = card("C4", "The calendar", "layout", "What is due, why it matters, and which part of this page it will move.",
    table(["When", "Event", "Last reading we hold", "Why it matters", "Moves"], [
        ("Mid-November", "CPI for October", feed(f'{sign(cpi_h["yoy"])} ({cpi_h["month"]})'), "The first full month of the oil shock in prices", "Clock C1, lesson 3"),
        ("End of October", "IIP for September", feed(f'{sign(MP["iip_general"]["yoy"])} ({MP["iip_general"]["month"]})'), "Whether factories slowed as rates rose", "Clock C1, lesson 4"),
        ("End of November", "GDP for July to September", NOFEED, "The quarter before the rate rise; the baseline for the slowdown", "Engines, lesson 4"),
        ("Next scheduled meeting", "RBI monetary policy", "rate rise in October <span class='nf'>news desk</span>", "Insurance move or the start of a series", "Clock C2, lesson 1"),
        ("Next scheduled meeting", "US Fed", NOFEED, "Whether US rates add to the pressure on the rupee", "US card, lesson 2"),
        ("November 2026", "US midterm elections", "—", "Tariff and fiscal policy for the next two years", "US card"),
        ("Early 2027", "Uttar Pradesh state election", "—", "Welfare promises in the largest state", "Political economy"),
        ("February 2027", "Union Budget", "—", "Capex, the deficit and fuel taxes for the year", "Referees, lesson 6"),
    ], "cal"),
    note("Exact dates load from the RBI's and the Fed's published schedules and the statistics ministry's release calendar in the feeds phase, "
         "never from the LLM."))

CLOCK = C1 + C2 + C3 + C4

# ═══════════════════════════ PULSE ═══════════════════════════

WHY = {
    "nifty_it": "IT shares rose even as the largest IT firm reported slow growth; the news desk ties it to a leading AI company's revenue coming in lower than reported, which eased fears that AI will eat IT services work.",
    "usdinr": "The rupee firmed as the RBI's new defences took hold: a dollar window for state oil firms, tighter hedging rules and a higher cash reserve rule.",
    "nifty_media": "No single story; a rebound in a beaten-down, thinly traded index.",
    "brent_crude": "Attacks on Gulf shipping rose this month despite emergency stock releases, and the Hormuz route stays closed.",
    "nifty50": "A modest rise led by IT, on a day foreign investors were net buyers for once.",
    "nifty_metal": "Metals edged up with copper; the draft steel policy and anti-dumping cases support domestic steel prices.",
}
pulse_rows = []
for m in D["movers"][:12]:
    helps, hurts, mixed = who_cares(m["id"], m["chg"])
    z = m["z"]; zw = min(100, abs(z) / 3 * 100)
    lesson = LESSON_FOR.get(m["id"]); cardref = CARD_FOR.get(m["id"])
    why = WHY.get(m["id"])
    pulse_rows.append(f'''<tr><td><b>{E(LABEL.get(m["id"], m["id"]))}</b><div class="tiny">{m["date"]} · {fmt(m["value"])}</div></td>
<td class="num mono {"pos" if m["chg"] > 0 else "neg"}">{sign(m["chg"], " bps" if m["unit"] == "bps" else "%")}</td>
<td><div class="zbar"><i class="{"zp" if z > 0 else "zn"}" style="width:{zw:.0f}%"></i></div><div class="tiny mono">{z:+.1f} σ</div></td>
<td>{f'<div class="why">{E(why)} <span class="tiny">news desk</span></div>' if why else ""}{(('<div><span class="tag-h">helps</span>' + chips(helps, "h") + "</div>") if helps else "")}{(('<div><span class="tag-x">hurts</span>' + chips(hurts, "x") + "</div>") if hurts else "")}{(('<div><span class="tag-m">' + ("reads it" if m["id"] in INDEX_INDUSTRY else "mixed") + '</span>' + chips(mixed, "m") + "</div>") if mixed else "")}</td>
<td class="tiny">{E(cardref) if cardref else "—"}{f'<br><a href="#learn">lesson {lesson}</a>' if lesson else ""}</td></tr>''')

MEANS = {
    "iip_general": "Factories are still accelerating; the rate rise and the oil shock are not in this print yet.",
    "iip_manufacturing": "The core of the IIP and the part most sensitive to demand.",
    "iip_capital_goods": "Still fast, a sign that public and incentive-led investment is running; slowing from a very high pace.",
    "iip_consumer_durables": "Festive stocking; slowing slightly, worth watching as loans get dearer.",
    "core_combined": "Heavy industry is growing, but more slowly than the IIP, a hint that broad momentum is fading.",
    "cpi_general": "Inflation is turning up from low levels, the reason the RBI moved.",
    "cpi_food_beverages": "Food is leading the rise; weak rains could add to it.",
    "cpi_housing_fuel": "Still low, because pump prices lag crude; this is where the oil shock will show next.",
    "india_exports": "Still growing, but slower; tariffs and freight are biting.",
    "india_imports": "Growing much faster than exports, so the trade gap is widening, before the full oil shock.",
}
pm_rows = "".join(
    f'<tr><td>{E(LABEL.get(p["id"], p["id"]))}</td><td class="mono">{p["month"]}</td><td class="num mono">{sign(p["yoy"])}</td><td class="num mono tiny">{sign(p["prev"])}</td>'
    f'<td><span class="pill {"up" if p["yoy"] > p["prev"] else "down"}">{"▲ faster" if p["yoy"] > p["prev"] else "▼ slower"}</span></td><td class="tiny-t">{E(MEANS.get(p["id"], ""))}</td></tr>'
    for p in D["monthly_prints"])

theme2 = "".join(
    f'''<div class="theme"><div class="th-h">{E(t["title"])}</div><div class="th-now">{E(t["stands_now"])}</div>
<div class="th-chg"><b>What changed.</b> {E(t["what_changed"])}</div>
<div class="th-chg"><b>Why it matters.</b> {E(t["why_it_matters"])}</div>
<div class="th-chg"><b>What to watch.</b> {E(t["what_to_watch"] or "")}</div>
<div class="th-gl">{"".join(f'<span class="ind h">{E(g)}</span>' for g in json.loads(t["gains"] or "[]"))}{"".join(f'<span class="ind x">{E(g)}</span>' for g in json.loads(t["loses"] or "[]"))}</div>
<div class="tiny">news desk note of {t["updated_at"]}</div></div>''' for t in D["themes"])

top = D["movers"][0]
topz = f'{top["z"]:+.1f} σ'
P0 = card("P0", "The day in plain words", "daily · written from the data", "What happened on 2026-10-16, in two paragraphs, before the tables.",
    para(f"IT stocks had the most unusual day: Nifty IT rose {feed(sign(top['chg']))}, a {feed(topz)} move, even though the largest IT company had "
         f"just reported slow growth. The news desk links it to a leading AI company's revenue coming in below expectations, which calmed fears that "
         f"AI tools will replace IT services work. The rupee firmed to {feed(fmt(U['value']))} per dollar as the RBI's new defences took hold. Brent "
         f"rose another {feed(sign(B['chg_1']))} to {feed(fmt(B['value']))} as attacks on Gulf shipping continued. Foreign investors were net buyers "
         f"for a day, {feed(rupee(FL['FII']))}, after a long selling run, while domestic funds sold {feed(rupee(FL['DII']))}. One day does not make a "
         f"trend: over twenty sessions foreign investors are still deep sellers."),
    para("The thread tying it together: the market is caught between an oil shock that hurts most of the economy and a rupee the RBI is now "
         "defending hard. Days when the rupee steadies are days when foreign selling pauses and the most-sold sectors bounce."),
    sowhat("A firmer rupee helps exporters less and oil consumers more; a higher Brent does the opposite. Today both happened, so the net effect "
           "on most industries was small, and the day belonged to a sector-specific story in IT."))
P1 = card("P1", "What moved", "daily · computed", "Every daily series we hold, ranked by how unusual today's move was against a year of daily moves (σ), not by its size.",
    table(["Series", "Move", "How unusual", "Why, and which industries care (direction of today's move)", "Read more"], [], "", "".join(pulse_rows)),
    h3("How to read this table"),
    para("A one percent move in a calm series can matter more than a three percent move in a volatile one, so the table ranks by σ: today's move "
         "divided by a typical daily move over the past year. Two σ happens roughly one day in twenty. The industries come from the 38 industry "
         "pages: each one lists the dials that move it and whether a rise helps or hurts, so the direction here already accounts for whether the "
         "series went up or down today. The one-line why comes from the news desk and is written for the mockup; in the live page it is drafted "
         "from the day's storylines."))
P2 = card("P2", "The latest monthly prints", "as released", "Growth in the last print against the one before it, and what each one means.",
    table(["Series", "Month", "Year on year", "Previous", "Direction", "What it means"], [], "", pm_rows),
    para("Read the prints as a set. Output is accelerating, inflation is turning up, and imports are growing much faster than exports. That is "
         "the reflation quadrant with a widening external gap: exactly the setting in which the RBI raised rates."))
P3 = card("P3", "Storylines", "from the news desk", "Plan 0021's seven themes as the news desk last wrote them. Green = sectors it expects to gain, red = to lose.",
    f'<div class="themes">{theme2}</div>')
P4 = card("P4", "The reverse dial index", "from the 38 industry pages", "Every industry page lists the macro dials that move it. Flipped around, every dial gets its audience.",
    table(["Dial", "Industries", "A rise helps", "A rise hurts"], [], "", rev_rows),
    para("The rupee and interest rates are the two dials the most industries listen to, ahead of oil. That is a useful reminder: for most Indian "
         "companies, oil matters through the rupee and the RBI as much as through their own fuel bill."),
    f'<div class="ex"><b>The feed backlog, ranked by how many industries ask for it:</b> {backlog}. These dials have no series in our database yet.</div>')
PULSE = P0 + P1 + P2 + P3 + P4

# ═══════════════════════════ PLAYBOOK ═══════════════════════════

B1 = card("B1", "What worked in each regime", "computed · research only",
    f"Average return against the Nifty in the month after each regime, sector indices, 2016 onward ({D['regime_months_total']} months).",
    h3("How the table is built"),
    para("For every month since 2016 we label the regime from market prices that have a long history: growth is up when copper has beaten gold "
         "over six months, and inflation is up when Brent's year-on-year change is higher than three months earlier. Then we measure each sector "
         "index's return against the Nifty in the following month. Cell colour strength follows the t-statistic, which measures how far the "
         "average is from zero in units of its own noise. Hover a cell for the share of months the sector beat the Nifty."),
    f'<table class="rtable"><thead><tr><th>Regime</th>{"".join(f"<th class=num>{n}</th>" for _, n in SECT)}</tr></thead><tbody>{regime_rows}</tbody></table>',
    f'<div class="ex"><b>Read it honestly.</b> The strongest cell is {best_s.lower()} in {best_q.lower()} months, |t| = {best_t:.1f}. {n_over} of '
    f'{n_cells} cells {"clears" if n_over == 1 else "clear"} our single-test bar of |t| ≥ 2.5, which is about what chance alone produces when you '
    f'look at {n_cells} cells; a fair bar for {n_cells} tests is |t| ≥ {bonf:.1f}, and none clears it. These are tendencies, not rules. Nothing '
    f'here moves a pick until it passes the factor promotion review. Market regime now: <b>{RN["regime"]}</b>.</div>',
    h3("What the reflation row says, with care"),
    para("In past reflation months metals, energy, infrastructure and realty tended to beat the Nifty, while gold, pharma and FMCG tended to lag. "
         "That fits the textbook: in a growth-and-inflation regime, companies that sell commodities or build things gain pricing power, and "
         "defensive or safe-haven assets lose favour. Two caveats. Today's reflation comes with an oil supply shock, which is worse for oil "
         "consumers than a demand-led reflation. And realty's past strength came in months when rates were low; this time the RBI is hiking."),
    sowhat("Use the table as a prior, not a signal: it tells you which way the wind has usually blown in this regime, and the industry pages tell "
           "you whether a particular company is built for it."))

SCEN = [
    ("base", "Base: the squeeze continues", "likely",
     "Oil stays high while Gulf shipping is disrupted. The RBI raises rates once more and keeps managing the rupee, which drifts weaker without "
     "breaking its July record. Inflation rises over the next two prints as fuel prices catch up. Growth slows from a strong level as loans get "
     "dearer. Foreign investors keep selling in waves; domestic funds keep absorbing most of it, so the index falls slowly rather than crashing.",
     ["Brent stays near its current level", "Reserves keep falling", "The RBI statement stays hawkish", "IIP slows in the September print"],
     ["IT and pharma exporters", "upstream oil", "defence", "banks with cheap deposits"], ["aviation", "paints", "autos", "property", "shadow banks"],
     "Equities flat to down with wide sector gaps; bond yields up; gold steady in rupees; cash earning more."),
    ("", "Upside: the route reopens", "possible",
     "A negotiated or military reopening of the Gulf route brings oil down sharply. The rupee recovers, the RBI pauses, and inflation fears fade. "
     "Foreign investors, sitting near their most bearish futures position in years, rush to cover. The most-sold, rate-sensitive sectors rally "
     "hardest and fastest.",
     ["Brent falls by a fifth or more", "FII futures long share climbs off the floor", "The rupee strengthens out of its recent range", "The RBI signals a pause"],
     ["rate-sensitives", "consumption", "large private banks", "aviation", "paints"], ["upstream oil", "exporters' rupee gains"],
     "Equities up sharply, led by large caps foreign investors own; bond yields down; gold softer."),
    ("", "Downside: the chain breaks", "possible, less likely",
     "Oil spikes further, the rupee breaks to a new low past its July record, and the RBI is forced into larger rate rises. US yields climb "
     "further and a global risk-off hits every emerging market at once. Domestic funds slow their buying as investors see losses. The fall "
     "becomes broad.",
     ["The rupee past its July record", "India VIX in its top tenth", "The US ten-year above its October peak", "A large outflow from domestic equity funds"],
     ["gold", "cash", "exporters"], ["banks", "small caps", "everything leveraged"],
     "Equities down broadly, small caps most; bond yields up sharply; gold up in rupees; cash is king."),
]
scen2 = "".join(f'''<div class="sc {cls}"><h4>{E(t)}</h4><div class="lk {"l" if lkw == "likely" else "p"}">{E(lkw)}</div><p>{E(story)}</p>
<div class="sc-h">Signposts</div><ul class="tight">{"".join(f"<li>{E(s)}</li>" for s in sig)}</ul>
<div><span class="tag-h">wins</span>{ichips(w, "h")}</div><div><span class="tag-x">loses</span>{ichips(l, "x")}</div>
<div class="sc-h">Assets</div><div>{E(a)}</div></div>''' for cls, t, lkw, story, sig, w, l, a in SCEN)
B2 = card("B2", "The house view", "weekly · written", "Three scenarios, each with a likelihood in words, the story, the signposts that would confirm it, and who wins and loses.",
    breath("The base case is a slow squeeze: oil stays high, the RBI keeps tightening, and the market grinds sideways with wide gaps between "
           "sectors. The trigger for a turn is the oil route and the rupee; bearish foreign positioning alone has not been a reliable rally signal."),
    f'<div class="scen">{scen2}</div>',
    note("Every week the house view is stored in the call log with its date and scored a quarter later. The likelihood words are deliberately "
         "coarse: likely, possible, unlikely. The point is calibration over time, not precision today."))

RADAR_IF = {
    "Oil shock": "Inflation rises with a lag, the RBI tightens further, oil consumers' margins shrink.",
    "US yields": "Foreign money keeps flowing home, the rupee weakens, richly valued growth stocks lose most.",
    "FII selling": "Pressure on large caps and the rupee; watch whether domestic funds keep absorbing it.",
    "Crowded FII short": "A sign of stress rather than a buy signal: since 2022 crowded shorts were not followed by better-than-normal months. Crowded longs were followed by weaker ones.",
    "Inflation turning": "The RBI hikes again; rate-sensitive stocks fall; real incomes squeeze consumption.",
    "Rupee slide": "Imported inflation, more RBI dollar sales, foreign selling; exporters gain.",
    "Fear gauge": "Indiscriminate selling; high-quality names fall with the rest and become cheap.",
    "Policy feed lag": "The clock is reading an old rate; trust the news desk until the feed catches up.",
}
radar2 = "".join(f'<div class="rr rr-{c}"><span class="rr-dot"></span><div><b>{E(n)}</b><div>{E(r)}</div><div class="tiny">{E(rule)}</div><div class="rr-if"><b>If it is red:</b> {E(RADAR_IF[n])}</div></div></div>' for n, r, c, rule in radar)
B3 = card("B3", "The risk radar", "daily · computed", "Eight tail risks, each with its reading from our feeds, the rule that colours it, and what happens if it turns red.",
    f'<div class="radar">{radar2}</div>',
    sowhat("Three reds at once, oil, US yields and foreign selling, is the 2013 and 2022 pattern. In both episodes the market bottomed when the oil "
           "or dollar pressure eased, not when the growth data improved. The radar tells you which of those reds to watch for the turn."))

B4 = card("B4", "The asset-class lens", "written · measured table in the playbook phase", "What each regime has usually meant for an investor who holds Indian equities, government bonds, gold and cash.",
    '''<table class="assets"><thead><tr><th>Regime</th><th>Equities</th><th>Long bonds</th><th>Gold</th><th>Cash</th></tr></thead><tbody>
      <tr><td><b>Goldilocks</b></td><td class="pos">favoured</td><td class="pos">favoured</td><td>neutral</td><td class="neg">lagging</td></tr>
      <tr class="rnow"><td><b>Reflation</b> ◀ now</td><td>favoured, cyclicals over defensives</td><td class="neg">hurt as yields rise</td><td>mixed</td><td>neutral</td></tr>
      <tr><td><b>Stagflation</b></td><td class="neg">hurt</td><td class="neg">hurt</td><td class="pos">favoured</td><td class="pos">favoured</td></tr>
      <tr><td><b>Deflation</b></td><td class="neg">hurt, defensives hold up</td><td class="pos">favoured as rates fall</td><td class="pos">favoured</td><td>neutral</td></tr>
    </tbody></table>''',
    h3("The Indian twists"),
    steps([
        ("Gold is priced in dollars but bought in rupees.", "A weaker rupee lifts the rupee price of gold even when the dollar price is flat, so "
         "Indian gold behaves better in a rupee crisis than the textbook suggests."),
        ("Government bonds have a new buyer.", "Indian bonds joined global bond indices in 2024, so foreign index funds now buy them steadily. That "
         "softens the sell-off in bonds when rates rise, but it also means foreign selling can hit bonds as well as shares in a crisis."),
        ("Cash pays more than it used to.", "With the RBI hiking, short-term deposits and liquid funds earn more, which makes waiting less costly "
         "than in a low-rate year."),
        ("Equities are not one asset.", "In India the gap between sectors in a regime is often larger than the move in the index. The regime "
         "table above is more useful than the equity column here."),
    ]),
    note("Our own history disagrees with the textbook in places: gold lagged the Nifty in reflation months in the regime table. The playbook phase "
         "replaces these words with the measured table."))

B5 = card("B5", "The call log", "layout", "Every week the clock's regime and the house view are stored with the date, then scored a quarter later against what happened.",
    table(["Week", "India regime", "Base case", "Likelihood", "Scored on", "Outcome"], [
        (feed("2026-10-17"), india_quad, "The squeeze continues", lk("likely"), feed("2027-01-15"), '<span class="nf">pending</span>'),
    ]),
    para("Scoring is simple: was the base case right, half right or wrong, and did the regime call hold. After a few quarters the log shows whether "
         "\"likely\" calls come true about as often as they should. That is the only honest way to know whether the house view is worth reading."))

PLAY = B1 + B2 + B3 + B4 + B5

# ═══════════════════════════ LEARN ═══════════════════════════

LESSONS = [
    (1, "Read an RBI policy statement", "What changed, what the hawks and doves said, and why the press conference matters."),
    (2, "Read a Fed statement and the dot plot", "How the Fed signals its path and why markets trade the dots."),
    (3, "Read a CPI release", "Headline, core, and food's role in India. Worked below.", True),
    (4, "Read a GDP release", "The spending split and why GVA and GDP can tell different stories."),
    (5, "Read the balance of payments", "Current account, capital account, reserves."),
    (6, "Read the Budget", "The deficit, capex, borrowing, and what sits off the books."),
    (7, "Read FII and DII flows", "Without over-reading them. Worked below.", True),
    (8, "Read a China data dump", "Factory surveys, producer prices, credit."),
    (9, "Connect a global shock to an Indian sector", "End to end, like card W6."),
    (10, "Read oil and the rupee together", "The twin-deficit chain. Worked below.", True),
    (11, "Read the bond market", "The yield curve, real rates, inversions."),
    (12, "Read derivatives positioning", "FII futures, put-call ratios, crowded shorts."),
]
lessons_html = "".join(f'<div class="lesson{" on" if len(l) > 3 else ""}"><span class="n">{l[0]}</span><b>{E(l[1])}</b><br>{E(l[2])}</div>' for l in LESSONS)

L3 = card("L3", "Lesson 3 · Read a CPI release", "worked example on our data", "The consumer price index is the price of a fixed basket a typical household buys. The RBI targets its year-on-year change.",
    steps([
        ("Start with the headline.", f"CPI rose {feed(sign(cpi_h['yoy']))} year on year in {cpi_h['month']}, up from {feed(sign(cpi_h['prev']))} the "
         "month before. The RBI targets four percent with a tolerance band around it, so this is above the middle and rising. The direction "
         "matters as much as the level: the RBI acts on where it thinks inflation is heading."),
        ("Then food.", f"Food and beverages rose {feed(sign(cpi_f['yoy']))}, up from {feed(sign(cpi_f['prev']))}. Food is close to half the Indian "
         "basket, far more than in rich countries, so a bad monsoon or a vegetable spike can move the headline on its own. The RBI usually looks "
         "through a food spike it thinks is temporary and acts when it spreads to other prices."),
        ("Then fuel and housing.", f"Housing and fuel rose {feed(sign(cpi_hf['yoy']))}, up from {feed(sign(cpi_hf['prev']))}. Pump prices are partly "
         "set by the government, so an oil shock reaches CPI slowly and in steps, often after a tax decision. That is why this line is still low "
         "while Brent has jumped: the pass-through is still to come."),
        ("Then core.", "Core inflation strips out food and fuel to show the underlying trend: whether price rises are spreading into services, "
         "rents and manufactured goods. We do not hold the core series yet, which is why the clock cannot yet say whether inflation is broadening."),
        ("Finally, the base effect.", "Year-on-year inflation compares this month with the same month last year. If prices jumped a year ago, this "
         "year's number looks low even if prices are rising now, and the reverse. Always check what happened twelve months earlier."),
    ]),
    '<div class="ex"><b>Exercise.</b><ol><li>Brent is up by more than a third in three months. Which CPI component should show it first, and why might it lag?</li><li>The RBI raised rates in October. Using the headline and food numbers above, write the one sentence its statement probably used to justify it.</li><li>Open the pulse. Which two industries in the reverse index are hurt most directly if food inflation keeps rising? Check against the FMCG and Food &amp; Beverages pages.</li></ol></div>')

L7 = card("L7", "Lesson 7 · Read FII and DII flows", "worked example on our data", "Foreign and domestic institutions report what they bought and sold every day. The numbers are useful and easy to over-read.",
    steps([
        ("Know what the number is.", f"On {FL['date']} foreign investors were net buyers of {feed(rupee(FL['FII']))} in the cash market and domestic "
         f"institutions net sellers of {feed(rupee(FL['DII']))}. These are provisional figures for the cash market only; derivatives positions "
         "are separate."),
        ("Never read one day.", f"One buying day after weeks of selling is noise. Over twenty sessions foreign investors sold {feed(rupee(F20['FII']))} "
         f"and domestic funds bought {feed(rupee(F20['DII']))}. The trend is what matters."),
        ("Look at both together.", "When foreign selling is matched by domestic buying, the index falls slowly and recovers quickly. When both sell, "
         "the fall is fast. Since the pandemic, monthly household investment has made domestic buying the norm."),
        ("Add positioning.", f"Cash flows say what investors did; futures positions say what they are betting. Foreign investors hold "
         f"{feed(str(FII['value']) + '%')} of their index futures long, the {feed(str(int(FII['pctile'])) + 'th')} percentile since 2022. Heavy "
         "cash selling plus an extreme short is a sign of stress; our data since 2022 does not show it reliably preceding a rally."),
        ("Ask why they are selling.", "Foreign investors sell India for global reasons as often as Indian ones: higher US yields, a stronger dollar, "
         "a better opportunity elsewhere. Check the US card before concluding that foreign investors have turned against India."),
    ]),
    '<div class="ex"><b>Exercise.</b><ol><li>Find the last day in the flows chart where both foreign and domestic investors sold. What did the Nifty do that week?</li><li>If foreign investors cover their futures shorts, which large-cap industries would you expect to rise first, and why?</li></ol></div>')

L10 = card("L10", "Lesson 10 · Read oil and the rupee together", "worked example on our data", "The twin-deficit chain from card M2, read off live numbers.",
    steps([
        ("Start with oil, in three windows.", f"Brent is {feed(fmt(B['value']))}: {feed(sign(B['chg_1']))} today, {feed(sign(B['chg_21']))} in a month, "
         f"{feed(sign(B['chg_63']))} in three months. The three-month change is what moves the import bill and inflation; the daily change moves "
         "sentiment."),
        ("Then the rupee.", f"USD/INR is {feed(fmt(U['value']))}, {feed(sign(U['chg_63']))} over three months, below its record of {feed('96.88')} on "
         "2026-07-24. Oil up sharply with the rupee roughly flat means something is holding the rupee: here, the RBI selling dollars and its new "
         "defences."),
        ("Then ask what is holding the line.", "If the RBI is holding the rupee, reserves are falling and money is tightening. That is not free: it "
         "moves the pressure from the currency to interest rates and liquidity, which is why the RBI also raised rates."),
        ("Then the second deficit.", "Check whether the government is cutting fuel taxes. If it is, inflation stays lower but the fiscal deficit widens "
         "and bond yields rise. If it is not, pump prices and inflation rise."),
        ("Finally, the stocks.", "Map each step to industries: oil consumers lose on cost, rate-sensitive borrowers lose on rates, exporters gain only if "
         "the rupee actually weakens. Today the rupee is being held, so exporters are getting less help than the oil price alone would suggest."),
    ]),
    '<div class="ex"><b>Exercise.</b><ol><li>If the RBI stopped defending the rupee tomorrow, which way would the rupee move, and which three industries would gain?</li><li>Using the risk radar, which reading would tell you first that reserves are running low?</li></ol></div>')

GLOSS = [
    ("Current-account deficit", "India buys more goods and services from the world than it sells; foreign money has to fill the gap."),
    ("Twin deficits", "A current-account deficit and a fiscal deficit at the same time; an oil shock widens both."),
    ("FII, FPI", "Foreign institutional or portfolio investors: overseas funds buying Indian shares and bonds."),
    ("FDI", "Foreign direct investment: a foreign company building or buying a business in India; it rarely leaves quickly."),
    ("DII", "Domestic institutional investors: Indian mutual funds, insurers and pension funds."),
    ("Systematic investment plan", "A fixed monthly investment into a mutual fund; the steady stream behind domestic buying."),
    ("Repo rate", "The rate at which the RBI lends to banks overnight; the policy rate everything else follows."),
    ("Cash reserve ratio", "The share of deposits banks must park with the RBI, earning nothing. Raising it drains money from the system."),
    ("Liquidity", "How much spare cash banks have; tight liquidity pushes short-term rates up even without a policy change."),
    ("Crowding out", "Government borrowing taking savings that companies would otherwise have borrowed, pushing rates up."),
    ("Forex reserves", "The RBI's holdings of dollars and other foreign assets; its ammunition for defending the rupee."),
    ("IIP", "Index of industrial production: monthly output of factories, mines and power plants."),
    ("CPI, core CPI", "Consumer prices; core removes food and fuel to show the underlying trend."),
    ("Base effect", "A year-on-year number looking high or low because of what happened twelve months earlier."),
    ("Regime quadrant", "Growth speeding up or slowing, against inflation rising or falling: four states with different winners."),
    ("Reflation, stagflation", "Growth and inflation both rising; inflation rising while growth slows."),
    ("σ (sigma)", "How many typical daily moves today's move was. Two σ happens roughly one day in twenty."),
    ("t-statistic", "How far an average is from zero in units of its own noise. Our bar for a factor is 2.5 before the multiple-testing haircut."),
    ("Crowded short", "Most traders already bet on a fall. Folklore calls it rally fuel; in our Indian data since 2022 it has not reliably been."),
    ("Carry trade", "Borrowing in a cheap currency such as the yen to buy higher-yielding assets; it unwinds violently when the cheap currency jumps."),
    ("Taper tantrum", "The 2013 sell-off in emerging markets after the Fed hinted it would slow its bond buying."),
    ("Carbon border tax", "An EU charge on the carbon in imported goods such as steel, aluminium, cement and fertiliser."),
]
gloss_html = '<dl class="fields">' + "".join(f"<dt>{E(a)}</dt><dd>{E(b)}</dd>" for a, b in GLOSS) + "</dl>"

LEARN = ('<a id="learn"></a>'
         + card("L", "The curriculum", "twelve lessons", "Each lesson uses our own data, and each pulse item links to the lesson it leans on.", f'<div class="lessons">{lessons_html}</div>')
         + L3 + L7 + L10 + card("§", "Glossary", "every term on this page", "One line each, plain words.", gloss_html))

# ═══════════════════════════ PAGE ═══════════════════════════

EXTRA2 = """
  .breath { margin: 0 0 14px; padding: 12px 14px; border-radius: 10px; background: var(--bg-primary); border: 1px solid var(--border-accent); font-size: 14.5px; color: var(--text-primary); line-height: 1.6; }
  .breath b { color: var(--accent); }
  h3.sub { font-size: 12.5px; letter-spacing: .08em; text-transform: uppercase; color: var(--text-muted); margin: 20px 0 8px; font-weight: 700; }
  .card p { max-width: 86ch; }
  ol.steps { margin: 6px 0 10px; padding-left: 0; list-style: none; counter-reset: s; }
  ol.steps li { counter-increment: s; position: relative; padding: 8px 0 8px 38px; border-bottom: 1px solid var(--border); font-size: 14px; color: var(--text-secondary); line-height: 1.55; }
  ol.steps li::before { content: counter(s); position: absolute; left: 0; top: 9px; width: 24px; height: 24px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); font-weight: 700; font-size: 12px; display: grid; place-items: center; font-family: var(--mono); }
  ol.steps li b { color: var(--text-primary); display: block; margin-bottom: 2px; }
  .nf { color: var(--text-muted); font-style: italic; font-size: 12px; }
  .eng-size { font-size: 11.5px; color: var(--text-muted); font-weight: 500; margin-left: 4px; }
  .tag-b { display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; padding: 1px 7px; border-radius: 999px; margin-right: 6px; color: var(--blue); background: var(--blue-bg); }
  .eng-inds { margin-top: 8px; }
  .ref-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 12px; }
  .ref { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: var(--bg-primary); }
  .ref h4 { margin: 0 0 8px; font-size: 15px; }
  .ref-row { display: grid; grid-template-columns: 120px 1fr; gap: 10px; font-size: 13px; color: var(--text-secondary); padding: 5px 0; border-top: 1px dashed var(--border); }
  .ref-row .rl { color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; padding-top: 2px; }
  .lk-l { color: var(--accent); } .lk-p { color: var(--amber); } .lk-u { color: var(--text-muted); }
  .hist2 { display: grid; grid-template-columns: 54px 1fr; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); font-size: 13.5px; color: var(--text-secondary); }
  .hist2 b { color: var(--text-primary); } .h2t { font-weight: 700; color: var(--text-primary); font-size: 14.5px; margin-bottom: 4px; }
  .hist2 > div > div { margin: 3px 0; }
  .rhyme { font-size: 10.5px; font-weight: 600; padding: 1px 8px; border-radius: 999px; margin-left: 6px; vertical-align: 1px; }
  .rh-strong { color: var(--red); background: var(--red-bg); } .rh-medium { color: var(--amber); background: var(--amber-bg); } .rh-weak { color: var(--text-muted); background: rgba(142,144,172,0.1); }
  ul.tight { margin: 4px 0; padding-left: 18px; } ul.tight li { margin: 2px 0; }
  .why { font-size: 12.5px; color: var(--text-primary); margin-bottom: 6px; max-width: 70ch; }
  td.tiny-t { font-size: 12px; color: var(--text-secondary); max-width: 40ch; }
  .sc p { margin: 0 0 8px; font-size: 13px; } .sc-h { font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase; color: var(--text-muted); margin: 8px 0 2px; font-weight: 700; }
  .rr-if { font-size: 12px; margin-top: 4px; color: var(--text-secondary); }
  @media (max-width: 900px) { .ref-grid { grid-template-columns: 1fr; } .ref-row { grid-template-columns: 1fr; gap: 2px; } }
"""

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Macro, explained</title>
<meta name="description" content="Mockup of the cockpit's macro page (plan 0028): map, clock, pulse, playbook and learn, on real data as of 2026-10-16.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{BASE_CSS}{EXTRA_CSS}{EXTRA2}</style>
</head>
<body>
<div class="topbar">
  <span class="crumb">Cockpit › <b>Macro</b></span>
  <span class="tag mock">Mockup · plan 0028 phase 1</span>
  <span class="right">data as of 2026-10-16 (rupee 2026-10-17) · every figure from our DB · written prose carries no figures</span>
</div>
<div class="wrap">
<nav class="side" id="nav">
  <div class="h">Five tabs</div>
  <a href="#" data-p="map"><span class="n">1</span>Map</a>
  <a href="#" data-p="clock"><span class="n">2</span>Clock</a>
  <a href="#" data-p="pulse"><span class="n">3</span>Pulse</a>
  <a href="#" data-p="play"><span class="n">4</span>Playbook</a>
  <a href="#" data-p="learn"><span class="n">5</span>Learn</a>
  <div class="h" style="margin-top:16px">Three speeds</div>
  <div class="tiny" style="padding:0 10px">Map: quarterly<br>Clock: weekly<br>Pulse: daily</div>
  <div class="h" style="margin-top:16px">Map cards</div>
  <div class="tiny" style="padding:0 10px;line-height:1.8">M0 India on one page<br>M1 The plumbing<br>M2 Twin deficits<br>M3 The engines<br>M4 The referees<br>M5 Political economy<br>M6 History<br>W1–W5 The world<br>W6 Shock walk-through</div>
</nav>
<main>
  <div class="hero">
    <div class="kicker">Macro · India and the world</div>
    <h1>Where the economy is, and what it means today</h1>
    <div class="one">A <b>map</b> of how the economy works, a <b>clock</b> that says where we are, and a <b>pulse</b> that says what changed today. The playbook turns the three into decisions; learn teaches you to read the raw releases yourself.</div>
    <div class="strip">
      <div class="kpi warn"><div class="l">India regime</div><div class="v sm" style="color:var(--amber)">{india_quad}</div><div class="s">growth and inflation both rising · {now_m}</div></div>
      <div class="kpi warn"><div class="l">RBI</div><div class="v sm" style="color:var(--red)">Hiking</div><div class="s">per the news desk · feed {MR["value"]}% to {MR["date"][:7]} ⚠ stale</div></div>
      <div class="kpi"><div class="l">Brent</div><div class="v">{B["value"]:.1f}</div><div class="s neg">{sign(B["chg_63"])} in 3 months</div></div>
      <div class="kpi"><div class="l">USD/INR</div><div class="v">{U["value"]:.2f}</div><div class="s">record 96.88 on 2026-07-24</div></div>
      <div class="kpi"><div class="l">US 10-year</div><div class="v">{T10}</div><div class="s">peak 5.31% on 2026-10-05</div></div>
      <div class="kpi"><div class="l">Flows, 20 sessions</div><div class="v sm"><span class="neg">FII {"−" if F20["FII"] < 0 else "+"}₹{abs(F20["FII"])/1000:,.0f}k cr</span></div><div class="s pos">DII {"−" if F20["DII"] < 0 else "+"}₹{abs(F20["DII"])/1000:,.0f}k cr</div></div>
      <div class="kpi"><div class="l">FII index futures</div><div class="v">{FII["value"]}% long</div><div class="s">{FII["pctile"]:.0f}th percentile since 2022</div></div>
    </div>
  </div>
  <div class="tabs" id="tabs">
    <button class="on" data-p="map">Map<small>quarterly</small></button>
    <button data-p="clock">Clock<small>weekly</small></button>
    <button data-p="pulse">Pulse<small>daily</small></button>
    <button data-p="play">Playbook<small>decide</small></button>
    <button data-p="learn">Learn<small>12 lessons</small></button>
  </div>
  <div class="panel on" id="p-map">{MAP}</div>
  <div class="panel" id="p-clock">{CLOCK}</div>
  <div class="panel" id="p-pulse">{PULSE}</div>
  <div class="panel" id="p-play">{PLAY}</div>
  <div class="panel" id="p-learn">{LEARN}</div>
</main>
</div>
<script>
  const show = p => {{
    document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.p === p));
    document.querySelectorAll('#nav a[data-p]').forEach(a => a.classList.toggle('on', a.dataset.p === p));
    document.querySelectorAll('.panel').forEach(x => x.classList.toggle('on', x.id === 'p-' + p));
    window.scrollTo({{ top: document.getElementById('tabs').offsetTop - 50, behavior: 'smooth' }});
  }};
  document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => show(b.dataset.p));
  document.querySelectorAll('#nav a[data-p]').forEach(a => a.onclick = e => {{ e.preventDefault(); show(a.dataset.p); }});
  document.querySelectorAll('a[href="#learn"]').forEach(a => a.onclick = e => {{ e.preventDefault(); show('learn'); }});
  document.querySelector('#nav a[data-p="map"]').classList.add('on');
</script>
</body>
</html>
"""
if __name__ == "__main__":
    OUT.write_text(page)
    print("wrote", OUT, len(page), "bytes")
