/* VideoHub — Main JS */

document.addEventListener('DOMContentLoaded', () => {
  initLoader();
  initSidebar();
  initNavbar();
  initUserMenu();
  initSearch();
  initNotifications();
  autoHideFlash();
  initToasts();
});

// ---- Page Loader ----
function initLoader() {
  const loader = document.getElementById('page-loader');
  if (!loader) return;
  window.addEventListener('load', () => {
    setTimeout(() => loader.classList.add('hidden'), 300);
  });
  setTimeout(() => loader.classList.add('hidden'), 1500);
}

// ---- Sidebar ----
function initSidebar() {
  const toggle = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('overlay');
  const wrapper = document.querySelector('.main-wrapper');
  if (!toggle || !sidebar) return;

  let isOpen = window.innerWidth >= 1280;
  
  function setSidebar(open) {
    isOpen = open;
    sidebar.classList.toggle('open', open);
    overlay.classList.toggle('visible', open && window.innerWidth < 1280);
    if (window.innerWidth >= 1280) {
      wrapper?.classList.toggle('sidebar-open', open);
    }
    // Animate hamburger
    const spans = toggle.querySelectorAll('span');
    if (open) {
      spans[0].style.cssText = 'transform:rotate(45deg) translate(5px,5px)';
      spans[1].style.cssText = 'opacity:0';
      spans[2].style.cssText = 'transform:rotate(-45deg) translate(5px,-5px)';
    } else {
      spans.forEach(s => s.style.cssText = '');
    }
  }
  
  setSidebar(window.innerWidth >= 1280);
  toggle.addEventListener('click', () => setSidebar(!isOpen));
  overlay.addEventListener('click', () => setSidebar(false));
  
  window.addEventListener('resize', () => {
    if (window.innerWidth >= 1280) {
      setSidebar(true);
      overlay.classList.remove('visible');
    } else if (isOpen) {
      setSidebar(false);
    }
  });
}

// ---- Navbar scroll effect ----
function initNavbar() {
  const nav = document.getElementById('navbar');
  if (!nav) return;
  window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 10);
  }, { passive: true });
}

// ---- User Dropdown ----
function initUserMenu() {
  const btn = document.getElementById('userMenuBtn');
  const dropdown = document.getElementById('userDropdown');
  const wrapper = document.getElementById('navDropdown');
  if (!btn || !dropdown || !wrapper) return;

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = wrapper.classList.toggle('open');
    dropdown.style.display = isOpen ? 'block' : 'none';
  });
  
  document.addEventListener('click', (e) => {
    if (!wrapper.contains(e.target)) {
      wrapper.classList.remove('open');
      dropdown.style.display = 'none';
    }
  });
  
  // Keep open when moving mouse inside dropdown
  dropdown.addEventListener('mouseleave', () => {});
}

// ---- Search Autocomplete ----
function initSearch() {
  const input = document.getElementById('searchInput');
  const suggestions = document.getElementById('searchSuggestions');
  if (!input || !suggestions) return;

  let timer = null;
  
  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) {
      suggestions.classList.add('hidden');
      return;
    }
    timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/v1/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        renderSuggestions(data.videos || []);
      } catch {}
    }, 300);
  });

  input.addEventListener('blur', () => {
    setTimeout(() => suggestions.classList.add('hidden'), 200);
  });
  input.addEventListener('focus', () => {
    if (suggestions.children.length > 0) suggestions.classList.remove('hidden');
  });

  function renderSuggestions(videos) {
    if (!videos.length) { suggestions.classList.add('hidden'); return; }
    suggestions.innerHTML = '';
    videos.slice(0, 5).forEach(v => {
      const item = document.createElement('div');
      item.className = 'suggestion-item';
      item.innerHTML = `
        ${v.thumbnail ? `<img src="${v.thumbnail}" alt="">` : '<div style="width:48px;height:28px;background:var(--bg-3);border-radius:4px;flex-shrink:0;"></div>'}
        <span class="suggestion-text">${escapeHtml(v.title)}</span>
      `;
      item.addEventListener('click', () => {
        window.location.href = `/videos/watch/${v.slug}`;
      });
      suggestions.appendChild(item);
    });
    suggestions.classList.remove('hidden');
  }
}

// ---- Notifications ----
function initNotifications() {
  const badge = document.getElementById('notifBadge');
  if (!badge) return;

  async function fetchCount() {
    try {
      const res = await fetch('/users/notifications/count');
      const data = await res.json();
      if (data.count > 0) {
        badge.textContent = data.count > 99 ? '99+' : data.count;
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    } catch {}
  }
  
  fetchCount();
  setInterval(fetchCount, 60000);
}

// ---- Flash auto-hide ----
function autoHideFlash() {
  document.querySelectorAll('.flash').forEach(flash => {
    setTimeout(() => {
      flash.style.animation = 'slideIn 0.3s ease reverse';
      setTimeout(() => flash.remove(), 300);
    }, 5000);
  });
}

// ---- Toast System ----
function initToasts() {
  if (!document.getElementById('toast-container')) {
    const container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
}

window.showToast = function(message, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.style.animation = 'toastIn 0.3s ease reverse';
    setTimeout(() => toast.remove(), 300);
  }, duration);
};

// ---- Confirm Dialog ----
window.showConfirm = function(message, onConfirm) {
  if (confirm(message)) onConfirm();
};

// ---- API Helper ----
window.apiCall = async function(url, method = 'GET', data = null) {
  const opts = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken()
    }
  };
  if (data) opts.body = JSON.stringify(data);
  const res = await fetch(url, opts);
  if (!res.ok && res.status !== 400) {
    // Non-JSON error response (e.g. 500 HTML page)
    throw new Error(`HTTP ${res.status}`);
  }
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error('Неверный ответ сервера');
  }
};

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) return meta.content;
  const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrf_token='));
  return cookie ? cookie.split('=')[1] : '';
}

// ---- Like/Dislike ----
window.handleLike = async function(videoId, isLike, btn) {
  try {
    const data = await apiCall(`/videos/${videoId}/like`, 'POST', { is_like: isLike });
    if (data.likes !== undefined) {
      const likeBtn = document.querySelector('[data-action="like"]');
      const dislikeBtn = document.querySelector('[data-action="dislike"]');
      if (likeBtn) likeBtn.querySelector('.count').textContent = formatCount(data.likes);
      if (dislikeBtn) dislikeBtn.querySelector('.count').textContent = formatCount(data.dislikes);
      
      // Update button states
      document.querySelectorAll('.action-btn[data-action]').forEach(b => {
        b.classList.remove('liked', 'disliked');
      });
      if (data.action !== 'removed') {
        if (isLike && likeBtn) likeBtn.classList.add('liked');
        if (!isLike && dislikeBtn) dislikeBtn.classList.add('disliked');
      }
    }
  } catch {
    showToast('Ошибка. Попробуйте ещё раз.', 'error');
  }
};

// ---- Subscribe ----
window.handleSubscribe = async function(userId, btn) {
  try {
    const data = await apiCall(`/users/subscribe/${userId}`, 'POST');
    if (data.action) {
      const isSubscribed = data.action === 'subscribed';
      btn.textContent = isSubscribed ? 'Отписаться' : 'Подписаться';
      btn.classList.toggle('subscribed', isSubscribed);
      
      const countEl = document.querySelector('.channel-subs');
      if (countEl && data.subscriber_count !== undefined) {
        countEl.textContent = formatCount(data.subscriber_count) + ' подписчиков';
      }
      showToast(isSubscribed ? 'Вы подписались!' : 'Вы отписались.');
    }
  } catch {
    showToast('Ошибка. Попробуйте ещё раз.', 'error');
  }
};

// ---- Comments ----
window.initComments = function(videoId) {
  const form = document.getElementById('commentForm');
  const input = document.getElementById('commentInput');
  const list = document.getElementById('commentsList');
  if (!form || !input) return;

  const submitBtn = form.querySelector('.comment-submit');
  if (submitBtn) {
    submitBtn.addEventListener('click', () => submitComment(null));
  }
  
  input.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'Enter') submitComment(null);
  });
  
  // Auto-expand textarea
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 200) + 'px';
  });
  
  async function submitComment(parentId = null) {
    const content = input.value.trim();
    if (!content) return;

    const btn = form.querySelector('.comment-submit');
    if (btn) { btn.disabled = true; btn.textContent = 'Отправка…'; }

    try {
      const data = await apiCall(`/videos/${videoId}/comment`, 'POST', { content, parent_id: parentId });
      if (data.id) {
        prependComment(data);
        input.value = '';
        input.style.height = '';
        showToast('Комментарий добавлен!');
      } else if (data.error) {
        showToast(data.error, 'error');
      }
    } catch(e) {
      showToast('Ошибка отправки. Попробуйте ещё раз.', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Отправить'; }
    }
  }
  
  function prependComment(c) {
    if (!list) return;
    const el = createCommentEl(c);
    list.insertBefore(el, list.firstChild);
  }
};

function createCommentEl(c) {
  const div = document.createElement('div');
  div.className = 'comment-item';
  div.dataset.id = c.id;
  div.innerHTML = `
    <div class="comment-avatar">
      <img src="/static/uploads/avatars/${c.avatar || 'default_avatar.png'}" 
           alt="${escapeHtml(c.author)}"
           onerror="this.src='/static/img/default_avatar.png'">
    </div>
    <div class="comment-body">
      <div class="comment-header">
        <a href="/users/${escapeHtml(c.author_username)}" class="comment-username">${escapeHtml(c.author)}</a>
        <span class="comment-time">только что</span>
      </div>
      <div class="comment-content">${escapeHtml(c.content)}</div>
      <div class="comment-footer">
        <button class="comment-btn">👍 0</button>
        <button class="comment-btn">Ответить</button>
        <button class="comment-btn delete-comment" onclick="deleteComment(${c.id}, this)">Удалить</button>
      </div>
    </div>
  `;
  return div;
}

window.deleteComment = async function(commentId, btn) {
  if (!confirm('Удалить комментарий?')) return;
  try {
    await apiCall(`/videos/comment/${commentId}/delete`, 'DELETE');
    btn.closest('.comment-item').remove();
    showToast('Комментарий удалён.');
  } catch {
    showToast('Ошибка.', 'error');
  }
};

// ---- Video Description Toggle ----
window.toggleDescription = function(btn) {
  const desc = document.querySelector('.video-description');
  if (!desc) return;
  const collapsed = desc.classList.toggle('collapsed');
  btn.textContent = collapsed ? 'Показать больше' : 'Показать меньше';
};

// ---- Upload drag & drop ----
window.initUpload = function() {
  const dropZone = document.querySelector('.drop-zone');
  const fileInput = dropZone?.querySelector('input[type="file"]');
  if (!dropZone || !fileInput) return;

  ['dragenter', 'dragover'].forEach(e => {
    dropZone.addEventListener(e, (ev) => {
      ev.preventDefault();
      dropZone.classList.add('drag-over');
    });
  });
  
  ['dragleave', 'drop'].forEach(e => {
    dropZone.addEventListener(e, (ev) => {
      ev.preventDefault();
      dropZone.classList.remove('drag-over');
      if (e === 'drop') {
        const files = ev.dataTransfer.files;
        if (files[0]) {
          fileInput.files = files;
          handleFileSelect(files[0]);
        }
      }
    });
  });
  
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) handleFileSelect(fileInput.files[0]);
  });
  
  function handleFileSelect(file) {
    const dropContent = dropZone.querySelector('.drop-content');
    if (dropContent) {
      dropContent.innerHTML = `
        <div class="drop-icon">🎬</div>
        <div class="drop-title">${escapeHtml(file.name)}</div>
        <div class="drop-subtitle">${formatFileSize(file.size)}</div>
      `;
    }
    
    // Auto-fill title
    const titleInput = document.getElementById('videoTitle');
    if (titleInput && !titleInput.value) {
      titleInput.value = file.name.replace(/\.[^.]+$/, '').replace(/[-_]/g, ' ');
    }
    
    // Show form
    const form = document.getElementById('uploadFormSection');
    if (form) form.style.display = 'block';
  }
};

// ---- Admin actions ----
window.adminUserAction = async function(userId, action, extra = {}) {
  const data = { action, ...extra };
  if (action === 'ban' && !data.reason) {
    data.reason = prompt('Причина блокировки:') || 'Нарушение правил';
  }
  if (action === 'delete' && !confirm('Удалить пользователя навсегда?')) return;
  
  try {
    const result = await apiCall(`/admin/users/${userId}/action`, 'POST', data);
    if (result.success) {
      showToast(result.message);
      setTimeout(() => location.reload(), 800);
    } else {
      showToast(result.error || 'Ошибка.', 'error');
    }
  } catch {
    showToast('Ошибка сервера.', 'error');
  }
};

window.adminVideoAction = async function(videoId, action) {
  if (action === 'delete' && !confirm('Удалить видео навсегда?')) return;
  
  try {
    const result = await apiCall(`/admin/videos/${videoId}/action`, 'POST', { action });
    if (result.success) {
      showToast('Готово!');
      setTimeout(() => location.reload(), 800);
    }
  } catch {
    showToast('Ошибка.', 'error');
  }
};

// ---- Utility Functions ----
function escapeHtml(text) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(String(text || '')));
  return div.innerHTML;
}

function formatCount(n) {
  if (n === undefined || n === null) return '0';
  if (n >= 1000000) return (n / 1000000).toFixed(1).replace('.0', '') + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1).replace('.0', '') + 'K';
  return String(n);
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1024 ** 3) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
  return (bytes / 1024 ** 3).toFixed(2) + ' GB';
}

// ---- Intersection Observer for lazy loading ----
if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const img = entry.target;
        if (img.dataset.src) {
          img.src = img.dataset.src;
          img.removeAttribute('data-src');
          observer.unobserve(img);
        }
      }
    });
  }, { rootMargin: '200px' });
  
  document.querySelectorAll('img[data-src]').forEach(img => observer.observe(img));
}

// ---- Report Video ----
window.reportVideo = function(videoId) {
  const reason = prompt('Причина жалобы:\n1. Спам\n2. Оскорбительный контент\n3. Нарушение авторских прав\n4. Другое\nВведите номер или описание:');
  if (!reason) return;
  apiCall('/api/v1/report', 'POST', { video_id: videoId, reason })
    .then(() => showToast('Жалоба отправлена.'))
    .catch(() => showToast('Ошибка.', 'error'));
};
