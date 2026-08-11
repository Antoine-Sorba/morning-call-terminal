from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import date, datetime, timezone
from typing import Iterable
from xml.etree import ElementTree as ET

import feedparser
import pandas as pd

from .cache import OfficialHttpClient
from .models import MarketDataset, SourceMetadata, unavailable_dataset


TREASURY_PAGE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "TextView?type=daily_treasury_yield_curve"
)
NYFED_SOFR_PAGE = "https://www.newyorkfed.org/markets/reference-rates/sofr"
ECB_FX_PAGE = (
    "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/"
    "euro_reference_exchange_rates/html/index.en.html"
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def _with_payload_time(metadata: SourceMetadata, retrieved_at: str) -> SourceMetadata:
    return SourceMetadata(
        source_name=metadata.source_name,
        series_name=metadata.series_name,
        source_url=metadata.source_url,
        frequency=metadata.frequency,
        unit=metadata.unit,
        delay=metadata.delay,
        transformation=metadata.transformation,
        licence_note=metadata.licence_note,
        observation_time=metadata.observation_time,
        retrieved_at=retrieved_at,
    )


def parse_treasury_xml(content: bytes | str) -> pd.DataFrame:
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    root = ET.fromstring(content)
    maturity_fields = {
        "BC_1MONTH": "1M",
        "BC_2MONTH": "2M",
        "BC_3MONTH": "3M",
        "BC_4MONTH": "4M",
        "BC_6MONTH": "6M",
        "BC_1YEAR": "1Y",
        "BC_2YEAR": "2Y",
        "BC_3YEAR": "3Y",
        "BC_5YEAR": "5Y",
        "BC_7YEAR": "7Y",
        "BC_10YEAR": "10Y",
        "BC_20YEAR": "20Y",
        "BC_30YEAR": "30Y",
    }
    records: list[dict[str, object]] = []
    for entry in root.iter():
        if _local_name(entry.tag).lower() != "entry":
            continue
        fields: dict[str, str] = {}
        for node in entry.iter():
            name = _local_name(node.tag).upper()
            if node.text and node.text.strip():
                fields[name] = node.text.strip()
        raw_date = fields.get("NEW_DATE") or fields.get("UPDATED") or fields.get("TITLE")
        if not raw_date:
            continue
        parsed_date = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(parsed_date):
            continue
        for field, maturity in maturity_fields.items():
            value = pd.to_numeric(fields.get(field), errors="coerce")
            if pd.notna(value):
                records.append(
                    {"date": parsed_date.tz_localize(None), "instrument": maturity, "value": float(value)}
                )
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("Treasury XML contained no recognised yield observations")
    return frame.sort_values(["date", "instrument"]).reset_index(drop=True)


def fetch_us_treasury_curve(client: OfficialHttpClient, year: int | None = None) -> MarketDataset:
    year = year or datetime.now(timezone.utc).year
    metadata = SourceMetadata(
        source_name="U.S. Department of the Treasury",
        series_name="Daily Treasury Par Yield Curve Rates",
        source_url=TREASURY_PAGE,
        frequency="Daily business-day close",
        unit="Percent",
        delay="Indicative close around 15:30 New York; not an intraday executable price",
        transformation="XML converted to long format; daily moves calculated in basis points",
        licence_note="Official U.S. government data. Cite the U.S. Treasury.",
    )
    try:
        payload = client.get(
            f"ust_nominal_curve_{year}",
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml",
            params={"data": "daily_treasury_yield_curve", "field_tdr_date_value": str(year)},
        )
        frame = parse_treasury_xml(payload.content)
        return MarketDataset(
            key="ust_curve",
            frame=frame,
            metadata=_with_payload_time(metadata, payload.retrieved_at),
            stale=payload.stale,
            from_cache=payload.from_cache,
            raw_reference=payload.cache_path,
        )
    except Exception as error:  # the UI must remain usable when an institution is down
        return unavailable_dataset("ust_curve", metadata, error)


def parse_nyfed_reference_rates(content: bytes | str) -> pd.DataFrame:
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    payload = json.loads(content)
    rows = payload.get("refRates") or payload.get("referenceRates") or payload.get("data") or []
    records = []
    for row in rows:
        raw_date = row.get("effectiveDate") or row.get("effective_date") or row.get("date")
        raw_value = row.get("percentRate") or row.get("percent_rate") or row.get("rate")
        parsed_date = pd.to_datetime(raw_date, errors="coerce")
        parsed_value = pd.to_numeric(raw_value, errors="coerce")
        if pd.notna(parsed_date) and pd.notna(parsed_value):
            records.append({"date": parsed_date, "instrument": "SOFR", "value": float(parsed_value)})
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("New York Fed response contained no recognised reference rates")
    return frame.sort_values("date").reset_index(drop=True)


def fetch_sofr(client: OfficialHttpClient, observations: int = 90) -> MarketDataset:
    metadata = SourceMetadata(
        source_name="Federal Reserve Bank of New York",
        series_name="Secured Overnight Financing Rate",
        source_url=NYFED_SOFR_PAGE,
        frequency="Daily business days",
        unit="Percent",
        delay="Published around 08:00 New York on the following business day",
        transformation="Daily change calculated in basis points",
        licence_note="Use is subject to New York Fed reference-rate terms and disclaimers.",
    )
    try:
        payload = client.get(
            "nyfed_sofr",
            f"https://markets.newyorkfed.org/api/rates/secured/sofr/last/{observations}.json",
        )
        return MarketDataset(
            key="sofr",
            frame=parse_nyfed_reference_rates(payload.content),
            metadata=_with_payload_time(metadata, payload.retrieved_at),
            stale=payload.stale,
            from_cache=payload.from_cache,
            raw_reference=payload.cache_path,
        )
    except Exception as error:
        return unavailable_dataset("sofr", metadata, error)


def parse_ecb_fx_xml(content: bytes | str) -> pd.DataFrame:
    if isinstance(content, str):
        content = content.encode("utf-8")
    root = ET.fromstring(content)
    records: list[dict[str, object]] = []
    for node in root.iter():
        raw_date = node.attrib.get("time")
        if not raw_date:
            continue
        parsed_date = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(parsed_date):
            continue
        for child in node:
            currency = child.attrib.get("currency")
            raw_rate = child.attrib.get("rate")
            value = pd.to_numeric(raw_rate, errors="coerce")
            if currency and pd.notna(value):
                records.append(
                    {"date": parsed_date, "instrument": f"EUR/{currency}", "value": float(value)}
                )
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("ECB FX XML contained no recognised rates")
    return frame.sort_values(["date", "instrument"]).reset_index(drop=True)


def derive_fx_crosses(frame: pd.DataFrame) -> pd.DataFrame:
    pivot = frame.pivot_table(index="date", columns="instrument", values="value", aggfunc="last")
    derived = pd.DataFrame(index=pivot.index)
    if "EUR/USD" in pivot:
        derived["EUR/USD"] = pivot["EUR/USD"]
    if {"EUR/USD", "EUR/GBP"}.issubset(pivot.columns):
        derived["GBP/USD"] = pivot["EUR/USD"] / pivot["EUR/GBP"]
        derived["EUR/GBP"] = pivot["EUR/GBP"]
    if {"EUR/JPY", "EUR/USD"}.issubset(pivot.columns):
        derived["USD/JPY"] = pivot["EUR/JPY"] / pivot["EUR/USD"]
    if {"EUR/CHF", "EUR/USD"}.issubset(pivot.columns):
        derived["USD/CHF"] = pivot["EUR/CHF"] / pivot["EUR/USD"]
    if {"EUR/CNY", "EUR/USD"}.issubset(pivot.columns):
        derived["USD/CNY"] = pivot["EUR/CNY"] / pivot["EUR/USD"]
    return derived.reset_index().melt(id_vars="date", var_name="instrument", value_name="value").dropna()


def fetch_ecb_fx(client: OfficialHttpClient) -> MarketDataset:
    metadata = SourceMetadata(
        source_name="European Central Bank",
        series_name="Euro foreign-exchange reference rates and derived crosses",
        source_url=ECB_FX_PAGE,
        frequency="Daily business days",
        unit="Currency units per base currency",
        delay="Reference rates usually published around 16:00 Central European time",
        transformation="GBP/USD, USD/JPY, USD/CHF and USD/CNY derived from EUR reference rates",
        licence_note="ECB attribution required; rates are for information, not transaction execution.",
    )
    try:
        payload = client.get(
            "ecb_fx_90d",
            "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml",
        )
        frame = derive_fx_crosses(parse_ecb_fx_xml(payload.content))
        return MarketDataset(
            key="ecb_fx",
            frame=frame,
            metadata=_with_payload_time(metadata, payload.retrieved_at),
            stale=payload.stale,
            from_cache=payload.from_cache,
            raw_reference=payload.cache_path,
        )
    except Exception as error:
        return unavailable_dataset("ecb_fx", metadata, error)


def _parse_ecb_csv(content: bytes, instrument: str) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(content))
    date_column = next((column for column in frame.columns if column.upper() == "TIME_PERIOD"), None)
    value_column = next((column for column in frame.columns if column.upper() == "OBS_VALUE"), None)
    if date_column is None or value_column is None:
        raise ValueError("ECB CSV did not contain TIME_PERIOD and OBS_VALUE")
    result = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce"),
            "instrument": instrument,
            "value": pd.to_numeric(frame[value_column], errors="coerce"),
        }
    ).dropna()
    return result.drop_duplicates(["date", "instrument"], keep="last")


def fetch_ecb_yield_curve(client: OfficialHttpClient, start_year: int | None = None) -> MarketDataset:
    start_year = start_year or datetime.now(timezone.utc).year - 2
    metadata = SourceMetadata(
        source_name="European Central Bank",
        series_name="Euro-area central government AAA nominal spot curve",
        source_url="https://data.ecb.europa.eu/data/datasets/YC",
        frequency="Daily business days",
        unit="Percent",
        delay="End-of-day official curve",
        transformation="Selected 2Y, 5Y, 10Y and 30Y maturities combined; changes in basis points",
        licence_note="ECB attribution required; disclose all transformations.",
    )
    try:
        frames = []
        retrieval_times = []
        stale = False
        from_cache = False
        raw_paths = []
        for maturity in ("2Y", "5Y", "10Y", "30Y"):
            key = f"B.U2.EUR.4F.G_N_A.SV_C_YM.SR_{maturity}"
            payload = client.get(
                f"ecb_yc_{maturity.lower()}",
                f"https://data-api.ecb.europa.eu/service/data/YC/{key}",
                params={"startPeriod": f"{start_year}-01-01", "format": "csvdata"},
                headers={"Accept": "text/csv"},
            )
            frames.append(_parse_ecb_csv(payload.content, maturity))
            retrieval_times.append(payload.retrieved_at)
            stale = stale or payload.stale
            from_cache = from_cache or payload.from_cache
            raw_paths.append(payload.cache_path)
        return MarketDataset(
            key="ecb_curve",
            frame=pd.concat(frames, ignore_index=True).sort_values(["date", "instrument"]),
            metadata=_with_payload_time(metadata, max(retrieval_times)),
            stale=stale,
            from_cache=from_cache,
            raw_reference=";".join(raw_paths),
        )
    except Exception as error:
        return unavailable_dataset("ecb_curve", metadata, error)


def _parse_boe_curve_zip(content: bytes) -> pd.DataFrame:
    records = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        csv_files = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        xlsx_files = [name for name in archive.namelist() if name.lower().endswith(".xlsx")]
        if not csv_files and xlsx_files:
            latest_name = next(
                (name for name in xlsx_files if "present" in name.lower()),
                sorted(xlsx_files)[-1],
            )
            workbook = io.BytesIO(archive.read(latest_name))
            table = pd.read_excel(workbook, sheet_name="4. spot curve", header=None)
            maturities = pd.to_numeric(table.iloc[3, 1:], errors="coerce")
            dates = pd.to_datetime(table.iloc[5:, 0], errors="coerce")
            for column_index, maturity in maturities.items():
                if pd.isna(maturity):
                    continue
                values = pd.to_numeric(table.iloc[5:, column_index], errors="coerce")
                valid = dates.notna() & values.notna()
                instrument = f"{float(maturity):g}Y"
                records.extend(
                    {"date": row_date, "instrument": instrument, "value": float(row_value)}
                    for row_date, row_value in zip(dates[valid], values[valid])
                )
        if not csv_files and not records:
            raise ValueError("Bank of England archive contained no supported curve file")
        for name in csv_files:
            raw = archive.read(name)
            for header_row in range(0, 12):
                try:
                    frame = pd.read_csv(io.BytesIO(raw), skiprows=header_row)
                except Exception:
                    continue
                date_column = next(
                    (column for column in frame.columns if "date" in str(column).lower()), None
                )
                if date_column is None:
                    continue
                dates = pd.to_datetime(frame[date_column], errors="coerce", dayfirst=True)
                for column in frame.columns:
                    if column == date_column:
                        continue
                    maturity = str(column).strip().replace(" years", "Y").replace(" year", "Y")
                    values = pd.to_numeric(frame[column], errors="coerce")
                    valid = dates.notna() & values.notna()
                    records.extend(
                        {"date": row_date, "instrument": maturity, "value": float(row_value)}
                        for row_date, row_value in zip(dates[valid], values[valid])
                    )
                if records:
                    break
            if records:
                break
    result = pd.DataFrame(records)
    if result.empty:
        raise ValueError("Could not recognise the Bank of England curve file layout")
    return result.sort_values(["date", "instrument"]).reset_index(drop=True)


def fetch_boe_nominal_curve(client: OfficialHttpClient) -> MarketDataset:
    metadata = SourceMetadata(
        source_name="Bank of England",
        series_name="UK nominal government liability curve",
        source_url="https://www.bankofengland.co.uk/statistics/yield-curves",
        frequency="Daily business days",
        unit="Percent",
        delay="Normally published by noon on the following business day",
        transformation="Official curve archive normalised to date, maturity and value",
        licence_note="Use BoE-owned data under its terms; check series-specific third-party rights.",
    )
    try:
        payload = client.get(
            "boe_nominal_curve",
            "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/glcnominalddata.zip",
        )
        return MarketDataset(
            key="boe_curve",
            frame=_parse_boe_curve_zip(payload.content),
            metadata=_with_payload_time(metadata, payload.retrieved_at),
            stale=payload.stale,
            from_cache=payload.from_cache,
            raw_reference=payload.cache_path,
        )
    except Exception as error:
        return unavailable_dataset("boe_curve", metadata, error)


def fetch_eia_energy(client: OfficialHttpClient, api_key: str | None = None) -> MarketDataset:
    api_key = api_key or os.getenv("EIA_API_KEY")
    metadata = SourceMetadata(
        source_name="U.S. Energy Information Administration",
        series_name="WTI and Brent spot-price series",
        source_url="https://www.eia.gov/opendata/",
        frequency="Daily business days",
        unit="U.S. dollars per barrel",
        delay="Official historical spot observations; not live futures prices",
        transformation="EIA series normalised and daily percentage changes calculated",
        licence_note="U.S. government data; acknowledge EIA and review third-party exceptions.",
    )
    if not api_key:
        return unavailable_dataset("eia_energy", metadata, "Add a free EIA_API_KEY to enable energy data")
    try:
        frames = []
        retrieval_times = []
        stale = False
        from_cache = False
        paths = []
        for instrument, series_id in {"WTI": "PET.RWTC.D", "Brent": "PET.RBRTE.D"}.items():
            payload = client.get(
                f"eia_{instrument.lower()}",
                f"https://api.eia.gov/v2/seriesid/{series_id}",
                params={"api_key": api_key, "length": 750},
            )
            parsed = json.loads(payload.content.decode("utf-8"))
            rows = parsed.get("response", {}).get("data", [])
            records = []
            for row in rows:
                raw_value = row.get("value")
                if raw_value is None:
                    candidates = [value for key, value in row.items() if key not in {"period", "seriesDescription", "unit"}]
                    raw_value = candidates[-1] if candidates else None
                parsed_date = pd.to_datetime(row.get("period"), errors="coerce")
                parsed_value = pd.to_numeric(raw_value, errors="coerce")
                if pd.notna(parsed_date) and pd.notna(parsed_value):
                    records.append({"date": parsed_date, "instrument": instrument, "value": float(parsed_value)})
            if records:
                frames.append(pd.DataFrame(records))
            retrieval_times.append(payload.retrieved_at)
            stale = stale or payload.stale
            from_cache = from_cache or payload.from_cache
            paths.append(payload.cache_path)
        if not frames:
            raise ValueError("EIA responses contained no recognised observations")
        return MarketDataset(
            key="eia_energy",
            frame=pd.concat(frames, ignore_index=True).sort_values(["date", "instrument"]),
            metadata=_with_payload_time(metadata, max(retrieval_times)),
            stale=stale,
            from_cache=from_cache,
            raw_reference=";".join(paths),
        )
    except Exception as error:
        return unavailable_dataset("eia_energy", metadata, error)


def _number_from_keys(row: dict, keys: Iterable[str]) -> float | None:
    for key in keys:
        if key in row:
            value = pd.to_numeric(row.get(key), errors="coerce")
            if pd.notna(value):
                return float(value)
    return None


def parse_cftc_disaggregated(content: bytes | str) -> pd.DataFrame:
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    rows = json.loads(content)
    records = []
    for row in rows:
        market = row.get("market_and_exchange_names") or row.get("market_and_exchange_name")
        report_date = pd.to_datetime(row.get("report_date_as_yyyy_mm_dd"), errors="coerce")
        long_value = _number_from_keys(row, ("m_money_positions_long_all", "money_manager_long_all"))
        short_value = _number_from_keys(row, ("m_money_positions_short_all", "money_manager_short_all"))
        open_interest = _number_from_keys(row, ("open_interest_all",))
        if market and pd.notna(report_date) and long_value is not None and short_value is not None:
            records.append(
                {
                    "date": report_date,
                    "instrument": market,
                    "value": long_value - short_value,
                    "long": long_value,
                    "short": short_value,
                    "open_interest": open_interest,
                }
            )
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("CFTC response contained no recognised managed-money positions")
    return frame.sort_values(["date", "instrument"]).reset_index(drop=True)


def fetch_cftc_positioning(client: OfficialHttpClient) -> MarketDataset:
    metadata = SourceMetadata(
        source_name="Commodity Futures Trading Commission",
        series_name="Disaggregated COT: managed-money net positions",
        source_url="https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
        frequency="Weekly",
        unit="Contracts",
        delay="Tuesday positions normally released Friday",
        transformation="Managed-money long minus short positions",
        licence_note="Official U.S. government public reporting data.",
    )
    try:
        payload = client.get(
            "cftc_disaggregated",
            "https://publicreporting.cftc.gov/resource/72hh-3qpy.json",
            params={"$limit": 5000, "$order": "report_date_as_yyyy_mm_dd DESC"},
        )
        return MarketDataset(
            key="cftc_positions",
            frame=parse_cftc_disaggregated(payload.content),
            metadata=_with_payload_time(metadata, payload.retrieved_at),
            stale=payload.stale,
            from_cache=payload.from_cache,
            raw_reference=payload.cache_path,
        )
    except Exception as error:
        return unavailable_dataset("cftc_positions", metadata, error)


def parse_bls_response(content: bytes | str, labels: dict[str, str]) -> pd.DataFrame:
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    payload = json.loads(content)
    series = payload.get("Results", {}).get("series", [])
    records = []
    for item in series:
        series_id = item.get("seriesID")
        label = labels.get(series_id, series_id)
        for row in item.get("data", []):
            period = row.get("period", "")
            if not period.startswith("M") or period == "M13":
                continue
            parsed_date = pd.to_datetime(f"{row.get('year')}-{period[1:]}-01", errors="coerce")
            parsed_value = pd.to_numeric(row.get("value"), errors="coerce")
            if pd.notna(parsed_date) and pd.notna(parsed_value):
                records.append({"date": parsed_date, "instrument": label, "value": float(parsed_value)})
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError("BLS response contained no recognised observations")
    return frame.sort_values(["date", "instrument"]).reset_index(drop=True)


def fetch_bls_macro(client: OfficialHttpClient) -> MarketDataset:
    labels = {
        "CUUR0000SA0": "US CPI index",
        "LNS14000000": "US unemployment rate",
        "CES0000000001": "US nonfarm payrolls (thousands)",
    }
    current_year = date.today().year
    metadata = SourceMetadata(
        source_name="U.S. Bureau of Labor Statistics",
        series_name="CPI, unemployment and nonfarm payrolls",
        source_url="https://www.bls.gov/developers/home.htm",
        frequency="Monthly",
        unit="Index / percent / thousands; see series label",
        delay="Official release schedule",
        transformation="BLS observations converted to dated time series",
        licence_note="Official U.S. government statistics. Cite BLS.",
    )
    try:
        payload = client.post_json(
            "bls_macro",
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            {
                "seriesid": list(labels),
                "startyear": str(current_year - 3),
                "endyear": str(current_year),
            },
        )
        return MarketDataset(
            key="bls_macro",
            frame=parse_bls_response(payload.content, labels),
            metadata=_with_payload_time(metadata, payload.retrieved_at),
            stale=payload.stale,
            from_cache=payload.from_cache,
            raw_reference=payload.cache_path,
        )
    except Exception as error:
        return unavailable_dataset("bls_macro", metadata, error)


OFFICIAL_RSS = {
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
    "ECB": "https://www.ecb.europa.eu/rss/press.html",
    "Bank of England": "https://www.bankofengland.co.uk/rss/news",
}


def fetch_official_headlines(limit_per_source: int = 6) -> pd.DataFrame:
    records = []
    for institution, url in OFFICIAL_RSS.items():
        feed = feedparser.parse(url)
        for entry in feed.entries[:limit_per_source]:
            records.append(
                {
                    "institution": institution,
                    "published": entry.get("published", entry.get("updated", "")),
                    "title": entry.get("title", "Untitled official release"),
                    "url": entry.get("link", url),
                }
            )
    return pd.DataFrame(records)
