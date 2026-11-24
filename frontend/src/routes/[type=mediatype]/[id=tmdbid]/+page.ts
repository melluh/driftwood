import { loadMediaDetails } from '#lib/media/load.ts';
import { loadInMyList } from '#lib/my-list/my-list.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
	const [media, inMyList] = await Promise.all([
		loadMediaDetails(params, fetch),
		loadInMyList({ media_type: params.type, id: params.id }, fetch)
	]);
	return { media, inMyList };
};
