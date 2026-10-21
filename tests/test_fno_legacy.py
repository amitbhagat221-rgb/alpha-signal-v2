"""Legacy F&O archive parser (sources.fno_pull.parse_legacy_fo) — offline, synthetic file."""

import io
import sqlite3
import zipfile

import pandas as pd

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


# Expiry day, rows verbatim from BSE's 2026-10-15 file: ClsPric of every expiring contract
# is the index settlement (74315.61); LastPric is the real last trade (bug fixed 2026-10-21).
BSE_EXPIRY_HEADER = BSE_HEADER.rstrip("\n") + ",Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
BSE_EXPIRY_ROWS = [
    "2026-10-15,2026-10-15,FO,BSE,IDO,1116190,,SENSEX,,2026-10-15,2026-10-15,74300.00,CE,SENSEX26O1574300CE,6.55,138.00,1.80,74315.61,15.50,8.50,74315.61,74315.61,4273680,3558040,514351260,38243046817410.00,4257929,F1,20,,,,,",
    "2026-10-15,2026-10-15,FO,BSE,IDO,1107722,,SENSEX,,2026-10-15,2026-10-15,74400.00,PE,SENSEX26O1574400PE,1244.25,1412.80,83.70,74315.61,84.45,1683.25,74315.61,74315.61,761540,758840,35058320,2617347539531.00,619237,F1,20,,,,,",
    "2026-10-15,2026-10-15,FO,BSE,IDO,1115854,,SENSEX,,2026-10-15,2026-10-15,76700.00,PE,SENSEX26O1576700PE,0.00,0.00,0.00,74315.61,0.00,4041.10,74315.61,74315.61,160,0,0,0.00,0,F1,20,,,,,",
    "2026-10-15,2026-10-15,FO,BSE,IDO,863889,,SENSEX,,2026-10-29,2026-10-29,74100.00,CE,SENSEX26OCT74100CE,334.30,949.05,334.30,736.70,776.15,334.90,74315.61,736.70,1600,1080,5340,399843415.00,233,F1,20,,,,,",
]


def _bse_expiry_day():
    from sources.bse_fo import parse
    df = parse((BSE_EXPIRY_HEADER + "\n".join(BSE_EXPIRY_ROWS) + "\n").encode())
    return df, df.set_index(["expiry_date", "strike", "option_type"])


def test_bse_expiry_day_close_is_the_last_trade_not_the_index():
    df, by = _bse_expiry_day()
    assert by.loc[("2026-10-15", 74300.0, "CE"), "close"] == 15.50
    assert by.loc[("2026-10-15", 74400.0, "PE"), "close"] == 84.45
    assert pd.isna(by.loc[("2026-10-15", 76700.0, "PE"), "close"])        # nothing traded: NULL, never the index
    assert by.loc[("2026-10-29", 74100.0, "CE"), "close"] == 736.70        # a contract not expiring keeps ClsPric
    # settle keeps the NSE expiry-day convention (index settlement), the other columns are untouched
    assert by.loc[("2026-10-15", 74300.0, "CE"), "settle"] == 74315.61
    assert (df.underlying_price == 74315.61).all()
    assert (df.close.dropna() < 0.5 * df.underlying_price[df.close.notna()]).all()


def test_bse_expiry_close_repair_updates_only_close(tmp_path, monkeypatch):
    import db
    from sources.bse_fo import write_expiry_close
    path = tmp_path / "t.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    df, _ = _bse_expiry_day()
    bad = df.assign(close=df.underlying_price.where(df.trade_date == df.expiry_date, df.close))
    cols = ["symbol", "instrument_type", "expiry_date", "strike", "option_type", "trade_date", "close", "settle",
            "underlying_price", "oi", "volume"]
    c.executemany(f"INSERT INTO fno_bhav ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                  bad[cols].astype(object).where(bad[cols].notna(), None).values.tolist())
    c.commit()
    monkeypatch.setattr(db, "DB_PATH", path)
    assert write_expiry_close(df) == 3                                     # the three expiring rows
    got = dict(((e, k, o), (cl, s, u, oi)) for e, k, o, cl, s, u, oi in c.execute(
        "SELECT expiry_date, strike, option_type, close, settle, underlying_price, oi FROM fno_bhav"))
    assert got[("2026-10-15", 74300.0, "CE")] == (15.5, 74315.61, 74315.61, 4273680)
    assert got[("2026-10-15", 76700.0, "PE")][0] is None
    assert got[("2026-10-29", 74100.0, "CE")][0] == 736.70
