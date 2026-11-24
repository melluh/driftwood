/** Stroke-based 24×24 icon paths. */
export const ICONS = {
	search: ['M10.5 18a7.5 7.5 0 1 0 0-15 7.5 7.5 0 0 0 0 15Z', 'm21 21-5.2-5.2'],
	close: ['M18 6 6 18', 'm6 6 12 12'],
	'chevron-left': ['m15 18-6-6 6-6'],
	'chevron-right': ['m9 18 6-6-6-6'],
	info: ['M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z', 'M12 16v-4', 'M12 8h.01'],
	film: [
		'M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z',
		'M7 3v18',
		'M17 3v18',
		'M3 7.5h4',
		'M3 12h18',
		'M3 16.5h4',
		'M17 7.5h4',
		'M17 16.5h4'
	],
	tv: ['M4 7h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1Z', 'm8 3 4 4 4-4'],
	person: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', 'M4 21a8 8 0 0 1 16 0'],
	star: ['m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9L12 3Z'],
	alert: [
		'M12 9v4',
		'M12 17h.01',
		'M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z'
	]
} satisfies Record<string, string[]>;

export type IconName = keyof typeof ICONS;
