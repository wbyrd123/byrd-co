import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { ShieldCheck, ArrowLeft } from "lucide-react";

export default function LendersTermsPage() {
  const [terms, setTerms] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/public/lender/terms")
      .then((r) => setTerms(r.data))
      .catch((e) => setErr(e?.response?.data?.detail || "Unable to load terms"));
  }, []);

  return (
    <div className="min-h-screen bg-[#FBF8F1]" data-testid="lender-terms-page">
      <div className="max-w-3xl mx-auto px-4 py-10 md:py-14">
        <Link
          to="/lenders/apply"
          className="inline-flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-[#6B6558] hover:text-[#C89434]"
          data-testid="back-to-apply"
        >
          <ArrowLeft size={12} /> Back to lender application
        </Link>

        <div className="bg-white border border-[#C89434] rounded-md p-6 md:p-8 mt-6">
          <div className="flex items-center gap-2 mb-1">
            <ShieldCheck size={22} className="text-[#C89434]" />
            <span className="text-xs font-mono uppercase tracking-widest text-[#C89434]">
              Byrd &amp; CO Lending Partners
            </span>
          </div>
          <h1 className="font-serif text-3xl md:text-4xl font-bold">
            {terms?.title || "Lender Non-Circumvention Agreement"}
          </h1>
          <div className="flex items-center gap-3 text-xs text-[#6B6558] mt-2">
            {terms?.version && <span>Version {terms.version}</span>}
            {terms?.effective_date && <span>· Effective {terms.effective_date}</span>}
          </div>

          {err && (
            <div className="mt-6 text-sm text-[#8A1F1A]" data-testid="terms-error">
              {err}
            </div>
          )}

          {terms?.text && (
            <div
              className="mt-6 text-sm text-[#1A1A1A] whitespace-pre-line leading-relaxed"
              data-testid="terms-body"
            >
              {terms.text}
            </div>
          )}

          <div className="mt-8 pt-6 border-t border-[#E4DFD1] text-xs text-[#6B6558]">
            Questions? Contact <a href="mailto:brokers@byrd-co.com" className="underline hover:text-[#C89434]">brokers@byrd-co.com</a>.
          </div>
        </div>
      </div>
    </div>
  );
}
