"""Legacy F&O archive parser (sources.fno_pull.parse_legacy_fo) — offline, synthetic file."""

import io
import zipfile

from sources.fno_pull import parse_legacy_fo

HEADER = ("INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,"
          "CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,\n")
ROWS = [
    "OPTIDX,NIFTY,19-Mar-2020,9500,CE,300,360,290,352.1,352.1,4311,0,117750,117750,12-MAR-2020,",
    "OPTIDX,NIFTY,19-Mar-2020,9500,PE,250,320,240,308.9,308.9,54270,0,458100,303675,12-MAR-2020,",
    "OPTIDX,NIFTY,19-Mar-2020,15000,CE,0,0,0,0.05,0.05,0,0,0,0,12-MAR-2020,",        # dead strike: dropped
    "FUTIDX,NIFTY,26-Mar-2020,0,XX,9600,9700,9500,9546.6,9546.6,1000,7500,5000,10,12-MAR-2020,",
    "OPTSTK,RELIANCE,26-Mar-2020,1100,CE,10,12,9,11,11,50,0,500,10,12-MAR-2020,",     # stock option: dropped
    "OPTIDX,NIFTYIT,26-Mar-2020,15000,CE,10,12,9,11,11,5,0,50,1,12-MAR-2020,",        # no index level: dropped
]


def _zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fo12MAR2020bhav.csv", HEADER + "\n".join(rows) + "\n")
    return buf.getvalue()


def test_index_contracts_only_with_index_level():
    df = parse_legacy_fo(_zip(ROWS), {"NIFTY": 9590.15})
    assert sorted(df.instrument_type) == ["IDF", "IDO", "IDO"]
    assert set(df.symbol) == {"NIFTY"}
    assert (df.underlying_price == 9590.15).all()
    assert set(df.trade_date) == {"2020-03-12"}


def test_columns_map_to_fno_bhav():
    df = parse_legacy_fo(_zip(ROWS), {"NIFTY": 9590.15}).set_index(["instrument_type", "option_type"])
    put = df.loc[("IDO", "PE")]
    assert (put.expiry_date, put.strike, put.settle, put.volume, put.oi) == ("2020-03-19", 9500.0, 308.9, 54270, 458100)
    fut = df.loc[("IDF", "XX")]
    assert (fut.strike, fut.expiry_date) == (0.0, "2020-03-26")


def test_nothing_to_keep_is_empty():
    assert parse_legacy_fo(_zip(ROWS[4:5]), {"NIFTY": 9590.15}).empty


# ── BSE UDiFF (sources.bse_fo.parse) ──

BSE_HEADER = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,"
              "StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,"
              "SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty\n")
BSE_ROWS = [
    "2026-10-08,2026-10-08,FO,BSE,IDO,1,,SENSEX,,2026-10-15,2026-10-15,72000,PE,x,1,1,1,150.5,150,140,71593.24,150.5,4000,200,600,0,87,F1,20",
    "2026-10-08,2026-10-08,FO,BSE,IDO,2,,SENSEX,,2026-10-15,2026-10-15,90000,CE,x,0,0,0,0.05,0,0,71593.24,0.05,0,0,0,0,0,F1,20",
    "2026-10-08,2026-10-08,FO,BSE,STO,3,,RELIANCE,,2026-10-29,2026-10-29,1400,CE,x,1,1,1,10,10,10,1380,10,500,0,500,0,5,F1,500",
]


def test_bse_udiff_volume_in_lots_oi_in_units():
    from sources.bse_fo import parse
    df = parse((BSE_HEADER + "\n".join(BSE_ROWS) + "\n").encode())
    assert len(df) == 1                              # dead strike and stock option dropped
    r = df.iloc[0]
    assert (r.symbol, r.instrument_type, r.option_type, r.strike) == ("SENSEX", "IDO", "PE", 72000.0)
    assert (r.volume, r.oi, r.underlying_price, r.expiry_date) == (30, 4000, 71593.24, "2026-10-15")
