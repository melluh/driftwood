<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import Button from '#lib/components/ui/Button.svelte';
	import LinkButton from '#lib/components/ui/LinkButton.svelte';
	import StatusMessage from '#lib/components/ui/StatusMessage.svelte';

	const notFound = $derived(page.status === 404);
</script>

<svelte:head>
	<title>{notFound ? 'Not found' : 'Something went wrong'} · Driftwood</title>
</svelte:head>

<!-- Also shown when the layout's own load fails, so there may be no header: always offer a way on. -->
<div class="error">
	<StatusMessage
		icon={notFound ? 'info' : 'alert'}
		tone={notFound ? 'neutral' : 'danger'}
		title={notFound ? 'Not found' : 'Something went wrong'}
		role="alert"
	>
		{page.error?.message}
		{#snippet actions()}
			{#if !notFound}
				<Button onclick={() => location.reload()}>Try again</Button>
			{/if}
			<!-- A full load: the layout may be what failed, and has to run again. -->
			<div data-sveltekit-reload>
				<LinkButton href={resolve('/')} variant={notFound ? 'primary' : 'secondary'}>
					Back to home
				</LinkButton>
			</div>
		{/snippet}
	</StatusMessage>
</div>

<style>
	.error {
		display: grid;
		place-items: center;
		min-height: 100dvh;
		padding: var(--header-height) var(--page-gutter);
	}
</style>
