document.addEventListener('DOMContentLoaded', function() {
  const refreshBtn = document.getElementById('refreshBtn');
  const lastSync = document.getElementById('lastSync');
  if (!refreshBtn) return;

  refreshBtn.addEventListener('click', async function() {
    // Simple UX: show loading state, then fetch monitoring endpoint to simulate refresh
    refreshBtn.disabled = true;
    refreshBtn.classList.add('opacity-60');
    try {
      const res = await fetch('/monitoring', { method: 'GET', cache: 'no-cache' });
      if (res.ok) {
        const now = new Date();
        const hh = String(now.getHours()).padStart(2,'0');
        const mm = String(now.getMinutes()).padStart(2,'0');
        lastSync.textContent = `Last synced: ${hh}:${mm}`;
        // brief bar animation
        document.querySelectorAll('[style*="height:"]').forEach(el => {
          el.style.transform = 'translateY(4px)';
          setTimeout(() => el.style.transform = '', 350);
        });
      }
    } catch (e) {
      console.warn('Refresh failed', e);
    } finally {
      refreshBtn.disabled = false;
      refreshBtn.classList.remove('opacity-60');
    }
  });
});
