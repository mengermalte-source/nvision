document.addEventListener('DOMContentLoaded', function() {
    // Sidebar toggle for mobile
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.querySelector('.sidebar');
    
    if (menuToggle && sidebar) {
        menuToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            if (window.innerWidth <= 1400) {
                sidebar.classList.toggle('active');
            } else {
                sidebar.classList.toggle('collapsed');
                document.body.classList.toggle('sidebar-collapsed');
            }
        });

        document.addEventListener('click', function(e) {
            if (window.innerWidth <= 1400) {
                if (sidebar.classList.contains('active') && 
                    !sidebar.contains(e.target) && 
                    !menuToggle.contains(e.target)) {
                    sidebar.classList.remove('active');
                }
            }
        });
    }

    // Auto-min-today for date inputs
    const today = new Date().toISOString().split("T")[0];
    document.querySelectorAll('input[type="date"].js-min-today').forEach(input => {
        input.min = today;
    });

    // Critical Projects Modal
    const criticalTrigger = document.getElementById('criticalTrigger');
    const criticalOverlay = document.getElementById('criticalOverlay');
    const closeCritical = document.getElementById('closeCritical');

    if (criticalTrigger && criticalOverlay) {
        criticalTrigger.addEventListener('click', () => {
            criticalOverlay.classList.add('active');
            document.body.style.overflow = 'hidden'; // Verhindert Scrollen im Hintergrund
        });

        const hideModal = () => {
            criticalOverlay.classList.remove('active');
            document.body.style.overflow = '';
        };

        if (closeCritical) {
            closeCritical.addEventListener('click', hideModal);
        }

        criticalOverlay.addEventListener('click', (e) => {
            if (e.target === criticalOverlay) {
                hideModal();
            }
        });

        // ESC-Taste zum Schließen
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && criticalOverlay.classList.contains('active')) {
                hideModal();
            }
        });
    }
});
