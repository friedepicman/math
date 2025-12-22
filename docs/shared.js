/* ============================================
   MOCK AIME - SHARED JAVASCRIPT
   ============================================ */

// Supabase Configuration
const SUPABASE_URL = 'https://ftdbplxkyaocyrjpmjyb.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ0ZGJwbHhreWFvY3lyanBtanliIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTIxMDgxMDUsImV4cCI6MjA2NzY4NDEwNX0.hE0V09JxdLYNbZqPVH3HZxNpLPP2rXIaBsNGUHO3upc';

// Initialize Supabase client (assumes supabase-js is loaded)
// Check if supabaseClient already exists (for pages with their own init)
let supabaseClient = window.supabaseClient;
if (!supabaseClient && typeof supabase !== 'undefined') {
  supabaseClient = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  window.supabaseClient = supabaseClient;
}

// Admin email
const ADMIN_EMAIL = 'dumplingcreampuff2@gmail.com';

// Protected pages that require login
const PROTECTED_PAGES = ['profile', 'admin', 'admin_reports'];

// Admin-only pages
const ADMIN_PAGES = ['admin', 'admin_reports'];

/* ============================================
   SESSION MANAGEMENT
   ============================================ */

function getSessionId() {
  let sessionId = localStorage.getItem('mockAIME_sessionId');
  if (!sessionId) {
    sessionId = 'sess_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now().toString(36);
    localStorage.setItem('mockAIME_sessionId', sessionId);
  }
  return sessionId;
}

/* ============================================
   DARK MODE
   ============================================ */

function initDarkMode() {
  const savedTheme = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);
  updateDarkModeButton(savedTheme);
}

function toggleDarkMode() {
  const html = document.documentElement;
  const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', newTheme);
  localStorage.setItem('theme', newTheme);
  updateDarkModeButton(newTheme);
}

function updateDarkModeButton(theme) {
  const btn = document.querySelector('.dark-mode-toggle');
  if (btn) {
    btn.textContent = theme === 'dark' ? '☀️ Light' : '🌙 Dark';
  }
}

/* ============================================
   MOBILE MENU
   ============================================ */

function toggleMobileMenu() {
  const navLinks = document.querySelector('.navbar-links');
  if (navLinks) {
    navLinks.classList.toggle('open');
  }
}

/* ============================================
   NAVBAR GENERATION
   ============================================ */

function generateNavbar(currentPage, user) {
  const isLoggedIn = !!user;
  const isAdmin = user?.email === ADMIN_EMAIL;
  
  let navHTML = `
    <nav class="navbar">
      <div class="navbar-container">
        <a href="index.html" class="navbar-brand">
          <img src="256px_transparentBG.png" alt="Mock AIME Logo">
          Mock AIME
        </a>
        <button class="mobile-menu-btn" onclick="toggleMobileMenu()" aria-label="Toggle menu">☰</button>
        <div class="navbar-links">
          <a href="index.html" ${currentPage === 'index' ? 'class="active"' : ''}>Mock Test</a>
          <a href="practice.html" ${currentPage === 'practice' ? 'class="active"' : ''}>Practice</a>
          <a href="past_tests.html" ${currentPage === 'past_tests' ? 'class="active"' : ''}>Past Tests</a>
          <a href="search.html" ${currentPage === 'search' ? 'class="active"' : ''}>Search</a>
  `;
  
  if (isAdmin) {
    navHTML += `
          <a href="admin.html" ${currentPage === 'admin' ? 'class="active"' : ''}>Admin</a>
          <a href="admin_reports.html" ${currentPage === 'admin_reports' ? 'class="active"' : ''}>Reports</a>
    `;
  }
  
  if (isLoggedIn) {
    navHTML += `
          <a href="profile.html" ${currentPage === 'profile' ? 'class="active"' : ''}>Profile</a>
          <a href="#" onclick="handleLogout(event)">Logout</a>
    `;
  } else {
    navHTML += `
          <a href="login.html" ${currentPage === 'login' ? 'class="active"' : ''}>Login</a>
    `;
  }
  
  navHTML += `
          <button class="dark-mode-toggle" onclick="toggleDarkMode()">🌙 Dark</button>
        </div>
      </div>
    </nav>
  `;
  
  return navHTML;
}

/* ============================================
   LOGOUT HANDLER
   ============================================ */

async function handleLogout(event) {
  if (event) event.preventDefault();
  
  if (!supabaseClient) return;
  
  // Get current page before logout
  const currentPage = document.body.dataset.page || 'index';
  
  await supabaseClient.auth.signOut();
  
  // Redirect if on a protected page
  if (PROTECTED_PAGES.includes(currentPage)) {
    window.location.href = 'index.html';
  } else {
    // Refresh the navbar to show login link
    window.location.reload();
  }
}

/* ============================================
   ACTIVITY LOGGING
   ============================================ */

async function logPageView(pageName, metadata = {}) {
  if (!supabaseClient) return;
  
  try {
    const { data: { user } } = await supabaseClient.auth.getUser();
    const userType = user ? (user.email === ADMIN_EMAIL ? 'admin' : 'user') : 'guest';
    const sessionId = getSessionId();
    
    const logData = {
      session_id: sessionId,
      user_id: user?.id || null,
      user_type: userType,
      event_type: 'page_view',
      page: pageName,
      url: window.location.href,
      referrer: document.referrer,
      metadata: metadata
    };
    
    // Log to both tables
    await Promise.all([
      supabaseClient.from('activity_log').insert(logData),
      supabaseClient.from('activity_all').insert(logData)
    ]);
  } catch (err) {
    console.error('Logging error:', err);
  }
}

async function logEvent(eventType, pageName, metadata = {}) {
  if (!supabaseClient) return;
  
  try {
    const { data: { user } } = await supabaseClient.auth.getUser();
    const userType = user ? (user.email === ADMIN_EMAIL ? 'admin' : 'user') : 'guest';
    const sessionId = getSessionId();
    
    const logData = {
      session_id: sessionId,
      user_id: user?.id || null,
      user_type: userType,
      event_type: eventType,
      page: pageName,
      url: window.location.href,
      referrer: document.referrer,
      metadata: metadata
    };
    
    // Log to both tables
    await Promise.all([
      supabaseClient.from('activity_log').insert(logData),
      supabaseClient.from('activity_all').insert(logData)
    ]);
  } catch (err) {
    console.error('Logging error:', err);
  }
}

/* ============================================
   PAGE INITIALIZATION
   ============================================ */

async function initPage(pageName, options = {}) {
  // Store page name on body for reference
  document.body.dataset.page = pageName;
  
  // Initialize dark mode first (no auth needed)
  initDarkMode();
  
  // Wait for Supabase to be ready
  if (!supabaseClient) {
    console.error('Supabase client not initialized');
    // Generate navbar for guest
    const navContainer = document.getElementById('navbar-container');
    if (navContainer) {
      navContainer.innerHTML = generateNavbar(pageName, null);
      updateDarkModeButton(localStorage.getItem('theme') || 'light');
    }
    return { user: null, isAdmin: false };
  }
  
  // Get current user
  let user = null;
  let isAdmin = false;
  
  try {
    const { data: { user: authUser } } = await supabaseClient.auth.getUser();
    user = authUser;
    isAdmin = user?.email === ADMIN_EMAIL;
  } catch (err) {
    console.error('Auth error:', err);
  }
  
  // Check if page requires authentication
  if (PROTECTED_PAGES.includes(pageName) && !user) {
    window.location.href = 'login.html';
    return { user: null, isAdmin: false };
  }
  
  // Check if page requires admin
  if (ADMIN_PAGES.includes(pageName) && !isAdmin) {
    window.location.href = 'index.html';
    return { user: null, isAdmin: false };
  }
  
  // Generate and insert navbar
  const navContainer = document.getElementById('navbar-container');
  if (navContainer) {
    navContainer.innerHTML = generateNavbar(pageName, user);
    updateDarkModeButton(localStorage.getItem('theme') || 'light');
  }
  
  // Log page view
  await logPageView(pageName, options.metadata || {});
  
  // Call page-specific init if provided
  if (options.onInit && typeof options.onInit === 'function') {
    options.onInit(user, isAdmin);
  }
  
  return { user, isAdmin };
}

/* ============================================
   UTILITY FUNCTIONS
   ============================================ */

// Format date for display
function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
}

// Format time for display
function formatTime(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Show a toast notification
function showToast(message, type = 'info') {
  // Remove existing toast
  const existingToast = document.querySelector('.toast');
  if (existingToast) existingToast.remove();
  
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  toast.style.cssText = `
    position: fixed;
    bottom: 20px;
    right: 20px;
    padding: 16px 24px;
    border-radius: 8px;
    color: white;
    font-weight: 500;
    z-index: 10000;
    animation: slideIn 0.3s ease;
    background: ${type === 'success' ? 'var(--success)' : type === 'error' ? 'var(--danger)' : 'var(--primary-blue)'};
  `;
  
  document.body.appendChild(toast);
  
  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// Add toast animations to page
const toastStyles = document.createElement('style');
toastStyles.textContent = `
  @keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  @keyframes slideOut {
    from { transform: translateX(0); opacity: 1; }
    to { transform: translateX(100%); opacity: 0; }
  }
`;
document.head.appendChild(toastStyles);

/* ============================================
   EXPORTS (for module usage if needed)
   ============================================ */

// Make functions globally available
window.initPage = initPage;
window.toggleDarkMode = toggleDarkMode;
window.toggleMobileMenu = toggleMobileMenu;
window.handleLogout = handleLogout;
window.logEvent = logEvent;
window.logPageView = logPageView;
window.getSessionId = getSessionId;
window.formatDate = formatDate;
window.formatTime = formatTime;
window.escapeHtml = escapeHtml;
window.showToast = showToast;
window.supabaseClient = supabaseClient;
window.ADMIN_EMAIL = ADMIN_EMAIL;