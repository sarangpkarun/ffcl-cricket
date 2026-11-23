"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { btnCls, btnGhost, ErrorText, Field, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, del, download, patch, post, type Bracket, type Fixture, type Season, type Standings, type Team } from "@/lib/api";

type PreviewRow = {
  index: number; round_no: number; team_a: string; team_b: string; scheduled_at: string;
  umpire: string | null; warnings: string[];
};
type Preview = {
  matches: PreviewRow[];
  summary: { teams: number; matches: number; rounds: number; without_umpire: number | null; with_warnings: number };
};
type Published = { published: number; notified: number; without_umpire: number[] };
type Umpire = { id: number; name: string };

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const show = (iso: string) => new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
const toLocalInput = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};
const tomorrow = () => {
  const d = new Date(Date.now() + 86_400_000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

function DraftRow({ f, umpires, onChange }: { f: Fixture; umpires: Umpire[]; onChange: () => void }) {
  const [when, setWhen] = useState(toLocalInput(f.scheduled_at));
  const [umpire, setUmpire] = useState(f.umpire_id ? String(f.umpire_id) : "");
  const [err, setErr] = useState<string | null>(null);
  // The list of umpires is capped, so always offer the one already assigned or the dropdown would lie.
  const options = f.umpire_id && !umpires.some((u) => u.id === f.umpire_id)
    ? [{ id: f.umpire_id, name: f.umpire ?? `#${f.umpire_id}` }, ...umpires]
    : umpires;
  const save = async (force = false) => {
    setErr(null);
    try {
      await patch(`/matches/${f.id}`, {
        scheduled_at: when ? new Date(when).toISOString() : null,
        umpire_id: umpire ? Number(umpire) : null,
        force,
      });
      onChange();
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <li className="space-y-2 rounded-lg border p-3" aria-label={`Draft match ${f.match_no}`}>
      <p className="text-sm font-medium">{f.round_label} · {f.team_a.name} vs {f.team_b.name}</p>
      <div className="flex flex-wrap gap-2">
        <input type="datetime-local" aria-label={`Time for match ${f.match_no}`} className="rounded border bg-background px-2 py-2 text-sm" value={when} onChange={(e) => setWhen(e.target.value)} />
        <select aria-label={`Umpire for match ${f.match_no}`} className="rounded border bg-background px-2 py-2 text-sm" value={umpire} onChange={(e) => setUmpire(e.target.value)}>
          <option value="">No umpire</option>
          {options.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </select>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className={btnGhost} onClick={() => void save()}>Save</button>
        <button className={btnGhost} onClick={async () => { try { await del(`/matches/${f.id}`); onChange(); } catch (e) { setErr((e as Error).message); } }}>Delete</button>
        {err?.startsWith("Clash") && <button className={btnGhost} onClick={() => void save(true)}>Save anyway</button>}
      </div>
      <ErrorText msg={err} />
    </li>
  );
}

function SeasonAdmin({ id }: { id: string }) {
  const [season, setSeason] = useState<Season | null>(null);
  const status = season?.status ?? null;
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  useEffect(() => { api<Season>(`/seasons/${id}`).then(setSeason).catch(() => {}); }, [id]);
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try { await fn(); setSeason(await api<Season>(`/seasons/${id}`)); setConfirm(false); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <section aria-label="Season archive and exports" className="space-y-3 rounded-lg border p-4">
      <h2 className="font-medium">Archive and exports</h2>
      {season?.slug && (
        <div className="space-y-1 rounded-md bg-muted p-3 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={!!season.is_public} onChange={(e) => act(() => patch(`/seasons/${id}`, { is_public: e.target.checked }))} />
            Show this season on the public site
          </label>
          <p className="text-xs text-foreground/80">Public address: <Link className="underline" href={`/league/${season.slug}`}>/league/{season.slug}</Link>{!season.is_public && " (hidden)"}</p>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {(["fixtures", "table", "players"] as const).map((k) => (
          <button key={k} className={btnGhost} onClick={() => act(() => download(`/seasons/${id}/export/${k}.csv`, `season-${id}-${k}.csv`))}>Download {k} (CSV)</button>
        ))}
      </div>
      <ErrorText msg={err} />
      {status === "archived" ? (
        <>
          <p className="text-sm text-muted-foreground">This season is archived and read-only.</p>
          <button className={btnGhost} onClick={() => act(() => post(`/seasons/${id}/unarchive`))}>Unarchive</button>
        </>
      ) : !confirm ? (
        <button className={btnGhost} onClick={() => setConfirm(true)}>Archive this season</button>
      ) : (
        <div className="space-y-2">
          <p className="text-sm">Nothing in an archived season can be changed. Continue?</p>
          <button className={btnCls} onClick={() => act(() => post(`/seasons/${id}/archive`))}>Yes, archive it</button>
        </div>
      )}
    </section>
  );
}

function Setup() {
  const { id } = useParams<{ id: string }>();
  const [season, setSeason] = useState<Season | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [drafts, setDrafts] = useState<Fixture[]>([]);
  const [umpires, setUmpires] = useState<Umpire[]>([]);
  const [form, setForm] = useState({
    stage_name: "League", legs: 1, start_date: tomorrow(), times: "19:00", parallel: 2, rest_slots: 1,
    assign_umpires: true, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  });
  const [days, setDays] = useState<boolean[]>(Array(7).fill(true));
  const [replace, setReplace] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<Published | null>(null);
  const [created, setCreated] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [standings, setStandings] = useState<Standings | null>(null);
  const [bracket, setBracket] = useState<Bracket | null>(null);
  const [ko, setKo] = useState({ first: "", second: "", incomplete: false });

  const reload = useCallback(async () => {
    try {
      setSeason(await api<Season>(`/seasons/${id}`));
      setTeams(await api<Team[]>(`/seasons/${id}/teams`));
      const all = await api<Fixture[]>(`/seasons/${id}/fixtures?include_drafts=true`);
      setDrafts(all.filter((f) => !f.published).sort((a, b) => a.match_no - b.match_no));
      setUmpires((await api<{ users: Umpire[] }>("/admin/users?role=umpire&limit=100")).users);
      setStandings(await api<Standings>(`/seasons/${id}/standings`));
      setBracket(await api<Bracket>(`/seasons/${id}/bracket`));
    } catch (e) { setErr((e as Error).message); }
  }, [id]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
  useEffect(() => { void reload(); }, [reload]);

  const body = () => {
    const times = form.times.split(/[\s,]+/).filter(Boolean);
    if (!times.length || times.some((t) => !/^\d{1,2}:\d{2}$/.test(t))) throw new Error("Enter kick-off times like 19:00 or 19:00, 20:30");
    if (!days.some(Boolean)) throw new Error("Pick at least one weekday");
    return { ...form, times, weekdays: days.every(Boolean) ? null : days.flatMap((on, i) => (on ? [i] : [])) };
  };
  const run = async (fn: () => Promise<void>) => { setErr(null); try { await fn(); } catch (e) { setErr((e as Error).message); } };

  return (
    <div className="space-y-6">
      <div>
        <Link href={`/seasons/${id}`} className="text-xs underline">← {season?.name ?? "Season"}</Link>
        <h1 className="text-xl font-semibold">Fixtures setup</h1>
        <p className="text-sm text-muted-foreground">{teams.length} teams. Build the schedule, check it, then publish.</p>
      </div>
      <ErrorText msg={err} />
      {teams.length < 2 && <p role="alert" className="text-sm text-red-600">Add at least two teams to the season first.</p>}

      <section className="space-y-3 rounded-lg border p-3">
        <h2 className="font-medium">1. Format</h2>
        <Field label="Stage name" value={form.stage_name} onChange={(e) => setForm({ ...form, stage_name: e.target.value })} />
        <label className="block space-y-1 text-sm"><span>Meetings</span>
          <select aria-label="Legs" className={inputCls} value={form.legs} onChange={(e) => setForm({ ...form, legs: Number(e.target.value) })}>
            <option value={1}>Everyone plays everyone once</option>
            <option value={2}>Home and away (twice)</option>
          </select>
        </label>
        <Field label="First day" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
        <Field label="Kick-off times (local, comma separated)" value={form.times} onChange={(e) => setForm({ ...form, times: e.target.value })} />
        <fieldset className="space-y-1 text-sm"><legend>Play on</legend>
          <div className="flex flex-wrap gap-2">
            {DAYS.map((d, i) => (
              <label key={d} className="flex items-center gap-1"><input type="checkbox" checked={days[i]} onChange={() => setDays(days.map((v, j) => (j === i ? !v : v)))} />{d}</label>
            ))}
          </div>
        </fieldset>
        <div className="grid grid-cols-2 gap-2">
          <label className="block space-y-1 text-sm"><span>Matches at the same time</span>
            <select aria-label="Parallel" className={inputCls} value={form.parallel} onChange={(e) => setForm({ ...form, parallel: Number(e.target.value) })}>
              {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="block space-y-1 text-sm"><span>Rest between a team&apos;s matches</span>
            <select aria-label="Rest" className={inputCls} value={form.rest_slots} onChange={(e) => setForm({ ...form, rest_slots: Number(e.target.value) })}>
              {[0, 1, 2, 3].map((n) => <option key={n} value={n}>{n} slot{n === 1 ? "" : "s"}</option>)}
            </select>
          </label>
        </div>
        <Field label="Time zone" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.assign_umpires} onChange={(e) => setForm({ ...form, assign_umpires: e.target.checked })} /> Suggest umpires ({umpires.length} available)</label>
        <button className={btnCls} disabled={teams.length < 2} onClick={() => run(async () => setPreview(await post<Preview>(`/seasons/${id}/fixtures/preview`, body())))}>Preview schedule</button>
      </section>

      {preview && (
        <section className="space-y-3 rounded-lg border p-3" aria-label="Preview">
          <h2 className="font-medium">2. Preview</h2>
          <p className="text-sm" role="status">{preview.summary.matches} matches · {preview.summary.rounds} rounds · {preview.summary.teams} teams</p>
          {preview.summary.without_umpire ? <p className="text-sm text-amber-700">{preview.summary.without_umpire} match(es) have no umpire yet.</p> : null}
          {preview.summary.with_warnings ? <p className="text-sm text-amber-700">{preview.summary.with_warnings} match(es) have warnings.</p> : null}
          <ul className="max-h-72 space-y-1 overflow-y-auto text-sm">
            {preview.matches.map((m) => (
              <li key={m.index} className="rounded border px-2 py-1">
                <b>R{m.round_no}</b> {m.team_a} v {m.team_b}<br />
                <span className="text-xs text-muted-foreground">{show(m.scheduled_at)}{m.umpire ? ` · ${m.umpire}` : ""}</span>
                {m.warnings.map((w) => <span key={w} className="block text-xs text-amber-700">⚠ {w}</span>)}
              </li>
            ))}
          </ul>
          {drafts.length > 0 && (
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> Replace the {drafts.length} existing draft(s)</label>
          )}
          <button className={btnCls} onClick={() => run(async () => {
            const r = await post<{ created: number }>(`/seasons/${id}/fixtures/generate`, { ...body(), replace_drafts: replace });
            setCreated(r.created); setPreview(null); setReplace(false); await reload();
          })}>Create {preview.summary.matches} draft fixtures</button>
        </section>
      )}

      {created !== null && <p role="status" className="text-sm text-green-700">Created {created} draft fixtures. Nobody can see them yet.</p>}

      <section className="space-y-3">
        <h2 className="font-medium">3. Review drafts ({drafts.length})</h2>
        {drafts.length === 0 && <p className="text-sm text-muted-foreground">No drafts. Generate a schedule above.</p>}
        <ul className="space-y-2">{drafts.map((f) => <DraftRow key={`${f.id}-${f.scheduled_at}-${f.umpire_id}`} f={f} umpires={umpires} onChange={() => void reload()} />)}</ul>
      </section>

      {drafts.length > 0 && (
        <section className="space-y-3 rounded-lg border-2 border-foreground p-3">
          <h2 className="font-medium">4. Publish</h2>
          <p className="text-sm text-muted-foreground">Publishing makes every draft visible and notifies all players and umpires.</p>
          {!confirming ? (
            <button className={btnCls} onClick={() => setConfirming(true)}>Publish {drafts.length} fixtures</button>
          ) : (
            <div className="flex gap-2">
              <button className={`${btnCls} flex-1`} onClick={() => run(async () => { setResult(await post<Published>(`/seasons/${id}/fixtures/publish`, {})); setConfirming(false); await reload(); })}>Yes, publish and notify everyone</button>
              <button className={btnGhost} onClick={() => setConfirming(false)}>Cancel</button>
            </div>
          )}
        </section>
      )}
      {standings && standings.matches_counted > 0 && (
        <section className="space-y-3 rounded-lg border p-3" aria-label="Knockouts setup">
          <h2 className="font-medium">5. Knockouts</h2>
          {bracket?.stage ? (
            <p role="status" className="text-sm">Knockouts are set: {bracket.matches.map((m) => `${m.round_label} ${m.team_a.name} v ${m.team_b.name}`).join(" · ")}. The final is created automatically when the semi-finals finish. <Link href="/standings" className="underline">See the bracket</Link></p>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                {standings.league_complete ? `The league is finished. The top ${standings.qualifiers} go through (1 v 4, 2 v 3).` : `${standings.pending_matches.length} league match(es) are still to be played.`}
              </p>
              <Field label="First semi-final" type="datetime-local" value={ko.first} onChange={(e) => setKo({ ...ko, first: e.target.value })} />
              <Field label="Second semi-final (blank = same time)" type="datetime-local" value={ko.second} onChange={(e) => setKo({ ...ko, second: e.target.value })} />
              {!standings.league_complete && (
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={ko.incomplete} onChange={(e) => setKo({ ...ko, incomplete: e.target.checked })} /> Start the knockouts anyway</label>
              )}
              <button className={btnCls} disabled={!ko.first} onClick={() => run(async () => {
                await post(`/seasons/${id}/knockouts/generate`, {
                  first_at: new Date(ko.first).toISOString(),
                  second_at: ko.second ? new Date(ko.second).toISOString() : null,
                  allow_incomplete: ko.incomplete,
                });
                await reload();
              })}>Create the knockouts</button>
            </>
          )}
        </section>
      )}
      <SeasonAdmin id={id} />
      {result && (
        <p role="status" className="rounded-lg bg-muted p-3 text-sm">
          Published {result.published} fixtures; {result.notified} people notified.
          {result.without_umpire.length ? ` Still no umpire for match ${result.without_umpire.join(", ")}.` : ""}{" "}
          <Link href="/fixtures" className="underline">See the fixtures</Link>
        </p>
      )}
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin><Setup /></RequireAuth>;
}
