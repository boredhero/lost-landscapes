const BROWSER_KEY = 'landscape-visitor-v1';
const VISIT_KEY = 'landscape-visit-v1';
const LIFETIME = 30 * 24 * 60 * 60 * 1000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function visitIdentifiers(local: Storage, session: Storage, now: number, randomUUID: () => string) {
  let browser: { id: string; expires: number } | undefined;
  try { browser = JSON.parse(local.getItem(BROWSER_KEY) ?? 'null') ?? undefined; } catch { /* Replace invalid state. */ }
  if (!browser || !UUID.test(browser.id) || !Number.isFinite(browser.expires) || browser.expires <= now || browser.expires > now + LIFETIME) {
    browser = { id: randomUUID(), expires: now + LIFETIME };
    local.setItem(BROWSER_KEY, JSON.stringify(browser));
  }
  const day = new Date(now).toISOString().slice(0, 10);
  let visit: { id: string; day: string } | undefined;
  try { visit = JSON.parse(session.getItem(VISIT_KEY) ?? 'null') ?? undefined; } catch { /* Replace invalid state. */ }
  if (!visit || !UUID.test(visit.id) || visit.day !== day) {
    visit = { id: randomUUID(), day };
    session.setItem(VISIT_KEY, JSON.stringify(visit));
  }
  return { browser_id: browser.id, visit_id: visit.id };
}

/** Best effort: never block terrain, retry, or recreate IDs when storage is blocked. */
export function recordVisit() {
  const privacy = navigator as Navigator & { globalPrivacyControl?: boolean };
  if (navigator.doNotTrack === '1' || privacy.globalPrivacyControl) return;
  try {
    const body = visitIdentifiers(localStorage, sessionStorage, Date.now(), () => crypto.randomUUID());
    void fetch('/api/visits', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), credentials: 'omit', signal: AbortSignal.timeout(3000),
    }).catch(() => { /* Analytics outages must not affect exploration. */ });
  } catch { /* Storage unavailable: do not count this browser. */ }
}
