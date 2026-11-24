import { error } from '@sveltejs/kit';
import { api, type MediaDetails, type MediaType } from '#lib/api/client.ts';

/** Loads a title's details for a route, turning API failures into SvelteKit errors. */
export async function loadMediaDetails(
	params: { type: MediaType; id: number },
	fetch: typeof globalThis.fetch
): Promise<MediaDetails> {
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
	return data;
}
