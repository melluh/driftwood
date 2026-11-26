import { loadHistory } from '#lib/progress/progress.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => ({ history: await loadHistory(0, fetch) });
