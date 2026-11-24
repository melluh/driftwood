import { loadMediaDetails } from '#lib/media/load.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => ({
	media: await loadMediaDetails(params, fetch)
});
