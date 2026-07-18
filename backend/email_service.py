"""Postmark-backed transactional email helper. Non-blocking, safe on API failure."""
import os
import logging
from typing import Iterable, Optional
from postmarker.core import PostmarkClient

logger = logging.getLogger("email")

_client: Optional[PostmarkClient] = None


def _get_client() -> Optional[PostmarkClient]:
    global _client
    token = os.environ.get("POSTMARK_TOKEN", "").strip()
    if not token:
        return None
    if _client is None:
        _client = PostmarkClient(server_token=token)
    return _client


def send_email(to: str | Iterable[str], subject: str, html: str, text: str, tag: str = "") -> None:
    """Fire-and-forget email send. Never raises; logs on failure."""
    client = _get_client()
    if not client:
        logger.warning("POSTMARK_TOKEN not set — skipping email: %s", subject)
        return
    from_name = os.environ.get("POSTMARK_FROM_NAME", "Byrd & CO")
    from_email = os.environ.get("POSTMARK_FROM", "notifications@mail.byrd-co.com")
    from_hdr = f"{from_name} <{from_email}>"
    recipients = [to] if isinstance(to, str) else list(to)
    for r in recipients:
        try:
            client.emails.send(
                From=from_hdr,
                To=r,
                Subject=subject,
                HtmlBody=html,
                TextBody=text,
                Tag=tag or None,
                MessageStream="outbound",
            )
            logger.info("Sent Postmark email tag=%s to=%s", tag, r)
        except Exception as e:
            logger.error("Postmark send failed tag=%s to=%s err=%s", tag, r, e)


def broker_emails() -> list[str]:
    raw = os.environ.get("BROKER_EMAILS", "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def public_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


# ---------- Templates ----------
def tmpl_quote(q: dict) -> tuple[str, str, str]:
    subject = f"New quote request — {q.get('name')} ({q.get('loan_type') or 'unspecified'})"
    text = (
        f"New quote request from the Byrd & CO website.\n\n"
        f"Name: {q.get('name')}\n"
        f"Email: {q.get('email')}\n"
        f"Phone: {q.get('phone') or '—'}\n"
        f"Loan Type: {q.get('loan_type') or '—'}\n"
        f"Loan Amount: {q.get('loan_amount') or '—'}\n"
        f"Property Type: {q.get('property_type') or '—'}\n\n"
        f"Message:\n{q.get('message') or '(none)'}\n\n"
        f"View in admin: {public_base_url()}/admin/quotes\n"
    )
    base = public_base_url()
    html = f"""
    <div style="font-family:Georgia,serif;max-width:600px;margin:auto;">
      <div style="background:#1A1A1A;color:#C89434;padding:20px;text-align:center;">
        <div style="font-size:20px;font-weight:bold;letter-spacing:0.1em;">BYRD &amp; CO</div>
        <div style="font-size:10px;color:#C9C1AF;text-transform:uppercase;letter-spacing:0.2em;">New Quote Request</div>
      </div>
      <div style="padding:24px;background:#FBF8F1;color:#1A1A1A;">
        <h2 style="margin:0 0 12px;font-family:Georgia,serif;">{q.get('name')}</h2>
        <table style="width:100%;font-family:Arial,sans-serif;font-size:14px;border-collapse:collapse;">
          <tr><td style="color:#6B6558;padding:4px 0;">Email</td><td><a href="mailto:{q.get('email')}">{q.get('email')}</a></td></tr>
          <tr><td style="color:#6B6558;padding:4px 0;">Phone</td><td>{q.get('phone') or '—'}</td></tr>
          <tr><td style="color:#6B6558;padding:4px 0;">Loan Type</td><td>{q.get('loan_type') or '—'}</td></tr>
          <tr><td style="color:#6B6558;padding:4px 0;">Loan Amount</td><td>{q.get('loan_amount') or '—'}</td></tr>
          <tr><td style="color:#6B6558;padding:4px 0;">Property Type</td><td>{q.get('property_type') or '—'}</td></tr>
        </table>
        <div style="margin-top:16px;padding:12px;background:#fff;border:1px solid #E4DFD1;font-family:Arial,sans-serif;font-size:14px;white-space:pre-wrap;">{q.get('message') or '(no message)'}</div>
        <div style="margin-top:20px;">
          <a href="{base}/admin/quotes" style="background:#C89434;color:#1A1A1A;padding:10px 18px;text-decoration:none;font-family:Arial,sans-serif;font-size:13px;font-weight:bold;">Open in Admin</a>
        </div>
      </div>
    </div>
    """
    return subject, html, text


def tmpl_invite(user: dict, invite_url: str) -> tuple[str, str, str]:
    name = user.get("name") or "there"
    subject = "Your Byrd & CO client portal invite"
    text = (
        f"Hi {name},\n\n"
        f"Wayne and Caleb at Byrd & CO have added you to their client portal. "
        f"Click the link below to set your password and access your document checklist:\n\n"
        f"{invite_url}\n\n"
        f"If you weren't expecting this email, please ignore it.\n\n"
        f"— Byrd & CO Commercial RE Lending\n"
    )
    html = f"""
    <div style="font-family:Georgia,serif;max-width:600px;margin:auto;">
      <div style="background:#1A1A1A;color:#C89434;padding:20px;text-align:center;">
        <div style="font-size:20px;font-weight:bold;letter-spacing:0.1em;">BYRD &amp; CO</div>
        <div style="font-size:10px;color:#C9C1AF;text-transform:uppercase;letter-spacing:0.2em;">Client Portal Invite</div>
      </div>
      <div style="padding:24px;background:#FBF8F1;color:#1A1A1A;">
        <h2 style="margin:0 0 12px;font-family:Georgia,serif;">Welcome, {name}.</h2>
        <p style="font-family:Arial,sans-serif;font-size:14px;line-height:1.55;">
          Wayne and Caleb at Byrd &amp; CO have set up your private document portal. Click below
          to choose a password and get started.
        </p>
        <div style="text-align:center;margin:24px 0;">
          <a href="{invite_url}" style="background:#C89434;color:#1A1A1A;padding:14px 28px;text-decoration:none;font-family:Arial,sans-serif;font-size:14px;font-weight:bold;">Activate Your Portal</a>
        </div>
        <p style="font-family:Arial,sans-serif;font-size:12px;color:#6B6558;">Or paste this into your browser:<br/><span style="word-break:break-all;">{invite_url}</span></p>
      </div>
    </div>
    """
    return subject, html, text


def tmpl_lender_activity(action: str, share: dict, viewer: dict, scen_name: str) -> tuple[str, str, str]:
    action_label = {
        "view_scenario": "opened your loan package",
        "download_pdf": "downloaded the PDF",
        "request_docs": "requested full document access",
    }.get(action, action)
    subject = f"{viewer.get('viewer_institution') or 'A lender'} {action_label}: {scen_name}"
    text = (
        f"Lender activity on Byrd & CO deal package.\n\n"
        f"Scenario: {scen_name}\n"
        f"Action: {action_label}\n"
        f"Lender: {viewer.get('viewer_name')} ({viewer.get('viewer_institution')})\n"
        f"Email: {viewer.get('viewer_email')}\n\n"
        f"Open the scenario: {public_base_url()}/admin/scenarios/{share.get('scenario_id')}\n"
    )
    base = public_base_url()
    highlight = " style=\"color:#C89434;font-weight:bold;\"" if action == "request_docs" else ""
    html = f"""
    <div style="font-family:Georgia,serif;max-width:600px;margin:auto;">
      <div style="background:#1A1A1A;color:#C89434;padding:20px;text-align:center;">
        <div style="font-size:20px;font-weight:bold;letter-spacing:0.1em;">BYRD &amp; CO</div>
        <div style="font-size:10px;color:#C9C1AF;text-transform:uppercase;letter-spacing:0.2em;">Lender Activity</div>
      </div>
      <div style="padding:24px;background:#FBF8F1;color:#1A1A1A;">
        <h2 style="margin:0 0 12px;font-family:Georgia,serif;"><span{highlight}>{viewer.get('viewer_institution') or 'A lender'}</span> {action_label}.</h2>
        <table style="width:100%;font-family:Arial,sans-serif;font-size:14px;border-collapse:collapse;">
          <tr><td style="color:#6B6558;padding:4px 0;">Scenario</td><td><b>{scen_name}</b></td></tr>
          <tr><td style="color:#6B6558;padding:4px 0;">Viewer</td><td>{viewer.get('viewer_name')}</td></tr>
          <tr><td style="color:#6B6558;padding:4px 0;">Email</td><td><a href="mailto:{viewer.get('viewer_email')}">{viewer.get('viewer_email')}</a></td></tr>
        </table>
        <div style="margin-top:20px;">
          <a href="{base}/admin/scenarios/{share.get('scenario_id')}" style="background:#C89434;color:#1A1A1A;padding:10px 18px;text-decoration:none;font-family:Arial,sans-serif;font-size:13px;font-weight:bold;">Open Scenario</a>
        </div>
      </div>
    </div>
    """
    return subject, html, text
