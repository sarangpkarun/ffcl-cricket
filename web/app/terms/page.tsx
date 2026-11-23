import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Terms", description: "The rules for using the FFCL league app." };

export default function Terms() {
  return (
    <article className="max-w-none space-y-4 text-sm">
      <h1 className="text-xl font-semibold">Terms of use</h1>
      <p>FFCL is a friendly league run by volunteers. By using the app you agree to the following.</p>
      <ul className="list-disc space-y-2 pl-5">
        <li><b>Play fair.</b> Submit your own digits, never share them before the reveal, and accept the umpire&apos;s decisions. Disputes go through the dispute screen, not the chat.</li>
        <li><b>Be kind.</b> No harassment, hate or spam in chat. Organisers can mute, suspend or ban an account, and every such action is recorded.</li>
        <li><b>One account per person,</b> with your own mobile number. Do not use someone else&apos;s.</li>
        <li><b>Results are decided by the league.</b> The app calculates scores from what the umpire records; an admin can correct a mistake, with a written reason that is kept.</li>
        <li><b>Availability.</b> The app is provided as it is, by volunteers, with no promise it will always be running.</li>
        <li><b>Leaving.</b> You can delete your account at any time. See <Link className="underline" href="/privacy">Privacy</Link>.</li>
      </ul>
    </article>
  );
}
