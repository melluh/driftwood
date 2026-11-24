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

/** Only same-origin paths are valid post-login destinations (mirrors the backend). */
export function safeNext(value: string | null | undefined): string {
	if (!value || !value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) {
		return '/';
	}
	return value;
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
