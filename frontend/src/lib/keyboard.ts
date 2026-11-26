/** Keys typed here are text, not app shortcuts (range sliders don't count: they take no text). */
export function isTypingTarget(target: EventTarget | null): boolean {
	if (!(target instanceof HTMLElement)) return false;
	if (target.isContentEditable) return true;
	if (target instanceof HTMLInputElement) return target.type !== 'range';
	return target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
}
