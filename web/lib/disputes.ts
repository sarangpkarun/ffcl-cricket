export type DisputeRow = {
  id: number; kind: string; status: string; season: { id: number; name: string | null };
  match: { id: number; match_no: number; teams: string } | null; against: string | null;
  raised_by: { id: number; name: string; as: string }; assigned_to: string | null; excerpt: string; created_at: string; updated_at: string;
};
export type DisputeMessage = { id: number; author: { id: number; name: string; is_raiser: boolean }; body: string; internal: boolean; created_at: string };
export type DisputeDetail = DisputeRow & {
  body: string; outcome: string | null; resolution: { action: string; adjustment_id?: number } | null; resolved_by: string | null; resolved_at: string | null;
  match_status: string | null; match_result: string | null; messages: DisputeMessage[];
  viewer: { level: "admin" | "party"; can_message: boolean; can_take: boolean; can_decide: boolean; can_reopen: boolean; can_withdraw: boolean };
};

export const KIND_LABEL: Record<string, string> = {
  scoring: "The score or result", eligibility: "Who was allowed to play", umpiring: "The umpiring", other: "Something else", conduct: "Someone's behaviour",
};
export const STATUS_LABEL: Record<string, string> = { open: "Open", in_review: "Being looked at", resolved: "Resolved", dismissed: "Dismissed", withdrawn: "Withdrawn" };
export const ACTION_LABEL: Record<string, string> = {
  none: "No change was needed", result_reversed: "The result was reversed", ball_corrected: "A ball was corrected",
  points_adjusted: "Points were adjusted", penalty_applied: "A penalty was applied", other: "Something else was done",
};
export const when = (iso: string) => new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
