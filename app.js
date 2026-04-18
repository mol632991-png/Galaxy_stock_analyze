const DATA_URL = './data/dashboard_data.json';

const sectionMeta = {
  limit_up_pullback: { analysisKey: 'fundamental_analysis' },
  low_absorption: { analysisKey: 'fundamental_analysis' },
  graphic_pattern: { analysisKey: 'fundamental_analysis' },
  recommendations: { analysisKey: 'technical_analysis' },
};

const hoverCard = document.getElementById('hoverCard');
const hoverTitle = document.getElementById('hoverTitle');
const hoverCode = document.getElementById('hoverCode');
const hoverFundamental = document.getElementById('hoverFundamental');
const hoverTechnical = document.getElementById('hoverTechnical');
const hoverRisks = document.getElementById('hoverRisks');

const state = { data: null, selectedDates: {}, expandedSections: {} };

function formatPct(value) {
  const number = Number(value || 0);
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`;
}

function formatPrice(value) {
  return Number(value || 0).toFixed(2);
}

function tagClass(tag) {
  if (tag.includes('涨停')) return 'tag tag-limit';
  if (tag.includes('低吸') || tag.includes('资金流') || tag.includes('短买')) return 'tag tag-low';
  if (tag.includes('图形') || tag.includes('建仓') || tag.includes('走势')) return 'tag tag-graphic';
  if (tag.includes('主图') || tag.includes('试盘') || tag.includes('60')) return 'tag tag-signal';
  return 'tag tag-default';
}

function showHover(item) {
  hoverTitle.textContent = item.name || '--';
  hoverCode.textContent = item.code || '--';
  hoverFundamental.textContent = item.fundamental_analysis || '暂无';
  hoverTechnical.textContent = item.technical_analysis || '暂无';
  hoverRisks.innerHTML = '';
  (item.risk_items || ['未发现明显风险']).forEach((risk) => {
    const li = document.createElement('li');
    li.textContent = risk;
    hoverRisks.appendChild(li);
  });
  hoverCard.classList.remove('hidden');
}

function hideHover() {
  hoverCard.classList.add('hidden');
}

function renderTopbar(data) {
  document.getElementById('calendarDate').textContent = data.calendar_date || '--';
  document.getElementById('limitUpCount').textContent = data.market_summary?.limit_up_count ?? '--';
  document.getElementById('gt7Count').textContent = data.market_summary?.gt_7_count ?? '--';
  document.getElementById('limitDownCount').textContent = data.market_summary?.limit_down_count ?? '--';
  const indexCards = document.getElementById('indexCards');
  indexCards.innerHTML = '';
  (data.indices || []).forEach((item) => {
    const card = document.createElement('div');
    card.className = 'index-card';
    const pctClass = Number(item.pct_change) >= 0 ? 'pct-rise' : 'pct-fall';
    card.innerHTML = `<span>${item.name}</span><strong>${formatPrice(item.price)}</strong><small class="${pctClass}">${formatPct(item.pct_change)} / ${Number(item.change || 0).toFixed(2)}</small>`;
    indexCards.appendChild(card);
  });
}

function createDatePicker(sectionKey, container) {
  const dates = state.data.available_dates || [];
  const selectedDate = state.selectedDates[sectionKey] || dates[0];
  const expanded = Boolean(state.expandedSections[sectionKey]);
  const visibleDates = expanded ? dates : dates.slice(0, 7);
  container.innerHTML = '';
  const chips = document.createElement('div');
  chips.className = 'date-chip-list';
  visibleDates.forEach((date) => {
    const btn = document.createElement('button');
    btn.className = `date-chip ${selectedDate === date ? 'active' : ''}`;
    btn.textContent = date;
    btn.addEventListener('click', () => {
      state.selectedDates[sectionKey] = date;
      renderSection(sectionKey);
    });
    chips.appendChild(btn);
  });
  const toggle = document.createElement('button');
  toggle.className = 'toggle-dates';
  toggle.textContent = expanded ? '收起' : '展开近两个月';
  toggle.addEventListener('click', () => {
    state.expandedSections[sectionKey] = !expanded;
    renderSection(sectionKey);
  });
  container.appendChild(chips);
  container.appendChild(toggle);
}

function createTags(tags = []) {
  const wrap = document.createElement('div');
  wrap.className = 'tag-list';
  if (!tags.length) {
    wrap.innerHTML = '<span class="tag tag-default">暂无标签</span>';
    return wrap;
  }
  tags.forEach((tag) => {
    const span = document.createElement('span');
    span.className = tagClass(tag);
    span.textContent = tag;
    wrap.appendChild(span);
  });
  return wrap;
}

function renderRows(sectionKey, items, tbody) {
  tbody.innerHTML = '';
  if (!items || !items.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="8" class="empty-state">该日期暂无数据</td>';
    tbody.appendChild(tr);
    return;
  }
  items.forEach((item) => {
    const tr = document.createElement('tr');
    tr.addEventListener('mouseenter', () => showHover(item));
    tr.addEventListener('mouseleave', hideHover);
    const pctClass = Number(item.pct_change) >= 0 ? 'pct-rise' : 'pct-fall';
    const prevPctClass = Number(item.prev_pct_change) >= 0 ? 'pct-rise' : 'pct-fall';
    const prev2PctClass = Number(item.prev2_pct_change) >= 0 ? 'pct-rise' : 'pct-fall';
    const analysisField = sectionMeta[sectionKey]?.analysisKey || 'fundamental_analysis';
    tr.innerHTML = `
      <td><div class="stock-cell"><strong>${item.name}</strong><span>${item.code}</span></div></td>
      <td>${formatPrice(item.price)}</td>
      <td class="${pctClass}">${formatPct(item.pct_change)}</td>
      <td>${item.industry || '--'}</td>
      <td class="${prevPctClass}">${formatPct(item.prev_pct_change)}</td>
      <td class="${prev2PctClass}">${formatPct(item.prev2_pct_change)}</td>
      <td>${item[analysisField] || '--'}</td>
      <td></td>
    `;
    tr.children[7].appendChild(createTags(item.strategy_tags || []));
    tbody.appendChild(tr);
  });
}

function renderSection(sectionKey) {
  const panel = document.querySelector(`[data-section="${sectionKey}"]`);
  if (!panel) return;
  const sectionData = state.data.sections?.[sectionKey] || {};
  const dates = state.data.available_dates || [];
  if (!state.selectedDates[sectionKey]) state.selectedDates[sectionKey] = dates[0];
  const picker = panel.querySelector('[data-role="date-picker"]');
  if (picker) createDatePicker(sectionKey, picker);
  const tbody = panel.querySelector('[data-role="table-body"]');
  renderRows(sectionKey, sectionData[state.selectedDates[sectionKey]] || [], tbody);
}

function renderHotspots() {
  const hotspotList = document.getElementById('hotspotList');
  hotspotList.innerHTML = '';
  (state.data.sections?.hotspots || []).forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'hotspot-item';
    row.innerHTML = `<div><strong>${index + 1}. ${item.name}</strong><div class="hotspot-meta">热度分 ${item.heat_score} / 板块内股票 ${item.stock_count}</div></div><div class="hotspot-meta">平均涨跌幅 ${formatPct(item.avg_pct)}<br />资金流入 ${Number(item.total_amount).toFixed(2)} 亿</div>`;
    hotspotList.appendChild(row);
  });
}

async function init() {
  try {
    const response = await fetch(DATA_URL, { cache: 'no-store' });
    state.data = await response.json();
    renderTopbar(state.data);
    renderSection('limit_up_pullback');
    renderSection('low_absorption');
    renderSection('graphic_pattern');
    renderSection('recommendations');
    renderHotspots();
  } catch (error) {
    console.error(error);
    document.body.innerHTML = '<div style="padding:24px;color:#fff;">页面数据加载失败，请确认 GitHub Actions 已成功生成 <code>data/dashboard_data.json</code>。</div>';
  }
}

document.addEventListener('DOMContentLoaded', init);
