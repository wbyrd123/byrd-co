"""Google Ads API integration for Byrd & CO AdsCopilot.

Phase 1 — READ-ONLY reporting. No campaign mutations.

Handles:
  * Building an authenticated GoogleAdsClient from env vars
  * Connection health check via CustomerService.list_accessible_customers
  * Traversing the MCC account hierarchy via GAQL on customer_client
  * Pulling campaign performance metrics via GAQL on campaign

The Google SDK is synchronous / blocking. Every public function here is safe to
call from a FastAPI async endpoint via `asyncio.run_in_executor`.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger("googleads")

# Standard Google Ads env-var names — the SDK's load_from_env() reads these.
_REQUIRED_ENV = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_MCC_CUSTOMER_ID",
)


class GoogleAdsNotConfigured(RuntimeError):
    """Raised when any required env var is missing so the caller can 503."""


def is_configured() -> bool:
    """Return True iff all five required env vars are non-empty."""
    return all(os.environ.get(k, "").strip() for k in _REQUIRED_ENV)


def _mcc_id() -> str:
    """MCC (manager) customer ID, digits-only. Raises if unset."""
    raw = os.environ.get("GOOGLE_ADS_MCC_CUSTOMER_ID", "").strip()
    if not raw:
        raise GoogleAdsNotConfigured("GOOGLE_ADS_MCC_CUSTOMER_ID is not set")
    return raw.replace("-", "").replace(" ", "")


@lru_cache(maxsize=1)
def _get_client():
    """Build a GoogleAdsClient once per process. Reads from env vars.

    NOTE: `use_proto_plus=True` is required by google-ads 31.x and gives us the
    dict-like access to protobuf fields we use in the response parsers below."""
    if not is_configured():
        missing = [k for k in _REQUIRED_ENV if not os.environ.get(k, "").strip()]
        raise GoogleAdsNotConfigured(
            f"Missing env vars: {', '.join(missing)}"
        )
    from google.ads.googleads.client import GoogleAdsClient
    # Prefer load_from_env which reads GOOGLE_ADS_* directly. We also normalize
    # login_customer_id after construction because it's easier to strip dashes
    # here than to enforce clean env-var input.
    os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"] = _mcc_id()
    os.environ.setdefault("GOOGLE_ADS_USE_PROTO_PLUS", "True")
    client = GoogleAdsClient.load_from_env()
    return client


def clear_client_cache() -> None:
    """Test helper — forces the next call to rebuild the client."""
    _get_client.cache_clear()


# ---------- Sync worker functions (called via run_in_executor) ----------

def _google_ads_error_dict(ex) -> dict:
    """Normalize a GoogleAdsException into a JSON-safe dict for the API layer."""
    try:
        errors = [
            {
                "message": e.message,
                "code": e.error_code.__class__.__name__,
                "location": [
                    {"field_name": fp.field_name}
                    for fp in (getattr(e, "location", None) and e.location.field_path_elements or [])
                ],
            }
            for e in ex.failure.errors
        ]
    except Exception:
        errors = [{"message": str(ex)}]
    return {
        "request_id": getattr(ex, "request_id", None),
        "errors": errors,
    }


def sync_check_connection() -> dict:
    """Health check — calls CustomerService.list_accessible_customers. Success
    proves the refresh token, OAuth client, and developer token all work.

    Returns { ok: bool, mcc: '<id>', accessible_customers: [ '<res_name>' ], error?: {...} }
    """
    from google.ads.googleads.errors import GoogleAdsException
    try:
        client = _get_client()
        service = client.get_service("CustomerService")
        response = service.list_accessible_customers()
        return {
            "ok": True,
            "mcc": _mcc_id(),
            "accessible_customers": list(response.resource_names),
        }
    except GoogleAdsException as ex:
        logger.warning("Google Ads connection check failed: %s", ex)
        return {"ok": False, "mcc": _mcc_id(), "error": _google_ads_error_dict(ex)}
    except GoogleAdsNotConfigured as ex:
        return {"ok": False, "error": {"message": str(ex)}}


_HIERARCHY_QUERY = """
    SELECT
      customer_client.client_customer,
      customer_client.id,
      customer_client.descriptive_name,
      customer_client.currency_code,
      customer_client.time_zone,
      customer_client.level,
      customer_client.manager,
      customer_client.status,
      customer_client.test_account
    FROM customer_client
    WHERE customer_client.status IN ('ENABLED', 'SUSPENDED')
    ORDER BY customer_client.level, customer_client.id
"""


def sync_list_mcc_accounts() -> dict:
    """Return every account visible under the configured MCC. Non-recursive —
    a single search_stream on customer_client returns the full sub-tree because
    the GAQL walks it for us. Deep manager-of-manager hierarchies still work
    because `customer_client` is transitive (all descendants, any depth)."""
    from google.ads.googleads.errors import GoogleAdsException
    try:
        client = _get_client()
        service = client.get_service("GoogleAdsService")
        mcc = _mcc_id()
        rows: list[dict] = []
        stream = service.search_stream(customer_id=mcc, query=_HIERARCHY_QUERY)
        for batch in stream:
            for row in batch.results:
                cc = row.customer_client
                rows.append({
                    "id": str(cc.id),
                    "resource_name": cc.client_customer,
                    "name": cc.descriptive_name or "(unnamed)",
                    "currency": cc.currency_code,
                    "timezone": cc.time_zone,
                    "level": int(cc.level),
                    "is_manager": bool(cc.manager),
                    "is_test_account": bool(cc.test_account),
                    "status": cc.status.name if hasattr(cc.status, "name") else str(cc.status),
                })
        return {"ok": True, "mcc": mcc, "accounts": rows}
    except GoogleAdsException as ex:
        logger.warning("Google Ads MCC tree failed: %s", ex)
        return {"ok": False, "error": _google_ads_error_dict(ex)}
    except GoogleAdsNotConfigured as ex:
        return {"ok": False, "error": {"message": str(ex)}}


_CAMPAIGN_REPORT_QUERY = """
    SELECT
      segments.date,
      campaign.id,
      campaign.name,
      campaign.status,
      campaign.advertising_channel_type,
      metrics.impressions,
      metrics.clicks,
      metrics.cost_micros,
      metrics.conversions,
      metrics.ctr,
      metrics.average_cpc
    FROM campaign
    WHERE segments.date BETWEEN '{start}' AND '{end}'
    ORDER BY segments.date DESC, metrics.cost_micros DESC
"""


def sync_campaign_report(customer_id: str, start_date: str, end_date: str) -> dict:
    """Pull daily campaign-level performance for a customer + date range.

    `customer_id` and dates are already validated at the API layer. `cost_micros`
    is normalized to dollars (float). `average_cpc` is also micros in the API."""
    from google.ads.googleads.errors import GoogleAdsException
    try:
        client = _get_client()
        service = client.get_service("GoogleAdsService")
        cid = customer_id.replace("-", "").replace(" ", "")
        query = _CAMPAIGN_REPORT_QUERY.format(start=start_date, end=end_date)
        rows: list[dict] = []
        stream = service.search_stream(customer_id=cid, query=query)
        for batch in stream:
            for row in batch.results:
                rows.append({
                    "date": row.segments.date,
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "status": row.campaign.status.name if hasattr(row.campaign.status, "name") else str(row.campaign.status),
                    "channel": row.campaign.advertising_channel_type.name if hasattr(row.campaign.advertising_channel_type, "name") else str(row.campaign.advertising_channel_type),
                    "impressions": int(row.metrics.impressions),
                    "clicks": int(row.metrics.clicks),
                    "cost": round(float(row.metrics.cost_micros) / 1_000_000.0, 2),
                    "conversions": round(float(row.metrics.conversions), 2),
                    "ctr_pct": round(float(row.metrics.ctr) * 100.0, 3),
                    "avg_cpc": round(float(row.metrics.average_cpc) / 1_000_000.0, 2),
                })
        totals = {
            "impressions": sum(r["impressions"] for r in rows),
            "clicks": sum(r["clicks"] for r in rows),
            "cost": round(sum(r["cost"] for r in rows), 2),
            "conversions": round(sum(r["conversions"] for r in rows), 2),
        }
        return {"ok": True, "customer_id": cid, "start_date": start_date,
                "end_date": end_date, "rows": rows, "totals": totals}
    except GoogleAdsException as ex:
        logger.warning("Google Ads campaign report failed: %s", ex)
        return {"ok": False, "error": _google_ads_error_dict(ex)}
    except GoogleAdsNotConfigured as ex:
        return {"ok": False, "error": {"message": str(ex)}}
