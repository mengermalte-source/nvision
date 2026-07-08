document.addEventListener('DOMContentLoaded', function() {
    // Sidebar toggle for mobile
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.querySelector('.sidebar');
    
    if (menuToggle && sidebar) {
        menuToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            // Einheitliches Togglen zwischen expanded und collapsed (Mini-Modus)
            // Die Sidebar ist jetzt immer sichtbar (mindestens als Mini-Sidebar)
            sidebar.classList.toggle('expanded');
            document.body.classList.toggle('sidebar-expanded');
            
            // Falls sie vorher 'collapsed' war (bei > 1400px), entfernen wir das,
            // da wir jetzt primär mit 'expanded' arbeiten.
            if (sidebar.classList.contains('collapsed')) {
                sidebar.classList.remove('collapsed');
                document.body.classList.remove('sidebar-collapsed');
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
