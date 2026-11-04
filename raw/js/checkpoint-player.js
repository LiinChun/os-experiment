(() => {
  function initialize() {
    document.querySelectorAll('.checkpoint-player').forEach(player => {
      if (player.dataset.ready) return;
      player.dataset.ready = 'true';
      const mode = player.querySelector('select');
      const steps = [...player.querySelectorAll('figure')];
      const previous = player.querySelector('[data-previous]');
      const next = player.querySelector('[data-next]');
      const status = player.querySelector('[role="status"]');
      let index = 0;
      function render() {
        const active = steps.filter(step => step.dataset.mode === mode.value);
        steps.forEach(step => { step.hidden = true; });
        active[index].hidden = false;
        previous.disabled = index === 0;
        next.disabled = index === active.length - 1;
        status.textContent = `第 ${index + 1} / ${active.length} 步`;
      }
      mode.addEventListener('change', () => { index = 0; render(); });
      previous.addEventListener('click', () => { if (index > 0) { index--; render(); } });
      next.addEventListener('click', () => {
        const count = steps.filter(step => step.dataset.mode === mode.value).length;
        if (index < count - 1) { index++; render(); }
      });
      render();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
  if (typeof document$ !== 'undefined') document$.subscribe(initialize);
})();
