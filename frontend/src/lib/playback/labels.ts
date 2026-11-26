import type {
	PlaybackAudioTrack,
	PlaybackSubtitleTrack,
	PlaybackVersion
} from '#lib/api/client.ts';
import { formatBytes } from '#lib/media/format.ts';
import { languageName } from '#lib/watch/labels.ts';

const AUDIO_CODECS: Record<string, string> = {
	aac: 'AAC',
	ac3: 'Dolby Digital',
	eac3: 'Dolby Digital Plus',
	truehd: 'TrueHD',
	dts: 'DTS',
	flac: 'FLAC',
	opus: 'Opus',
	mp3: 'MP3',
	vorbis: 'Vorbis'
};

const SOURCES: Record<string, string> = {
	remux: 'Remux',
	'bluray-encode': 'Blu-ray',
	'web-dl': 'WEB-DL',
	webrip: 'WEBRip',
	hdtv: 'HDTV',
	dvd: 'DVD'
};

const HDR: Record<string, string> = { dv: 'Dolby Vision', hdr10: 'HDR10', hdr10plus: 'HDR10+' };

function channelLayout(channels: number | null | undefined): string | null {
	if (!channels) return null;
	if (channels === 1) return 'Mono';
	if (channels === 2) return 'Stereo';
	return `${channels - 1}.1`;
}

/** `English`, `Japanese (Commentary)`, `Track 2` */
export function audioName(track: PlaybackAudioTrack): string {
	const language = track.language ? languageName(track.language) : null;
	const title = track.title?.trim();
	if (language && title && !title.toLowerCase().includes(language.toLowerCase())) {
		return `${language} (${title})`;
	}
	return title || language || `Track ${track.id + 1}`;
}

/** `Dolby Digital Plus · 5.1` */
export function audioDetail(track: PlaybackAudioTrack): string {
	return [AUDIO_CODECS[track.codec] ?? track.codec.toUpperCase(), channelLayout(track.channels)]
		.filter(Boolean)
		.join(' · ');
}

/** `English`, `English (SDH)`, `Signs & Songs`, `English · Forced` */
export function subtitleName(track: PlaybackSubtitleTrack): string {
	const language = track.language ? languageName(track.language) : null;
	const title = track.title?.trim();
	let name =
		title && language && !title.toLowerCase().includes(language.toLowerCase())
			? `${language} (${title})`
			: title || language || `Track ${track.id + 1}`;
	if (track.hearing_impaired && !/sdh|\bcc\b/i.test(name)) name += ' (SDH)';
	return name;
}

/** `2160p · Remux · HEVC · Dolby Vision` */
export function versionName(version: PlaybackVersion): string {
	const codec = version.video_codec === 'h264' ? 'H.264' : version.video_codec?.toUpperCase();
	const parts = [
		version.height ? `${version.height}p` : null,
		version.source ? (SOURCES[version.source] ?? version.source) : null,
		codec ?? null,
		...version.hdr_flags.map((flag) => HDR[flag] ?? flag)
	].filter(Boolean);
	return parts.length ? parts.join(' · ') : version.name;
}

export function versionSize(version: PlaybackVersion): string {
	return formatBytes(version.size) ?? '';
}

/** `4:05`, `1:02:09` */
export function formatTime(seconds: number): string {
	if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
	const total = Math.floor(seconds);
	const hours = Math.floor(total / 3600);
	const minutes = Math.floor((total % 3600) / 60);
	const secs = String(total % 60).padStart(2, '0');
	return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`;
}
