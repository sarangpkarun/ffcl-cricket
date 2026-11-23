"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { VerifyPhone } from "@/components/admin/VerifyPhone";
import { btnCls, btnGhost, ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, post, type Season } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { adminSeasons, chooseSeason, rememberSeason } from "@/lib/seasons";

type Row = { line: number; name: string; phone: string; team: string; ok: boolean; errors: string[] };
type Preview = { rows: Row[]; ok: number; errors: number };
type Invite = { id: number; name: string; phone: string; team: string | null; team_id: number; state: string; expires_at: string };
type Issued = Invite & { token: string };
type Unverified = { id: number; name: string; phone: string | null; team: string };

const TEMPLATE = "name,phone,team\nAsha Rao,+919800000001,Pink\n";
const link = (token: string) => `${window.location.origin}/join/${token}`;

function Import() {
  const { adminScope } = useAuth();
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [sid, setSid] = useState("");
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [issued, setIssued] = useState<Issued[]>([]);
  const [skipped, setSkipped] = useState<Row[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [unverified, setUnverified] = useState<Unverified[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api<Season[]>("/seasons").then((all) => { const mine = adminSeasons(all, adminScope); setSeasons(mine); setSid(String(chooseSeason(mine)?.id ?? "")); }).catch((e) => setErr(e.message));
  }, [adminScope]);
  const load = useCallback(async (current: () => boolean = () => true) => {
    if (!sid) return;
    try {
      const [i, u] = await Promise.all([api<Invite[]>(`/admin/seasons/${sid}/invites`), api<Unverified[]>(`/admin/seasons/${sid}/unverified-phones`)]);
      if (current()) { setInvites(i); setUnverified(u); }
    } catch (e) { if (current()) setErr((e as Error).message); }
  }, [sid]);
  useEffect(() => {
    let live = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset the screen when the season changes
    setPreview(null); setIssued([]); setSkipped([]);
    void load(() => live);
    return () => { live = false; };
  }, [load]);

  const run = async (fn: () => Promise<void>) => { setErr(null); try { await fn(); } catch (e) { setErr((e as Error).message); } };
  const allLinks = issued.map((i) => `${i.name}\t${i.phone}\t${i.team ?? ""}\t${link(i.token)}`).join("\n");

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Add players</h1>
      <select aria-label="Season" className={inputCls} value={sid} onChange={(e) => { rememberSeason(e.target.value); setSid(e.target.value); }}>
        {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
      <ErrorText msg={err} />

      <section className="space-y-2" aria-label="Import players">
        <h2 className="font-medium">1. Paste or upload the list</h2>
        <p className="text-xs text-muted-foreground">One player per line: name, phone and the team&apos;s name. Each person gets a private link that creates their account, verifies their number (you vouch for it) and puts them in the team.</p>
        <textarea aria-label="Players (CSV)" className={`${inputCls} h-40 font-mono text-sm`} placeholder={TEMPLATE} value={text} onChange={(e) => { setText(e.target.value); setPreview(null); }} />
        <input type="file" accept=".csv,text/csv,text/plain" aria-label="Upload a CSV file" onChange={async (e) => { const f = e.target.files?.[0]; if (f) { setText(await f.text()); setPreview(null); } }} />
        <button className={btnGhost} disabled={!text.trim() || !sid} onClick={() => run(async () => { setPreview(await post<Preview>(`/admin/seasons/${sid}/invites/preview`, { csv: text })); })}>Check the list</button>
      </section>

      {preview && (
        <section className="space-y-2" aria-label="Check result">
          <h2 className="font-medium">2. Check</h2>
          <p role="status" className="text-sm">{preview.ok} ready{preview.errors > 0 && `, ${preview.errors} with problems (they are skipped)`}.</p>
          <ul className="space-y-1 text-sm">
            {preview.rows.map((r) => (
              <li key={r.line} className={`rounded border p-2 ${r.ok ? "" : "border-red-500"}`}>
                <b>{r.name || "(no name)"}</b> · {r.phone} · {r.team} <span className="text-xs text-muted-foreground">line {r.line}</span>
                {r.errors.map((m) => <p key={m} className="text-xs text-red-700">{m}</p>)}
              </li>
            ))}
          </ul>
          <button className={btnCls} disabled={preview.ok === 0} onClick={() => run(async () => {
            const r = await post<{ invites: Issued[]; skipped: Row[] }>(`/admin/seasons/${sid}/invites`, { csv: text });
            setIssued(r.invites); setSkipped(r.skipped); setPreview(null); setText(""); await load();
          })}>Create {preview.ok} invite link{preview.ok === 1 ? "" : "s"}</button>
        </section>
      )}

      {issued.length > 0 && (
        <section className="space-y-2" aria-label="New links">
          <h2 className="font-medium">3. Send the links</h2>
          <p role="status" className="rounded-lg bg-muted p-2 text-sm">The links are shown only now and expire in 14 days. Each works once. If one is lost, reissue it below.</p>
          <div className="flex gap-2 print:hidden">
            <button className={btnGhost} onClick={async () => { try { await navigator.clipboard.writeText(allLinks); setCopied(true); } catch { setErr("Could not copy; select the links and copy them by hand"); } }}>{copied ? "Copied" : "Copy all"}</button>
            <button className={btnGhost} onClick={() => window.print()}>Print</button>
          </div>
          <ul className="space-y-2 text-sm">
            {issued.map((i) => <li key={i.id} className="rounded border p-2"><b>{i.name}</b> · {i.team}<br /><span className="break-all font-mono text-xs">{link(i.token)}</span></li>)}
          </ul>
          {skipped.length > 0 && <p className="text-sm text-red-700">{skipped.length} row{skipped.length === 1 ? " was" : "s were"} skipped: {skipped.map((r) => `line ${r.line}`).join(", ")}.</p>}
        </section>
      )}

      <section className="space-y-2 print:hidden" aria-label="Invites">
        <h2 className="font-medium">Invites for this season</h2>
        {invites.length === 0 && <p className="text-sm text-muted-foreground">None yet.</p>}
        <ul className="space-y-2 text-sm">
          {invites.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 rounded border p-2">
              <span><b>{i.name}</b> · {i.team} · {i.state}</span>
              {i.state !== "used" && (
                <span className="flex gap-2">
                  {i.state === "open" && <button className={btnGhost} onClick={() => run(async () => { await post(`/admin/invites/${i.id}/revoke`); await load(); })}>Revoke</button>}
                  <button className={btnGhost} onClick={() => run(async () => { const n = await post<Issued>(`/admin/invites/${i.id}/reissue`); setIssued((cur) => [n, ...cur]); await load(); })}>New link</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2 print:hidden" aria-label="Numbers to verify">
        <h2 className="font-medium">Numbers nobody has verified</h2>
        {unverified.length === 0 && <p className="text-sm text-muted-foreground">Every member&apos;s number is verified.</p>}
        <ul className="space-y-2 text-sm">
          {unverified.map((u) => (
            <li key={u.id} className="space-y-1 rounded border p-2"><p><b>{u.name}</b> · {u.team} · {u.phone}</p><VerifyPhone u={u} onDone={() => void load()} /></li>
          ))}
        </ul>
      </section>
      <p className="text-xs"><Link className="underline" href="/admin">Back to admin</Link></p>
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin><Import /></RequireAuth>;
}
