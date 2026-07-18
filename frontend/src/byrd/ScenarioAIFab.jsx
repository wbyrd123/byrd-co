import React, { useState } from "react";
import { Sparkles, X } from "lucide-react";
import ScenarioAIChat from "@/byrd/ScenarioAIChat";

/**
 * Floating "AI Assist" button + drawer for scenario pages.
 * Renders in a portal-like fixed position, opens a right-side drawer.
 */
export default function ScenarioAIFab({ scenarioId, onApplyUpdates, onSendToLender }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* FAB */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-40 h-14 pl-5 pr-6 rounded-full bg-[#1A1A1A] text-white shadow-2xl hover:bg-[#2A2A2A] inline-flex items-center gap-2 transition-transform hover:-translate-y-0.5"
          data-testid="ai-fab"
        >
          <Sparkles size={18} className="text-[#C89434]" />
          <span className="font-semibold text-sm">AI Assist</span>
        </button>
      )}

      {/* Drawer */}
      {open && (
        <div className="fixed inset-0 z-40 pointer-events-none" data-testid="ai-fab-drawer">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/30 pointer-events-auto"
            onClick={() => setOpen(false)}
          />
          {/* Panel */}
          <div className="absolute right-0 top-0 bottom-0 w-full sm:w-[440px] md:w-[520px] bg-white shadow-2xl border-l border-[#E4DFD1] pointer-events-auto flex flex-col">
            <div className="px-4 py-3 border-b border-[#E4DFD1] flex items-center justify-between">
              <div className="inline-flex items-center gap-2">
                <div className="w-8 h-8 rounded-full bg-[#F3EEE0] text-[#C89434] grid place-items-center border border-[#E4DFD1]">
                  <Sparkles size={14} />
                </div>
                <div>
                  <div className="font-serif text-lg font-bold leading-tight">AI Assist</div>
                  <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">Deal Engine · Claude</div>
                </div>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="text-[#6B6558] hover:text-[#1A1A1A] p-1"
                data-testid="ai-fab-close"
              >
                <X size={18} />
              </button>
            </div>
            <div className="flex-1 min-h-0">
              <ScenarioAIChat
                scenarioId={scenarioId}
                onApplyUpdates={onApplyUpdates}
                onSendToLender={onSendToLender}
                compact
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
