<script lang="ts">
	import IconButton from '../ui/IconButton.svelte';

	let { onclick }: { onclick: () => void } = $props();

	function isTypingTarget(target: EventTarget | null): boolean {
		return (
			target instanceof HTMLElement &&
			(target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
		);
	}

	/** "/" or Ctrl/Cmd+K open search from anywhere. */
	function handleKeydown(event: KeyboardEvent) {
		const isShortcut =
			(event.key === '/' && !isTypingTarget(event.target)) ||
			(event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey));
		if (isShortcut) {
			event.preventDefault();
			onclick();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<IconButton icon="search" label="Search (/)" ghost {onclick} />
