import React, { useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { ShieldCheck, HelpCircle, X } from "lucide-react";

/**
 * Compact header widget for the client + lender portals.
 * - If 2FA is not enabled: shows "Enable 2FA" pill with a "?" that opens a description modal
 * - If 2FA is enabled: shows a small "2FA On" badge (clickable → Security page)
 * `securityPath` defaults to /portal/security; pass /lender/portal/security for lenders.
 */
export default function TwoFAHeaderLink({ enabled, securityPath = "/portal/security" }) {
  const [helpOpen, setHelpOpen] = useState(false);

  if (enabled) {
    return (
      <Link
        to={securityPath}
        data-testid="two-fa-header-status"
        className="hidden sm:inline-flex items-center gap-1.5 h-10 px-3 rounded-md border border-[#1A1A1A] bg-[#1A1A1A] text-[#C89434] text-xs font-mono uppercase tracking-widest hover:opacity-90"
        title="Manage 2FA"
      >
        <ShieldCheck size={14} /> 2FA On
      </Link>
    );
  }

  return (
    <>
      <div className="hidden sm:inline-flex items-center">
        <Link
          to={securityPath}
          data-testid="two-fa-header-enable"
          className="inline-flex items-center gap-1.5 h-10 pl-3 pr-2 rounded-l-md border border-[#C89434] bg-[#C89434] text-[#1A1A1A] text-xs font-mono uppercase tracking-widest hover:brightness-95"
        >
          <ShieldCheck size={14} /> Enable 2FA
        </Link>
        <button
          type="button"
          onClick={() => setHelpOpen(true)}
          data-testid="two-fa-header-help"
          aria-label="What is 2FA?"
          className="h-10 px-2 rounded-r-md border border-l-0 border-[#C89434] bg-[#C89434] text-[#1A1A1A] hover:brightness-95"
          title="What is 2FA?"
        >
          <HelpCircle size={14} />
        </button>
      </div>

      {helpOpen && createPortal(
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => setHelpOpen(false)}
        >
          <div
            className="bg-[#FBF8F1] max-w-md w-full rounded-md shadow-xl p-6"
            onClick={(e) => e.stopPropagation()}
            data-testid="two-fa-help-modal"
          >
            <div className="flex items-center justify-between mb-3">
              <div className="font-serif text-lg font-bold flex items-center gap-2">
                <ShieldCheck size={18} className="text-[#C89434]" />
                What is Two-Factor Authentication?
              </div>
              <button
                onClick={() => setHelpOpen(false)}
                className="text-[#6B6558] hover:text-[#1A1A1A]"
                data-testid="two-fa-help-close"
              >
                <X size={18} />
              </button>
            </div>

            <div className="space-y-3 text-sm text-[#2A2A2A] leading-relaxed">
              <p>
                Two-factor authentication (2FA) is a second layer of protection on your account.
                Instead of only needing your password to sign in, you'll also enter a fresh 6-digit code.
              </p>
              <p className="text-[#6B6558]">
                <b>Why it matters:</b> your Byrd &amp; CO portal holds sensitive financial documents — tax returns,
                PFS, entity docs. Even if someone learned your password, they still couldn't get in without the
                second code.
              </p>
              <div className="pt-2 border-t border-[#E4DFD1]">
                <div className="font-serif font-bold mb-2">You'll be able to pick from:</div>
                <ul className="list-disc list-inside space-y-1.5 text-[#2A2A2A]">
                  <li>
                    <b>Authenticator App</b> (recommended) — codes come from 1Password, Google Authenticator,
                    Authy, or Microsoft Authenticator. Strongest security.
                  </li>
                  <li>
                    <b>Email Code</b> — we send a fresh 6-digit code to your inbox each time you sign in.
                    No app to install.
                  </li>
                </ul>
              </div>
              <p className="text-xs text-[#6B6558] pt-1">
                Setup takes about 60 seconds and you'll also get 10 downloadable backup codes as a lifeline.
              </p>
            </div>

            <div className="flex justify-end gap-2 mt-5 pt-4 border-t border-[#E4DFD1]">
              <button
                onClick={() => setHelpOpen(false)}
                className="byrd-btn byrd-btn-outline"
                data-testid="two-fa-help-later"
              >
                Maybe later
              </button>
              <Link
                to={securityPath}
                onClick={() => setHelpOpen(false)}
                data-testid="two-fa-help-goto"
                className="byrd-btn byrd-btn-dark"
              >
                <ShieldCheck size={14} /> Set it up now
              </Link>
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
