import type { DownloadStatus } from '#lib/api/client.ts';

/** `4 min left`, `1 h 20 min left`, `< 1 min left`: short enough for the progress ring. */
export function formatEta(seconds: number): string {
	if (seconds < 60) return '< 1 min left';
	const minutes = Math.round(seconds / 60);
	if (minutes < 60) return `${minutes} min left`;
	const hours = Math.floor(minutes / 60);
	const rest = minutes % 60;
	return rest ? `${hours} h ${rest} min left` : `${hours} h left`;
}

/** What's happening, as the progress screen's heading. */
export function downloadHeadline(download: DownloadStatus): string {
	switch (download.state) {
		case 'importing':
			return 'Adding to your library';
		case 'completed':
			return 'Starting playback';
		case 'failed':
			return "The download didn't finish";
		case 'cancelled':
			return 'Download cancelled';
	}
	// Before the first bytes it's all "Downloading" (with "Starting download…" below it).
	const started = download.downloaded > 0 || download.progress > 0;
	if (started && download.activity === 'stalled') return 'Waiting for peers';
	if (started && download.activity === 'checking') return 'Checking files';
	if (download.activity === 'paused') return 'Paused in qBittorrent';
	return 'Downloading';
}
