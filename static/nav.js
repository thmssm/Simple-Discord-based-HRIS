// === HRIS Navigation — Drawer Toggle ===

function toggleDrawer() {
  const overlay = document.getElementById('nav-drawer-overlay');
  const drawer = document.getElementById('nav-drawer');
  if (!overlay || !drawer) return;
  const isOpen = drawer.classList.contains('open');
  if (isOpen) {
    drawer.classList.remove('open');
    overlay.classList.remove('open');
    document.body.style.overflow = '';
  } else {
    drawer.classList.add('open');
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
}

document.addEventListener('DOMContentLoaded', function() {
  const overlay = document.getElementById('nav-drawer-overlay');
  if (overlay) overlay.addEventListener('click', toggleDrawer);

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      const drawer = document.getElementById('nav-drawer');
      if (drawer && drawer.classList.contains('open')) toggleDrawer();
    }
  });

  const activeItem = document.querySelector('.nav-item.active');
  if (activeItem) {
    const pageTitle = document.getElementById('mobile-page-title');
    if (pageTitle) {
      const label = activeItem.querySelector('.label');
      if (label) pageTitle.textContent = label.textContent;
    }
  }
});