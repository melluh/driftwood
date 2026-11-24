import { error, redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import { api } from '#lib/api/client.ts';
import { loginHref, markSignedIn, safeNext } from '#lib/auth/session.ts';
import type { LayoutLoad } from './$types';

// Single-page app: all data comes from the Driftwood API at runtime.
export const ssr = false;

/**
 * Every page requires a session, except the login page. Runs once per page load:
 * signing in and out both do full-page navigations, so the user can't go stale.
 */
export const load: LayoutLoad = async ({ fetch, url, untrack }) => {
	const { data: user, response } = await api.GET('/api/auth/me', { fetch });
	const { pathname, search, searchParams } = untrack(() => url);
	const onLoginPage = pathname === resolve('/login');

	if (!user) {
		if (response.status !== 401) error(503, 'Could not reach the Driftwood server');
		if (!onLoginPage) redirect(307, loginHref(pathname + search));
		return { user: null };
	}

	markSignedIn();
	if (onLoginPage) redirect(307, safeNext(searchParams.get('next')));
	return { user };
};
