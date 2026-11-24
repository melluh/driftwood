import { error } from '@sveltejs/kit';
import { api } from '#lib/api/client.ts';
import { loadMyList } from '#lib/my-list/my-list.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const [{ data }, myList] = await Promise.all([
		api.GET('/api/home', { fetch }),
		loadMyList(fetch)
	]);
	if (!data) error(502, 'Could not load suggestions');
	return { home: data, myList };
};
