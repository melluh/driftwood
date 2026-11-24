import { api } from '#lib/api/client.ts';
import { safeNext } from '#lib/auth/session.ts';
import type { PageLoad } from './$types';

function shuffle<T>(items: T[]): T[] {
	const result = [...items];
	for (let i = result.length - 1; i > 0; i--) {
		const j = Math.floor(Math.random() * (i + 1));
		[result[i], result[j]] = [result[j], result[i]];
	}
	return result;
}

export const load: PageLoad = async ({ fetch, url }) => {
	const [config, backdrop] = await Promise.all([
		api.GET('/api/auth/config', { fetch }),
		// Decoration only: the login screen works fine without it.
		api.GET('/api/auth/backdrop', { fetch }).catch(() => ({ data: undefined }))
	]);
	return {
		config: config.data ?? { provider_name: 'SSO', configured: true },
		posters: shuffle(backdrop.data ?? []),
		next: safeNext(url.searchParams.get('next')),
		error: url.searchParams.get('error')
	};
};
