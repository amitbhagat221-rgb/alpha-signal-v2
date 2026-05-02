/* Alpha Signal Cockpit — JS */

document.addEventListener('DOMContentLoaded', () => {

    // Conviction bar animation on load
    document.querySelectorAll('.conviction-marker').forEach(marker => {
        const target = marker.style.left;
        marker.style.left = '0%';
        marker.style.transition = 'none';
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                marker.style.transition = 'left 0.8s cubic-bezier(0.34, 1.56, 0.64, 1)';
                marker.style.left = target;
            });
        });
    });

    // Signal bar animation
    document.querySelectorAll('[data-fill]').forEach(bar => {
        const target = bar.style.width;
        bar.style.width = '0%';
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                bar.style.transition = 'width 0.6s ease';
                bar.style.width = target;
            });
        });
    });

    // Keyboard shortcut: / to focus search (on explorer page)
    document.addEventListener('keydown', (e) => {
        if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
            const search = document.querySelector('input[placeholder*="Search"]');
            if (search && document.activeElement !== search) {
                e.preventDefault();
                search.focus();
            }
        }
        // Escape closes search
        if (e.key === 'Escape') {
            const search = document.querySelector('input[placeholder*="Search"]');
            if (search) search.blur();
        }
    });

    // Click outside search dropdown to close
    document.addEventListener('click', (e) => {
        if (!e.target.closest('[x-data="searchApp()"]')) {
            // Alpine handles this via x-show
        }
    });
});
