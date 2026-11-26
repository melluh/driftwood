import { loadMediaDetails } from '#lib/media/load.ts';
import { loadAvailability } from '#lib/library/library.ts';
import { loadResumeAt } from '#lib/progress/progress.ts';
import type { PageLoad } from './$types';

function positiveInt(value: string | null): number | null {
	const number = Number(value);
	return value && Number.isInteger(number) && number > 0 ? number : null;
}

export const load: PageLoad = async ({ params, fetch, url }) => {
	const key = { media_type: params.type, id: params.id };
	// Series watch one episode: ?season=&episode=, defaulting to S01E01.
	const episode =
		params.type === 'tv'
			? {
					season: positiveInt(url.searchParams.get('season')) ?? 1,
					episode: positiveInt(url.searchParams.get('episode')) ?? 1
				}
			: null;
	const [media, availability, resumeAt] = await Promise.all([
		loadMediaDetails(params, fetch),
		loadAvailability(key, fetch),
		loadResumeAt(key, episode, fetch)
	]);
	return { media, episode, availability, resumeAt };
};
