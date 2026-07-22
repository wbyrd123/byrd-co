import React from "react";
import { Link } from "react-router-dom";
import { LOGO_URL, CONTACT } from "@/byrd/data";
import { Phone, Mail, MapPin } from "lucide-react";

export default function BrandFooter() {
  return (
    <footer className="bg-[#1A1A1A] text-[#FBF8F1] mt-24">
      <div className="max-w-7xl mx-auto px-5 sm:px-8 py-14">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-10">
          <div className="md:col-span-2">
            <img src={LOGO_URL} alt="Byrd & CO" className="h-14 w-auto bg-white p-2 rounded-md" />
            <p className="mt-5 text-sm text-[#C9C1AF] max-w-md leading-relaxed">
              Byrd &amp; CO is a commercial real estate lending brokerage placing debt across multifamily,
              hospitality, office, condo and 1–4 unit properties nationwide.
            </p>
          </div>
          <div>
            <div className="font-serif text-lg font-semibold text-[#E5B968]">Wayne Byrd</div>
            <div className="text-xs uppercase tracking-widest text-[#8F8877] mt-1">Principal</div>
            <div className="mt-3 space-y-2 text-sm">
              <a href={`tel:${CONTACT.wayne.phone}`} className="flex items-center gap-2 hover:text-[#E5B968]">
                <Phone size={14} /> {CONTACT.wayne.phone}
              </a>
              <a href={`mailto:${CONTACT.wayne.email}`} className="flex items-center gap-2 hover:text-[#E5B968] break-all">
                <Mail size={14} /> {CONTACT.wayne.email}
              </a>
            </div>
          </div>
          <div>
            <div className="font-serif text-lg font-semibold text-[#E5B968]">Caleb Byrd</div>
            <div className="text-xs uppercase tracking-widest text-[#8F8877] mt-1">Principal</div>
            <div className="mt-3 space-y-2 text-sm">
              <a href={`tel:${CONTACT.caleb.phone}`} className="flex items-center gap-2 hover:text-[#E5B968]">
                <Phone size={14} /> {CONTACT.caleb.phone}
              </a>
              <a href={`mailto:${CONTACT.caleb.email}`} className="flex items-center gap-2 hover:text-[#E5B968] break-all">
                <Mail size={14} /> {CONTACT.caleb.email}
              </a>
            </div>
          </div>
        </div>

        <div className="border-t border-[#3A3A3A] mt-12 pt-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="font-mono text-[11px] uppercase tracking-widest text-[#8F8877]">
            © {new Date().getFullYear()} Byrd &amp; CO Commercial RE Lending — All rights reserved
          </div>
          <div className="flex items-center gap-4 text-sm flex-wrap">
            <Link to="/portal/login" className="text-[#C9C1AF] hover:text-[#E5B968]">Client Login</Link>
            <Link to="/lenders/apply" className="text-[#C9C1AF] hover:text-[#E5B968]" data-testid="footer-lender-apply">Become a Lending Partner</Link>
            <a href="#contact" className="text-[#C9C1AF] hover:text-[#E5B968]">Contact</a>
          </div>
        </div>
      </div>
    </footer>
  );
}
