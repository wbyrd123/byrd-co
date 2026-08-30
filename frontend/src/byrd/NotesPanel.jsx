import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { MessageSquare, Plus, PenLine, Trash2, X, Send } from "lucide-react";

/**
 * NotesPanel — shared conversation trail for a scenario or a specific document.
 *
 * Props:
 *   scenarioId (required unless fetchUrl set)
 *   docId       (optional) — null/undefined = general scenario notes; string = per-doc notes
 *   title       (default "Notes")
 *   readOnly    (default false)
 *   compact     (default false) — tighter styling for inline / doc-row use
 *   fetchUrl    (optional) — override GET endpoint (used by LenderView token pages)
 *
 * All parties on the scenario see all notes. Author (or admin) can edit / delete their own.
 */
export default function NotesPanel({
  scenarioId, docId, title = "Notes",
  readOnly = false, compact = false, fetchUrl = null,
}) {
  const [state, setState] = useState({ notes: [], editable: false, currentUserId: null, loading: true });
  const [draft, setDraft] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editBody, setEditBody] = useState("");
  const [busy, setBusy] = useState(false);

  const listUrl = fetchUrl || `/scenarios/${scenarioId}/notes${docId ? `?doc_id=${docId}` : ""}`;

  const load = async () => {
    try {
      const res = await api.get(listUrl);
      setState({
        notes: res.data.notes || [],
        editable: !!res.data.editable && !readOnly && !fetchUrl,
        currentUserId: res.data.current_user_id || null,
        loading: false,
      });
    } catch (e) {
      setState((s) => ({ ...s, loading: false }));
      toast.error(e?.response?.data?.detail || "Couldn't load notes");
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [scenarioId, docId, fetchUrl]);

  const submitNew = async () => {
    const body = draft.trim();
    if (!body) return;
    setBusy(true);
    try {
      await api.post(`/scenarios/${scenarioId}/notes`, { body, doc_id: docId || null });
      setDraft("");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't save note");
    } finally { setBusy(false); }
  };

  const beginEdit = (n) => { setEditingId(n.id); setEditBody(n.body); };
  const cancelEdit = () => { setEditingId(null); setEditBody(""); };

  const submitEdit = async (n) => {
    const body = editBody.trim();
    if (!body) return;
    setBusy(true);
    try {
      await api.patch(`/scenarios/${scenarioId}/notes/${n.id}`, { body, doc_id: n.doc_id });
      cancelEdit();
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't update note");
    } finally { setBusy(false); }
  };

  const remove = async (n) => {
    if (!window.confirm("Delete this note?")) return;
    try {
      await api.delete(`/scenarios/${scenarioId}/notes/${n.id}`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't delete note");
    }
  };

  const canModify = (n) => state.editable && n.author_id === state.currentUserId;
  const canModifyAsAdmin = () => state.editable; // note: server also allows admin over any note

  const roleBadge = (role) => {
    const map = { admin: ["Byrd & CO", "bg-[#1A1A1A] text-[#C89434]"],
                  client: ["Borrower",  "bg-[#F1EBDD] text-[#8A6A1F]"],
                  lender: ["Lender",    "bg-[#EDE7F3] text-[#4B357A]"] };
    const [label, cls] = map[role] || [role || "", "bg-[#F3EEE0] text-[#2A2A2A]"];
    return <span className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-widest ${cls}`}>{label}</span>;
  };

  if (state.loading) {
    return <div className="byrd-card p-4 text-sm text-[#6B6558]" data-testid="notes-loading">Loading notes…</div>;
  }

  return (
    <div className={`byrd-card ${compact ? "p-4" : "p-5"}`} data-testid={docId ? `doc-notes-${docId}` : "general-notes-panel"}>
      <div className="flex items-center gap-2 mb-3">
        <div className="w-8 h-8 rounded-md grid place-items-center bg-[#1A1A1A] text-[#C89434] shrink-0">
          <MessageSquare size={15} />
        </div>
        <div>
          <div className="font-serif font-bold leading-tight">{title}</div>
          <div className="text-[10px] uppercase font-mono tracking-widest text-[#6B6558]">
            {docId ? "// Visible to all parties on this document" : "// Shared with Byrd & CO, you, and invited lenders"}
          </div>
        </div>
      </div>

      {state.notes.length === 0 && !state.editable && (
        <div className="text-xs text-[#6B6558] italic">No notes yet.</div>
      )}

      <div className="space-y-2">
        {state.notes.map((n) => {
          const isEditing = editingId === n.id;
          const modifiable = canModify(n) || (state.editable && canModifyAsAdmin && n.author_role !== "admin" && state.currentUserId && n.author_id !== state.currentUserId && false);
          return (
            <div key={n.id} className="border border-[#E4DFD1] rounded-md p-2.5 bg-white" data-testid={`note-${n.id}`}>
              <div className="flex items-center gap-2 mb-1">
                {roleBadge(n.author_role)}
                <span className="text-xs font-medium text-[#2A2A2A] truncate">{n.author_name || "—"}</span>
                <span className="text-[10px] text-[#6B6558] ml-auto whitespace-nowrap">
                  {n.updated_at && n.updated_at !== n.created_at
                    ? `edited ${new Date(n.updated_at).toLocaleString()}`
                    : new Date(n.created_at).toLocaleString()}
                </span>
              </div>
              {isEditing ? (
                <div>
                  <textarea
                    value={editBody}
                    onChange={(e) => setEditBody(e.target.value)}
                    rows={2}
                    data-testid={`note-edit-${n.id}`}
                    className="w-full px-2 py-1.5 rounded-md border border-[#C89434] bg-white text-sm resize-y"
                    autoFocus
                  />
                  <div className="flex justify-end gap-1.5 mt-1.5">
                    <button onClick={cancelEdit} data-testid={`note-cancel-${n.id}`} className="text-xs text-[#6B6558] hover:text-[#1A1A1A] px-2 py-1">Cancel</button>
                    <button onClick={() => submitEdit(n)} disabled={busy || !editBody.trim()} data-testid={`note-save-${n.id}`} className="text-xs bg-[#1A1A1A] text-[#C89434] rounded-md px-3 py-1 disabled:opacity-50">
                      {busy ? "Saving…" : "Save"}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="text-sm text-[#2A2A2A] whitespace-pre-wrap leading-relaxed">{n.body}</div>
                  {canModify(n) && !readOnly && (
                    <div className="flex justify-end gap-1 mt-1">
                      <button onClick={() => beginEdit(n)} data-testid={`note-edit-btn-${n.id}`} className="p-1 text-[#6B6558] hover:text-[#1A1A1A]" title="Edit"><PenLine size={11} /></button>
                      <button onClick={() => remove(n)} data-testid={`note-delete-btn-${n.id}`} className="p-1 text-[#6B6558] hover:text-[#B23B3B]" title="Delete"><Trash2 size={11} /></button>
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>

      {state.editable && !readOnly && (
        <div className="mt-3">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={docId ? "Add a note about this document…" : "Add a note for this deal…"}
            rows={2}
            data-testid={docId ? `doc-notes-input-${docId}` : "general-notes-input"}
            className="w-full px-2 py-2 rounded-md border border-[#E4DFD1] bg-white text-sm resize-y focus:outline-none focus:ring-1 focus:ring-[#C89434]"
          />
          <div className="flex justify-end mt-1.5">
            <button
              onClick={submitNew}
              disabled={busy || !draft.trim()}
              data-testid={docId ? `doc-notes-submit-${docId}` : "general-notes-submit"}
              className="inline-flex items-center gap-1 text-xs bg-[#1A1A1A] text-[#C89434] rounded-md px-3 py-1.5 disabled:opacity-50 hover:brightness-110"
            >
              <Send size={12} /> {busy ? "Posting…" : "Post note"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Compact "Notes" button for a single document row. Shows a badge with note count and,
 *  when clicked, expands into the NotesPanel inline right beneath the row. */
export function DocNoteButton({ scenarioId, docId, count = 0, open, onToggle }) {
  return (
    <button
      onClick={onToggle}
      data-testid={`doc-note-btn-${docId}`}
      className={`relative inline-flex items-center gap-1 text-xs rounded-md border px-2 py-1 transition-colors ${
        open ? "bg-[#1A1A1A] text-[#C89434] border-[#1A1A1A]"
             : "border-[#E4DFD1] text-[#6B6558] hover:text-[#1A1A1A] hover:bg-[#F3EEE0]"
      }`}
      title={count > 0 ? `${count} note${count === 1 ? "" : "s"}` : "Add a note"}
    >
      <MessageSquare size={11} />
      {count > 0 ? "Notes" : "Add Note"}
      {count > 0 && (
        <span
          data-testid={`doc-note-badge-${docId}`}
          className="ml-0.5 inline-flex items-center justify-center min-w-[16px] h-[16px] rounded-full bg-[#C89434] text-[#1A1A1A] text-[10px] font-bold px-1"
        >
          {count}
        </span>
      )}
    </button>
  );
}
