import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  MessageSquareQuote, Plus, Save, Trash2, X, Star, ArrowUp, ArrowDown, Eye, EyeOff, Image as ImageIcon,
} from "lucide-react";

const emptyForm = { name: "", title: "", quote: "", rating: 5, avatar: "", published: true };

export default function AdminTestimonials() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // null | "new" | id

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.get("/admin/testimonials");
      setItems(res.data);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const save = async (payload, tid) => {
    if (tid === "new") {
      await api.post("/admin/testimonials", payload);
      toast.success("Testimonial added");
    } else {
      await api.patch(`/admin/testimonials/${tid}`, payload);
      toast.success("Testimonial updated");
    }
    setEditing(null);
    load();
  };

  const remove = async (t) => {
    if (!window.confirm(`Delete "${t.name}"? This can't be undone.`)) return;
    await api.delete(`/admin/testimonials/${t.id}`);
    toast.success("Removed");
    load();
  };

  const togglePublished = async (t) => {
    await api.patch(`/admin/testimonials/${t.id}`, { published: !t.published });
    load();
  };

  const move = async (index, dir) => {
    const next = [...items];
    const j = index + dir;
    if (j < 0 || j >= next.length) return;
    [next[index], next[j]] = [next[j], next[index]];
    setItems(next);
    await api.post("/admin/testimonials/reorder", { order: next.map((x) => x.id) });
  };

  return (
    <div className="space-y-6" data-testid="admin-testimonials">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase text-[#6B6558] tracking-widest">// Marketing</div>
          <h1 className="font-serif text-4xl md:text-5xl font-bold mt-2">Testimonials.</h1>
          <p className="text-sm text-[#6B6558] mt-2 max-w-xl">
            These appear on your public homepage (<code className="font-mono text-xs">byrd-co.com</code>). Only <b>published</b> testimonials
            are shown. Reorder to control what visitors see first.
          </p>
        </div>
        <button
          onClick={() => setEditing("new")}
          className="byrd-btn byrd-btn-dark"
          data-testid="new-testimonial-btn"
        >
          <Plus size={14} /> New Testimonial
        </button>
      </div>

      {loading ? (
        <div className="text-sm text-[#6B6558]">Loading…</div>
      ) : items.length === 0 ? (
        <EmptyState onCreate={() => setEditing("new")} />
      ) : (
        <div className="space-y-3">
          {items.map((t, i) => (
            <TestimonialRow
              key={t.id}
              t={t}
              index={i}
              total={items.length}
              onEdit={() => setEditing(t.id)}
              onRemove={() => remove(t)}
              onTogglePublish={() => togglePublished(t)}
              onMoveUp={() => move(i, -1)}
              onMoveDown={() => move(i, +1)}
            />
          ))}
        </div>
      )}

      {editing && (
        <TestimonialDialog
          initial={
            editing === "new"
              ? emptyForm
              : items.find((x) => x.id === editing) || emptyForm
          }
          isNew={editing === "new"}
          onClose={() => setEditing(null)}
          onSave={(payload) => save(payload, editing)}
        />
      )}
    </div>
  );
}

function EmptyState({ onCreate }) {
  return (
    <div className="byrd-card p-10 text-center">
      <div className="w-14 h-14 mx-auto rounded-full bg-[#F3EEE0] grid place-items-center text-[#C89434]">
        <MessageSquareQuote size={22} />
      </div>
      <h3 className="font-serif text-2xl font-bold mt-4">No testimonials yet.</h3>
      <p className="text-[#6B6558] mt-2 max-w-md mx-auto">
        Add client quotes to build trust on your homepage. Rating stars, avatar, and title all show up publicly.
      </p>
      <button onClick={onCreate} className="byrd-btn byrd-btn-primary mt-5">
        Add First Testimonial <Plus size={14} />
      </button>
    </div>
  );
}

function Stars({ n }) {
  return (
    <div className="inline-flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          size={12}
          className={i <= n ? "fill-[#C89434] text-[#C89434]" : "text-[#E4DFD1]"}
        />
      ))}
    </div>
  );
}

function TestimonialRow({ t, index, total, onEdit, onRemove, onTogglePublish, onMoveUp, onMoveDown }) {
  return (
    <div className="byrd-card p-4 flex items-start gap-4" data-testid={`testimonial-row-${t.id}`}>
      {/* Order controls */}
      <div className="flex flex-col gap-1 pt-1">
        <button
          onClick={onMoveUp}
          disabled={index === 0}
          className="w-7 h-7 grid place-items-center rounded-md border border-[#E4DFD1] disabled:opacity-30 disabled:cursor-not-allowed hover:bg-[#F3EEE0]"
          title="Move up"
          data-testid={`move-up-${t.id}`}
        >
          <ArrowUp size={12} />
        </button>
        <button
          onClick={onMoveDown}
          disabled={index === total - 1}
          className="w-7 h-7 grid place-items-center rounded-md border border-[#E4DFD1] disabled:opacity-30 disabled:cursor-not-allowed hover:bg-[#F3EEE0]"
          title="Move down"
          data-testid={`move-down-${t.id}`}
        >
          <ArrowDown size={12} />
        </button>
      </div>

      {/* Avatar */}
      <div className="w-14 h-14 rounded-full bg-[#F3EEE0] overflow-hidden shrink-0 border border-[#E4DFD1] grid place-items-center">
        {t.avatar ? (
          <img src={t.avatar} alt={t.name} className="w-full h-full object-cover" />
        ) : (
          <span className="font-serif text-lg font-bold text-[#C89434]">{(t.name || "?")[0]}</span>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="font-semibold">{t.name}</div>
          <Stars n={t.rating || 5} />
          {t.published ? (
            <span className="byrd-chip byrd-chip-green"><Eye size={10} /> Published</span>
          ) : (
            <span className="byrd-chip"><EyeOff size={10} /> Draft</span>
          )}
        </div>
        {t.title && <div className="text-xs text-[#6B6558] mt-0.5">{t.title}</div>}
        <div className="text-sm text-[#2A2A2A] mt-2 italic leading-relaxed">&ldquo;{t.quote}&rdquo;</div>
      </div>

      {/* Actions */}
      <div className="flex flex-col gap-2 shrink-0">
        <button onClick={onEdit} className="byrd-btn byrd-btn-outline h-9 px-3 text-xs" data-testid={`edit-testimonial-${t.id}`}>
          Edit
        </button>
        <button
          onClick={onTogglePublish}
          className="byrd-btn byrd-btn-outline h-9 px-3 text-xs"
          data-testid={`toggle-testimonial-${t.id}`}
        >
          {t.published ? <><EyeOff size={12} /> Unpublish</> : <><Eye size={12} /> Publish</>}
        </button>
        <button
          onClick={onRemove}
          className="byrd-btn byrd-btn-outline h-9 px-3 text-xs text-[#8A1F1A] border-[#E38380] hover:bg-[#FADCDA]"
          data-testid={`remove-testimonial-${t.id}`}
        >
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  );
}

function TestimonialDialog({ initial, isNew, onClose, onSave }) {
  const [form, setForm] = useState({ ...initial });
  const [busy, setBusy] = useState(false);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name?.trim() || !form.quote?.trim()) {
      toast.error("Name and quote are required");
      return;
    }
    setBusy(true);
    try {
      await onSave({
        name: form.name.trim(),
        title: (form.title || "").trim(),
        quote: form.quote.trim(),
        rating: Number(form.rating) || 5,
        avatar: (form.avatar || "").trim(),
        published: !!form.published,
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={onClose} role="dialog" data-testid="testimonial-dialog">
      <div className="bg-white rounded-lg border border-[#E4DFD1] shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-[#E4DFD1] flex items-start justify-between">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-[#6B6558]">
              {isNew ? "// New Testimonial" : "// Edit Testimonial"}
            </div>
            <h2 className="font-serif text-2xl font-bold mt-1">{isNew ? "Add a quote" : "Update quote"}</h2>
          </div>
          <button onClick={onClose} className="w-9 h-9 grid place-items-center rounded-md border border-[#E4DFD1]" data-testid="testimonial-dialog-close">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-4 overflow-y-auto">
          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Name *</label>
            <input
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              required
              placeholder="e.g. Marcus Reyes"
              data-testid="t-name"
              className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
            />
          </div>

          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Title / Company · City</label>
            <input
              value={form.title || ""}
              onChange={(e) => set("title", e.target.value)}
              placeholder="e.g. Multifamily Investor · Houston, TX"
              data-testid="t-title"
              className="mt-1 w-full h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
            />
          </div>

          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Quote *</label>
            <textarea
              value={form.quote}
              onChange={(e) => set("quote", e.target.value)}
              required
              rows={4}
              placeholder="What did they say about working with Byrd & CO?"
              data-testid="t-quote"
              className="mt-1 w-full px-3 py-2 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434] resize-y"
            />
            <div className="text-[10px] text-[#6B6558] mt-1">{(form.quote || "").length}/1000 · quotes read best under ~280 characters</div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Rating</label>
              <div className="mt-2 inline-flex items-center gap-1" data-testid="t-rating">
                {[1, 2, 3, 4, 5].map((i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => set("rating", i)}
                    className="p-0.5"
                    aria-label={`${i} stars`}
                    data-testid={`t-rating-${i}`}
                  >
                    <Star
                      size={22}
                      className={i <= (Number(form.rating) || 5) ? "fill-[#C89434] text-[#C89434]" : "text-[#E4DFD1] hover:text-[#C89434]/50"}
                    />
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Visibility</label>
              <div className="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => set("published", true)}
                  className={`px-3 h-9 rounded-md border text-xs inline-flex items-center gap-1 ${
                    form.published ? "bg-[#245C25] text-white border-[#245C25]" : "bg-white border-[#E4DFD1]"
                  }`}
                  data-testid="t-publish"
                >
                  <Eye size={12} /> Published
                </button>
                <button
                  type="button"
                  onClick={() => set("published", false)}
                  className={`px-3 h-9 rounded-md border text-xs inline-flex items-center gap-1 ${
                    !form.published ? "bg-[#1A1A1A] text-white border-[#1A1A1A]" : "bg-white border-[#E4DFD1]"
                  }`}
                  data-testid="t-draft"
                >
                  <EyeOff size={12} /> Draft
                </button>
              </div>
            </div>
          </div>

          <div>
            <label className="text-[10px] font-mono uppercase tracking-widest text-[#6B6558]">Avatar URL <span className="normal-case text-[#6B6558]">(optional)</span></label>
            <div className="flex items-center gap-3">
              <input
                value={form.avatar || ""}
                onChange={(e) => set("avatar", e.target.value)}
                placeholder="https://…"
                data-testid="t-avatar"
                className="mt-1 flex-1 h-11 px-3 rounded-md border border-[#E4DFD1] bg-white focus:outline-none focus:ring-2 focus:ring-[#C89434]/40 focus:border-[#C89434]"
              />
              <div className="w-11 h-11 rounded-full overflow-hidden border border-[#E4DFD1] bg-[#F3EEE0] grid place-items-center shrink-0 mt-1">
                {form.avatar ? (
                  <img src={form.avatar} alt="" className="w-full h-full object-cover" />
                ) : (
                  <ImageIcon size={14} className="text-[#6B6558]" />
                )}
              </div>
            </div>
            <div className="text-[10px] text-[#6B6558] mt-1">
              Leave blank to show initials. Any hotlinkable image URL works (e.g. LinkedIn photo, Unsplash, uploaded image).
            </div>
          </div>
        </form>

        <div className="px-6 py-4 border-t border-[#E4DFD1] flex items-center gap-2">
          <button onClick={onClose} className="byrd-btn byrd-btn-outline flex-1" data-testid="testimonial-dialog-cancel">
            Cancel
          </button>
          <button onClick={submit} disabled={busy} className="byrd-btn byrd-btn-dark flex-1" data-testid="testimonial-dialog-save">
            {busy ? "Saving…" : <><Save size={14} /> {isNew ? "Add Testimonial" : "Save Changes"}</>}
          </button>
        </div>
      </div>
    </div>
  );
}
