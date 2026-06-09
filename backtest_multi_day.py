"""
Multi-day backtest van Krush's watchlists (22 apr – 2 jun 2026).

Simuleert scenario A (Break + 2x volume, geen ORB) met één cash pool.
Compounding aan: winst/verlies rolt over naar de volgende dag.
Geen nieuwe trade als er onvoldoende cash is (zit vast in open positie).

Gebruik:
    python backtest_multi_day.py [--capital 50]
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

from stocktrader.market_data import fetch_1m
from stocktrader.parser import Setup


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeResult:
    ticker:            str
    entry_price:       Optional[float]
    entry_time:        Optional[str]
    exit_price:        Optional[float]
    exit_time:         Optional[str]
    exit_reason:       str
    shares:            int
    spend:             float
    pnl:               float
    pnl_pct:           float
    breakout_vol_mult: Optional[float]


# ---------------------------------------------------------------------------
# Watchlists — gesorteerd op datum
# ---------------------------------------------------------------------------

WATCHLISTS: Dict[date, List[Setup]] = {
    date(2026, 4, 22): [
        Setup("TDIC",  1.10,  1.20,  1.70,  2.50),
        Setup("ELPW",  2.40,  2.56,  3.00,  3.70),
        Setup("KBSX",  1.90,  1.98,  2.20,  2.50),
        Setup("VELO",  15.50, 16.10, 20.00, 24.00),
        Setup("XRTX",  3.00,  3.30,  3.70,  4.40),
        Setup("CLIK",  3.90,  4.20,  5.30,  6.60),
        Setup("BIYA",  1.30,  1.45,  1.70,  2.00),
        Setup("PBI",   14.50, 14.87, 20.00, 22.00),
        Setup("POET",  10.80, 11.30, 13.00, 15.00),
        Setup("BANL",  0.64,  0.68,  0.77,  0.88),
        Setup("ALLR",  1.38,  1.43,  1.70,  2.00),
        Setup("SPRC",  5.50,  6.00,  6.50,  7.00),
        Setup("FGI",   11.50, 12.23, 15.00, 20.00),
        Setup("LOCL",  3.10,  3.30,  3.83,  4.70),
    ],
    date(2026, 4, 23): [
        Setup("AKAN",  11.50, 12.00, 20.00, 30.00),
        Setup("PAPL",  0.88,  1.00,  1.20,  2.00),
        Setup("YCBD",  1.20,  1.32,  1.50,  2.00),
        Setup("BEEM",  1.95,  2.05,  2.20,  2.50),
        Setup("FCEL",  11.50, 11.90, 14.00, 15.00),
        Setup("MEHA",  0.165, 0.18,  0.20,  0.24),
        Setup("TORO",  7.00,  7.70,  8.50,  10.00),
        Setup("ELPW",  2.20,  2.50,  2.80,  3.00),
        Setup("HCAI",  12.70, 14.30, 16.50, 17.50),
        Setup("SHFS",  1.05,  1.15,  1.30,  1.50),
        Setup("TOMZ",  0.70,  0.77,  0.90,  1.00),
        Setup("POET",  12.80, 13.32, 15.00, 18.00),
        Setup("LHSW",  0.30,  0.34,  0.50,  0.75),
        Setup("NMAX",  10.50, 11.20, 13.50, 16.00),
    ],
    date(2026, 4, 24): [
        Setup("IQST",  2.45,  2.72,  3.50,  4.20),
        Setup("RENX",  3.30,  3.50,  4.00,  5.00),
        Setup("TIVC",  1.40,  1.55,  2.00,  2.50),
        Setup("MXL",   46.00, 49.00, 55.00, 60.00),
        Setup("ITOC",  0.48,  0.54,  0.75,  1.00),
        Setup("TRT",   14.80, 16.35, 20.00, 22.00),
        Setup("AUUD",  5.00,  5.60,  7.00,  7.70),
        Setup("REPL",  2.80,  2.96,  3.30,  4.20),
        Setup("FCEL",  12.00, 12.43, 14.00, 15.00),
        Setup("NCEL",  4.70,  5.13,  5.70,  7.50),
        Setup("ELPW",  2.70,  2.80,  3.12,  3.60),
        Setup("POET",  12.00, 12.50, 15.00, 20.00),
    ],
    date(2026, 4, 30): [
        Setup("XTLB",  3.10,  3.30,  3.90,  5.00),
        Setup("SAGT",  1.90,  2.20,  2.70,  3.30),
        Setup("ABTS",  1.55,  1.73,  2.00,  3.00),
        Setup("BRLS",  2.00,  2.25,  2.50,  3.00),
        Setup("VSME",  1.20,  1.25,  1.50,  2.00),
        Setup("BIYA",  2.07,  2.19,  3.00,  3.70),
        Setup("FCEL",  14.50, 15.00, 20.00, 22.00),
        Setup("KALV",  26.61, 26.76, 30.00, 33.00),
        Setup("FATN",  3.00,  3.20,  4.00,  4.70),
        Setup("SIMO",  217.00,235.00,260.00,280.00),
    ],
    date(2026, 5, 1): [
        Setup("MRAM",  18.50, 19.71, 22.00, 25.00),
        Setup("HCAI",  12.70, 14.45, 16.50, 17.60),
        Setup("FATN",  3.00,  3.20,  3.50,  4.00),
        Setup("SOBR",  0.75,  0.83,  1.00,  1.25),
        Setup("CUE",   31.00, 34.92, 40.00, 44.00),
        Setup("ISPC",  6.60,  7.34,  10.88, 12.53),
        Setup("SHPH",  1.40,  1.55,  2.00,  2.70),
        Setup("AIOS",  14.00, 15.00, 17.74, 28.18),
        Setup("WNW",   5.00,  5.70,  6.50,  7.00),
        Setup("TWLO",  167.00,176.69,200.00,210.00),
        Setup("SILC",  37.00, 39.90, 44.00, 50.00),
        Setup("VSAT",  65.00, 67.00, 75.00, 80.00),
        Setup("XRX",   2.20,  2.50,  3.00,  3.30),
        Setup("ABTS",  1.20,  1.35,  1.50,  1.75),
        Setup("VSME",  1.00,  1.20,  1.36,  1.50),
        Setup("XTLB",  3.70,  3.95,  4.50,  4.87),
        Setup("AKAN",  62.00, 64.00, 75.00, 80.00),
        Setup("SKLZ",  7.10,  7.70,  8.40,  9.00),
    ],
    date(2026, 5, 4): [
        Setup("SOBR",  0.97,  1.12,  1.26,  1.50),
        Setup("PN",    4.50,  5.00,  6.20,  7.80),
        Setup("WOLF",  36.60, 40.00, 44.00, 50.00),
        Setup("CUE",   34.00, 36.60, 40.00, 45.00),
        Setup("AMS",   1.90,  2.05,  2.40,  2.60),
        Setup("STAK",  1.15,  1.30,  1.70,  2.00),
        Setup("MRAM",  22.00, 23.50, 30.00, 33.00),
        Setup("TWLO",  180.00,184.00,220.00,240.00),
        Setup("ISPC",  5.00,  5.80,  6.60,  7.70),
        Setup("TLIH",  4.15,  4.61,  5.55,  6.75),
        Setup("LNAI",  0.40,  0.42,  0.60,  0.80),
    ],
    date(2026, 5, 6): [
        Setup("MASK",  2.40,  2.68,  3.30,  4.30),
        Setup("BLZE",  7.80,  8.42,  10.00, 11.00),
        Setup("EZGO",  2.30,  2.60,  3.40,  4.00),
        Setup("SOBR",  1.40,  1.56,  2.10,  2.50),
        Setup("OCG",   2.40,  2.62,  3.10,  3.50),
        Setup("EVC",   7.00,  7.55,  8.50,  10.00),
        Setup("AVTX",  23.00, 27.80, 33.00, 35.00),
        Setup("AREB",  0.36,  0.39,  0.60,  0.70),
        Setup("FATE",  2.30,  2.43,  3.00,  4.00),
        Setup("AMDL",  46.00, 47.08, 55.00, 60.00),
        Setup("EVER",  23.00, 24.49, 28.00, 30.00),
    ],
    date(2026, 5, 7): [
        Setup("PMAX",  4.50,  4.80,  5.40,  6.00),
        Setup("OSS",   15.50, 16.27, 20.00, 22.00),
        Setup("IFRX",  2.60,  2.86,  3.30,  3.50),
        Setup("ERNA",  6.60,  7.70,  8.50,  9.00),
        Setup("GLE",   0.60,  0.64,  0.75,  0.80),
        Setup("BLMN",  8.10,  8.56,  9.50,  10.70),
        Setup("EVC",   7.80,  8.35,  9.50,  10.50),
        Setup("STFS",  8.00,  8.99,  10.00, 15.00),
        Setup("FLNC",  17.70, 19.40, 25.00, 30.00),
        Setup("LBGJ",  1.10,  1.27,  2.00,  2.50),
        Setup("MASK",  2.50,  2.74,  4.45,  5.00),
        Setup("OCG",   2.35,  2.50,  3.00,  3.50),
        Setup("WKHS",  4.00,  4.26,  5.00,  5.50),
    ],
    date(2026, 5, 8): [
        Setup("RMSG",  1.78,  1.86,  2.20,  2.60),
        Setup("AGL",   60.00, 64.00, 75.00, 80.00),
        Setup("ERNA",  7.80,  8.49,  10.00, 12.00),
        Setup("SOBR",  1.85,  1.99,  3.00,  3.50),
        Setup("GLE",   0.66,  0.76,  0.90,  1.00),
        Setup("AIIO",  0.92,  0.99,  1.20,  1.50),
        Setup("EVC",   6.50,  7.00,  7.80,  10.00),
    ],
    date(2026, 5, 11): [
        Setup("MASK",  3.20,  3.40,  4.00,  4.50),
        Setup("YMAT",  0.60,  0.68,  0.90,  1.00),
        Setup("WEST",  8.37,  8.62,  9.50,  10.01),
        Setup("AEHL",  2.62,  2.84,  4.20,  4.75),
        Setup("MRAM",  35.70, 39.00, 44.00, 50.00),
        Setup("RXT",   6.00,  6.20,  7.00,  7.50),
        Setup("MTEX",  7.60,  7.90,  8.80,  9.50),
        Setup("CODX",  2.60,  2.77,  3.05,  3.50),
        Setup("CSIQ",  19.90, 20.47, 23.00, 26.00),
        Setup("INO",   1.70,  1.79,  2.00,  2.20),
        Setup("FCEL",  14.00, 14.50, 15.50, 18.00),
        Setup("HPAI",  1.48,  1.57,  2.00,  2.40),
        Setup("VRAX",  0.23,  0.24,  0.28,  0.33),
    ],
    date(2026, 5, 12): [
        Setup("JZXN",  1.30,  1.45,  1.60,  1.90),
        Setup("DGXX",  8.35,  8.59,  9.50,  10.00),
        Setup("XGN",   4.00,  4.13,  5.00,  6.60),
        Setup("AMBO",  3.25,  4.35,  5.25,  6.75),
        Setup("XOS",   2.63,  2.77,  3.00,  3.60),
        Setup("MRAM",  43.00, 44.67, 50.00, 55.00),
        Setup("VEEE",  8.20,  8.80,  10.00, 12.00),
        Setup("FCEL",  16.60, 17.40, 20.00, 22.00),
        Setup("EVC",   8.65,  8.90,  9.90,  10.60),
        Setup("BZFD",  1.90,  2.27,  2.50,  3.00),
        Setup("GSIT",  12.50, 13.30, 16.50, 18.50),
        Setup("HTCO",  7.90,  8.30,  10.00, 12.00),
        Setup("BW",    18.50, 20.00, 22.00, 25.00),
        Setup("QUBT",  11.80, 12.55, 14.00, 16.60),
    ],
    date(2026, 5, 13): [
        Setup("SIBN",  13.32, 14.05, 15.90, 21.89),
        Setup("BWEN",  4.80,  4.95,  5.50,  6.00),
        Setup("VELO",  16.61, 17.90, 23.84, 30.00),
        Setup("WOK",   11.20, 11.90, 15.00, 20.00),
        Setup("TDIC",  3.43,  3.81,  4.40,  5.00),
        Setup("ERNA",  15.26, 15.88, 24.78, 26.10),
        Setup("OCG",   2.57,  2.71,  3.15,  3.50),
        Setup("AMBQ",  66.43, 67.50, 75.00, 80.00),
        Setup("STAK",  2.23,  2.28,  3.00,  3.30),
        Setup("FCHL",  1.95,  2.00,  2.33,  3.34),
        Setup("DGXX",  9.22,  9.50,  10.63, 11.55),
        Setup("VSTS",  12.15, 12.65, 17.83, 20.00),
        Setup("AEHL",  2.05,  2.27,  3.95,  4.18),
        Setup("BZFD",  1.82,  1.85,  2.27,  2.50),
        Setup("FCEL",  18.72, 19.47, 22.00, 25.00),
    ],
    date(2026, 5, 14): [
        Setup("VIVO",  4.50,  4.88,  5.50,  6.00),
        Setup("OCG",   2.40,  2.50,  2.75,  3.00),
        Setup("AEHL",  5.88,  6.35,  7.00,  7.50),
        Setup("QUCY",  1.05,  1.20,  2.00,  2.60),
        Setup("DXF",   2.10,  2.38,  3.00,  3.40),
        Setup("AIIO",  2.60,  2.79,  3.60,  4.50),
        Setup("INBS",  3.80,  4.09,  5.03,  5.54),
        Setup("SNAL",  1.00,  1.12,  1.40,  1.80),
        Setup("VELO",  21.00, 21.60, 23.84, 30.00),
        Setup("BESS",  3.30,  3.55,  4.50,  5.50),
        Setup("NRGV",  6.00,  6.30,  7.00,  7.50),
        Setup("GUTS",  0.94,  0.99,  1.10,  1.20),
        Setup("MSGY",  0.58,  0.66,  0.73,  0.80),
        Setup("CMPS",  10.60, 11.08, 13.00, 15.00),
        Setup("FCHL",  2.30,  2.40,  2.80,  3.10),
    ],
    date(2026, 5, 15): [
        Setup("TRT",   14.40, 14.75, 16.50, 19.00),
        Setup("LNKS",  1.90,  2.00,  2.20,  2.47),
        Setup("MOBX",  3.50,  3.80,  4.50,  5.00),
        Setup("HCWB",  0.86,  0.93,  1.20,  1.60),
        Setup("PIII",  7.00,  7.72,  9.00,  10.00),
        Setup("BIYA",  1.28,  1.41,  2.00,  2.40),
        Setup("LESL",  3.50,  3.90,  5.40,  6.30),
        Setup("RDW",   13.60, 14.60, 16.49, 20.00),
        Setup("COYA",  5.20,  5.36,  6.00,  7.70),
        Setup("POET",  24.00, 25.70, 30.00, 33.00),
        Setup("SNAL",  1.20,  1.35,  1.50,  1.67),
        Setup("VIVO",  5.10,  5.25,  6.00,  6.50),
        Setup("WYFI",  30.00, 31.22, 35.00, 39.00),
    ],
    date(2026, 5, 18): [
        Setup("SLE",   5.50,  5.90,  6.50,  7.10),
        Setup("NXXT",  0.58,  0.66,  1.00,  1.40),
        Setup("AUUD",  2.20,  2.38,  3.30,  4.00),
        Setup("HCWB",  0.96,  1.00,  1.42,  1.70),
    ],
    date(2026, 5, 19): [
        Setup("VRAX",  0.23,  0.28,  0.33,  0.50),
        Setup("AUUD",  2.20,  2.60,  3.00,  4.00),
        Setup("SACH",  1.45,  1.55,  1.75,  2.00),
        Setup("AMST",  1.10,  1.28,  1.50,  2.00),
        Setup("GCTS",  2.60,  2.71,  3.00,  3.30),
        Setup("AMPG",  3.70,  3.93,  4.30,  4.60),
        Setup("GOVX",  1.80,  2.40,  3.40,  4.40),
        Setup("AIIO",  6.00,  7.00,  10.00, 13.00),
        Setup("BRC",   85.00, 86.65, 93.00, 100.00),
    ],
    date(2026, 5, 20): [
        Setup("WNW",   5.30,  6.00,  7.00,  10.00),
        Setup("MTVA",  1.78,  2.00,  2.30,  3.00),
        Setup("GIPR",  0.54,  0.59,  0.70,  0.80),
        Setup("CODX",  2.47,  2.75,  3.50,  4.50),
        Setup("CNEY",  1.40,  1.77,  2.00,  2.20),
        Setup("INM",   1.65,  1.80,  1.93,  2.10),
        Setup("GCL",   0.85,  0.92,  1.20,  2.00),
        Setup("AMPG",  4.10,  4.28,  4.88,  6.00),
        Setup("VRAX",  0.28,  0.33,  0.38,  0.50),
        Setup("GCTS",  2.80,  2.96,  3.30,  3.50),
        Setup("AMST",  1.60,  1.80,  2.00,  2.30),
        Setup("NXXT",  0.60,  0.70,  0.95,  1.50),
    ],
    date(2026, 5, 21): [
        Setup("CODX",  2.55,  2.75,  3.30,  4.00),
        Setup("VIDA",  4.33,  4.82,  5.50,  6.00),
        Setup("LPG",   46.60, 48.12, 55.00, 60.00),
        Setup("NCPL",  0.62,  0.68,  0.80,  1.00),
        Setup("UCAR",  1.85,  2.00,  2.40,  2.80),
        Setup("STFS",  15.00, 17.54, 20.00, 22.00),
        Setup("LIMN",  0.25,  0.29,  0.50,  0.60),
        Setup("MTVA",  3.00,  3.31,  4.00,  4.40),
        Setup("AMPG",  4.75,  4.88,  6.00,  7.00),
        Setup("PRFX",  2.20,  2.50,  2.80,  3.00),
        Setup("PSNL",  7.70,  8.10,  10.00, 11.50),
        Setup("BNZI",  5.50,  5.87,  7.50,  10.00),
        Setup("GIPR",  0.55,  0.59,  0.75,  1.00),
        Setup("PHGE",  0.74,  0.80,  1.00,  1.50),
    ],
    date(2026, 5, 22): [
        Setup("ATPC",  3.65,  4.00,  5.00,  6.00),
        Setup("GOVX",  2.50,  2.65,  3.50,  4.00),
        Setup("ARQQ",  16.70, 17.40, 20.00, 25.00),
        Setup("AKTX",  13.00, 15.73, 18.00, 20.00),
        Setup("PCLA",  3.25,  4.00,  5.00,  8.00),
        Setup("EDHL",  3.50,  4.00,  5.00,  5.50),
        Setup("LFS",   3.00,  3.36,  4.00,  4.40),
        Setup("AMPG",  5.40,  5.60,  6.50,  7.00),
        Setup("NCPL",  0.90,  0.96,  1.10,  1.25),
        Setup("NIVF",  0.97,  1.20,  1.60,  2.00),
        Setup("FCEL",  26.00, 27.00, 30.00, 33.00),
        Setup("INFQ",  15.00, 16.11, 18.00, 20.00),
        Setup("QUBT",  11.70, 12.13, 14.50, 16.50),
        Setup("WYFI",  31.50, 33.32, 40.00, 44.00),
        Setup("CODX",  3.50,  3.75,  4.10,  4.50),
        Setup("VIDA",  4.50,  5.07,  5.79,  6.50),
        Setup("PHGE",  0.65,  0.70,  0.80,  0.90),
        Setup("MTVA",  3.00,  3.31,  4.50,  5.50),
    ],
    date(2026, 5, 26): [
        Setup("VCIG",  1.50,  1.69,  2.00,  2.20),
        Setup("ARTL",  2.00,  2.10,  2.50,  3.30),
        Setup("PHGE",  1.10,  1.20,  1.50,  2.00),
        Setup("FEMY",  0.57,  0.62,  0.80,  0.90),
        Setup("GOVX",  3.70,  4.00,  5.00,  5.50),
        Setup("PCLA",  6.60,  7.50,  10.00, 11.50),
    ],
    date(2026, 5, 27): [
        Setup("CPSH",  11.30, 12.00, 15.00, 20.00),
        Setup("MNTS",  19.00, 20.00, 22.00, 25.00),
        Setup("GRRR",  16.20, 16.95, 20.00, 22.00),
        Setup("SNGX",  0.92,  0.98,  1.10,  1.50),
        Setup("VCIG",  3.80,  4.75,  6.00,  7.50),
        Setup("QUCY",  1.05,  1.20,  2.00,  2.60),
        Setup("DXF",   2.10,  2.38,  3.00,  3.40),
        Setup("AIIO",  2.60,  2.79,  3.60,  4.50),
        Setup("INBS",  3.80,  4.09,  5.03,  5.54),
        Setup("NCPL",  1.40,  1.59,  2.00,  2.20),
        Setup("CODX",  10.00, 10.80, 13.00, 15.00),
        Setup("VELO",  21.00, 21.60, 23.84, 30.00),
        Setup("RDW",   24.00, 24.97, 30.00, 33.00),
        Setup("NRGV",  6.00,  6.30,  7.00,  7.50),
        Setup("BESS",  3.30,  3.55,  4.50,  5.50),
        Setup("CMPS",  10.60, 11.08, 13.00, 15.00),
        Setup("FCHL",  2.30,  2.40,  2.80,  3.10),
        Setup("GUTS",  0.94,  0.99,  1.10,  1.20),
        Setup("FCEL",  19.80, 21.00, 25.00, 30.00),
        Setup("AMBQ",  69.00, 72.50, 80.00, 85.00),
        Setup("MSGY",  0.58,  0.66,  0.73,  0.80),
        Setup("QTEX",  1.55,  1.60,  2.20,  2.50),
        Setup("UZX",   1.00,  1.16,  1.65,  2.00),
        Setup("AEHL",  5.88,  6.35,  7.00,  7.50),
    ],
    date(2026, 5, 28): [
        Setup("SNGX",  0.80,  1.00,  1.10,  1.30),
        Setup("ASTC",  10.80, 13.00, 15.00, 24.00),
        Setup("NCPL",  1.47,  1.60,  1.80,  2.00),
        Setup("HOTH",  1.60,  1.75,  2.10,  2.60),
        Setup("IMRN",  1.75,  1.91,  2.20,  3.00),
        Setup("ATPC",  7.10,  8.30,  12.50, 15.00),
        Setup("QTTB",  13.00, 14.40, 20.00, 22.00),
        Setup("NTCL",  0.66,  0.76,  0.85,  1.00),
        Setup("ASTI",  7.10,  7.40,  9.00,  10.00),
        Setup("SUUN",  1.20,  1.28,  1.50,  2.00),
        Setup("EDIT",  3.75,  3.94,  4.50,  5.00),
        Setup("CRSR",  12.50, 13.00, 15.00, 18.00),
        Setup("FGL",   2.50,  2.80,  3.10,  3.50),
        Setup("BRTX",  0.40,  0.46,  0.55,  0.68),
        Setup("VCIG",  3.90,  4.40,  5.00,  6.00),
        Setup("SNOW",  230.00,240.00,280.00,300.00),
    ],
    date(2026, 5, 29): [
        Setup("IOTR",  3.30,  3.90,  5.00,  5.50),
        Setup("PRFX",  4.50,  6.30,  10.00, 13.00),
        Setup("SPRC",  14.00, 15.65, 18.00, 20.00),
        Setup("ASTC",  36.00, 43.05, 50.00, 55.00),
        Setup("UMAC",  31.50, 33.46, 40.00, 44.00),
        Setup("NEXR",  2.10,  2.47,  3.40,  4.40),
        Setup("CODX",  12.80, 13.54, 15.00, 20.00),
        Setup("MX",    7.00,  7.15,  8.00,  8.50),
        Setup("AVEX",  40.00, 41.16, 50.00, 55.00),
        Setup("GMEX",  2.00,  2.10,  2.40,  3.33),
        Setup("SWMR",  56.00, 60.00, 69.00, 75.00),
        Setup("BRR",   2.30,  2.43,  3.00,  3.70),
        Setup("ONDL",  26.00, 27.47, 33.00, 36.00),
        Setup("APPS",  8.45,  8.91,  10.00, 12.00),
        Setup("AIRO",  8.90,  9.60,  10.70, 13.00),
        Setup("ZENA",  1.68,  1.77,  2.00,  2.50),
        Setup("GCDT",  1.35,  1.68,  2.00,  2.20),
        Setup("ATPC",  7.30,  8.50,  9.50,  11.00),
        Setup("RCAT",  14.00, 15.06, 16.50, 18.50),
    ],
    date(2026, 6, 1): [
        Setup("HUBC",  0.35,  0.40,  0.50,  0.60),
        Setup("ASTC",  48.00, 52.00, 60.00, 70.00),
        Setup("NAMM",  2.35,  2.49,  3.00,  4.40),
        Setup("MX",    9.30,  9.78,  11.00, 13.00),
        Setup("OLOX",  8.00,  8.70,  11.00, 12.50),
        Setup("ZENA",  1.60,  1.80,  2.00,  2.50),
        Setup("SPRC",  9.00,  10.00, 11.30, 14.00),
        Setup("UMAC",  31.00, 33.00, 40.00, 44.00),
        Setup("MASK",  3.80,  4.20,  6.75,  8.40),
        Setup("MNTS",  18.30, 20.30, 35.00, 43.50),
    ],
    date(2026, 6, 2): [
        Setup("ABTS",  1.85,  2.30,  3.30,  4.40),
        Setup("ANY",   4.80,  5.30,  6.00,  7.00),
        Setup("DBGI",  1.10,  1.30,  1.60,  2.20),
        Setup("VSA",   7.60,  8.00,  9.00,  13.00),
        Setup("DXST",  2.50,  2.91,  4.00,  5.00),
        Setup("CTNT",  3.00,  3.30,  4.00,  4.40),
        Setup("SOAR",  0.36,  0.43,  0.50,  0.70),
        Setup("ZNB",   2.90,  3.16,  3.40,  4.00),
        Setup("LFVN",  10.80, 11.00, 15.00, 20.00),
        Setup("AMZE",  0.20,  0.22,  0.25,  0.30),
        Setup("FLNC",  27.50, 29.00, 33.50, 40.00),
        Setup("HUBC",  0.50,  0.55,  0.65,  1.00),
        Setup("HKIT",  3.80,  5.00,  9.80,  16.00),
    ],
}


# ---------------------------------------------------------------------------
# Backtest één dag
# ---------------------------------------------------------------------------

def run_day(
    watchlist: List[Setup],
    data: Dict[str, Optional[pd.DataFrame]],
    capital: float,
    orb_minutes: int = 0,
    *,
    t2_runner: bool = True,
) -> tuple[float, List[TradeResult]]:
    """
    Simuleert één handelsdag met één cash pool.
    orb_minutes=0  → scenario A: direct traden, geen ORB filter
    orb_minutes=15 → scenario C: eerste 15 bars opbouwen, daarna volume filter
    Geeft (eind_cash, trades) terug.
    """
    cash = capital

    # ORB avg volume per ticker (eerste orb_minutes candles, of 5 als orb=0 voor compat)
    orb_window = orb_minutes if orb_minutes > 0 else 0
    orb_avg_vol: Dict[str, Optional[float]] = {}
    for setup in watchlist:
        df = data.get(setup.ticker)
        if orb_window > 0 and df is not None and len(df) >= orb_window:
            orb_avg_vol[setup.ticker] = float(df.iloc[:orb_window]["Volume"].mean())
        else:
            orb_avg_vol[setup.ticker] = None

    # Chronologische tijdlijn
    all_rows = []
    for setup in watchlist:
        df = data.get(setup.ticker)
        if df is None:
            continue
        for ts, row in df.iterrows():
            all_rows.append((ts, setup.ticker, row))
    all_rows.sort(key=lambda x: x[0])

    positions: Dict[str, dict] = {}
    closed:    Dict[str, TradeResult] = {}
    setup_map = {s.ticker: s for s in watchlist}
    bar_count: Dict[str, int] = {}

    # Vooraf: skip te dure en no-data tickers
    skipped = set()
    for setup in watchlist:
        if data.get(setup.ticker) is None:
            skipped.add(setup.ticker)
        elif int(capital // setup.break_) < 1:
            skipped.add(setup.ticker)

    for ts, ticker, row in all_rows:
        if ticker in closed or ticker in skipped:
            continue

        bar_count[ticker] = bar_count.get(ticker, 0) + 1

        setup  = setup_map[ticker]
        high   = float(row["High"])
        low    = float(row["Low"])
        volume = float(row["Volume"])
        avg_v  = orb_avg_vol.get(ticker)

        # ORB window: geen trades tijdens de eerste orb_minutes bars
        if orb_window > 0 and bar_count[ticker] <= orb_window:
            continue

        vol_ok = (avg_v is None or avg_v == 0) or (volume >= 2 * avg_v)

        if ticker not in positions:
            shares = int(cash // setup.break_)
            if shares < 1:
                continue
            if high >= setup.break_ and vol_ok:
                spend = shares * setup.break_
                cash -= spend
                vol_mult = (volume / avg_v) if avg_v and avg_v > 0 else None
                positions[ticker] = {
                    "entry_price": setup.break_,
                    "entry_time":  ts.strftime("%H:%M"),
                    "shares":      shares,
                    "spend":       spend,
                    "vol_mult":    vol_mult,
                    "stop":        setup.hold,
                    "target":      setup.t1,
                    "t2":          setup.t2,
                }
        else:
            pos = positions[ticker]

            def close(exit_price: float, reason: str) -> None:
                nonlocal cash
                pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                cash += exit_price * pos["shares"]
                pnl_pct = pnl / pos["spend"] * 100
                vm = pos["vol_mult"]
                closed[ticker] = TradeResult(
                    ticker=ticker,
                    entry_price=pos["entry_price"],
                    entry_time=pos["entry_time"],
                    exit_price=exit_price,
                    exit_time=ts.strftime("%H:%M"),
                    exit_reason=reason,
                    shares=pos["shares"],
                    spend=pos["spend"],
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 1),
                    breakout_vol_mult=round(vm, 1) if vm else None,
                )
                del positions[ticker]

            if low <= pos["stop"]:
                if t2_runner:
                    reason = "T1" if pos["t2"] > pos["entry_price"] and pos["stop"] >= pos["entry_price"] else "STOP"
                else:
                    reason = "STOP"
                close(pos["stop"], reason)
            elif high >= pos["target"]:
                if t2_runner and pos["t2"] > pos["target"]:
                    pos["stop"] = pos["target"]
                    pos["target"] = pos["t2"]
                    if high >= pos["t2"]:
                        close(pos["t2"], "T2")
                else:
                    if t2_runner:
                        runner_t2 = (
                            pos["t2"] > pos["entry_price"]
                            and pos["target"] >= pos["t2"]
                            and pos["stop"] >= pos["entry_price"]
                        )
                        reason = "T2" if runner_t2 else "T1"
                    else:
                        reason = "T1"
                    close(pos["target"], reason)

    # EOD
    for ticker, pos in list(positions.items()):
        df = data.get(ticker)
        if df is not None and not df.empty:
            exit_price = float(df.iloc[-1]["Close"])
            pnl = (exit_price - pos["entry_price"]) * pos["shares"]
            cash += exit_price * pos["shares"]
            pnl_pct = pnl / pos["spend"] * 100
            vm = pos["vol_mult"]
            closed[ticker] = TradeResult(
                ticker=ticker,
                entry_price=pos["entry_price"],
                entry_time=pos["entry_time"],
                exit_price=exit_price,
                exit_time="15:59",
                exit_reason="EOD",
                shares=pos["shares"],
                spend=pos["spend"],
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 1),
                breakout_vol_mult=round(vm, 1) if vm else None,
            )

    results = list(closed.values())
    return cash, results


# ---------------------------------------------------------------------------
# Vergelijking T1-only vs T2-runner
# ---------------------------------------------------------------------------

def _run_multi(
    capital: float,
    orb_minutes: int,
    *,
    t2_runner: bool,
) -> tuple[float, List[TradeResult], list]:
    dates = sorted(WATCHLISTS.keys())
    cash = capital
    all_trades: List[TradeResult] = []
    day_results = []

    for trade_date in dates:
        watchlist = WATCHLISTS[trade_date]
        tickers = list({s.ticker for s in watchlist})
        data: Dict[str, Optional[pd.DataFrame]] = {}
        for ticker in tickers:
            data[ticker] = fetch_1m(ticker, trade_date)

        day_capital = cash
        end_cash, trades = run_day(
            watchlist, data, day_capital,
            orb_minutes=orb_minutes,
            t2_runner=t2_runner,
        )
        day_pnl = end_cash - day_capital
        all_trades.extend(trades)
        cash = end_cash
        wins = [t for t in trades if t.exit_reason in ("T1", "T2")]
        stops = [t for t in trades if t.exit_reason == "STOP"]
        t2s = [t for t in trades if t.exit_reason == "T2"]
        day_results.append((trade_date, day_capital, end_cash, day_pnl, len(trades), len(wins), len(stops), len(t2s)))
    return cash, all_trades, day_results


def _run_compare(capital: float, orb_minutes: int) -> None:
    dates = sorted(WATCHLISTS.keys())
    print(f"\nMulti-day vergelijking | {dates[0]} -> {dates[-1]} | {len(dates)} dagen")
    print(f"Startkapitaal: ${capital:.2f} | ORB: {orb_minutes}min | COMPOUND\n")

    results = {}
    for label, t2_runner in [("T1-only (oud)", False), ("T2-runner (nieuw)", True)]:
        end_cash, trades, day_results = _run_multi(capital, orb_minutes, t2_runner=t2_runner)
        wins = [t for t in trades if t.exit_reason in ("T1", "T2")]
        t2s = [t for t in trades if t.exit_reason == "T2"]
        stops = [t for t in trades if t.exit_reason == "STOP"]
        ret = (end_cash - capital) / capital * 100
        results[label] = {
            "end_cash": end_cash,
            "trades": len(trades),
            "wins": len(wins),
            "t2s": len(t2s),
            "stops": len(stops),
            "ret": ret,
            "day_results": day_results,
        }
        print(f"--- {label} ---")
        for row in day_results:
            td, cap, end, pnl, n, w, s, t2 = row
            print(f"  {td}  cap=${cap:>7.2f}  eind=${end:>7.2f}  pnl=${pnl:>+7.2f}  trades={n:>2}  [{w}W/{t2}T2/{s}S]")
        print()

    print(f"{'='*65}")
    print(f"  {'Scenario':<22}  {'Eind':>8}  {'Return':>8}  {'Trades':>7}  {'T2':>4}  {'Stops':>6}")
    print(f"  {'-'*60}")
    for label, r in results.items():
        print(
            f"  {label:<22}  ${r['end_cash']:>7.2f}  {r['ret']:>+7.1f}%  "
            f"{r['trades']:>7}  {r['t2s']:>4}  {r['stops']:>6}"
        )
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=float, default=50.0)
    parser.add_argument("--orb", type=int, default=0, help="ORB minuten (0=geen, 15=scenario C)")
    parser.add_argument("--no-t2-runner", action="store_true", help="Sluit bij T1 (geen runner naar T2)")
    parser.add_argument("--compare-t2", action="store_true", help="Vergelijk T1-only vs T2-runner")
    args = parser.parse_args()

    if args.compare_t2:
        _run_compare(args.capital, args.orb)
        return

    dates = sorted(WATCHLISTS.keys())
    mode = "T1-only" if args.no_t2_runner else "T2-runner"
    print(f"\nMulti-day backtest | {dates[0]} -> {dates[-1]} | {len(dates)} handelsdagen")
    print(f"Startkapitaal: ${args.capital:.2f} | Mode: COMPOUND | ORB: {args.orb}min | Exit: {mode}\n")

    capital        = args.capital
    total_pnl      = 0.0
    all_trades:    List[TradeResult] = []
    day_results    = []

    for trade_date in dates:
        watchlist = WATCHLISTS[trade_date]
        tickers   = list({s.ticker for s in watchlist})

        # Data ophalen
        data: Dict[str, Optional[pd.DataFrame]] = {}
        for ticker in tickers:
            data[ticker] = fetch_1m(ticker, trade_date)

        day_capital = capital
        end_cash, trades = run_day(
            watchlist, data, day_capital,
            orb_minutes=args.orb,
            t2_runner=not args.no_t2_runner,
        )

        day_pnl = end_cash - day_capital
        total_pnl += day_pnl
        all_trades.extend(trades)

        capital = end_cash

        wins   = [t for t in trades if t.exit_reason in ("T1", "T2")]
        stops  = [t for t in trades if t.exit_reason == "STOP"]
        eods   = [t for t in trades if t.exit_reason == "EOD"]
        win_str = f"{len(wins)}W/{len(stops)}S/{len(eods)}EOD"
        day_results.append((trade_date, day_capital, end_cash, day_pnl, trades))

        print(
            f"  {trade_date}  cap=${day_capital:>7.2f}  "
            f"eind=${end_cash:>7.2f}  pnl=${day_pnl:>+7.2f}  "
            f"trades={len(trades):>2}  [{win_str}]"
        )

    # Samenvattting
    wins_all   = [t for t in all_trades if t.exit_reason in ("T1", "T2")]
    stops_all  = [t for t in all_trades if t.exit_reason == "STOP"]
    eods_all   = [t for t in all_trades if t.exit_reason == "EOD"]
    win_rate   = len(wins_all) / len(all_trades) * 100 if all_trades else 0
    gross_win  = sum(t.pnl for t in wins_all)
    gross_loss = sum(t.pnl for t in stops_all + eods_all if t.pnl < 0)
    pf         = gross_win / abs(gross_loss) if gross_loss != 0 else float("inf")

    # Best / worst days
    day_results.sort(key=lambda x: x[3])
    worst_day = day_results[0]
    best_day  = day_results[-1]

    # Beste tickers
    ticker_pnl: Dict[str, float] = {}
    for t in all_trades:
        ticker_pnl[t.ticker] = ticker_pnl.get(t.ticker, 0) + t.pnl
    top5 = sorted(ticker_pnl.items(), key=lambda x: -x[1])[:5]
    bot5 = sorted(ticker_pnl.items(), key=lambda x: x[1])[:5]

    start_cap = args.capital
    ret = (capital - args.capital) / args.capital * 100

    print(f"\n{'='*65}")
    print(f"  SAMENVATTING")
    print(f"{'='*65}")
    print(f"  Handelsdagen          : {len(dates)}")
    print(f"  Totaal trades         : {len(all_trades)}  ({len(wins_all)}W / {len(stops_all)}S / {len(eods_all)} EOD)")
    print(f"  Win rate              : {win_rate:.1f}%")
    print(f"  Profit factor         : {pf:.2f}")
    print(f"  Startkapitaal         : ${args.capital:.2f}")
    print(f"  Eindkapitaal          : ${capital:.2f}  ({ret:+.1f}%)")
    print(f"  Beste dag             : {best_day[0]}  ${best_day[3]:+.2f}")
    print(f"  Slechtste dag         : {worst_day[0]}  ${worst_day[3]:+.2f}")
    print(f"\n  Top 5 tickers (PnL):")
    for ticker, pnl in top5:
        cnt = sum(1 for t in all_trades if t.ticker == ticker)
        print(f"    {ticker:<8} ${pnl:>+8.2f}  ({cnt}x)")
    print(f"\n  Slechtste 5 tickers:")
    for ticker, pnl in bot5:
        cnt = sum(1 for t in all_trades if t.ticker == ticker)
        print(f"    {ticker:<8} ${pnl:>+8.2f}  ({cnt}x)")
    print()


if __name__ == "__main__":
    main()
