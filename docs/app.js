const money = n => n >= 1e8 ? `${(n / 1e8).toFixed(2)} 亿` : `${(n / 1e4).toFixed(0)} 万`;
async function get(path) { const r = await fetch(path, {cache:'no-store'}); if (!r.ok) throw Error(r.status); return r.json(); }
async function render() {
  try {
    const [latest, history] = await Promise.all([get('data/latest.json'), get('data/history.json')]);
    document.querySelector('#summary').textContent = latest.updated_at ? `最后更新：${new Date(latest.updated_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false})}` : '尚未运行';
    document.querySelector('#status').innerHTML = `<p class="muted">状态：${latest.status}　扫描：${latest.total_scanned ?? 0} 只　入选：${latest.stocks.length} 只</p>`;
    const weather = latest.market_weather;
    document.querySelector('#weather').innerHTML = weather ? `<span class="weather-label">${weather.label}</span><p>${weather.reason}</p><p class="weather-metrics">上涨 ${weather.rising ?? '—'} 家 / 下跌 ${weather.falling ?? '—'} 家　涨跌比：${weather.ratio ? `${weather.ratio}:1` : '—'}</p><div class="weather-indexes">${(weather.indexes || []).map(i => `<span>${i.name} ${i.close} / MA20 ${i.ma20}（${i.above_ma20 ? '上方' : '下方'}）</span>`).join('')}</div>` : '<p class="muted">首次交易日更新后显示。</p>';
    document.querySelector('#strategy').textContent = latest.strategy ? `${latest.strategy.name}（版本 ${latest.strategy.version}）` : '首次运行后显示';
    document.querySelector('#stocks').innerHTML = latest.stocks.length ? latest.stocks.map(s => `<tr><td>${s.ts_code}</td><td>${s.name}</td><td>${s.close}</td><td class="${s.pct_chg >= 0 ? 'positive':'negative'}">${s.pct_chg}%</td><td>${money(s.amount_yuan)}</td><td>${s.reason}</td></tr>`).join('') : '<tr><td colspan="6" class="muted">暂无可展示的股票池结果。</td></tr>';
    document.querySelector('#history').innerHTML = history.map(h => `<li>${h.run_id} · ${h.status} · ${h.count} 只</li>`).join('') || '<li>暂无历史记录</li>';
  } catch { document.querySelector('#summary').textContent = '数据暂时不可用，请稍后刷新。'; }
}
render();
