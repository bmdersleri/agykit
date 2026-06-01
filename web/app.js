        // ── Gear status indicator helpers ──
        function gearPath(cx, cy, n, Ro, Ri, Rh) {
            const PI2 = 2 * Math.PI;
            const step = PI2 / n;
            const tw = step * 0.30;
            const pt = (r, a) =>
                `${(cx + r * Math.cos(a)).toFixed(2)},${(cy + r * Math.sin(a)).toFixed(2)}`;
            let d = '';
            for (let i = 0; i < n; i++) {
                const a = i * step;
                const rA = a - tw, tS = a - tw * 0.48, tE = a + tw * 0.48, rB = a + tw;
                const nA = (i + 1) * step - tw;
                if (i === 0) d += `M ${pt(Ri, rA)}`;
                else         d += ` L ${pt(Ri, rA)}`;
                d += ` L ${pt(Ro, tS)} L ${pt(Ro, tE)} L ${pt(Ri, rB)}`;
                d += ` A ${Ri} ${Ri} 0 0 1 ${pt(Ri, nA)}`;
            }
            d += ' Z';
            const h1x = (cx + Rh).toFixed(2), h2x = (cx - Rh).toFixed(2), cys = String(cy);
            d += ` M ${h1x},${cys} A ${Rh} ${Rh} 0 1 0 ${h2x},${cys} A ${Rh} ${Rh} 0 1 0 ${h1x},${cys} Z`;
            return d;
        }

        function gearStatusHTML(statusClass, labelText) {
            const working = statusClass === 'active';
            const stale   = statusClass === 'stale';
            const bigP    = gearPath(13, 17, 14, 13, 10,   3.5);
            const smallP  = gearPath(32, 17,  9,  8.5, 6.5, 2.5);
            const bigCol   = working ? '#10b981' : stale ? '#d97706' : '#374151';
            const smallCol = working ? '#22d3ee' : stale ? '#b45309' : '#1f2937';
            const bigOp    = working ? '0.9' : '0.4';
            const smallOp  = working ? '0.9' : '0.35';
            const bigAnim  = working
                ? ' style="transform-origin:13px 17px;animation:gear-cw 3s linear infinite"' : '';
            const smAnim   = working
                ? ' style="transform-origin:32px 17px;animation:gear-ccw 2s linear infinite"' : '';
            return `<div class="gear-status-cell">
                <svg viewBox="0 0 43 35" width="46" height="36"
                     xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle;overflow:visible">
                    <path d="${bigP}" fill="${bigCol}" fill-rule="evenodd" opacity="${bigOp}"${bigAnim}/>
                    <circle cx="13" cy="17" r="2" fill="#0a0a1a"/>
                    <path d="${smallP}" fill="${smallCol}" fill-rule="evenodd" opacity="${smallOp}"${smAnim}/>
                    <circle cx="32" cy="17" r="1.5" fill="#0a0a1a"/>
                </svg>
                <span class="gear-status-label ${statusClass}">${labelText}</span>
            </div>`;
        }

        let mainChartInstance = null;
        let mixChartInstance = null;
        let currentChartSource = null;

        const sourceSelect = document.getElementById('sourceSelect');
        const rangeSelect = document.getElementById('rangeSelect');
        const warningBanner = document.getElementById('warningBanner');
        const warningText = document.getElementById('warningText');
        const noDataContainer = document.getElementById('noDataContainer');
        const chartsGrid = document.getElementById('chartsGrid');
        const liveDot = document.getElementById('liveDot');
        const themeToggleBtn = document.getElementById('themeToggle');

        const colors = [
            'rgba(56, 189, 248, 1)',   // light blue
            'rgba(244, 63, 94, 1)',    // rose
            'rgba(16, 185, 129, 1)',   // emerald
            'rgba(245, 158, 11, 1)',   // amber
            'rgba(139, 92, 246, 1)',   // violet
            'rgba(236, 72, 153, 1)',   // pink
            'rgba(20, 184, 166, 1)',   // teal
            'rgba(239, 68, 68, 1)',    // red
        ];
        const bgColors = [
            'rgba(56, 189, 248, 0.2)',
            'rgba(244, 63, 94, 0.2)',
            'rgba(16, 185, 129, 0.2)',
            'rgba(245, 158, 11, 0.2)',
            'rgba(139, 92, 246, 0.2)',
            'rgba(236, 72, 153, 0.2)',
            'rgba(20, 184, 166, 0.2)',
            'rgba(239, 68, 68, 0.2)',
        ];

        // Theme management
        let currentTheme = localStorage.getItem('theme') || 'dark';
        applyTheme(currentTheme);

        themeToggleBtn.addEventListener('click', () => {
            currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
            applyTheme(currentTheme);
        });

        function getChartColors() {
            const isDark = document.body.getAttribute('data-theme') === 'dark';
            return {
                text: isDark ? '#9ca3af' : '#64748b',
                grid: isDark ? '#374151' : '#e2e8f0',
            };
        }

        function applyTheme(theme) {
            document.body.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
            themeToggleBtn.textContent = theme === 'dark' ? '☀️' : '🌙';
            
            const cColors = getChartColors();
            Chart.defaults.color = cColors.text;
            Chart.defaults.borderColor = cColors.grid;
            
            if (mainChartInstance) {
                if (mainChartInstance.options.scales.x) {
                    mainChartInstance.options.scales.x.grid.color = cColors.grid;
                    mainChartInstance.options.scales.x.ticks.color = cColors.text;
                }
                if (mainChartInstance.options.scales.y) {
                    mainChartInstance.options.scales.y.grid.color = cColors.grid;
                    mainChartInstance.options.scales.y.ticks.color = cColors.text;
                }
                if (mainChartInstance.options.scales.y1) {
                    mainChartInstance.options.scales.y1.grid.color = cColors.grid;
                    mainChartInstance.options.scales.y1.ticks.color = cColors.text;
                }
                mainChartInstance.update();
            }
            if (mixChartInstance) {
                if (mixChartInstance.options.scales.x) {
                    mixChartInstance.options.scales.x.grid.color = cColors.grid;
                    mixChartInstance.options.scales.x.ticks.color = cColors.text;
                }
                if (mixChartInstance.options.scales.y) {
                    mixChartInstance.options.scales.y.grid.color = cColors.grid;
                    mixChartInstance.options.scales.y.ticks.color = cColors.text;
                }
                mixChartInstance.update();
            }
        }

        function showWarning(msg) {
            if (msg) {
                warningText.textContent = msg;
                warningBanner.style.display = 'flex';
            } else {
                warningBanner.style.display = 'none';
            }
        }

        async function loadData() {
            const source = sourceSelect.value;
            const range = rangeSelect.value;

            try {
                const response = await fetch(`/api/data?source=${source}&range=${range}`);
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.error || 'Server error');
                }
                const data = await response.json();

                showWarning(data.warning);

                if (!data.labels || data.labels.length === 0) {
                    noDataContainer.style.display = 'block';
                    chartsGrid.style.display = 'none';
                    return;
                }

                noDataContainer.style.display = 'none';
                chartsGrid.style.display = 'grid';

                renderCharts(source, data);
            } catch (err) {
                showWarning(`Veri yüklenemedi: ${err.message}`);
                noDataContainer.style.display = 'block';
                chartsGrid.style.display = 'none';
            } finally {
                const el = document.getElementById('footer-ts');
                if (el) {
                    el.textContent = new Date().toLocaleString('tr-TR');
                }
            }
        }

        function buildMixDatasets(entries) {
            const datasets = [];
            let colorIdx = 0;
            for (const [model, vals] of Object.entries(entries || {})) {
                datasets.push({
                    label: model,
                    data: vals,
                    backgroundColor: bgColors[colorIdx % bgColors.length],
                    borderColor: colors[colorIdx % colors.length],
                    borderWidth: 1,
                    stack: 'stack0'
                });
                colorIdx++;
            }
            return datasets;
        }

        function createClaudeCharts(ctxMain, ctxMix, data, cColors) {
            const noAnim = { animation: { duration: 0 } };
            mainChartInstance = new Chart(ctxMain, {
                type: 'line',
                data: {
                    labels: data.labels,
                    datasets: [{
                        label: 'Toplam Token',
                        data: data.tokens_total,
                        borderColor: 'rgba(56, 189, 248, 1)',
                        backgroundColor: 'rgba(56, 189, 248, 0.1)',
                        fill: true,
                        tension: 0.3,
                        borderWidth: 2
                    }]
                },
                options: {
                    ...noAnim,
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { color: cColors.grid }, ticks: { color: cColors.text, maxTicksLimit: 6, maxRotation: 0 } },
                        y: { beginAtZero: true, grid: { color: cColors.grid }, ticks: { color: cColors.text, callback: v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v } }
                    }
                }
            });
            mixChartInstance = new Chart(ctxMix, {
                type: 'bar',
                data: { labels: data.labels, datasets: buildMixDatasets(data.tokens_by_model) },
                options: {
                    ...noAnim,
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title: (items) => items[0]?.label || '',
                                label: (item) => {
                                    const name = item.dataset.label
                                        .replace(/^@cf\//,'').replace(/^claude-/,'')
                                        .replace(/^MiniMaxAI\//,'').slice(0, 28);
                                    const val = item.raw >= 1000 ? Math.round(item.raw/1000)+'k' : item.raw;
                                    return ` ${name}: ${val}`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: { stacked: true, grid: { color: cColors.grid }, ticks: { color: cColors.text, maxTicksLimit: 6, maxRotation: 0 } },
                        y: { stacked: true, beginAtZero: true, grid: { color: cColors.grid }, ticks: { color: cColors.text, callback: v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v } }
                    }
                }
            });
        }

        function createAgyCharts(ctxMain, ctxMix, data, cColors) {
            const noAnim = { animation: { duration: 0 } };
            mainChartInstance = new Chart(ctxMain, {
                type: 'line',
                data: {
                    labels: data.labels,
                    datasets: [
                        {
                            label: 'Oturumlar',
                            data: data.sessions,
                            borderColor: 'rgba(16, 185, 129, 1)',
                            backgroundColor: 'rgba(16, 185, 129, 0.1)',
                            fill: true,
                            tension: 0.3,
                            borderWidth: 2,
                            yAxisID: 'y'
                        },
                        {
                            label: 'Araç Çağrıları',
                            data: data.tool_calls,
                            borderColor: 'rgba(139, 92, 246, 1)',
                            backgroundColor: 'transparent',
                            tension: 0.3,
                            borderWidth: 2,
                            borderDash: [4, 4],
                            yAxisID: 'y1'
                        }
                    ]
                },
                options: {
                    ...noAnim,
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { grid: { color: cColors.grid }, ticks: { color: cColors.text, maxTicksLimit: 6, maxRotation: 0 } },
                        y: {
                            type: 'linear', display: true, position: 'left', beginAtZero: true,
                            title: { display: true, text: 'Oturumlar' },
                            grid: { color: cColors.grid },
                            ticks: { color: cColors.text, callback: v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v }
                        },
                        y1: {
                            type: 'linear', display: true, position: 'right', beginAtZero: true,
                            title: { display: true, text: 'Araç Çağrıları' },
                            grid: { drawOnChartArea: false },
                            ticks: { color: cColors.text, callback: v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v }
                        }
                    }
                }
            });
            mixChartInstance = new Chart(ctxMix, {
                type: 'bar',
                data: { labels: data.labels, datasets: buildMixDatasets(data.model_mix) },
                options: {
                    ...noAnim,
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { stacked: true, grid: { color: cColors.grid }, ticks: { color: cColors.text, maxTicksLimit: 6, maxRotation: 0 } },
                        y: { stacked: true, beginAtZero: true, grid: { color: cColors.grid }, ticks: { color: cColors.text, callback: v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v } }
                    }
                }
            });
        }

        function renderCharts(source, data) {
            const cColors = getChartColors();

            if (source === 'claude') {
                document.getElementById('mainChartTitle').textContent = 'Günlük Token Kullanımı';
                document.getElementById('mixChartTitle').textContent = 'Model Dağılımı';

                if (currentChartSource === 'claude' && mainChartInstance && mixChartInstance) {
                    mainChartInstance.data.labels = data.labels;
                    mainChartInstance.data.datasets[0].data = data.tokens_total;
                    mainChartInstance.update('none');
                    mixChartInstance.data.labels = data.labels;
                    mixChartInstance.data.datasets = buildMixDatasets(data.tokens_by_model);
                    mixChartInstance.update('none');
                } else {
                    if (mainChartInstance) mainChartInstance.destroy();
                    if (mixChartInstance) mixChartInstance.destroy();
                    const ctxMain = document.getElementById('mainChart').getContext('2d');
                    const ctxMix = document.getElementById('mixChart').getContext('2d');
                    createClaudeCharts(ctxMain, ctxMix, data, cColors);
                    currentChartSource = 'claude';
                }
            } else {
                document.getElementById('mainChartTitle').textContent = 'Günlük Aktivite (Oturumlar & Araçlar)';
                document.getElementById('mixChartTitle').textContent = 'Model Dağılımı';

                if (currentChartSource === 'agy' && mainChartInstance && mixChartInstance) {
                    mainChartInstance.data.labels = data.labels;
                    mainChartInstance.data.datasets[0].data = data.sessions;
                    mainChartInstance.data.datasets[1].data = data.tool_calls;
                    mainChartInstance.update('none');
                    mixChartInstance.data.labels = data.labels;
                    mixChartInstance.data.datasets = buildMixDatasets(data.model_mix);
                    mixChartInstance.update('none');
                } else {
                    if (mainChartInstance) mainChartInstance.destroy();
                    if (mixChartInstance) mixChartInstance.destroy();
                    const ctxMain = document.getElementById('mainChart').getContext('2d');
                    const ctxMix = document.getElementById('mixChart').getContext('2d');
                    createAgyCharts(ctxMain, ctxMix, data, cColors);
                    currentChartSource = 'agy';
                }
            }
        }

        sourceSelect.addEventListener('change', loadData);
        rangeSelect.addEventListener('change', loadData);

        // ── Quota Panel (3 accounts grid) ──
        const quotaGrid = document.getElementById('quotaGrid');
        const qcCountdowns = {};

        setInterval(() => {
            const now = Date.now() / 1000;
            for (const [id, ct] of Object.entries(qcCountdowns)) {
                const rem = Math.max(0, ct.targetEpoch - now);
                const win = ct.windowSecs || 1;
                const ratio = rem / win;
                
                if (ct.cdEl) {
                    ct.cdEl.textContent = rem > 0 ? fmtReset(Math.round(rem)) : '✓ Sıfırlandı';
                }
                
                if (ct.upperRect) {
                    const y = 5 + 35 * (1 - ratio);
                    const h = 35 * ratio;
                    ct.upperRect.setAttribute('y', y);
                    ct.upperRect.setAttribute('height', h);
                }
                if (ct.lowerRect) {
                    const y = 75 - 35 * (1 - ratio);
                    const h = 35 * (1 - ratio);
                    ct.lowerRect.setAttribute('y', y);
                    ct.lowerRect.setAttribute('height', h);
                }
            }
        }, 1000);

        function loadQuota() {
            Promise.all([
                fetch('/api/quota').then(r => r.json()),
                fetch('/api/active-account').then(r => r.json()).catch(() => ({email: null})),
                fetch('/api/statusline').then(r => r.json()).catch(() => ({email: null}))
            ]).then(([data, activeData, slData]) => {
                const activeEmail = activeData.email || slData.email || null;
                const activeWorking = !!(
                    slData.available
                    && slData.email
                    && slData.email === activeEmail
                    && !['idle', ''].includes(String(slData.agent_state || '').toLowerCase())
                    && Number(slData.age_seconds || 0) <= 300
                );
                quotaGrid.innerHTML = '';
                
                for (const k of Object.keys(qcCountdowns)) {
                    delete qcCountdowns[k];
                }

                if (!data.accounts || data.accounts.length === 0) {
                    quotaGrid.innerHTML = '<div class="cq-unavail">Hesap verisi yok.</div>';
                    return;
                }

                const windowSecs = data.quota_window_seconds || 14400;
                const nowEpoch = Date.now() / 1000;

                const sorted = [...data.accounts].sort((a, b) => 
                    a.email === activeEmail ? -1 : b.email === activeEmail ? 1 : 0
                );

                sorted.forEach((acct, i) => {
                    const exhausted = acct.status === 'exhausted';
                    const isActive = acct.email === activeEmail;
                    const isWorking = isActive && activeWorking && !exhausted;
                    const handle = acct.email.split('@')[0];
                    const domain = '@' + (acct.email.split('@')[1] || '');
                    const qid = `qc${i}`;
                    
                    let statusHtml = '';
                    
                    if (exhausted && acct.resets_in_seconds > 0) {
                        const total = acct.resets_in_seconds + (acct.elapsed_seconds || 0);
                        const ratio = Math.max(0, Math.min(1, acct.resets_in_seconds / total));
                        
                        statusHtml = `
                            <div class="exhausted-container">
                                <div class="hourglass-wrapper">
                                    <svg class="hourglass-svg" viewBox="0 0 60 80" width="40" height="53">
                                        <defs>
                                            <clipPath id="upper-clip-${qid}">
                                                <rect id="upper-rect-${qid}" x="0" y="${5 + 35 * (1 - ratio)}" width="60" height="${35 * ratio}" />
                                            </clipPath>
                                            <clipPath id="lower-clip-${qid}">
                                                <rect id="lower-rect-${qid}" x="0" y="${75 - 35 * (1 - ratio)}" width="60" height="${35 * (1 - ratio)}" />
                                            </clipPath>
                                        </defs>
                                        <!-- Frame -->
                                        <path d="M 10,5 L 50,5 L 30,40 Z" fill="none" stroke="var(--border)" stroke-width="3.5" stroke-linejoin="round" />
                                        <path d="M 10,75 L 50,75 L 30,40 Z" fill="none" stroke="var(--border)" stroke-width="3.5" stroke-linejoin="round" />
                                        <!-- Upper sand -->
                                        <polygon points="10,5 50,5 30,40" fill="var(--warning)" clip-path="url(#upper-clip-${qid})" />
                                        <!-- Lower sand -->
                                        <polygon points="10,75 50,75 30,40" fill="var(--warning)" clip-path="url(#lower-clip-${qid})" />
                                        <!-- Stream -->
                                        <line x1="30" y1="40" x2="30" y2="75" stroke="var(--warning)" stroke-width="2" stroke-dasharray="4,4" class="dripping-sand" />
                                    </svg>
                                </div>
                                <div class="countdown-container">
                                    <div class="countdown-value" id="${qid}-cd">${fmtReset(acct.resets_in_seconds)}</div>
                                    <div class="reset-time-lbl">Sıfırlanma: ${acct.resets_at || '—'}</div>
                                </div>
                            </div>
                        `;
                        
                        setTimeout(() => {
                            qcCountdowns[qid] = {
                                cdEl: document.getElementById(`${qid}-cd`),
                                upperRect: document.getElementById(`upper-rect-${qid}`),
                                lowerRect: document.getElementById(`lower-rect-${qid}`),
                                targetEpoch: nowEpoch + acct.resets_in_seconds,
                                windowSecs: total
                            };
                        }, 0);
                    } else if (isWorking) {
                        statusHtml = `
                            <div class="available-container working-container">
                                ${gearStatusHTML('active', 'Çalışıyor')}
                                <div class="working-model">${slData.model || 'agy aktif'}</div>
                                ${acct.last_exhausted_at ? `<div class="last-violation">Son ihlal: ${acct.last_exhausted_at}</div>` : ''}
                            </div>
                        `;
                    } else {
                        statusHtml = `
                            <div class="available-container">
                                <svg class="checkmark-svg" viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="var(--success)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                                    <polyline points="22 4 12 14.01 9 11.01" />
                                </svg>
                                <span class="available-text">Müsait</span>
                                ${acct.last_exhausted_at ? `<div class="last-violation">Son ihlal: ${acct.last_exhausted_at}</div>` : ''}
                            </div>
                        `;
                    }

                    const isPro = !!acct.is_pro;
                    const card = document.createElement('div');
                    card.className = `qcard ${isActive ? 'qcard-active' : ''} ${exhausted ? 'qcard-exhausted' : 'qcard-ok'} ${!isPro ? 'qcard-free' : ''}`;

                    // Avatar: Google profile picture or gradient fallback
                    const avatarHtml = acct.picture
                        ? `<img class="qcard-avatar" src="${acct.picture}" alt="${handle}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
                          + `<div class="qcard-avatar-fallback" style="display:none">${handle[0].toUpperCase()}</div>`
                        : `<div class="qcard-avatar-fallback">${handle[0].toUpperCase()}</div>`;

                    card.innerHTML = `
                        <div class="qcard-header">
                            <div class="qcard-badges-top">
                                ${isActive ? '<span class="qcard-active-badge">● AKTİF</span>' : ''}
                                ${isPro ? '<span class="qcard-pro-badge">PRO</span>' : ''}
                                <span class="qbadge ${exhausted ? 'qbadge-exhausted' : 'qbadge-available'}">${exhausted ? 'TÜKENDİ' : 'MÜSAİT'}</span>
                            </div>
                            <div class="qcard-identity">
                                ${avatarHtml}
                                <div class="qcard-identity-text">
                                    <span class="qcard-handle">${acct.name || handle}</span>
                                    <span class="qcard-domain">${acct.email}</span>
                                </div>
                            </div>
                        </div>
                        
                        <div class="qcard-body">
                            ${statusHtml}
                        </div>

                        <!-- Model Quota Area -->
                        <div class="mq-card-section" style="${isActive ? '' : 'display: none;'}">
                            <div class="mq-card-section-header">
                                <span class="mq-card-section-title">Model Kotası <span class="mq-via">via agy /usage</span></span>
                                ${isActive ? `<button class="mq-card-section-refresh" onclick="event.stopPropagation(); loadModelQuota(true);">Yenile</button>` : ''}
                            </div>
                            <div class="mq-card-section-body" id="${isActive ? 'activeModelQuotaBody' : ''}">
                                ${isActive ? `<div class="loading-text">Yükleniyor…</div>` : `<div class="not-active-text">Aktif hesap değil</div>`}
                            </div>
                        </div>

                        <!-- agy Canlı Durum (yalnızca aktif kart) -->
                        ${isActive ? `
                        <div class="mq-card-section">
                            <div class="mq-card-section-header">
                                <span class="mq-card-section-title">Canlı Durum</span>
                                <span id="slAge" style="font-size: 0.72rem; color: var(--muted); font-weight: 500;"></span>
                            </div>
                            <div class="mq-card-section-body" id="statuslineBody">
                                <div class="loading-text">Yükleniyor…</div>
                            </div>
                        </div>
                        ` : ''}

                        <div class="qcard-footer">
                            <span>${acct.session_count} oturum</span>
                            <span>${acct.exhaustion_count} kota ihlali</span>
                        </div>
                    `;
                    quotaGrid.appendChild(card);
                });

                if (activeEmail) {
                    loadModelQuota();
                }
                loadStatusline();

                if (data.warning) {
                    showWarning(data.warning);
                }
            }).catch(() => {
                quotaGrid.innerHTML = '<div class="cq-unavail">Kota verisi yüklenemedi.</div>';
            });
        }

        // ── Claude Quota Panel ──
        const claudeQuotaBody = document.getElementById('claudeQuotaBody');
        const clCountdowns = {};

        setInterval(() => {
            const now = Date.now() / 1000;
            for (const [id, ct] of Object.entries(clCountdowns)) {
                const rem = Math.max(0, Math.round(ct.targetEpoch - now));
                if (ct.el) ct.el.textContent = rem > 0 ? (ct.fmt || fmtReset)(rem) : 'şimdi';
            }
        }, 1000);

        function loadClaudeQuota() {
            claudeQuotaBody.innerHTML = '<div class="loading-text">Yükleniyor…</div>';
            fetch('/api/claude-quota').then(r => r.json()).then(data => {
                for (const k of Object.keys(clCountdowns)) {
                    delete clCountdowns[k];
                }
                
                if (data.warning || !data.quotas || data.quotas.length === 0) {
                    claudeQuotaBody.innerHTML = `<div class="cq-unavail">${data.warning || 'Claude kota verisi bulunamadı.'}</div>`;
                    return;
                }

                const nowEpoch = Date.now() / 1000;
                let html = '';
                
                data.quotas.forEach((q, i) => {
                    const pct = q.pct_remaining;
                    const usage = 100 - pct;
                    const col = usage < 40 ? 'var(--success)' : (usage <= 75 ? 'var(--warning)' : 'var(--danger)');
                    const cdId = `clcd${i}`;
                    let resetHtml = '';
                    
                    if (q.resets_in_seconds > 0) {
                        const targetEpoch = nowEpoch + q.resets_in_seconds;
                        resetHtml = `<span id="${cdId}" class="cq-reset-time"><b>${fmtReset(q.resets_in_seconds)}</b></span>`;
                        setTimeout(() => {
                            const el = document.getElementById(cdId);
                            if (el) clCountdowns[cdId] = {
                                el: el.querySelector('b'),
                                targetEpoch,
                                fmt: fmtReset
                            };
                        }, 0);
                    } else {
                        resetHtml = `<span class="cq-reset-time">—</span>`;
                    }
                    
                    html += `
                        <div class="cq-row">
                            <span class="cq-tier-name">${q.label}</span>
                            <div class="cq-bar-container">
                                <div id="cq-bar-fill-${i}" class="cq-bar-fill" style="width: 0%; background: ${col};"></div>
                            </div>
                            <span class="cq-pct-remaining" style="color: ${col};">${pct}%</span>
                            ${resetHtml}
                        </div>
                    `;
                    
                    setTimeout(() => {
                        const fillEl = document.getElementById(`cq-bar-fill-${i}`);
                        if (fillEl) fillEl.style.width = `${pct}%`;
                    }, 50);
                });
                claudeQuotaBody.innerHTML = html;
            }).catch(e => {
                claudeQuotaBody.innerHTML = `<div class="cq-unavail">Yüklenemedi: ${e}</div>`;
            });
        }

        // ── Codex Kullanımı Paneli ──
        const codexUsageBody = document.getElementById('codexUsageBody');

        function fmtNum(n) {
            const v = Number(n || 0);
            if (v >= 1_000_000) return (v / 1_000_000).toFixed(1).replace('.0', '') + 'M';
            if (v >= 1_000) return Math.round(v / 1_000) + 'k';
            return String(v);
        }

        function escapeHtml(s) {
            return String(s || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function loadCodexUsage() {
            if (!codexUsageBody) return;
            codexUsageBody.innerHTML = '<div class="loading-text">Yükleniyor…</div>';
            fetch('/api/codex-usage').then(r => r.json()).then(data => {
                if (!data.available) {
                    codexUsageBody.innerHTML = `<div class="cq-unavail">${data.warning || 'Codex kullanım verisi bulunamadı.'}</div>`;
                    return;
                }

                const s = data.summary || {};
                const p = data.current_project || {};
                const models = (s.models || []).slice(0, 3).map(escapeHtml).join(', ') || '—';
                const prompts = (data.recent_prompts || []).slice(0, 3);
                const promptHtml = prompts.length
                    ? prompts.map(item => `
                        <div class="codex-prompt-row">
                            <span class="codex-prompt-time">${escapeHtml(item.display_time)}</span>
                            <span class="codex-prompt-text">${escapeHtml(item.text)}</span>
                        </div>
                    `).join('')
                    : '<div class="cq-unavail codex-empty">Son prompt yok.</div>';

                codexUsageBody.innerHTML = `
                    <div class="codex-stat-grid">
                        <div class="cc-stat-chip"><span class="cc-stat-val">${fmtNum(s.sessions)}</span><span class="cc-stat-lbl">oturum</span></div>
                        <div class="cc-stat-chip"><span class="cc-stat-val">${fmtNum(s.prompts)}</span><span class="cc-stat-lbl">prompt</span></div>
                        <div class="cc-stat-chip"><span class="cc-stat-val">${fmtNum(s.tokens_used)}</span><span class="cc-stat-lbl">token</span></div>
                        <div class="cc-stat-chip"><span class="cc-stat-val">${fmtNum(p.sessions)}</span><span class="cc-stat-lbl">${escapeHtml(p.name || 'proje')}</span></div>
                    </div>
                    <div class="codex-meta-row">
                        <span>Model: <b>${models}</b></span>
                        <span>Son aktivite: <b>${escapeHtml(s.last_activity || '—')}</b></span>
                        <span>Bu proje token: <b>${fmtNum(p.tokens_used)}</b></span>
                    </div>
                    <div class="codex-recent-list">${promptHtml}</div>
                    ${data.warning ? `<div class="codex-warning">${escapeHtml(data.warning)}</div>` : ''}
                `;
            }).catch(e => {
                codexUsageBody.innerHTML = `<div class="cq-unavail">Yüklenemedi: ${escapeHtml(e)}</div>`;
            });
        }

        // ── Codex Hesap Durumu Kartı ──
        const codexAccountBody = document.getElementById('codexAccountBody');

        function loadCodexStatus() {
            if (!codexAccountBody) return;
            codexAccountBody.innerHTML = '<div class="loading-text">Yükleniyor…</div>';
            fetch('/api/codex-status').then(r => r.json()).then(data => {
                if (!data.available) {
                    codexAccountBody.innerHTML = `<div class="cq-unavail">${data.warning || 'Codex hesap verisi bulunamadı.'}</div>`;
                    return;
                }
                const acct = data.account || {};
                const model = data.current_model || '—';
                const threads = data.thread_count || 0;
                const tokens = fmtNum(data.total_tokens_used || 0);
                const email = acct.email || '—';
                const plan = acct.plan_type || '—';
                const sub = acct.subscription_active_until ? fmtTime(acct.subscription_active_until) : '—';
                codexAccountBody.innerHTML = `
                    <table class="sl-table">
                        <tr><td class="sl-key">E-posta</td><td class="sl-val">${escapeHtml(email)}</td></tr>
                        <tr><td class="sl-key">Plan</td><td class="sl-val">${escapeHtml(plan)}</td></tr>
                        <tr><td class="sl-key">Abonelik</td><td class="sl-val">${escapeHtml(sub)}</td></tr>
                        <tr><td class="sl-key">Model</td><td class="sl-val">${escapeHtml(model)}</td></tr>
                        <tr><td class="sl-key">Thread</td><td class="sl-val">${threads}</td></tr>
                        <tr><td class="sl-key">Token</td><td class="sl-val">${tokens}</td></tr>
                    </table>
                    ${data.warning ? `<div class="codex-warning">${escapeHtml(data.warning)}</div>` : ''}
                `;
            }).catch(e => {
                codexAccountBody.innerHTML = `<div class="cq-unavail">Yüklenemedi: ${escapeHtml(e)}</div>`;
            });
        }

        // ── agy Canlı Durum (aktif hesap kartına enjekte edilir) ──
        function loadStatusline() {
            const statuslineBody = document.getElementById('statuslineBody');
            const slAge = document.getElementById('slAge');
            if (!statuslineBody) return;
            fetch('/api/statusline').then(r => r.json()).then(d => {
                if (!d.available) {
                    statuslineBody.innerHTML = `<div class="sl-unavail">${d.warning}</div>`;
                    if (slAge) slAge.textContent = '';
                    return;
                }
                const age = d.age_seconds;
                const stale = age > 300;
                if (slAge) slAge.textContent = `(${age < 60 ? age+'sn' : Math.round(age/60)+'dk'} önce)`;
                
                const ctxPct = Math.round(d.context_pct || 0);
                const ctxColor = ctxPct >= 90 ? 'var(--danger)' : ctxPct >= 60 ? 'var(--warning)' : 'var(--success)';
                const inTok = d.context_input_tokens >= 1000 ? Math.round(d.context_input_tokens/1000)+'k' : d.context_input_tokens;
                const outTok = d.context_output_tokens >= 1000 ? Math.round(d.context_output_tokens/1000)+'k' : d.context_output_tokens;
                
                const statusClass = stale ? 'stale' : d.agent_state === 'idle' ? 'idle' : 'active';
                const statusLabel = stale ? 'Eski veri' : d.agent_state === 'idle' ? 'Boşta' : 'Çalışıyor';

                statuslineBody.innerHTML = `
                    <table class="sl-table">
                        <tr>
                            <td class="sl-key">Durum</td>
                            <td class="sl-val">${gearStatusHTML(statusClass, statusLabel)}</td>
                        </tr>
                        <tr>
                            <td class="sl-key">Bağlam Kullanımı</td>
                            <td class="sl-val">
                                <div class="ctx-usage-container">
                                    <span class="ctx-pct-text" style="color: ${ctxColor};">${ctxPct}%</span>
                                    <div class="ctx-bar-container">
                                        <div class="ctx-bar-fill" style="width: ${ctxPct}%; background: ${ctxColor};"></div>
                                    </div>
                                </div>
                            </td>
                        </tr>
                        <tr>
                            <td class="sl-key">Giriş Tokenleri</td>
                            <td class="sl-val">${inTok}</td>
                        </tr>
                        <tr>
                            <td class="sl-key">Çıkış Tokenleri</td>
                            <td class="sl-val">${outTok}</td>
                        </tr>
                        <tr>
                            <td class="sl-key">Model</td>
                            <td class="sl-val ${stale ? 'stale' : ''}">${d.model || '—'}</td>
                        </tr>
                        <tr>
                            <td class="sl-key">Plan</td>
                            <td class="sl-val">${d.plan_tier || '—'}</td>
                        </tr>
                        <tr>
                            <td class="sl-key">Hesap</td>
                            <td class="sl-val">${d.email ? d.email.split('@')[0] : '—'}</td>
                        </tr>
                        <tr>
                            <td class="sl-key">VCS Dal</td>
                            <td class="sl-val">${d.vcs_branch ? `${d.vcs_branch}${d.vcs_dirty ? ' *' : ''}` : '—'}</td>
                        </tr>
                        <tr>
                            <td class="sl-key">Sandbox</td>
                            <td class="sl-val">${d.sandbox ? 'Açık' : 'Kapalı'}</td>
                        </tr>
                        <tr>
                            <td class="sl-key">Artifacts</td>
                            <td class="sl-val">${d.artifacts ?? 0}</td>
                        </tr>
                        <tr>
                            <td class="sl-key">Alt Agent</td>
                            <td class="sl-val">${d.subagents ?? 0}</td>
                        </tr>
                        <tr>
                            <td class="sl-key">Arka Plan Görev</td>
                            <td class="sl-val">${d.bg_tasks ?? 0}</td>
                        </tr>
                    </table>
                    <div class="sl-captured-at">Son güncelleme: ${d.captured_at}</div>
                `;
            }).catch(() => {
                statuslineBody.innerHTML = '<div class="sl-unavail">Durum verisi yüklenemedi.</div>';
            });
        }

        // ── Son agy Oturumu Panel ──
        const lastSessionBody = document.getElementById('lastSessionBody');

        function fmtSec(sec) {
            if (!sec || sec <= 0) return '0s';
            const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
            if (h > 0) return `${h}h ${m}m`;
            if (m > 0) return `${m}m ${s}s`;
            return `${s}s`;
        }

        function fmtReset(sec) {
            if (!sec || sec <= 0) return '—';
            const days = Math.floor(sec / 86400);
            const hours = Math.floor((sec % 86400) / 3600);
            const mins = Math.floor((sec % 3600) / 60);
            if (days > 0)  return `${days}g ${hours}sa ${mins}dk`;
            if (hours > 0) return `${hours}sa ${mins}dk`;
            return `${mins}dk`;
        }

        function fmtDur(sec) {
            if (!sec) return '—';
            const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
            if (h > 0) return `${h}sa ${m}dk`;
            if (m > 0) return `${m}dk ${s}s`;
            return `${s}s`;
        }

        function fmtTime(iso) {
            if (!iso) return '—';
            const m = iso.match(/T(\d{2}:\d{2})/);
            const d = iso.match(/(\d{4}-\d{2}-\d{2})/);
            return m ? (d ? d[1].slice(5)+' '+m[1] : m[1]) : iso;
        }

        function loadLastSession() {
            fetch('/api/last-session').then(r => r.json()).then(d => {
                if (!d.available) {
                    lastSessionBody.innerHTML = `<div class="sl-unavail">${d.warning}</div>`;
                    return;
                }

                const modelShort = (d.model || '').replace('Gemini ', '').trim() || '—';
                const typeEntries = Object.entries(d.record_types || {}).sort((a, b) => b[1] - a[1]);
                const maxCount = typeEntries.length ? typeEntries[0][1] : 1;
                const typeColors = [
                    '#38bdf8', '#818cf8', '#34d399', '#fb923c',
                    '#f87171', '#a78bfa', '#fbbf24', '#6ee7b7'
                ];

                const barRows = typeEntries.map(([t, c], i) => `
                    <div class="ls-bar-row">
                        <span class="ls-bar-label" title="${t}">${t}</span>
                        <div class="ls-bar-track">
                            <div class="ls-bar-fill" style="width: ${Math.round(c/maxCount*100)}%; background: ${typeColors[i%typeColors.length]};"></div>
                        </div>
                        <span class="ls-bar-count">${c}</span>
                    </div>
                `).join('');

                lastSessionBody.innerHTML = `
                    <div class="ls-stats">
                        <div class="ls-stat-card">
                            <div class="ls-stat-val">${d.tool_call_count}</div>
                            <div class="ls-stat-lbl">Araç Çağrısı</div>
                        </div>
                        <div class="ls-stat-card">
                            <div class="ls-stat-val">${d.record_count}</div>
                            <div class="ls-stat-lbl">Kayıt</div>
                        </div>
                        <div class="ls-stat-card">
                            <div class="ls-stat-val">${fmtDur(d.duration_seconds)}</div>
                            <div class="ls-stat-lbl">Süre</div>
                        </div>
                    </div>
                    
                    <div class="ls-meta-section">
                        ${d.model ? `<div class="ls-model-badge" title="${d.model}">${modelShort}</div>` : ''}
                        <div class="ls-meta-details">
                            <div class="ls-meta-row"><span>Başlangıç:</span> <b>${fmtTime(d.started_at)}</b></div>
                            <div class="ls-meta-row"><span>Bitiş:</span> <b>${fmtTime(d.ended_at)}</b></div>
                            <div class="ls-meta-row"><span>ID:</span> <code class="ls-id-code">${d.session_id.slice(0, 8)}…</code></div>
                        </div>
                    </div>

                    <div class="ls-chart-section">
                        <div class="ls-chart-title">Kayıt Türü Dağılımı</div>
                        <div class="ls-chart-body">
                            ${barRows || '<div class="not-active-text">Kayıt türü verisi yok.</div>'}
                        </div>
                    </div>
                    ${d.warning ? `<div class="warning-text-small">⚠ ${d.warning}</div>` : ''}
                `;
            }).catch(() => {
                lastSessionBody.innerHTML = '<div class="sl-unavail">Son oturum yüklenemedi.</div>';
            });
        }

        // ── Refresh all agy accounts ──
        const refreshAllStatus = document.getElementById('refreshAllStatus');
        
        function refreshAllAccounts() {
            const btn = document.getElementById('refreshAllBtn');
            btn.disabled = true;
            btn.textContent = '⟳ Çalışıyor…';
            refreshAllStatus.style.display = 'block';
            refreshAllStatus.textContent = 'Hesaplar sırayla çalıştırılıyor, lütfen bekleyin…';
            
            fetch('/api/agy-refresh-accounts').then(r => r.json()).then(data => {
                btn.disabled = false;
                btn.textContent = '⟳ Tüm Hesapları Çalıştır';
                if (data.warning) {
                    refreshAllStatus.textContent = '⚠ ' + data.warning;
                    return;
                }
                const lines = (data.results || []).map(r => 
                    `${r.ok ? '✓' : '✗'} ${r.email}${r.error ? ' — '+r.error : ''}`
                );
                refreshAllStatus.textContent = lines.join('  |  ') || 'Tamamlandı.';
                loadQuota();
                loadStatusline();
                loadLastSession();
            }).catch(e => {
                btn.disabled = false;
                btn.textContent = '⟳ Tüm Hesapları Çalıştır';
                refreshAllStatus.textContent = 'Hata: ' + e;
            });
        }

        // ── agy Model Quota Panel (inject into active account card) ──
        function shortenModelName(name) {
            if (!name) return '—';
            const lower = name.toLowerCase();
            if (lower.includes('flash') && (lower.includes('medium') || lower.includes('med'))) return 'Flash Med';
            if (lower.includes('flash') && lower.includes('high')) return 'Flash High';
            if (lower.includes('pro') && (lower.includes('low') || lower.includes('lo'))) return 'Pro Low';
            if (lower.includes('pro') && (lower.includes('medium') || lower.includes('med'))) return 'Pro Med';
            if (lower.includes('pro') && lower.includes('high')) return 'Pro High';
            if (lower.includes('lite') && (lower.includes('medium') || lower.includes('med'))) return 'Lite Med';
            if (lower.includes('lite') && lower.includes('high')) return 'Lite High';
            if (lower.includes('lite') && lower.includes('low')) return 'Lite Low';
            
            let short = name.replace(/^Gemini\s+/i, '');
            short = short.replace(/\(Medium\)/i, 'Med');
            short = short.replace(/\(High\)/i, 'High');
            short = short.replace(/\(Low\)/i, 'Low');
            return short;
        }

        function loadModelQuota(force = false) {
            const el = document.getElementById('activeModelQuotaBody');
            if (!el) return;
            el.innerHTML = '<div class="loading-text">agy başlatılıyor, kota ekranı yakalanıyor (~30sn)…</div>';
            
            fetch(`/api/agy-model-quota${force ? '?refresh=1' : ''}`).then(r => r.json()).then(data => {
                if (data.warning && (!data.models || data.models.length === 0)) {
                    el.innerHTML = `<div class="mq-err">⚠ ${data.warning}</div>`;
                    return;
                }
                
                let html = '';
                if (data.plan) {
                    html += `
                        <div class="mq-meta">
                            <span>${data.plan}</span>
                            <span class="mq-captured-time">@ ${data.captured_at || ''}</span>
                        </div>
                    `;
                }

                // Banner: only when any model is exhausted (has refreshes_in)
                const anyExhausted = (data.models || []).some(m => m.refreshes_in);
                if (anyExhausted) {
                    html += `<div class="mq-reset-banner">
                        <span class="mq-reset-icon">⚠</span>
                        <span>Bazı modeller <strong style="color:var(--danger)">kota limitine ulaştı</strong> — sıfırlanma süreleri aşağıda</span>
                    </div>`;
                }

                (data.models || []).forEach(m => {
                    const pct = m.pct_shown ?? m.pct_remaining ?? 100;
                    const col = pct >= 60 ? 'var(--success)' : pct >= 25 ? 'var(--warning)' : 'var(--danger)';
                    const name = shortenModelName(m.display_name);

                    // Reset time: ONLY show when model is actually exhausted.
                    // Google AI Pro models have short windows (38m–4.5h), NOT 24h.
                    // When available, show nothing — we don't have the true next-reset time.
                    let resetHtml;
                    if (m.refreshes_in) {
                        resetHtml = `<span class="mq-reset mq-reset-urgent" title="Sıfırlanıyor">⏱ ${m.refreshes_in}</span>`;
                    } else {
                        resetHtml = `<span class="mq-reset mq-reset-ok">✓</span>`;
                    }

                    html += `
                        <div class="mq-row">
                            <span class="mq-model-name" title="${m.display_name}">${name}</span>
                            <div class="mq-bar-container">
                                <div class="mq-bar-fill" style="width: ${pct}%; background: ${col};"></div>
                            </div>
                            <span class="mq-pct" style="color: ${col};">${pct}%</span>
                            ${resetHtml}
                        </div>
                    `;
                });

                if (data.warning) {
                    html += `<div class="mq-err" style="margin-top:.5rem;">⚠ ${data.warning}</div>`;
                }
                
                el.innerHTML = html || '<div class="not-active-text">Model verisi bulunamadı.</div>';
            }).catch(e => {
                el.innerHTML = `<div class="mq-err">Yüklenemedi: ${e}</div>`;
            });
        }

        function loadActiveAccount() {
            return fetch('/api/active-account').then(r => r.json()).catch(() => ({email: null}));
        }

        let _feedFilter = 'all';
        let _feedData = null;

        function setFeedFilter(filter) {
            _feedFilter = filter;
            document.querySelectorAll('.feed-filter-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.filter === filter);
            });
            if (_feedData) renderActivityFeed(_feedData);
        }

        function renderActivityFeed(data) {
            const el = document.getElementById('activityFeedBody');
            const statsEl = document.getElementById('activityFeedStats');

            const ls = data.latest_stats || {};
            if (ls.available) {
                statsEl.innerHTML = `<div class="cc-stat-chips">
                    <div class="cc-stat-chip"><span class="cc-stat-val">${ls.messages}</span><span class="cc-stat-lbl">mesaj</span></div>
                    <div class="cc-stat-chip"><span class="cc-stat-val">${ls.tool_calls}</span><span class="cc-stat-lbl">araç</span></div>
                    <div class="cc-stat-chip"><span class="cc-stat-val">${ls.sessions}</span><span class="cc-stat-lbl">oturum</span></div>
                </div><div class="cc-date-label">${ls.date}</div>`;
            } else {
                statsEl.innerHTML = '';
            }

            let events = (data.events || []);
            if (_feedFilter !== 'all') {
                events = events.filter(e => e.kind === _feedFilter);
            }

            if (events.length === 0) {
                el.innerHTML = `<div class="sl-unavail">${data.warning || 'Henüz aktivite yok.'}</div>`;
                return;
            }

            const rows = events.map(e => {
                const ago = timeAgo(e.ts_epoch * 1000);
                if (e.kind === 'agy') {
                    const statusOk = e.status === 'success' || e.status === 'quota-rotate';
                    const statusClass = statusOk ? 'ops-ok' : 'ops-err';
                    const statusLabel = {
                        'success': 'OK', 'quota-rotate': 'ROTA',
                        'exhausted': 'TÜKENDI', 'verify-failed': 'HATA', 'all-exhausted': 'TAM TÜKENDI'
                    }[e.status] || e.status;
                    const cmd = (e.cmd || '').slice(0, 24);
                    const model = shortenModelName(e.model || '');
                    const acct = (e.account || '').split('@')[0].slice(0, 10);
                    const promptFull = (e.prompt || '').replace(/"/g, '&quot;');
                    const promptShort = (e.prompt || '').slice(0, 50);
                    return `<div class="feed-row feed-agy" onclick="this.querySelector('.feed-prompt-full').classList.toggle('hidden')">
                        <span class="feed-kind-badge agy">agy</span>
                        <span class="feed-ago">${ago}</span>
                        <span class="feed-cmd" title="${promptFull}">${cmd}</span>
                        <span class="feed-status ${statusClass}">${statusLabel}</span>
                        ${model ? `<span class="feed-model">${model}</span>` : ''}
                        ${acct ? `<span class="feed-acct">${acct}</span>` : ''}
                        <div class="feed-prompt-full hidden">${promptFull || '—'}</div>
                    </div>`;
                } else {
                    const proj = e.project || '';
                    const displayFull = (e.display || '').replace(/"/g, '&quot;');
                    const displayShort = (e.display || '').slice(0, 55);
                    return `<div class="feed-row feed-cc" onclick="this.querySelector('.feed-prompt-full').classList.toggle('hidden')">
                        <span class="feed-kind-badge cc">CC</span>
                        <span class="feed-ago">${ago}</span>
                        ${proj ? `<span class="feed-project">${proj}</span>` : ''}
                        <span class="feed-prompt-short" title="${displayFull}">${displayShort}</span>
                        <div class="feed-prompt-full hidden">${displayFull || '—'}</div>
                    </div>`;
                }
            }).join('');

            let html = `<div class="feed-list">${rows}</div>`;
            if (data.warning) {
                html += `<div class="warning-text-small">⚠ ${data.warning}</div>`;
            }
            el.innerHTML = html;
        }

        function loadActivityFeed() {
            const el = document.getElementById('activityFeedBody');
            el.innerHTML = '<div class="sl-unavail">Yükleniyor…</div>';
            fetch('/api/activity-feed').then(r => r.json()).then(data => {
                _feedData = data;
                renderActivityFeed(data);
            }).catch(() => {
                el.innerHTML = '<div class="sl-unavail">Aktivite akışı yüklenemedi.</div>';
            });
        }

        function fmtTokens(n) {
            if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
            if (n >= 1_000) return Math.round(n / 1_000) + 'K';
            return String(n);
        }

        function timeAgo(tsMs) {
            const diffS = Math.floor((Date.now() - tsMs) / 1000);
            if (diffS < 60) return 'az önce';
            if (diffS < 3600) return Math.floor(diffS / 60) + 'dk';
            if (diffS < 86400) return Math.floor(diffS / 3600) + 'sa';
            return new Date(tsMs).toLocaleDateString('tr-TR', {day:'2-digit', month:'2-digit'});
        }

        function loadRtkStats() {
            const el = document.getElementById('rtkStatsBody');
            fetch('/api/rtk-stats').then(r => r.json()).then(data => {
                if (data.warning && !data.tokens_saved) {
                    el.innerHTML = `<div class="sl-unavail">⚠ ${data.warning}</div>`;
                    return;
                }
                const top3 = (data.top_commands || []).slice(0, 3).map(c =>
                    `<div class="rtk-cmd-row">
                        <span class="rtk-cmd-name" title="${c.cmd}">${c.cmd.slice(0, 20)}</span>
                        <span class="rtk-cmd-count">${c.count}</span>
                        <span class="rtk-cmd-pct">${c.avg_pct.toFixed(0)}%</span>
                    </div>`
                ).join('');
                const effW = Math.min(100, data.efficiency_pct || 0);
                el.innerHTML = `
                    <div class="rtk-big-number">${fmtTokens(data.tokens_saved || 0)}</div>
                    <div class="rtk-sub">token tasarruf · ${data.total_commands || 0} komut</div>
                    <div class="eff-bar-track"><div class="eff-bar" style="width:${effW}%"></div></div>
                    <div class="rtk-eff-label">%${(data.efficiency_pct || 0).toFixed(1)} verimlilik</div>
                    <div class="rtk-cmd-table">${top3}</div>
                `;
            }).catch(() => {
                el.innerHTML = '<div class="sl-unavail">RTK verisi alınamadı.</div>';
            });
        }

        // ── Active Job Card ──
        function loadActiveJob() {
            const el = document.getElementById('activeJobBody');
            if (!el) return;
            fetch('/api/active-job').then(r => r.json()).then(data => {
                if (!data.active) {
                    el.innerHTML = '<div class="sl-unavail">Aktif job yok.</div>';
                    return;
                }
                const s = data.active.snapshot;
                const status = s.status || '';
                const stage = s.stage || '';
                const account = s.account || '—';
                const model = s.model || '—';
                const prompt = (s.prompt || '').slice(0, 60);
                const error = s.last_error || '';
                const errorDetail = s.error_detail || '';
                const errorCategory = s.error_category || '';
                const duration = s.duration_seconds;
                const badgeClass = 'aj-badge-' + status;
                const badgeLabel = status.replace(/_/g, ' ');

                let eventsHtml = '';
                (data.active.events || []).slice(-5).forEach(e => {
                    const ts = (e.ts || '').slice(-8);
                    const ev = e.event || '';
                    const msg = e.message || '';
                    eventsHtml += `<div class="aj-event-row">
                        <span class="aj-event-ts">${ts}</span>
                        <span class="aj-event-type">${ev}</span>
                        <span class="aj-event-msg">${escapeHtml(msg)}</span>
                    </div>`;
                });

                const durHtml = duration != null ? fmtDur(Math.round(duration)) : '—';
                const catHtml = errorCategory ? `<span class="aj-error-cat aj-cat-${errorCategory}">${errorCategory}</span>` : '';
                const detailHtml = errorDetail
                    ? `<tr><td class="aj-key">Error Detail</td>
                       <td class="aj-val"><span class="aj-error-detail-toggle" onclick="this.nextElementSibling.classList.toggle('hidden');this.textContent=this.nextElementSibling.classList.contains('hidden')?'Göster':'Gizle'">Göster</span>
                       <pre class="aj-error-detail-full hidden">${escapeHtml(errorDetail)}</pre></td></tr>`
                    : '';

                el.innerHTML = `
                    <table class="aj-table">
                        <tr><td class="aj-key">Status</td><td class="aj-val"><span class="aj-badge ${badgeClass}">${badgeLabel}</span></td></tr>
                        <tr><td class="aj-key">Stage</td><td class="aj-val">${escapeHtml(stage)}</td></tr>
                        <tr><td class="aj-key">Account</td><td class="aj-val">${escapeHtml(account)}</td></tr>
                        <tr><td class="aj-key">Model</td><td class="aj-val">${escapeHtml(model)}</td></tr>
                        <tr><td class="aj-key">Duration</td><td class="aj-val">${durHtml}</td></tr>
                        <tr><td class="aj-key">Prompt</td><td class="aj-val" title="${escapeHtml(s.prompt || '')}">${escapeHtml(prompt)}${(s.prompt || '').length > 60 ? '…' : ''}</td></tr>
                        ${error ? `<tr><td class="aj-key">Error</td><td class="aj-val" style="color:var(--danger)">${escapeHtml(error.slice(0, 100))} ${catHtml}</td></tr>` : ''}
                        ${detailHtml}
                    </table>
                    <div style="margin-top:0.5rem;font-size:0.78rem;color:var(--muted);font-weight:600;">Son Olaylar</div>
                    ${eventsHtml || '<div style="font-size:0.78rem;color:var(--muted)">Olay yok.</div>'}
                `;
            }).catch(() => {
                if (el) el.innerHTML = '<div class="sl-unavail">Aktif job yüklenemedi.</div>';
            });
        }

        // ── Job Analytics Card ──
        function loadJobAnalytics() {
            const el = document.getElementById('jobAnalyticsBody');
            if (!el) return;
            fetch('/api/job-stats').then(r => r.json()).then(d => {
                if (d.total === 0) {
                    el.innerHTML = '<div class="sl-unavail">Henüz job verisi yok.</div>';
                    return;
                }

                const rate = d.success_rate_24h;
                const avgDur = d.avg_duration_seconds != null ? fmtDur(Math.round(d.avg_duration_seconds)) : '—';
                const errCats = Object.entries(d.error_breakdown || {}).sort((a, b) => b[1] - a[1]);
                const maxErr = errCats.length ? errCats[0][1] : 1;

                const rateColor = rate == null ? 'var(--muted)' : rate >= 80 ? 'var(--success)' : rate >= 50 ? 'var(--warning)' : 'var(--danger)';
                const ratePct = rate != null ? rate + '%' : '—';

                const dailyEntries = Object.entries(d.daily_counts || {}).sort();
                const maxDaily = dailyEntries.length ? Math.max(...dailyEntries.map(e => e[1])) : 1;
                const dailyBars = dailyEntries.map(([day, count]) => {
                    const short = day.slice(5);
                    const pct = Math.round(count / maxDaily * 100);
                    return `<div class="ja-daily-row" title="${day}: ${count}">
                        <span class="ja-daily-label">${short}</span>
                        <div class="ja-daily-track"><div class="ja-daily-fill" style="width:${pct}%"></div></div>
                        <span class="ja-daily-count">${count}</span>
                    </div>`;
                }).join('');

                const errRows = errCats.map(([cat, count]) => {
                    const pct = Math.round(count / maxErr * 100);
                    return `<div class="ja-err-row">
                        <span class="aj-error-cat aj-cat-${cat}">${cat}</span>
                        <div class="ja-err-track"><div class="ja-err-fill" style="width:${pct}%"></div></div>
                        <span class="ja-err-count">${count}</span>
                    </div>`;
                }).join('');

                el.innerHTML = `
                    <div class="ja-stats-grid">
                        <div class="ja-stat-card">
                            <div class="ja-stat-val" style="color:${rateColor}">${ratePct}</div>
                            <div class="ja-stat-lbl">24s Başarı</div>
                        </div>
                        <div class="ja-stat-card">
                            <div class="ja-stat-val">${avgDur}</div>
                            <div class="ja-stat-lbl">Ort. Süre</div>
                        </div>
                        <div class="ja-stat-card">
                            <div class="ja-stat-val">${d.total}</div>
                            <div class="ja-stat-lbl">Toplam Job</div>
                        </div>
                        <div class="ja-stat-card">
                            <div class="ja-stat-val">${d.last_24h.total}</div>
                            <div class="ja-stat-lbl">24s Job</div>
                        </div>
                    </div>
                    ${dailyBars ? `<div class="ja-section">
                        <div class="ja-section-title">Günlük Job Sayısı (14g)</div>
                        <div class="ja-daily-list">${dailyBars}</div>
                    </div>` : ''}
                    ${errRows ? `<div class="ja-section">
                        <div class="ja-section-title">Hata Dağılımı</div>
                        <div class="ja-err-list">${errRows}</div>
                    </div>` : ''}
                `;
            }).catch(() => {
                if (el) el.innerHTML = '<div class="sl-unavail">Job analitik yüklenemedi.</div>';
            });
        }

        // Footer timestamp
        // Doldurma loadData() tamamlandığında yapılır.

        function loadQuotaAlerts() {
            fetch('/api/quota-alerts').then(r => r.json()).then(data => {
                const alerts = data.alerts || [];
                if (alerts.length > 0) {
                    warningText.textContent = alerts.map(a => a.message).join(' | ');
                    warningBanner.style.display = 'flex';
                } else {
                    warningBanner.style.display = 'none';
                }
            }).catch(() => {});
        }

        // Initial Load
        loadData();
        loadClaudeQuota();
        loadCodexUsage();
        loadCodexStatus();
        loadQuota();
        loadStatusline();
        loadLastSession();
        loadActivityFeed();
        loadActiveJob();
        loadJobAnalytics();
        loadRtkStats();
        loadQuotaAlerts();
        setInterval(loadRtkStats, 60_000);
        setInterval(loadJobAnalytics, 120_000);

        // SSE connection — typed events for selective refresh
        const HEAVY_REFRESH_INTERVAL_MS = 60_000;
        let lastHeavyRefresh = 0;

        function connectSSE() {
            const es = new EventSource('/events');

            es.addEventListener('meta', function(ev) {
                // connected
            });

            function onEvent(eventType, fn) {
                es.addEventListener(eventType, function(ev) {
                    liveDot.classList.remove('flash');
                    void liveDot.offsetWidth;
                    liveDot.classList.add('flash');
                    fn();
                });
            }

            // Lightweight — refresh on every change
            onEvent('statusline', loadStatusline);

            // Medium weight — refresh on specific source changes
            onEvent('claude', function() {
                loadClaudeQuota();
                loadData();
                loadActivityFeed();
            });
            onEvent('codex', function() {
                loadCodexUsage();
                loadCodexStatus();
            });
            onEvent('quota', function() {
                loadQuota();
                loadStatusline();
            });

            // Catch-all for unknown event types (throttled full refresh)
            es.onmessage = function(ev) {
                if (ev.data === 'refresh') {
                    const now = Date.now();
                    if (now - lastHeavyRefresh >= HEAVY_REFRESH_INTERVAL_MS) {
                        lastHeavyRefresh = now;
                        loadData();
                        loadClaudeQuota();
                        loadCodexUsage();
                        loadCodexStatus();
                        loadQuota();
                        loadLastSession();
                        loadActivityFeed();
                        loadActiveJob();
                        loadJobAnalytics();
                        loadQuotaAlerts();
                    }
                }
            };

            es.onerror = function() {
                es.close();
                setTimeout(connectSSE, 5000);
            };
        }
        connectSSE();
    
