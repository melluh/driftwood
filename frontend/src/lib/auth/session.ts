import { resolve } from '$app/paths';

/** The login page, returning to `next` after signing in. */
export function loginHref(next?: string): string {
	const login = resolve('/login');
	return next && next !== '/' ? `${login}?next=${encodeURIComponent(next)}` : login;
}

/** Starts the OAuth flow on the backend (a full-page navigation, not a SvelteKit route). */
export function oauthLoginHref(next: string): string {
	return `/api/auth/login?next=${encodeURIComponent(next)}`;
}

/** A stand-in origin to resolve `next` against; only "is it still this origin?" matters. */
const SAME_ORIGIN = 'http://driftwood.invalid';

/**
 * Only same-origin paths are valid post-login destinations (no open redirect).
 *
 * Checked by resolving it the way navigation will, not by looking at the string:
 * URL parsing drops tabs and newlines and reads `\` as `/`, so `/\t/evil.com`
 * would otherwise slip past a `//` check and land on `//evil.com`. The normalized
 * result is checked again, as dot segments can collapse into one (`/.//evil.com`).
 */
export function safeNext(value: string | null | undefined): string {
	if (!value?.startsWith('/')) return '/';
	const path = sameOriginPath(value);
	return path !== null && sameOriginPath(path) === path ? path : '/';
}

function sameOriginPath(value: string): string | null {
	try {
		const url = new URL(value, SAME_ORIGIN);
		return url.origin === SAME_ORIGIN ? url.pathname + url.search + url.hash : null;
	} catch {
		return null;
	}
}

let signedIn = false;

/** Set once the root layout has confirmed a session. */
export function markSignedIn(): void {
	signedIn = true;
}

/**
 * The session ended under a signed-in page (expired or revoked elsewhere): start
 * over at the login page, coming back here afterwards. Before the first session
 * check this is a no-op, as the root layout does the redirect itself.
 */
export function handleSessionLost(): void {
	if (!signedIn) return;
	signedIn = false;
	const { pathname, search } = window.location;
	window.location.assign(loginHref(pathname + search));
}

/** Ends the session and returns to the login page with a clean slate. */
export async function logout(): Promise<void> {
	try {
		await fetch('/api/auth/logout', { method: 'POST' });
	} finally {
		signedIn = false;
		window.location.assign(resolve('/login'));
	}
}
