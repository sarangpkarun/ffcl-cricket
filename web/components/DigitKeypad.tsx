"use client";

import { useState } from "react";

const EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"];
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
            className="flex h-12 items-center justify-center rounded-md border text-xl"
          >
            {digits[i] ? EMOJI[digits[i] - 1] : "—"}
          </li>
        ))}
      </ol>
      <div className="grid grid-cols-3 gap-3">
        {EMOJI.map((e, i) => (
          <button
            key={e}
            type="button"
            aria-label={`digit ${i + 1}`}
            disabled={full}
            onClick={() => setDigits((d) => [...d, i + 1])}
            className="h-16 rounded-lg border text-3xl active:scale-95 disabled:opacity-40"
          >
            {e}
          </button>
        ))}
      </div>
      <div className="flex gap-3">
        <button type="button" onClick={() => setDigits([])} className="flex-1 rounded-md border py-3">
          Clear
        </button>
        <button
          type="button"
          onClick={() => setDigits((d) => d.slice(0, -1))}
          className="flex-1 rounded-md border py-3"
        >
          Undo
        </button>
        <button
          type="button"
          disabled={!full}
          onClick={() => onConfirm?.(digits)}
          className="flex-1 rounded-md bg-foreground py-3 text-background disabled:opacity-40"
        >
          Confirm
        </button>
      </div>
    </div>
  );
}
