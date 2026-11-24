import { loadMediaDetails } from '#lib/media/load.ts';
import type { PageLoad } from './$types';

function positiveInt(value: string | null): number | null {
	const number = Number(value);
	return value && Number.isInteger(number) && number > 0 ? number : null;
}

export const load: PageLoad = async ({ params, fetch, url }) => {
	const media = await loadMediaDetails(params, fetch);
	// Series watch one episode: ?season=&episode=, defaulting to S01E01.
	const episode =
		media.media_type === 'tv'
			? {
					season: positiveInt(url.searchParams.get('season')) ?? 1,
					episode: positiveInt(url.searchParams.get('episode')) ?? 1
				}
			: null;
	return { media, episode };
};
