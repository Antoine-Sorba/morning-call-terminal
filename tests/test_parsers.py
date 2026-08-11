import io
import zipfile

import pandas as pd

from ficc_terminal.official_sources import (
    _parse_boe_curve_zip,
    derive_fx_crosses,
    parse_ecb_fx_xml,
    parse_nyfed_reference_rates,
    parse_treasury_xml,
)


def test_treasury_xml_parser() -> None:
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"
          xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
      <entry><content><m:properties>
        <d:NEW_DATE>2026-08-07T00:00:00</d:NEW_DATE>
        <d:BC_2YEAR>4.19</d:BC_2YEAR><d:BC_10YEAR>4.65</d:BC_10YEAR>
      </m:properties></content></entry>
      <entry><content><m:properties>
        <d:NEW_DATE>2026-08-10T00:00:00</d:NEW_DATE>
        <d:BC_2YEAR>4.25</d:BC_2YEAR><d:BC_10YEAR>4.72</d:BC_10YEAR>
      </m:properties></content></entry>
    </feed>"""
    frame = parse_treasury_xml(xml)
    assert len(frame) == 4
    latest_10y = frame.loc[(frame["date"] == "2026-08-10") & (frame["instrument"] == "10Y"), "value"]
    assert latest_10y.iloc[0] == 4.72


def test_ecb_fx_crosses() -> None:
    xml = """<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
      xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
      <Cube><Cube time="2026-08-10"><Cube currency="USD" rate="1.1700"/>
      <Cube currency="GBP" rate="0.8700"/><Cube currency="JPY" rate="172.00"/></Cube></Cube>
    </gesmes:Envelope>"""
    frame = derive_fx_crosses(parse_ecb_fx_xml(xml))
    gbpusd = frame.loc[frame["instrument"] == "GBP/USD", "value"].iloc[0]
    usdjpy = frame.loc[frame["instrument"] == "USD/JPY", "value"].iloc[0]
    assert round(gbpusd, 4) == round(1.17 / 0.87, 4)
    assert round(usdjpy, 4) == round(172 / 1.17, 4)


def test_nyfed_parser() -> None:
    payload = '{"refRates":[{"effectiveDate":"2026-08-10","percentRate":4.31}]}'
    frame = parse_nyfed_reference_rates(payload)
    assert frame.iloc[0]["instrument"] == "SOFR"
    assert frame.iloc[0]["value"] == 4.31


def test_boe_xlsx_archive_parser() -> None:
    table = pd.DataFrame(index=range(8), columns=range(4))
    table.iloc[3, 1:] = [0.5, 2.0, 10.0]
    table.iloc[5, 0] = "2026-08-07"
    table.iloc[6, 0] = "2026-08-10"
    table.iloc[5, 1:] = [4.10, 4.20, 4.40]
    table.iloc[6, 1:] = [4.12, 4.24, 4.46]

    workbook = io.BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        table.to_excel(writer, sheet_name="4. spot curve", header=False, index=False)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("GLC Nominal daily data_2025 to present.xlsx", workbook.getvalue())

    frame = _parse_boe_curve_zip(archive.getvalue())
    latest_10y = frame.loc[
        (frame["date"] == pd.Timestamp("2026-08-10")) & (frame["instrument"] == "10Y"),
        "value",
    ]
    assert latest_10y.iloc[0] == 4.46
