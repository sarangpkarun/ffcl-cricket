"use client";

import { useEffect, useState } from "react";

const FORMAT: Intl.DateTimeFormatOptions = { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" };

/** The server prints the time in UTC (so the page works without JavaScript); the browser then shows it in the visitor's own time zone. */
export function LocalTime({ iso }: { iso: string | null }) {
  const [text, setText] = useState(iso ? `${new Date(iso).toLocaleString("en-GB", { ...FORMAT, timeZone: "UTC" })} UTC` : "Time to be confirmed");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- switch from the server's UTC text to the visitor's time zone
    if (iso) setText(new Date(iso).toLocaleString([], FORMAT));
  }, [iso]);
  return <time dateTime={iso ?? undefined} suppressHydrationWarning>{text}</time>;
}
