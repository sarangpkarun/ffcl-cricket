import type { Season } from "@/lib/api";

const KEY = "ffcl.season";

/** The season to show first: the one this person picked last time, else the first active one, else the newest. */
export function chooseSeason(list: Season[]): Season | undefined {
  let remembered: number | null = null;
  try {
    const v = localStorage.getItem(KEY);
    remembered = v ? Number(v) : null;
  } catch {
    /* private mode: no memory */
  }
  return list.find((s) => s.id === remembered) ?? list.find((s) => s.status === "active") ?? list[0];
}

export function rememberSeason(id: number | string): void {
  try {
    localStorage.setItem(KEY, String(id));
  } catch {
    /* private mode: it just will not be remembered */
  }
}

/** For admin screens: a season admin only gets their own seasons, a global admin gets all. */
export function adminSeasons(list: Season[], scope: { is_global: boolean; seasons: number[] }): Season[] {
  return scope.is_global ? list : list.filter((s) => scope.seasons.includes(s.id));
}
