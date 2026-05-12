"""
services/govt_cross_reference.py -- Government data cross-reference service.

Links: CIN <-> DPIIT <-> GST <-> MSME <-> GeM
Enriches leads by cross-referencing across all government data sources
and computes a verification score.

Usage:
    service = GovtCrossReferenceService()
    enriched = await service.enrich_lead(lead)
    print(enriched.govt_verification_score)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from backend.collectors.apisetu_client import APISetuClient
from backend.collectors.dpiit_v2 import DPIITv2Collector
from backend.collectors.mca21_v2 import MCA21Collector
from backend.collectors.gem import GeMCollector
from backend.collectors.msme import MSMECollector

logger = structlog.get_logger(__name__)


@dataclass
class EnrichedLead:
    """Enriched lead with merged government data and verification score."""

    # Original lead fields
    company_name: str = ""
    cin_number: str = ""
    gst_number: str = ""
    udyam_number: str = ""
    pan: str = ""
    industry: str = ""
    location: str = ""
    website: str = ""

    # MCA21 merged data
    mca_verified: bool = False
    company_type: str = ""
    company_status: str = ""
    incorporation_date: str = ""
    authorized_capital: float = 0.0
    paid_up_capital: float = 0.0
    directors: list[dict] = field(default_factory=list)
    registrar: str = ""
    nic_code: str = ""

    # GST verification data
    gst_verified: bool = False
    gst_trade_name: str = ""
    gst_address: str = ""
    gst_state: str = ""
    gst_status: str = ""

    # MSME merged data
    msme_verified: bool = False
    msme_owner_name: str = ""
    msme_owner_email: str = ""
    msme_owner_phone: str = ""
    msme_org_type: str = ""
    msme_major_activity: str = ""
    msme_social_category: str = ""
    msme_gender: str = ""
    msme_is_women_owned: bool = False

    # DPIIT data
    dpiit_recognized: bool = False
    dpiit_certificate: str = ""
    dpiit_sector: str = ""
    dpiit_stage: str = ""
    dpiit_funding_amount: float = 0.0
    dpiit_investors: list[str] = field(default_factory=list)
    dpiit_employees: int = 0
    dpiit_founder_name: str = ""
    dpiit_founder_email: str = ""
    dpiit_is_women_led: bool = False

    # GeM vendor data
    gem_vendor: bool = False
    gem_vendor_id: str = ""
    gem_categories: list[str] = field(default_factory=list)
    gem_rating: float = 0.0
    gem_total_orders: int = 0
    gem_total_value: float = 0.0
    gem_tender_history: list[dict] = field(default_factory=list)

    # Composite score
    govt_verification_score: float = 0.0

    # Raw merged metadata
    raw_meta: dict[str, Any] = field(default_factory=dict)


class GovtCrossReferenceService:
    """Cross-reference government data sources to enrich leads."""

    def __init__(self, apisetu_api_key: str | None = None) -> None:
        self.dpiit_client = DPIITv2Collector()
        self.mca_client = MCA21Collector()
        self.gem_client = GeMCollector()
        self.msme_client = MSMECollector()
        self.apisetu_client = APISetuClient(api_key=apisetu_api_key)

    async def enrich_lead(self, lead: EnrichedLead) -> EnrichedLead:
        """Enrich a lead by cross-referencing against all government data sources.

        Attempts to match by CIN, GST, Udyam, and industry/category.
        Returns the enriched lead with a govt_verification_score.
        """
        enriched = EnrichedLead(**lead.__dict__)

        # 1. Cross-reference by CIN via MCA21
        if lead.cin_number:
            try:
                mca_data = await self.mca_client._get_company_details(lead.cin_number)
                if mca_data:
                    enriched = self._merge_mca_data(enriched, mca_data)
            except Exception as e:
                logger.warning("mca21_lookup_failed", cin=lead.cin_number, error=str(e))

        # 2. Cross-reference by CIN via API Setu MCA21 (fallback if MCA21 didn't find data)
        if lead.cin_number and not enriched.mca_verified:
            try:
                apisetu_mca = await self.apisetu_client.search_mca21(lead.cin_number)
                if apisetu_mca:
                    enriched = self._merge_mca_data(enriched, apisetu_mca.raw_meta)
            except Exception as e:
                logger.warning("apisetu_mca21_lookup_failed", cin=lead.cin_number, error=str(e))

        # 3. Cross-reference by GST via API Setu
        if lead.gst_number:
            try:
                gst_data = await self._verify_gst(lead.gst_number)
                if gst_data:
                    enriched = self._merge_gst_data(enriched, gst_data)
            except Exception as e:
                logger.warning("gst_lookup_failed", gst=lead.gst_number, error=str(e))

        # 4. Cross-reference by Udyam number via API Setu
        if lead.udyam_number:
            try:
                udyam_post = await self.apisetu_client.lookup_udyam(lead.udyam_number)
                if udyam_post:
                    enriched = self._merge_msme_data(enriched, udyam_post.raw_meta)
            except Exception as e:
                logger.warning("udyam_lookup_failed", udyam=lead.udyam_number, error=str(e))
            # Fallback: try MSME collector
            if not enriched.msme_verified:
                try:
                    msme_results = await self.msme_client._search_msme(
                        state=lead.location or "",
                        nic="",
                    )
                    matching = [
                        m
                        for m in msme_results
                        if m.get("udyamNumber") == lead.udyam_number
                    ]
                    if matching:
                        enriched = self._merge_msme_data(enriched, matching[0])
                except Exception as e:
                    logger.warning(
                        "msme_lookup_failed", udyam=lead.udyam_number, error=str(e)
                    )

        # 5. Search GeM for vendor by industry
        if lead.industry:
            try:
                gem_results = await self.gem_client._search_vendors(lead.industry)
                if gem_results:
                    enriched = self._merge_gem_data(enriched, gem_results[0])
            except Exception as e:
                logger.warning(
                    "gem_lookup_failed", industry=lead.industry, error=str(e)
                )

        # 5. Calculate composite verification score
        enriched.govt_verification_score = self._calculate_verification_score(enriched)

        logger.info(
            "govt_cross_reference_complete",
            cin=lead.cin_number,
            gst=lead.gst_number,
            udyam=lead.udyam_number,
            score=enriched.govt_verification_score,
        )
        return enriched

    def _merge_mca_data(self, enriched: EnrichedLead, data: dict) -> EnrichedLead:
        """Merge MCA21 company data into the enriched lead."""
        enriched.mca_verified = True
        enriched.company_type = data.get("companyType", enriched.company_type)
        enriched.company_status = data.get("companyStatus", enriched.company_status)
        enriched.incorporation_date = data.get(
            "dateOfIncorporation", enriched.incorporation_date
        )
        enriched.authorized_capital = data.get(
            "authorizedCapital", enriched.authorized_capital
        )
        enriched.paid_up_capital = data.get(
            "paidUpCapital", enriched.paid_up_capital
        )
        enriched.directors = data.get("directors", enriched.directors)
        enriched.registrar = data.get(
            "registrarOfCompanies", enriched.registrar
        )
        enriched.nic_code = data.get("nicCode", enriched.nic_code)
        if not enriched.industry:
            enriched.industry = data.get("industry", "")
        if not enriched.website:
            enriched.website = data.get("website", "")
        enriched.raw_meta["mca21"] = data
        return enriched

    def _merge_gst_data(self, enriched: EnrichedLead, data: dict) -> EnrichedLead:
        """Merge GST verification data into the enriched lead."""
        enriched.gst_verified = True
        enriched.gst_trade_name = data.get("tradeName", enriched.gst_trade_name)
        enriched.gst_address = data.get("address", enriched.gst_address)
        enriched.gst_state = data.get("state", enriched.gst_state)
        enriched.gst_status = data.get("status", enriched.gst_status)
        if not enriched.company_name:
            enriched.company_name = data.get("tradeName", "")
        enriched.raw_meta["gst"] = data
        return enriched

    def _merge_msme_data(self, enriched: EnrichedLead, data: dict) -> EnrichedLead:
        """Merge MSME registration data into the enriched lead."""
        enriched.msme_verified = True
        enriched.msme_owner_name = data.get("ownerName", enriched.msme_owner_name)
        enriched.msme_owner_email = data.get("ownerEmail", enriched.msme_owner_email)
        enriched.msme_owner_phone = data.get("ownerPhone", enriched.msme_owner_phone)
        enriched.msme_org_type = data.get(
            "organizationType", enriched.msme_org_type
        )
        enriched.msme_major_activity = data.get(
            "majorActivity", enriched.msme_major_activity
        )
        enriched.msme_social_category = data.get(
            "socialCategory", enriched.msme_social_category
        )
        enriched.msme_gender = data.get("gender", enriched.msme_gender)
        enriched.msme_is_women_owned = data.get(
            "isWomenOwned", enriched.msme_is_women_owned
        )
        enriched.raw_meta["msme"] = data
        return enriched

    def _merge_gem_data(self, enriched: EnrichedLead, data: dict) -> EnrichedLead:
        """Merge GeM vendor data into the enriched lead."""
        enriched.gem_vendor = True
        enriched.gem_vendor_id = data.get("vendorId", enriched.gem_vendor_id)
        enriched.gem_categories = [data.get("category", "")]
        enriched.gem_rating = data.get("rating", enriched.gem_rating)
        enriched.gem_total_orders = data.get(
            "totalOrders", enriched.gem_total_orders
        )
        enriched.gem_total_value = data.get(
            "totalValue", enriched.gem_total_value
        )
        enriched.gem_tender_history = data.get(
            "tenderHistory", enriched.gem_tender_history
        )
        enriched.raw_meta["gem"] = data
        return enriched

    async def _verify_gst(self, gst_number: str) -> dict:
        """Verify GST number via API Setu GST gateway.

        Returns GST registration data dict if valid, empty dict otherwise.
        """
        try:
            gst_post = await self.apisetu_client.verify_gst(gst_number)
            if gst_post is not None:
                logger.info("gst_verified_via_apisetu", gst=gst_number)
                return gst_post.raw_meta
        except Exception as exc:
            logger.warning("apisetu_gst_failed", gst=gst_number, error=str(exc))

        logger.info("gst_verification_not_found", gst=gst_number)
        return {}

    def _calculate_verification_score(self, lead: EnrichedLead) -> float:
        """Calculate government verification score (0-1).

        Scoring breakdown:
          - CIN verified via MCA21: 0.25
          - GST verified:             0.20
          - DPIIT recognized:         0.20
          - MSME registered:          0.15
          - GeM vendor presence:      0.10
          - Company status Active:    0.10
        """
        score = 0.0

        if lead.cin_number and lead.mca_verified:
            score += 0.25

        if lead.gst_number and lead.gst_verified:
            score += 0.20

        if lead.dpiit_recognized:
            score += 0.20

        if lead.udyam_number and lead.msme_verified:
            score += 0.15

        if lead.gem_vendor:
            score += 0.10

        if lead.company_status == "Active":
            score += 0.10

        return min(1.0, score)
