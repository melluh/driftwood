import { defineParams } from '@sveltejs/kit/params';
import { isMediaType } from '#lib/media/media-type.ts';

export const params = defineParams({
	mediatype: (param) => (isMediaType(param) ? param : undefined),
	tmdbid: (param) => (/^[1-9]\d{0,9}$/.test(param) ? Number(param) : undefined)
});
