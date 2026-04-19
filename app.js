const state = {
  data: {},
  globalSelectedDate: null,
  isDateDropdownOpen: false
};

async function init() {
  try {
    const res = await fetch('./data/dashboard_data.json?v=' + Date.now());
    state.data = await res.json();

    const dates = state.data.available_dates || [];
    state.globalSelectedDate = dates[0];

    renderApp();
  } catch (err) {
    console.error('Failed to load data:', err);
    document.body.innerHTML = `<div style="padding: 50px; text-align: center;"><h1>数据加载失败</h1><p>${err.message}</p></div>`;
  }
}

function renderApp() {
  if (!state.data.sections) return;

  // 更新顶栏日期显示
  const calendarDisplay = document.getElementById('calendarDateDisplay');
  if (calendarDisplay) calendarDisplay.textContent = state.globalSelectedDate || '--';

  // 大盘卡片
  renderIndices();
  // 统计
  renderSummary();
  // 侧边栏：热点板块
  renderHotspots();

  // 选股池全局日期筛选
  renderGlobalDatePicker();

  // 各大选股模块
  const sections = ['limit_up_pullback', 'fund_flow', 'low_absorption', 'graphic_pattern', 'recommendations'];
  sections.forEach(key => renderSection(key));
}

function renderGlobalDatePicker() {
  const container = document.getElementById('globalDatePicker');
  if (!container) return;

  const dates = state.data.available_dates || [];
  const latest5 = dates.slice(0, 5);

  container.innerHTML = '';

  const chipList = document.createElement('div');
  chipList.className = 'date-chip-list';

  latest5.forEach(date => {
    const btn = document.createElement('button');
    btn.className = `date-chip ${state.globalSelectedDate === date ? 'active' : ''}`;
    btn.textContent = date.split('-').slice(1).join('/'); // 显示 MM/DD
    btn.title = date;
    btn.onclick = () => {
      state.globalSelectedDate = date;
      renderApp();
    };
    chipList.appendChild(btn);
  });

  const moreBtn = document.createElement('button');
  moreBtn.className = 'toggle-dates';
  moreBtn.innerHTML = '<i>📅</i> 更多';
  moreBtn.onclick = (e) => {
    e.stopPropagation();
    state.isDateDropdownOpen = !state.isDateDropdownOpen;
    renderGlobalDatePicker();
  };

  container.appendChild(chipList);
  container.appendChild(moreBtn);

  if (state.isDateDropdownOpen) {
    const dropdown = document.createElement('div');
    dropdown.className = 'full-date-dropdown';
    dates.forEach(date => {
      const b = document.createElement('button');
      b.className = `date-chip ${state.globalSelectedDate === date ? 'active' : ''}`;
      b.textContent = date;
      b.onclick = () => {
        state.globalSelectedDate = date;
        state.isDateDropdownOpen = false;
        renderApp();
      };
      dropdown.appendChild(b);
    });
    container.appendChild(dropdown);

    // 点击外部关闭
    const closer = () => {
      state.isDateDropdownOpen = false;
      renderGlobalDatePicker();
      document.removeEventListener('click', closer);
    };
    setTimeout(() => document.addEventListener('click', closer), 10);
  }
}

function renderSection(sectionKey) {
  const panel = document.querySelector(`.panel[data-section="${sectionKey}"]`) || document.querySelector(`.subpanel[data-section="${sectionKey}"]`);
  if (!panel) return;

  const tbody = panel.querySelector('[data-role="table-body"]');
  if (!tbody) return;

  const sectionData = state.data.sections[sectionKey] || {};
  const list = sectionData[state.globalSelectedDate] || [];

  tbody.innerHTML = '';
  if (list.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-state">该日期暂无选股结果。</td></tr>`;
    return;
  }

  list.forEach(item => {
    const tr = document.createElement('tr');
    tr.onclick = () => showDetail(item);

    const pctClass = item.pct_change >= 0 ? 'pct-rise' : 'pct-fall';
    const prevClass = item.prev_pct_change >= 0 ? 'pct-rise' : 'pct-fall';
    const prev2Class = item.prev2_pct_change >= 0 ? 'pct-rise' : 'pct-fall';

    tr.innerHTML = `
      <td class="stock-cell"><strong>${item.name}</strong><span>${item.code}</span></td>
      <td><strong>${item.price.toFixed(2)}</strong></td>
      <td class="${pctClass}"><strong>${formatPct(item.pct_change)}</strong></td>
      <td>${item.industry || '--'}</td>
      <td class="${prevClass}">${formatPct(item.prev_pct_change)}</td>
      <td class="${prev2Class}">${formatPct(item.prev2_pct_change)}</td>
      <td style="font-size: 11px; max-width: 200px;">${item.fundamental_analysis || '--'}</td>
      <td class="tag-cell">${createTags(item.strategy_tags)}</td>
    `;
    tbody.appendChild(tr);
  });
}

function formatPct(val) {
  if (val === null || val === undefined) return '--';
  return (val > 0 ? '+' : '') + Number(val).toFixed(2) + '%';
}

function createTags(tags = []) {
  if (typeof tags === 'string') tags = tags.split('|');
  return (tags || []).map(tag => {
    let cls = 'tag-default';
    if (tag.includes('涨停')) cls = 'tag-limit';
    if (tag.includes('低吸')) cls = 'tag-low';
    if (tag.includes('图形')) cls = 'tag-graphic';
    if (tag.includes('资金')) cls = 'tag-signal';
    return `<span class="tag ${cls}">${tag}</span>`;
  }).join('');
}

function renderIndices() {
  const container = document.getElementById('indexCards');
  if (!container) return;
  container.innerHTML = (state.data.indices || []).map(idx => {
    const cls = idx.pct_change >= 0 ? 'price-rise' : 'price-fall';
    return `<div class="index-card"><span>${idx.name}</span><strong class="${cls}">${idx.price.toFixed(2)}</strong><small class="${cls}">${formatPct(idx.pct_change)}</small></div>`;
  }).join('');
}

function renderSummary() {
  const s = state.data.market_summary || {};
  const update = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val !== undefined ? val : '--';
  };
  update('limitUpCount', s.limit_up_count);
  update('gt7Count', s.gt_7_count);
  update('limitDownCount', s.limit_down_count);
}

function renderHotspots() {
  const hotspotList = document.getElementById('hotspotList');
  if (!hotspotList) return;
  hotspotList.innerHTML = '';
  (state.data.sections?.hotspots || []).forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'hotspot-item';
    const pctClass = Number(item.avg_pct) >= 0 ? 'pct-rise' : 'pct-fall';
    row.innerHTML = `
      <div>
        <strong>${index + 1}. ${item.name}</strong>
        <div class="hotspot-meta">龙头：${item.top_stock || '--'}</div>
      </div>
      <div class="hotspot-meta" style="text-align: right;">
        <span class="${pctClass}" style="font-weight:bold;">${formatPct(item.avg_pct)}</span><br />
        <span style="color:var(--gold)">${Number(item.total_amount).toFixed(2)} 亿</span>
      </div>`;
    hotspotList.appendChild(row);
  });
}

function showDetail(item) {
  const card = document.getElementById('hoverCard');
  document.getElementById('hoverTitle').textContent = item.name;
  document.getElementById('hoverCode').textContent = item.code;
  document.getElementById('hoverFundamental').textContent = item.fundamental_analysis || '暂无数据';
  document.getElementById('hoverTechnical').textContent = item.technical_analysis || '暂无数据';

  const risksUl = document.getElementById('hoverRisks');
  risksUl.innerHTML = (item.risk_items || ['未发现明显风险']).map(r => `<li>${r}</li>`).join('');

  card.classList.remove('hidden');
  card.onclick = () => card.classList.add('hidden');
}

window.onload = init;
