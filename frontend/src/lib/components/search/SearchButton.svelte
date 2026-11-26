<script lang="ts">
	import { isTypingTarget } from '#lib/keyboard.ts';
	import IconButton from '../ui/IconButton.svelte';

	let { onclick }: { onclick: () => void } = $props();

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
