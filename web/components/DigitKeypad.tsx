"use client";

import { useState } from "react";

const DIGITS = ["1", "2", "3", "4", "5", "6"];
const SLOTS = 6;

export function DigitKeypad({ onConfirm }: { onConfirm?: (digits: number[]) => void }) {
  const [digits, setDigits] = useState<number[]>([]);
  const full = digits.length === SLOTS;

  return (
    <div className="space-y-4">
      <ol className="grid grid-cols-6 gap-2" aria-label="Selected digits">
        {Array.from({ length: SLOTS }, (_, i) => (
          <li
            key={i}
            data-testid="slot"
            className={`flex h-12 items-center justify-center rounded-xl border text-xl font-bold ${digits[i] ? "border-primary bg-primary text-primary-foreground" : "border-dashed text-muted-foreground"}`}
          >
            {digits[i] ? DIGITS[digits[i] - 1] : "—"}
          </li>
        ))}
      </ol>
      <div className="grid grid-cols-3 gap-3">
        {DIGITS.map((e, i) => (
          <button
            key={e}
            type="button"
            aria-label={`digit ${i + 1}`}
            disabled={full}
            onClick={() => setDigits((d) => [...d, i + 1])}
            className="card-elevated h-16 rounded-2xl border bg-card text-3xl font-bold text-primary transition active:scale-95 active:bg-accent disabled:opacity-40"
          >
            {e}
          </button>
        ))}
      </div>
      <div className="flex gap-3">
        <button type="button" onClick={() => setDigits([])} className="flex-1 rounded-xl border bg-card py-3">
          Clear
        </button>
        <button
          type="button"
          onClick={() => setDigits((d) => d.slice(0, -1))}
          className="flex-1 rounded-xl border bg-card py-3"
        >
          Undo
        </button>
        <button
          type="button"
          disabled={!full}
          onClick={() => onConfirm?.(digits)}
          className="flex-1 rounded-xl bg-primary py-3 font-medium text-primary-foreground disabled:opacity-40"
        >
          Confirm
        </button>
      </div>
    </div>
  );
}
