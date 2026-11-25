/**
 * Home's data calls. true = that call has finished: an answer came back, it failed, or this person does not
 * need it (for example Team calls for a client without telecalling).
 */
export interface HomeParts {
  /** Hot bar, "Waiting for your reply", the other lists and the Today numbers (top of the page). */
  today: boolean;
  /** The person's saved choice of Today boxes (top of the page). */
  layout: boolean;
  /** The "Finish setup" card, which sits above everything else. */
  setup: boolean;
  /** The Ad spend chart card (bottom of the page). */
  adSpend: boolean;
  /** The Team calls chart card (bottom of the page). */
  teamCalls: boolean;
}

/** Home never keeps the loader up longer than this, whatever is still missing. */
export const HOME_WAIT_CAP_MS = 5_000;

/**
 * Should Home open now? `settled` says which calls have finished, `waitedMs` how long the loader has been up.
 * Once this says yes the page stays open: it is never asked again.
 */
export function homeIsReady(settled: HomeParts, waitedMs: number): boolean {
  // The cap first: one stuck call must never trap the person on the loader.
  if (waitedMs >= HOME_WAIT_CAP_MS) return true;
  // Strict: every call, the two chart cards at the bottom included, so nothing appears after the page opens.
  // To let the bottom cards arrive late instead, drop adSpend and teamCalls from this line.
  return settled.today && settled.layout && settled.setup && settled.adSpend && settled.teamCalls;
}
