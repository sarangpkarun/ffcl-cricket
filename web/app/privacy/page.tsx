import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Privacy", description: "What the FFCL league app keeps about you, why, who sees it and how to leave." };

export default function Privacy() {
  return (
    <article className="prose-sm max-w-none space-y-4 text-sm">
      <h1 className="text-2xl font-bold text-primary">Privacy</h1>
      <p>FFCL is a small league run by volunteers. This page says plainly what the app keeps about you.</p>
      <section className="space-y-1"><h2 className="font-medium">What we keep</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>Your name, email address, mobile number and a scrambled (hashed) password.</li>
          <li>Your teams, lineups, the digits you submitted, the results you were part of, and awards.</li>
          <li>Chat messages you send, disputes you raise, and notifications sent to you.</li>
          <li>The devices you are signed in on (their browser description and when they were last used) and, if you turn on alerts, the address your browser gives us for push messages.</li>
          <li>A record of actions organisers take (who changed what, and why), so decisions can be checked.</li>
        </ul>
      </section>
      <section className="space-y-1"><h2 className="font-medium">Who sees it</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li><b>The public</b> sees league results, tables, statistics and scorecards with players&apos; names. Turn off <em>Show my name on the public site</em> on your profile and you appear only as your player ID. Your email, number and chat are never public.</li>
          <li><b>Other players</b> see your name and team. <b>Organisers</b> see your email and number so they can verify you and run the league.</li>
        </ul>
      </section>
      <section className="space-y-1"><h2 className="font-medium">Your numbers are checked by people</h2>
        <p>The app does not send text messages. An organiser verifies your mobile number, and their name and the time are recorded.</p>
      </section>
      <section className="space-y-1"><h2 className="font-medium">Browser storage</h2>
        <p>Only what the app needs to work: your sign-in, the season you last looked at, and whether you dismissed the install prompt. There are no advertising or tracking cookies, and nothing is shared with other companies. Push messages travel through your browser maker&apos;s push service.</p>
      </section>
      <section className="space-y-1"><h2 className="font-medium">How long we keep things</h2>
        <p>Match records stay as long as the league does. Old sign-ins, one-time codes and used invite links are cleared automatically within weeks, read notifications after 90 days, and organiser action records after two years.</p>
      </section>
      <section className="space-y-1"><h2 className="font-medium">Your choices</h2>
        <ul className="list-disc space-y-1 pl-5">
          <li><b>Download your data</b> from your profile: everything above, as a file.</li>
          <li><b>Delete your account</b> from your profile. Your name, email, number and password are removed and you are signed out everywhere. Your matches stay in the results as <em>Former player</em>, so tables and statistics stay correct, and your chat messages stay in the conversation under that name. Captains, umpires and admins hand their role over first.</li>
          <li>Ask an organiser if you want something corrected.</li>
        </ul>
      </section>
      <p><Link className="underline" href="/terms">Terms of use</Link></p>
    </article>
  );
}
