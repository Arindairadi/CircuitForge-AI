"""Distributor integration interface. Adapters only work with credentials and a live network; nothing is cached or invented.
The Mouser adapter follows Mouser's public Search API documentation as understood by the author and has NOT been verified against the live service."""
import datetime as dt
import os
from typing import Protocol

import httpx


class DistributorUnavailable(Exception):
    pass


class DistributorAdapter(Protocol):
    name: str
    def search_part_number(self, mpn: str) -> list[dict]: ...


class MouserAdapter:
    name = "Mouser Search API (unverified adapter)"
    URL = "https://api.mouser.com/api/v1/search/partnumber"

    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        self.key = api_key or os.environ.get("MOUSER_API_KEY", "")
        self.transport = transport

    def search_part_number(self, mpn: str) -> list[dict]:
        if not self.key: raise DistributorUnavailable("MOUSER_API_KEY is not configured")
        try:
            with httpx.Client(timeout=15, transport=self.transport) as cl:
                r = cl.post(self.URL, params={"apiKey": self.key}, json={"SearchByPartRequest": {"mouserPartNumber": mpn}})
                r.raise_for_status(); data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise DistributorUnavailable(f"Lookup failed: {type(e).__name__}") from e
        if data.get("Errors"): raise DistributorUnavailable("The service returned an error: " + str(data["Errors"])[:200])
        now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
        out = []
        for p in (data.get("SearchResults") or {}).get("Parts") or []:
            out.append({"manufacturer": p.get("Manufacturer"), "mpn": p.get("ManufacturerPartNumber"), "description": p.get("Description"),
                        "datasheet_url": p.get("DataSheetUrl") or None, "availability": p.get("Availability"),
                        "price_breaks": [{"quantity": b.get("Quantity"), "price": b.get("Price"), "currency": b.get("Currency")} for b in (p.get("PriceBreaks") or [])][:5],
                        "source": self.name, "retrieved": now})
        return out
