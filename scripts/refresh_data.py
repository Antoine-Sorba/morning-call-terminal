"""Refresh every official adapter once.

Run this from the project root manually or from cron/Task Scheduler. The same
raw-response cache is then available to the Streamlit application.
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from ficc_terminal.cache import OfficialHttpClient
from ficc_terminal.official_sources import (
    fetch_bls_macro,
    fetch_boe_nominal_curve,
    fetch_cftc_positioning,
    fetch_ecb_fx,
    fetch_ecb_yield_curve,
    fetch_eia_energy,
    fetch_sofr,
    fetch_us_treasury_curve,
)


def main() -> None:
    load_dotenv()
    client = OfficialHttpClient("data/raw")
    loaders = [
        fetch_us_treasury_curve,
        fetch_sofr,
        fetch_ecb_fx,
        fetch_ecb_yield_curve,
        fetch_boe_nominal_curve,
        fetch_cftc_positioning,
        fetch_bls_macro,
    ]
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(loader, client) for loader in loaders]
        futures.append(executor.submit(fetch_eia_energy, client, os.getenv("EIA_API_KEY")))
        for future in as_completed(futures):
            dataset = future.result()
            print(f"{dataset.key:20} {dataset.status_label():24} {dataset.latest_date}")


if __name__ == "__main__":
    main()
