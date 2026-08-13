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


def send_email(to: str | Iterable[str], subject: str, html: str, text: str, tag: str = "",
               from_email: Optional[str] = None, from_name: Optional[str] = None,
               reply_to: Optional[str] = None,
               attachments: Optional[list] = None) -> dict:
    """Fire-and-forget email send. Never raises; logs on failure.
    Optionally override the default From address (e.g. wayne@byrd-co.com for personal assistant emails).
    `attachments` — list of {"Name": filename, "Content": base64_str, "ContentType": mime}.
    Returns a summary {'ok': bool, 'error': str|None, 'sent': int, 'failed': int} — callers that need
    immediate feedback (like the assistant email) can use it; background callers can ignore it."""
    client = _get_client()
    if not client:
        logger.warning("POSTMARK_TOKEN not set — skipping email: %s", subject)
        return {"ok": False, "error": "Email service not configured (POSTMARK_TOKEN missing)", "sent": 0, "failed": 0}
    resolved_name = from_name or os.environ.get("POSTMARK_FROM_NAME", "Byrd & CO")
    resolved_email = from_email or os.environ.get("POSTMARK_FROM", "notifications@mail.byrd-co.com")
    from_hdr = f"{resolved_name} <{resolved_email}>"
    recipients = [to] if isinstance(to, str) else list(to)
    sent = 0
    failed = 0
    last_err: Optional[str] = None
    for r in recipients:
        try:
            kwargs = dict(
                From=from_hdr,
                To=r,
                Subject=subject,
                HtmlBody=html,
                TextBody=text,
                Tag=tag or None,
                MessageStream="outbound",
            )
            if reply_to:
                kwargs["ReplyTo"] = reply_to
            if attachments:
                kwargs["Attachments"] = attachments
            client.emails.send(**kwargs)
            sent += 1
            logger.info("Sent Postmark email tag=%s to=%s from=%s", tag, r, resolved_email)
        except Exception as e:
            failed += 1
            last_err = str(e)
            logger.error("Postmark send failed tag=%s to=%s err=%s", tag, r, e)
    return {"ok": failed == 0 and sent > 0, "error": last_err, "sent": sent, "failed": failed}


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



def tmpl_lender_application_received(lender_name: str, contact_email: str) -> tuple[str, str, str]:
    subject = "Byrd & CO — Application received"
    text = (
        f"Thank you for applying to become a Byrd & CO lending partner.\n\n"
        f"We've received your application for {lender_name} and one of the brokers will "
        f"review it shortly. You'll get another email once you're approved with instructions "
        f"on how to set your password and access your lender portal.\n\n"
        f"— Byrd & CO Commercial RE Lending\n"
    )
    html = f"""
    <div style="font-family:Georgia,serif;max-width:600px;margin:auto;">
      <div style="background:#1A1A1A;color:#C89434;padding:20px;text-align:center;">
        <div style="font-size:20px;font-weight:bold;letter-spacing:0.1em;">BYRD &amp; CO</div>
        <div style="font-size:10px;color:#C9C1AF;text-transform:uppercase;letter-spacing:0.2em;">Lender Application</div>
      </div>
      <div style="padding:24px;background:#FBF8F1;color:#1A1A1A;">
        <h2 style="margin:0 0 12px;font-family:Georgia,serif;">Application received</h2>
        <p style="font-family:Arial,sans-serif;font-size:14px;line-height:1.55;">
          Thanks for applying to become a Byrd &amp; CO lending partner. We've received your
          application for <b>{lender_name}</b> and one of our brokers will review it shortly.
        </p>
        <p style="font-family:Arial,sans-serif;font-size:14px;line-height:1.55;">
          You'll get another email once you're approved, with instructions to set your password
          and access your lender portal — where you'll see deals matched to your credit box and
          submit term sheets.
        </p>
      </div>
    </div>
    """
    return subject, html, text


def tmpl_lender_approved(lender_name: str, activate_url: str) -> tuple[str, str, str]:
    subject = "You're approved — activate your Byrd & CO lender portal"
    text = (
        f"Great news — {lender_name} has been approved as a Byrd & CO lending partner.\n\n"
        f"Click the link below to set your password and access your lender portal:\n\n"
        f"{activate_url}\n\n"
        f"Inside you'll be able to update your credit box, review deal invites from Byrd & CO "
        f"brokers, and submit term sheets on active scenarios.\n\n"
        f"— Byrd & CO Commercial RE Lending\n"
    )
    html = f"""
    <div style="font-family:Georgia,serif;max-width:600px;margin:auto;">
      <div style="background:#1A1A1A;color:#C89434;padding:20px;text-align:center;">
        <div style="font-size:20px;font-weight:bold;letter-spacing:0.1em;">BYRD &amp; CO</div>
        <div style="font-size:10px;color:#C9C1AF;text-transform:uppercase;letter-spacing:0.2em;">Lender Portal Access</div>
      </div>
      <div style="padding:24px;background:#FBF8F1;color:#1A1A1A;">
        <h2 style="margin:0 0 12px;font-family:Georgia,serif;">Welcome aboard, {lender_name}.</h2>
        <p style="font-family:Arial,sans-serif;font-size:14px;line-height:1.55;">
          You've been approved as a Byrd &amp; CO lending partner. Click below to activate your
          portal and set a password.
        </p>
        <div style="text-align:center;margin:24px 0;">
          <a href="{activate_url}" style="background:#C89434;color:#1A1A1A;padding:14px 28px;text-decoration:none;font-family:Arial,sans-serif;font-size:14px;font-weight:bold;">Activate My Portal</a>
        </div>
        <p style="font-family:Arial,sans-serif;font-size:12px;color:#6B6558;">Or paste this into your browser:<br/><span style="word-break:break-all;">{activate_url}</span></p>
      </div>
    </div>
    """
    return subject, html, text


def tmpl_lender_invite(lender_name: str, scen_name: str, portal_url: str, broker_note: str = "") -> tuple[str, str, str]:
    subject = f"New deal for you: {scen_name}"
    note_block = f"\n\nBroker note: {broker_note}\n" if broker_note else ""
    text = (
        f"Hi {lender_name},\n\n"
        f"A new deal has been shared with you at Byrd & CO — {scen_name}. It matches "
        f"the parameters in your credit box.{note_block}\n"
        f"Log in to review and submit a term sheet:\n{portal_url}\n\n"
        f"— Byrd & CO Commercial RE Lending\n"
    )
    note_html = f"<div style=\"background:#fff;border-left:3px solid #C89434;padding:12px;margin:12px 0;font-family:Arial,sans-serif;font-size:13px;\">{broker_note}</div>" if broker_note else ""
    html = f"""
    <div style="font-family:Georgia,serif;max-width:600px;margin:auto;">
      <div style="background:#1A1A1A;color:#C89434;padding:20px;text-align:center;">
        <div style="font-size:20px;font-weight:bold;letter-spacing:0.1em;">BYRD &amp; CO</div>
        <div style="font-size:10px;color:#C9C1AF;text-transform:uppercase;letter-spacing:0.2em;">New Deal Invite</div>
      </div>
      <div style="padding:24px;background:#FBF8F1;color:#1A1A1A;">
        <h2 style="margin:0 0 12px;font-family:Georgia,serif;">New deal for {lender_name}</h2>
        <p style="font-family:Arial,sans-serif;font-size:14px;line-height:1.55;">
          A new scenario has been shared with you — <b>{scen_name}</b>. It matches the parameters
          in your credit box.
        </p>
        {note_html}
        <div style="text-align:center;margin:24px 0;">
          <a href="{portal_url}" style="background:#C89434;color:#1A1A1A;padding:14px 28px;text-decoration:none;font-family:Arial,sans-serif;font-size:14px;font-weight:bold;">Review & Term Sheet</a>
        </div>
      </div>
    </div>
    """
    return subject, html, text


def tmpl_term_sheet_submitted(broker_name: str, lender_name: str, scen_name: str, rate: str, ltv: str, loan_amount: str, admin_url: str) -> tuple[str, str, str]:
    subject = f"{lender_name} submitted a term sheet on {scen_name}"
    text = (
        f"Hi {broker_name},\n\n"
        f"{lender_name} just submitted a term sheet on {scen_name}.\n\n"
        f"Rate: {rate}\nLoan Amount: {loan_amount}\nLTV: {ltv}\n\n"
        f"Review it here: {admin_url}\n"
    )
    html = f"""
    <div style="font-family:Georgia,serif;max-width:600px;margin:auto;">
      <div style="background:#1A1A1A;color:#C89434;padding:20px;text-align:center;">
        <div style="font-size:20px;font-weight:bold;letter-spacing:0.1em;">BYRD &amp; CO</div>
        <div style="font-size:10px;color:#C9C1AF;text-transform:uppercase;letter-spacing:0.2em;">Term Sheet Received</div>
      </div>
      <div style="padding:24px;background:#FBF8F1;color:#1A1A1A;">
        <h2 style="margin:0 0 12px;font-family:Georgia,serif;">{lender_name} submitted a term sheet</h2>
        <p style="font-family:Arial,sans-serif;font-size:14px;">On <b>{scen_name}</b>.</p>
        <table style="width:100%;font-family:Arial,sans-serif;font-size:14px;border-collapse:collapse;">
          <tr><td style="color:#6B6558;padding:4px 0;">Rate</td><td><b>{rate}</b></td></tr>
          <tr><td style="color:#6B6558;padding:4px 0;">Loan Amount</td><td>{loan_amount}</td></tr>
          <tr><td style="color:#6B6558;padding:4px 0;">LTV</td><td>{ltv}</td></tr>
        </table>
        <div style="text-align:center;margin:24px 0;">
          <a href="{admin_url}" style="background:#C89434;color:#1A1A1A;padding:12px 22px;text-decoration:none;font-family:Arial,sans-serif;font-size:13px;font-weight:bold;">Open in Admin</a>
        </div>
      </div>
    </div>
    """
    return subject, html, text


def tmpl_term_sheet_status_change(lender_name: str, scen_name: str, status: str, broker_note: str) -> tuple[str, str, str]:
    label = {"accepted": "accepted", "countered": "countered", "passed": "passed on"}.get(status, status)
    subject = f"Update on your term sheet — {scen_name}"
    note_block = f"\n\nBroker note: {broker_note}\n" if broker_note else ""
    text = (
        f"Hi {lender_name},\n\n"
        f"The broker has {label} your term sheet on {scen_name}.{note_block}\n"
        f"— Byrd & CO\n"
    )
    color = "#245C25" if status == "accepted" else ("#7A5410" if status == "countered" else "#8A1F1A")
    note_html = f"<div style=\"background:#fff;border-left:3px solid {color};padding:12px;margin:12px 0;font-family:Arial,sans-serif;font-size:13px;\">{broker_note}</div>" if broker_note else ""
    html = f"""
    <div style="font-family:Georgia,serif;max-width:600px;margin:auto;">
      <div style="background:#1A1A1A;color:#C89434;padding:20px;text-align:center;">
        <div style="font-size:20px;font-weight:bold;letter-spacing:0.1em;">BYRD &amp; CO</div>
        <div style="font-size:10px;color:#C9C1AF;text-transform:uppercase;letter-spacing:0.2em;">Term Sheet Update</div>
      </div>
      <div style="padding:24px;background:#FBF8F1;color:#1A1A1A;">
        <h2 style="margin:0 0 12px;font-family:Georgia,serif;">Broker <span style="color:{color};">{label}</span> your term sheet</h2>
        <p style="font-family:Arial,sans-serif;font-size:14px;">On <b>{scen_name}</b>.</p>
        {note_html}
      </div>
    </div>
    """
    return subject, html, text


def tmpl_password_reset(name: str, reset_url: str) -> tuple[str, str, str]:
    subject = "Reset your Byrd & CO password"
    text = (
        f"Hi {name},\n\n"
        f"Someone (hopefully you) asked to reset the password for your Byrd & CO account.\n\n"
        f"Click the link below within 60 minutes to choose a new one:\n\n"
        f"{reset_url}\n\n"
        f"If you didn't request this, you can ignore this email — your password won't change.\n\n"
        f"— Byrd & CO Commercial RE Lending\n"
    )
    html = f"""
    <div style="font-family:Georgia,serif;max-width:600px;margin:auto;">
      <div style="background:#1A1A1A;color:#C89434;padding:20px;text-align:center;">
        <div style="font-size:20px;font-weight:bold;letter-spacing:0.1em;">BYRD &amp; CO</div>
        <div style="font-size:10px;color:#C9C1AF;text-transform:uppercase;letter-spacing:0.2em;">Password Reset</div>
      </div>
      <div style="padding:24px;background:#FBF8F1;color:#1A1A1A;">
        <h2 style="margin:0 0 12px;font-family:Georgia,serif;">Hi {name},</h2>
        <p style="font-family:Arial,sans-serif;font-size:14px;line-height:1.55;">
          Someone (hopefully you) asked to reset the password for your Byrd &amp; CO account.
          Click the button below within 60 minutes to choose a new one.
        </p>
        <div style="text-align:center;margin:24px 0;">
          <a href="{reset_url}" style="background:#C89434;color:#1A1A1A;padding:14px 28px;text-decoration:none;font-family:Arial,sans-serif;font-size:14px;font-weight:bold;">Reset My Password</a>
        </div>
        <p style="font-family:Arial,sans-serif;font-size:12px;color:#6B6558;">
          Or paste this into your browser:<br/><span style="word-break:break-all;">{reset_url}</span>
        </p>
        <p style="font-family:Arial,sans-serif;font-size:12px;color:#6B6558;margin-top:24px;">
          If you didn't request this, you can ignore this email — your password won't change.
        </p>
      </div>
    </div>
    """
    return subject, html, text

