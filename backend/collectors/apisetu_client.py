"""
collectors/apisetu_client.py — API Setu Government API Client.

API Setu (apisetu.gov.in) is India's government API gateway providing
access to 4,200+ APIs. This client integrates MCA21 (company registration),
GST (tax verification), and Udyam (MSME certification) data sources.

Cross-references with existing govt data via GovtCrossReferenceService.

Env vars required:
  APISETU_API_KEY — API key for API Setu gateway
"""
from __future__ import annotations

from typing import Any

import httpx
import structlog

from backend.collectors.base import RawPost

logger = structlog.get_logger(__name__)

APISETU_BASE_URL = "https://api.apisetu.gov.in"


class API_SETUError(Exception):
    """Raised on API Setu request failures."""


class API_SETUMCA21Error(API_SETUError):
    """MCA21-specific API error."""


class API_SETUGSTError(API_SETUError):
    """GST-specific API error."""


class API_SETUUdyamError(API_SETUError):
    """Udyam-specific API error."""


class APISetuClient:
    """Async HTTPX client for the API Setu government API gateway.

    Integrates three data sources:
      - MCA21: Company master data by CIN
      - GST: GST registration verification by GSTIN
      - Udyam: MSME certification lookup by Udhyam Aadhaar number
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._headers = {
            "Accept": "application/json",
        }
        if api_key:
            self._headers["X-APISETU-APIKEY"] = api_key

    # ── Public API ─────────────────────────────────────────────────────────────

    async def search_mca21(self, cin: str) -> RawPost | None:
        """Fetch company master data by CIN via API Setu MCA21 gateway.

        Returns a RawPost if found, None if the CIN is not found or invalid.
        """
        if not cin or not cin.strip():
            return None

        try:
            data = await self._get_mca21_data(cin.strip().upper())
            if not data or data.get("status") == "NOT_FOUND":
                return None
            return self._mca21_to_rawpost(data)
        except API_SETUMCA21Error as exc:
            logger.warning("apisetu_mca21_failed", cin=cin, error=str(exc))
            return None

    async def verify_gst(self, gstin: str) -> RawPost | None:
        """Verify GST registration by GSTIN via API Setu GST gateway.

        Returns a RawPost with GST data if valid, None if not found.
        """
        if not gstin or not gstin.strip():
            return None

        try:
            data = await self._get_gst_data(gstin.strip().upper())
            if not data or data.get("status") == "NOT_FOUND":
                return None
            return self._gst_to_rawpost(data)
        except API_SETUGSTError as exc:
            logger.warning("apisetu_gst_failed", gstin=gstin, error=str(exc))
            return None

    async def lookup_udyam(self, udyam_number: str) -> RawPost | None:
        """Look up MSME / Udyam registration by Udhyam Aadhaar number.

        Returns a RawPost if found, None if not found.
        """
        if not udyam_number or not udyam_number.strip():
            return None

        try:
            data = await self._get_udyam_data(udyam_number.strip())
            if not data or data.get("status") == "NOT_FOUND":
                return None
            return self._udyam_to_rawpost(data)
        except API_SETUUdyamError as exc:
            logger.warning("apisetu_udyam_failed", udyam=udyam_number, error=str(exc))
            return None

    async def enrich_company(self, cin: str | None = None, gstin: str | None = None,
                             udyam: str | None = None) -> dict[str, RawPost | None]:
        """Cross-reference a company across all three API Setu sources in parallel.

        Returns a dict keyed by source name (mca21, gst, udyam) with RawPost
        results or None.
        """
        import asyncio

        tasks: dict[str, Any] = {}

        if cin:
            tasks["mca21"] = self.search_mca21(cin)
        if gstin:
            tasks["gst"] = self.verify_gst(gstin)
        if udyam:
            tasks["udyam"] = self.lookup_udyam(udyam)

        if not tasks:
            return {}

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return {
            name: (res if isinstance(res, RawPost | None) else None)
            for name, res in zip(tasks, results, strict=False)
        }

    # ── MCA21 ──────────────────────────────────────────────────────────────────

    async def _get_mca21_data(self, cin: str) -> dict[str, Any]:
        """Call the MCA21 API Setu endpoint to get company master data."""
        url = f"{APISETU_BASE_URL}/mca/v1/company/{cin}"
        async with httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout
        ) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return {"status": "NOT_FOUND"}
            if response.status_code == 403:
                raise API_SETUMCA21Error(
                    f"API Setu MCA21 access denied (check API key)"
                )
            response.raise_for_status()
            return response.json()

    def _mca21_to_rawpost(self, data: dict[str, Any]) -> RawPost:
        """Transform API Setu MCA21 response into RawPost."""
        company = data.get("data") or data
        cin = company.get("cin", "")
        return RawPost(
            source="apisetu_mca21",
            external_id=cin,
            url=(
                "https://www.mca.gov.in/mcafoportal/"
                f"showCompanyMasterData.do?cin={cin}"
            ),
            title=company.get("companyName", ""),
            body=(
                f"{company.get('companyType', '')} company — "
                f"{company.get('registeredOfficeAddress', '')}"
            ),
            author="",
            score=0,
            raw_meta={
                "api_source": "apisetu",
                "cin": cin,
                "company_name": company.get("companyName"),
                "company_type": company.get("companyType"),
                "company_status": company.get("companyStatus"),
                "incorporation_date": company.get("dateOfIncorporation"),
                "registered_office_address": company.get("registeredOfficeAddress"),
                "registered_office_city": company.get("registeredOfficeCity"),
                "registered_office_state": company.get("registeredOfficeState"),
                "registered_office_pincode": company.get("registeredOfficePincode"),
                "authorized_capital": company.get("authorizedCapital"),
                "paid_up_capital": company.get("paidUpCapital"),
                "email": company.get("email"),
                "website": company.get("website"),
                "industry": company.get("industry"),
                "nic_code": company.get("nicCode"),
                "directors": company.get("directors", []),
                "registrar_of_companies": company.get("registrarOfCompanies"),
                "is_active": company.get("companyStatus") == "Active",
            },
        )

    # ── GST ────────────────────────────────────────────────────────────────────

    async def _get_gst_data(self, gstin: str) -> dict[str, Any]:
        """Call the GST API Setu endpoint to verify GST registration."""
        url = f"{APISETU_BASE_URL}/gst/v1/{gstin}"
        async with httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout
        ) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return {"status": "NOT_FOUND"}
            if response.status_code == 403:
                raise API_SETUGSTError(
                    f"API Setu GST access denied (check API key)"
                )
            response.raise_for_status()
            return response.json()

    def _gst_to_rawpost(self, data: dict[str, Any]) -> RawPost:
        """Transform API Setu GST response into RawPost."""
        gst = data.get("data") or data
        return RawPost(
            source="apisetu_gst",
            external_id=gst.get("gstin", ""),
            url="",
            title=gst.get("tradeName", gst.get("legalName", "")),
            body=(
                f"GST registered entity — {gst.get('tradeName', '')} "
                f"in {gst.get('state', '')}"
            ),
            author="",
            score=0,
            raw_meta={
                "api_source": "apisetu",
                "gstin": gst.get("gstin"),
                "trade_name": gst.get("tradeName"),
                "legal_name": gst.get("legalName"),
                "address": gst.get("address"),
                "state": gst.get("state"),
                "status": gst.get("status"),
                "registration_date": gst.get("registrationDate"),
                "last_update_date": gst.get("lastUpdateDate"),
                "entity_type": gst.get("entityType"),
                "business_nature": gst.get("businessNature"),
                "center_jurisdiction": gst.get("centerJurisdiction"),
                "state_jurisdiction": gst.get("stateJurisdiction"),
                "is_active": gst.get("status", "").lower() == "active",
            },
        )

    # ── Udyam ──────────────────────────────────────────────────────────────────

    async def _get_udyam_data(self, udyam_number: str) -> dict[str, Any]:
        """Call the Udyam API Setu endpoint to lookup MSME registration."""
        url = f"{APISETU_BASE_URL}/udyam/v1/{udyam_number}"
        async with httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout
        ) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return {"status": "NOT_FOUND"}
            if response.status_code == 403:
                raise API_SETUUdyamError(
                    f"API Setu Udyam access denied (check API key)"
                )
            response.raise_for_status()
            return response.json()

    def _udyam_to_rawpost(self, data: dict[str, Any]) -> RawPost:
        """Transform API Setu Udyam response into RawPost."""
        udyam = data.get("data") or data
        return RawPost(
            source="apisetu_udyam",
            external_id=udyam.get("udyamNumber", ""),
            url="",
            title=udyam.get("enterpriseName", ""),
            body=(
                f"MSME registered — {udyam.get('enterpriseName', '')} "
                f"({udyam.get('classification', '')})"
            ),
            author=udyam.get("ownerName", ""),
            score=0,
            raw_meta={
                "api_source": "apisetu",
                "udyam_number": udyam.get("udyamNumber"),
                "enterprise_name": udyam.get("enterpriseName"),
                "classification": udyam.get("classification"),
                "type": udyam.get("type"),
                "major_activity": udyam.get("majorActivity"),
                "organization_type": udyam.get("organizationType"),
                "owner_name": udyam.get("ownerName"),
                "owner_email": udyam.get("ownerEmail"),
                "owner_phone": udyam.get("ownerPhone"),
                "gender": udyam.get("gender"),
                "social_category": udyam.get("socialCategory"),
                "is_women_owned": udyam.get("isWomenOwned", False),
                "address": udyam.get("address"),
                "state": udyam.get("state"),
                "district": udyam.get("district"),
                "pincode": udyam.get("pincode"),
                "registration_date": udyam.get("registrationDate"),
                "valid_up_to": udyam.get("validUpTo"),
                "is_active": udyam.get("status", "").lower() == "active",
            },
        )


# ── Direct invocation for testing ──────────────────────────────────────────

if __name__ == "__main__":

    async def _main() -> None:
        import logging
        logging.basicConfig(level=logging.INFO)

        from backend.shared.config import settings
        client = APISetuClient(api_key=getattr(settings, "APISETU_API_KEY", None))

        # Test MCA21 lookup
        print("Testing MCA21 lookup...")
        result = await client.search_mca21("U74999MH2020PTC345678")
        if result:
            print(f"  Found: {result.title}")
        else:
            print("  Not found (expected with mock/no API key)")

        # Test GST verification
        print("Testing GST verification...")
        result = await client.verify_gst("27AAJCA1234A1Z5")
        if result:
            print(f"  Found: {result.title}")
        else:
            print("  Not found (expected with mock/no API key)")

        # Test Udyam lookup
        print("Testing Udyam lookup...")
        result = await client.lookup_udyam("UDYAM-MH-01-0000001")
        if result:
            print(f"  Found: {result.title}")
        else:
            print("  Not found (expected with mock/no API key)")

    import asyncio
    asyncio.run(_main())
