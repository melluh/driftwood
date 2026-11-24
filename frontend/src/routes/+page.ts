import { error } from '@sveltejs/kit';
import { api } from '#lib/api/client.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const { data } = await api.GET('/api/home', { fetch });
	if (!data) error(502, 'Could not load suggestions');
	return { home: data };
};
