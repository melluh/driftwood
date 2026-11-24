import { error } from '@sveltejs/kit';
import { api } from '#lib/api/client.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
	const { data, response } = await api.GET('/api/media/{media_type}/{media_id}', {
		params: { path: { media_type: params.type, media_id: params.id } },
		fetch
	});
	if (!data) {
		error(
			response.status === 404 ? 404 : 502,
			response.status === 404 ? 'Not found' : 'Could not load this title'
		);
	}
	return { media: data };
};
