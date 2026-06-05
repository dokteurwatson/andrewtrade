"""
Multi-dag backtest Krush watchlists — 04-05-2026 t/m 04-06-2026
Kapitaal start op $50 en rolt dagelijks door (compounding).
Scenario A  = geen ORB-high filter, alleen volume >= 2x ORB-gemiddelde (bot-default).
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
import warnings
warnings.filterwarnings("ignore")

from datetime import date
from stocktrader.parser import Setup
from stocktrader.market_data import fetch_1m
from backtest_watchlist import run_scenario

FEE_PCT = 0.0015  # T212: 0.15% per zijde (0.30% round-trip)

# ---------------------------------------------------------------------------
# Dagelijkse watchlists (chronologisch)  –  Setup(ticker, hold, break_, t1, t2)
# ---------------------------------------------------------------------------
DAYS: list[tuple[date, list[Setup]]] = [

    # ── 04-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 4), [
        Setup("SOBR", 0.97,   1.12,   1.26,   1.50),
        Setup("PN",   4.50,   5.00,   6.20,   7.80),
        Setup("WOLF", 36.60,  40.00,  44.00,  50.00),
        Setup("CUE",  34.00,  36.60,  40.00,  45.00),
        Setup("AMS",  1.90,   2.05,   2.40,   2.60),
        Setup("STAK", 1.15,   1.30,   1.70,   2.00),
        Setup("MRAM", 22.00,  23.50,  30.00,  33.00),
        Setup("TWLO", 180.00, 184.00, 220.00, 240.00),
        Setup("ISPC", 5.00,   5.80,   6.60,   7.70),
        Setup("TLIH", 4.15,   4.61,   5.55,   6.75),
        Setup("LNAI", 0.40,   0.42,   0.60,   0.80),
    ]),

    # ── 06-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 6), [
        Setup("MASK", 2.40,  2.68,  3.30,  4.30),
        Setup("BLZE", 7.80,  8.42,  10.00, 11.00),
        Setup("EZGO", 2.30,  2.60,  3.40,  4.00),
        Setup("SOBR", 1.40,  1.56,  2.10,  2.50),
        Setup("OCG",  2.40,  2.62,  3.10,  3.50),
        Setup("EVC",  7.00,  7.55,  8.50,  10.00),
        Setup("AVTX", 23.00, 27.80, 33.00, 35.00),
        Setup("AREB", 0.36,  0.39,  0.60,  0.70),
        Setup("FATE", 2.30,  2.43,  3.00,  4.00),
        Setup("AMDL", 46.00, 47.08, 55.00, 60.00),
        Setup("EVER", 23.00, 24.49, 28.00, 30.00),
    ]),

    # ── 07-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 7), [
        Setup("PMAX", 4.50,  4.80,  5.40,  6.00),
        Setup("OSS",  15.50, 16.27, 20.00, 22.00),
        Setup("IFRX", 2.60,  2.86,  3.30,  3.50),
        Setup("ERNA", 6.60,  7.70,  8.50,  9.00),
        Setup("GLE",  0.60,  0.64,  0.75,  0.80),
        Setup("BLMN", 8.10,  8.56,  9.50,  10.70),
        Setup("EVC",  7.80,  8.35,  9.50,  10.50),
        Setup("STFS", 8.00,  8.99,  10.00, 15.00),
        Setup("FLNC", 17.70, 19.40, 25.00, 30.00),
        Setup("LBGJ", 1.10,  1.27,  2.00,  2.50),
        Setup("MASK", 2.50,  2.74,  4.45,  5.00),
        Setup("OCG",  2.35,  2.50,  3.00,  3.50),
        Setup("WKHS", 4.00,  4.26,  5.00,  5.50),
    ]),

    # ── 08-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 8), [
        Setup("RMSG", 1.78,  1.86,  2.20,  2.60),
        Setup("AGL",  60.00, 64.00, 75.00, 80.00),
        Setup("ERNA", 7.80,  8.49,  10.00, 12.00),
        Setup("SOBR", 1.85,  1.99,  3.00,  3.50),
        Setup("GLE",  0.66,  0.76,  0.90,  1.00),
        Setup("AIIO", 0.92,  0.99,  1.20,  1.50),
        Setup("EVC",  6.50,  7.00,  7.80,  10.00),
    ]),

    # ── 11-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 11), [
        Setup("MASK", 3.20,  3.40,  4.00,  4.50),
        Setup("YMAT", 0.60,  0.68,  0.90,  1.00),
        Setup("WEST", 8.37,  8.62,  9.50,  10.01),
        Setup("AEHL", 2.62,  2.84,  4.20,  4.75),
        Setup("MRAM", 35.70, 39.00, 44.00, 50.00),
        Setup("RXT",  6.00,  6.20,  7.00,  7.50),
        Setup("MTEX", 7.60,  7.90,  8.80,  9.50),
        Setup("CODX", 2.60,  2.77,  3.05,  3.50),
        Setup("CSIQ", 19.90, 20.47, 23.00, 26.00),
        Setup("INO",  1.70,  1.79,  2.00,  2.20),
        Setup("FCEL", 14.00, 14.50, 15.50, 18.00),
        Setup("HPAI", 1.48,  1.57,  2.00,  2.40),
        Setup("VRAX", 0.23,  0.24,  0.28,  0.33),
    ]),

    # ── 12-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 12), [
        Setup("JZXN", 1.30,  1.45,  1.60,  1.90),
        Setup("DGXX", 8.35,  8.59,  9.50,  10.00),
        Setup("XGN",  4.00,  4.13,  5.00,  6.60),
        Setup("AMBO", 3.25,  4.35,  5.25,  6.75),
        Setup("XOS",  2.63,  2.77,  3.00,  3.60),
        Setup("MRAM", 43.00, 44.67, 50.00, 55.00),
        Setup("VEEE", 8.20,  8.80,  10.00, 12.00),
        Setup("FCEL", 16.60, 17.40, 20.00, 22.00),
        Setup("EVC",  8.65,  8.90,  9.90,  10.60),
        Setup("BZFD", 1.90,  2.27,  2.50,  3.00),
        Setup("GSIT", 12.50, 13.30, 16.50, 18.50),
        Setup("HTCO", 7.90,  8.30,  10.00, 12.00),
        Setup("BW",   18.50, 20.00, 22.00, 25.00),
        Setup("QUBT", 11.80, 12.55, 14.00, 16.60),
    ]),

    # ── 13-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 13), [
        Setup("SIBN", 13.32, 14.05, 15.90, 21.89),
        Setup("BWEN", 4.80,  4.95,  5.50,  6.00),
        Setup("VELO", 16.61, 17.90, 23.84, 30.00),
        Setup("WOK",  11.20, 11.90, 15.00, 20.00),
        Setup("TDIC", 3.43,  3.81,  4.40,  5.00),
        Setup("ERNA", 15.26, 15.88, 24.78, 26.10),
        Setup("OCG",  2.57,  2.71,  3.15,  3.50),
        Setup("AMBQ", 66.43, 67.50, 75.00, 80.00),
        Setup("STAK", 2.23,  2.28,  3.00,  3.30),
        Setup("FCHL", 1.95,  2.00,  2.33,  3.34),
        Setup("DGXX", 9.22,  9.50,  10.63, 11.55),
        Setup("VSTS", 12.15, 12.65, 17.83, 20.00),
        Setup("AEHL", 2.05,  2.27,  3.95,  4.18),
        Setup("BZFD", 1.82,  1.85,  2.27,  2.50),
        Setup("FCEL", 18.72, 19.47, 22.00, 25.00),
    ]),

    # ── 14-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 14), [
        Setup("VIVO", 4.50,  4.88,  5.50,  6.00),
        Setup("OCG",  2.40,  2.50,  2.75,  3.00),
        Setup("AEHL", 5.88,  6.35,  7.00,  7.50),
        Setup("QUCY", 1.05,  1.20,  2.00,  2.60),
        Setup("DXF",  2.10,  2.38,  3.00,  3.40),
        Setup("AIIO", 2.60,  2.79,  3.60,  4.50),
        Setup("INBS", 3.80,  4.09,  5.03,  5.54),
        Setup("SNAL", 1.00,  1.12,  1.40,  1.80),
        Setup("VELO", 21.00, 21.60, 23.84, 30.00),
        Setup("BESS", 3.30,  3.55,  4.50,  5.50),
        Setup("NRGV", 6.00,  6.30,  7.00,  7.50),
        Setup("GUTS", 0.94,  0.99,  1.10,  1.20),
        Setup("MSGY", 0.58,  0.66,  0.73,  0.80),
        Setup("CMPS", 10.60, 11.08, 13.00, 15.00),
        Setup("FCHL", 2.30,  2.40,  2.80,  3.10),
    ]),

    # ── 15-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 15), [
        Setup("TRT",  14.40, 14.75, 16.50, 19.00),
        Setup("LNKS", 1.90,  2.00,  2.20,  2.47),
        Setup("MOBX", 3.50,  3.80,  4.50,  5.00),
        Setup("HCWB", 0.86,  0.93,  1.20,  1.60),
        Setup("PIII", 7.00,  7.72,  9.00,  10.00),
        Setup("BIYA", 1.28,  1.41,  2.00,  2.40),
        Setup("LESL", 3.50,  3.90,  5.40,  6.30),
        Setup("RDW",  13.60, 14.60, 16.49, 20.00),
        Setup("COYA", 5.20,  5.36,  6.00,  7.70),
        Setup("POET", 24.00, 25.70, 30.00, 33.00),
        Setup("SNAL", 1.20,  1.35,  1.50,  1.67),
        Setup("VIVO", 5.10,  5.25,  6.00,  6.50),
        Setup("WYFI", 30.00, 31.22, 35.00, 39.00),
    ]),

    # ── 18-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 18), [
        Setup("SLE",  5.50,  5.90,  6.50,  7.10),
        Setup("NXXT", 0.58,  0.66,  1.00,  1.40),
        Setup("AUUD", 2.20,  2.38,  3.30,  4.00),
        Setup("HCWB", 0.96,  1.00,  1.42,  1.70),
    ]),

    # ── 19-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 19), [
        Setup("VRAX", 0.23,  0.28,  0.33,  0.50),
        Setup("AUUD", 2.20,  2.60,  3.00,  4.00),
        Setup("SACH", 1.45,  1.55,  1.75,  2.00),
        Setup("AMST", 1.10,  1.28,  1.50,  2.00),
        Setup("GCTS", 2.60,  2.71,  3.00,  3.30),
        Setup("AMPG", 3.70,  3.93,  4.30,  4.60),
        Setup("GOVX", 1.80,  2.40,  3.40,  4.40),
        Setup("AIIO", 6.00,  7.00,  10.00, 13.00),
        Setup("BRC",  85.00, 86.65, 93.00, 100.00),
    ]),

    # ── 20-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 20), [
        Setup("WNW",  5.30,  6.00,  7.00,  10.00),
        Setup("MTVA", 1.78,  2.00,  2.30,  3.00),
        Setup("GIPR", 0.54,  0.59,  0.70,  0.80),
        Setup("CODX", 2.47,  2.75,  3.50,  4.50),
        Setup("CNEY", 1.40,  1.77,  2.00,  2.20),
        Setup("INM",  1.65,  1.80,  1.93,  2.10),
        Setup("GCL",  0.85,  0.92,  1.20,  2.00),
        Setup("AMPG", 4.10,  4.28,  4.88,  6.00),
        Setup("VRAX", 0.28,  0.33,  0.38,  0.50),
        Setup("GCTS", 2.80,  2.96,  3.30,  3.50),
        Setup("AMST", 1.60,  1.80,  2.00,  2.30),
        Setup("NXXT", 0.60,  0.70,  0.95,  1.50),
    ]),

    # ── 21-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 21), [
        Setup("CODX", 2.55,  2.75,  3.30,  4.00),
        Setup("VIDA", 4.33,  4.82,  5.50,  6.00),
        Setup("LPG",  46.60, 48.12, 55.00, 60.00),
        Setup("NCPL", 0.62,  0.68,  0.80,  1.00),
        Setup("UCAR", 1.85,  2.00,  2.40,  2.80),
        Setup("STFS", 15.00, 17.54, 20.00, 22.00),
        Setup("LIMN", 0.25,  0.29,  0.50,  0.60),
        Setup("MTVA", 3.00,  3.31,  4.00,  4.40),
        Setup("AMPG", 4.75,  4.88,  6.00,  7.00),
        Setup("PRFX", 2.20,  2.50,  2.80,  3.00),
        Setup("PSNL", 7.70,  8.10,  10.00, 11.50),
        Setup("BNZI", 5.50,  5.87,  7.50,  10.00),
        Setup("GIPR", 0.55,  0.59,  0.75,  1.00),
        Setup("PHGE", 0.74,  0.80,  1.00,  1.50),
    ]),

    # ── 22-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 22), [
        Setup("ATPC", 3.65,  4.00,  5.00,  6.00),
        Setup("GOVX", 2.50,  2.65,  3.50,  4.00),
        Setup("ARQQ", 16.70, 17.40, 20.00, 25.00),
        Setup("AKTX", 13.00, 15.73, 18.00, 20.00),
        Setup("PCLA", 3.25,  4.00,  5.00,  8.00),
        Setup("EDHL", 3.50,  4.00,  5.00,  5.50),
        Setup("LFS",  3.00,  3.36,  4.00,  4.40),
        Setup("AMPG", 5.40,  5.60,  6.50,  7.00),
        Setup("NCPL", 0.90,  0.96,  1.10,  1.25),
        Setup("NIVF", 0.97,  1.20,  1.60,  2.00),
        Setup("FCEL", 26.00, 27.00, 30.00, 33.00),
        Setup("INFQ", 15.00, 16.11, 18.00, 20.00),
        Setup("QUBT", 11.70, 12.13, 14.50, 16.50),
        Setup("WYFI", 31.50, 33.32, 40.00, 44.00),
        Setup("CODX", 3.50,  3.75,  4.10,  4.50),
        Setup("VIDA", 4.50,  5.07,  5.79,  6.50),
        Setup("PHGE", 0.65,  0.70,  0.80,  0.90),
        Setup("MTVA", 3.00,  3.31,  4.50,  5.50),
    ]),

    # ── 26-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 26), [
        Setup("VCIG", 1.50,  1.69,  2.00,  2.20),
        Setup("ARTL", 2.00,  2.10,  2.50,  3.30),
        Setup("PHGE", 1.10,  1.20,  1.50,  2.00),
        Setup("FEMY", 0.57,  0.62,  0.80,  0.90),
        Setup("GOVX", 3.70,  4.00,  5.00,  5.50),
        Setup("PCLA", 6.60,  7.50,  10.00, 11.50),
    ]),

    # ── 27-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 27), [
        Setup("CPSH", 11.30, 12.00, 15.00, 20.00),
        Setup("MNTS", 19.00, 20.00, 22.00, 25.00),
        Setup("GRRR", 16.20, 16.95, 20.00, 22.00),
        Setup("SNGX", 0.92,  0.98,  1.10,  1.50),
        Setup("VCIG", 3.80,  4.75,  6.00,  7.50),
        Setup("QUCY", 1.05,  1.20,  2.00,  2.60),
        Setup("DXF",  2.10,  2.38,  3.00,  3.40),
        Setup("AIIO", 2.60,  2.79,  3.60,  4.50),
        Setup("INBS", 3.80,  4.09,  5.03,  5.54),
        Setup("NCPL", 1.40,  1.59,  2.00,  2.20),
        Setup("CODX", 10.00, 10.80, 13.00, 15.00),
        Setup("VELO", 21.00, 21.60, 23.84, 30.00),
        Setup("RDW",  24.00, 24.97, 30.00, 33.00),
        Setup("NRGV", 6.00,  6.30,  7.00,  7.50),
        Setup("BESS", 3.30,  3.55,  4.50,  5.50),
        Setup("CMPS", 10.60, 11.08, 13.00, 15.00),
        Setup("FCHL", 2.30,  2.40,  2.80,  3.10),
        Setup("GUTS", 0.94,  0.99,  1.10,  1.20),
        Setup("FCEL", 19.80, 21.00, 25.00, 30.00),
        Setup("AMBQ", 69.00, 72.50, 80.00, 85.00),
        Setup("MSGY", 0.58,  0.66,  0.73,  0.80),
        Setup("QTEX", 1.55,  1.60,  2.20,  2.50),
        Setup("UZX",  1.00,  1.16,  1.65,  2.00),
        Setup("AEHL", 5.88,  6.35,  7.00,  7.50),
    ]),

    # ── 28-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 28), [
        Setup("SNGX", 0.80,  1.00,  1.10,  1.30),
        Setup("ASTC", 10.80, 13.00, 15.00, 24.00),
        Setup("NCPL", 1.47,  1.60,  1.80,  2.00),
        Setup("HOTH", 1.60,  1.75,  2.10,  2.60),
        Setup("IMRN", 1.75,  1.91,  2.20,  3.00),
        Setup("ATPC", 7.10,  8.30,  12.50, 15.00),
        Setup("QTTB", 13.00, 14.40, 20.00, 22.00),
        Setup("NTCL", 0.66,  0.76,  0.85,  1.00),
        Setup("ASTI", 7.10,  7.40,  9.00,  10.00),
        Setup("SUUN", 1.20,  1.28,  1.50,  2.00),
        Setup("EDIT", 3.75,  3.94,  4.50,  5.00),
        Setup("CRSR", 12.50, 13.00, 15.00, 18.00),
        Setup("FGL",  2.50,  2.80,  3.10,  3.50),
        Setup("BRTX", 0.40,  0.46,  0.55,  0.68),
        Setup("VCIG", 3.90,  4.40,  5.00,  6.00),
        Setup("SNOW", 230.00, 240.00, 280.00, 300.00),
    ]),

    # ── 29-05-2026 ───────────────────────────────────────────────────────────
    (date(2026, 5, 29), [
        Setup("IOTR", 3.30,  3.90,  5.00,  5.50),
        Setup("PRFX", 4.50,  6.30,  10.00, 13.00),
        Setup("SPRC", 14.00, 15.65, 18.00, 20.00),
        Setup("ASTC", 36.00, 43.05, 50.00, 55.00),
        Setup("UMAC", 31.50, 33.46, 40.00, 44.00),
        Setup("NEXR", 2.10,  2.47,  3.40,  4.40),
        Setup("CODX", 12.80, 13.54, 15.00, 20.00),
        Setup("MX",   7.00,  7.15,  8.00,  8.50),
        Setup("AVEX", 40.00, 41.16, 50.00, 55.00),
        Setup("GMEX", 2.00,  2.10,  2.40,  3.33),
        Setup("SWMR", 56.00, 60.00, 69.00, 75.00),
        Setup("BRR",  2.30,  2.43,  3.00,  3.70),
        Setup("ONDL", 26.00, 27.47, 33.00, 36.00),
        Setup("APPS", 8.45,  8.91,  10.00, 12.00),
        Setup("AIRO", 8.90,  9.60,  10.70, 13.00),
        Setup("ZENA", 1.68,  1.77,  2.00,  2.50),
        Setup("GCDT", 1.35,  1.68,  2.00,  2.20),
        Setup("ATPC", 7.30,  8.50,  9.50,  11.00),
        Setup("RCAT", 14.00, 15.06, 16.50, 18.50),
    ]),

    # ── 01-06-2026 ───────────────────────────────────────────────────────────
    (date(2026, 6, 1), [
        Setup("HUBC", 0.35,  0.40,  0.50,  0.60),
        Setup("ASTC", 48.00, 52.00, 60.00, 70.00),
        Setup("NAMM", 2.35,  2.49,  3.00,  4.40),
        Setup("MX",   9.30,  9.78,  11.00, 13.00),
        Setup("OLOX", 8.00,  8.70,  11.00, 12.50),
        Setup("ZENA", 1.60,  1.80,  2.00,  2.50),
        Setup("SPRC", 9.00,  10.00, 11.30, 14.00),
        Setup("UMAC", 31.00, 33.00, 40.00, 44.00),
        Setup("MASK", 3.80,  4.20,  6.75,  8.40),
        Setup("MNTS", 18.30, 20.30, 35.00, 43.50),
    ]),

    # ── 02-06-2026 ───────────────────────────────────────────────────────────
    (date(2026, 6, 2), [
        Setup("ABTS", 1.85,  2.30,  3.30,  4.40),
        Setup("ANY",  4.80,  5.30,  6.00,  7.00),
        Setup("DBGI", 1.10,  1.30,  1.60,  2.20),
        Setup("VSA",  7.60,  8.00,  9.00,  13.00),
        Setup("DXST", 2.50,  2.91,  4.00,  5.00),
        Setup("CTNT", 3.00,  3.30,  4.00,  4.40),
        Setup("SOAR", 0.36,  0.43,  0.50,  0.70),
        Setup("ZNB",  2.90,  3.16,  3.40,  4.00),
        Setup("LFVN", 10.80, 11.00, 15.00, 20.00),
        Setup("AMZE", 0.20,  0.22,  0.25,  0.30),
        Setup("FLNC", 27.50, 29.00, 33.50, 40.00),
        Setup("HUBC", 0.50,  0.55,  0.65,  1.00),
        Setup("HKIT", 3.80,  5.00,  9.80,  16.00),
    ]),

    # ── 03-06-2026 ───────────────────────────────────────────────────────────
    (date(2026, 6, 3), [
        Setup("DXST", 5.40,  5.82,  6.50,  7.00),
        Setup("KULR", 5.20,  5.43,  6.00,  6.50),
        Setup("DEVS", 0.66,  0.70,  0.80,  0.90),
        Setup("LASE", 3.20,  3.67,  4.40,  5.00),
        Setup("XOS",  5.00,  5.43,  7.00,  8.00),
        Setup("STAK", 2.10,  2.40,  3.00,  3.30),
        Setup("RZLT", 4.30,  4.50,  5.00,  6.00),
        Setup("TOPS", 1.50,  1.70,  2.00,  2.30),
        Setup("VRAX", 0.27,  0.30,  0.35,  0.40),
        Setup("PMI",  0.37,  0.41,  0.46,  0.55),
        Setup("PUSA", 6.40,  6.50,  7.70,  8.50),
        Setup("GNTA", 2.30,  2.58,  3.30,  4.00),
        Setup("URG",  2.10,  2.20,  2.50,  3.00),
        Setup("YMAT", 1.35,  1.45,  1.80,  2.25),
        Setup("ABTS", 2.20,  2.60,  3.20,  3.70),
        Setup("ANY",  3.90,  4.25,  5.00,  5.50),
        Setup("VSA",  4.30,  5.00,  6.50,  7.60),
        Setup("SOAR", 0.28,  0.32,  0.40,  0.50),
    ]),

    # ── 04-06-2026 ───────────────────────────────────────────────────────────
    (date(2026, 6, 4), [
        Setup("XOS",  6.30,  7.00,  8.00,  10.00),
        Setup("STAK", 3.50,  3.90,  4.50,  5.00),
        Setup("SBEV", 0.34,  0.39,  0.45,  0.50),
        Setup("FOXX", 4.40,  4.80,  6.00,  8.00),
        Setup("TWAV", 2.20,  2.60,  3.00,  4.00),
        Setup("YYGH", 0.20,  0.22,  0.25,  0.30),
        Setup("SDOT", 6.40,  7.00,  8.50,  9.50),
        Setup("BNRG", 1.80,  2.00,  2.70,  3.50),
        Setup("FOFO", 6.00,  7.20,  8.00,  9.50),
        Setup("CXAI", 0.25,  0.28,  0.33,  0.40),
        Setup("VGNT", 48.00, 49.92, 55.00, 60.00),
        Setup("TURB", 1.70,  1.90,  2.20,  2.50),
        Setup("RZLT", 4.50,  4.64,  5.30,  6.00),
        Setup("DRTS", 10.80, 11.00, 12.00, 15.00),
        Setup("SELX", 0.56,  0.65,  0.80,  0.90),
        Setup("WCT",  2.80,  3.00,  3.50,  4.00),
        Setup("PMI",  0.29,  0.33,  0.39,  0.46),
    ]),
]


# ---------------------------------------------------------------------------
# Multi-dag backtest
# ---------------------------------------------------------------------------

def run_series(days, start_capital: float = 50.0, fee_pct: float = 0.0015) -> None:
    capital = start_capital
    print(f"\n{'='*72}")
    print(f"  KRUSH SERIES BACKTEST  |  {days[0][0]} → {days[-1][0]}")
    print(f"  Startkapitaal: ${start_capital:.2f}  |  Fee: {fee_pct*100:.2f}% p/zijde  |  {len(days)} handelsdagen")
    print(f"  Scenario A: geen ORB-high filter, volume >= 2x ORB-gemiddelde")
    print(f"{'='*72}\n")

    print(f"  {'Datum':<12} {'Tickers':>7} {'Trades':>7} {'Wins':>5} {'Stops':>6} {'PnL':>9}  {'Kapitaal':>10}  Beste trade")
    print(f"  {'-'*70}")

    daily_summary = []

    for trade_date, watchlist in days:
        # Data ophalen
        data = {}
        for s in watchlist:
            data[s.ticker] = fetch_1m(s.ticker, trade_date)

        results = run_scenario(watchlist, data, "A", 0, capital, fee_pct)

        trades = [r for r in results if r.exit_reason not in ("NO_ENTRY", "NO_DATA", "TOO_EXPENSIVE")]
        wins   = [r for r in trades  if r.exit_reason == "T1"]
        stops  = [r for r in trades  if r.exit_reason == "STOP"]
        day_pnl = sum(r.pnl for r in trades)

        best = max(trades, key=lambda r: r.pnl) if trades else None
        best_str = f"{best.ticker} {best.pnl:+.2f} ({best.pnl_pct:+.0f}%)" if best else "—"

        capital_prev = capital
        capital += day_pnl
        pnl_sign = "+" if day_pnl >= 0 else ""

        print(
            f"  {trade_date}  {len(watchlist):>7}  {len(trades):>6}  {len(wins):>5}  {len(stops):>5}"
            f"  {pnl_sign}${day_pnl:>7.2f}  ${capital:>9.2f}  {best_str}"
        )

        daily_summary.append({
            "date": trade_date,
            "tickers": len(watchlist),
            "trades": len(trades),
            "wins": len(wins),
            "stops": len(stops),
            "pnl": day_pnl,
            "capital_end": capital,
            "results": results,
        })

    # ── Eindrapport ──────────────────────────────────────────────────────────
    total_pnl   = capital - start_capital
    total_trades = sum(d["trades"] for d in daily_summary)
    total_wins   = sum(d["wins"]   for d in daily_summary)
    total_stops  = sum(d["stops"]  for d in daily_summary)
    win_rate     = total_wins / total_trades * 100 if total_trades else 0
    growth_pct   = total_pnl / start_capital * 100

    best_day  = max(daily_summary, key=lambda d: d["pnl"])
    worst_day = min(daily_summary, key=lambda d: d["pnl"])
    pos_days  = sum(1 for d in daily_summary if d["pnl"] > 0)
    neg_days  = sum(1 for d in daily_summary if d["pnl"] < 0)

    print(f"\n{'='*72}")
    print(f"  EINDRESULTAAT")
    print(f"{'='*72}")
    print(f"  Startkapitaal  : ${start_capital:.2f}")
    print(f"  Eindkapitaal   : ${capital:.2f}")
    print(f"  Totaal PnL     : ${total_pnl:+.2f}  ({growth_pct:+.1f}%)")
    print(f"  Handelsdagen   : {len(daily_summary)}  ({pos_days} positief, {neg_days} negatief)")
    print(f"  Totaal trades  : {total_trades}  (wins: {total_wins}, stops: {total_stops}, win rate: {win_rate:.0f}%)")
    print(f"  Beste dag      : {best_day['date']}  +${best_day['pnl']:.2f}")
    print(f"  Slechtste dag  : {worst_day['date']}  ${worst_day['pnl']:+.2f}")
    print(f"{'='*72}\n")

    # ── Detailrapport elke dag die trades had ────────────────────────────────
    print("\nDETAIL PER DAG (alleen actieve trades):\n")
    for d in daily_summary:
        trades = [r for r in d["results"] if r.exit_reason not in ("NO_ENTRY", "NO_DATA", "TOO_EXPENSIVE")]
        if not trades:
            print(f"  [{d['date']}]  geen trades")
            continue
        print(f"  [{d['date']}]  PnL: ${d['pnl']:+.2f}  |  kapitaal na dag: ${d['capital_end']:.2f}")
        for r in trades:
            icon = "WIN " if r.exit_reason == "T1" else ("STOP" if r.exit_reason == "STOP" else "EOD ")
            print(
                f"    {r.ticker:<6} {r.entry_price:>7.2f} -> {r.exit_price:>7.2f}"
                f"  {r.entry_time}->{r.exit_time}  {r.shares:>5}x  ${r.pnl:>+7.2f} ({r.pnl_pct:>+5.1f}%)  [{icon}]"
            )


if __name__ == "__main__":
    run_series(DAYS, start_capital=50.0, fee_pct=0.0015)
