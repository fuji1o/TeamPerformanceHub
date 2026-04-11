/* ═══════════════════════════════════════════
   Team Performance Hub — Frontend
   ═══════════════════════════════════════════ */
const API_BASE = "http://127.0.0.1:8000/api";

let currentProjectId = null; // null = все проекты
let currentViewMode = "developer"; // "developer" или "overview"
let commitsChart = null; // Глобальная переменная для графика
let currentChartRange = 'month'; // Текущий период графика
let lastReportData = null; // Последние данные отчёта

/* ═══════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════ */
function formatDate(iso) {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString("ru-RU", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });
}

function formatHours(h) {
    if (h == null) return "—";
    if (h < 24) {
        return `${Math.round(h)} ч`;
    }
    return `${(h / 24).toFixed(1)} дн`;
}

function stateBadge(state) {
    return `<span class="st-badge st-${state}">${state}</span>`;
}

function escHtml(s) {
    if (!s) return "";
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
}

/* ═══════════════════════════════════════════
   SIGNALS_CONFIG — 4 сигнала
   ═══════════════════════════════════════════ */
const SIGNALS_CONFIG = [
    {
        key: "commits",
        icon: "📦",
        title: "Активность коммитов",
        compute(r, username) {
            const byAuthor = r.commits?.by_author ?? {};
            let authorStats = null;
            
            for (const [name, stats] of Object.entries(byAuthor)) {
                if (name.toLowerCase().includes(username.toLowerCase()) ||
                    username.toLowerCase().includes(name.toLowerCase())) {
                    authorStats = stats;
                    break;
                }
            }
            
            const total = authorStats?.commits ?? 0;
            const days = r.period_days ?? 30;
            
            return { 
                status: "neutral", 
                badge: `${total} <span class="stat-highlight">коммитов</span> за ${days} ${days === 1 ? 'день' : 'дней'}`, 
                hint: `${total} коммитов за ${days} дней` 
            };
        },
    },
    {
        key: "mr",
        icon: "🔀",
        title: "Merge Requests",
        compute(r, username) {
            const mrs = r.merge_requests ?? [];
            const total = mrs.length;
            const merged = mrs.filter(m => m.state === 'merged').length;
            const opened = mrs.filter(m => m.state === 'opened').length;
            const closed = mrs.filter(m => m.state === 'closed').length;
            
            let parts = [];
            if (merged > 0) parts.push(`<span class="stat-highlight stat-merged">${merged}</span> смержено`);
            if (opened > 0) parts.push(`<span class="stat-highlight stat-opened">${opened}</span> открыто`);
            if (closed > 0) parts.push(`<span class="stat-highlight stat-closed">${closed}</span> закрыто`);
            
            const badgeText = parts.length ? parts.join(', ') : `${total} MR`;
            
            return { 
                status: "neutral", 
                badge: badgeText,
                hint: `Всего ${total} merge request'ов: ${merged} смержено, ${opened} открыто, ${closed} закрыто` 
            };
        },
    },
    {
        key: "review",
        icon: "👁",
        title: "Скорость ревью",
        compute(r, username) {
            const mrs = r.merge_requests ?? [];
            const delays = mrs
                .map(m => m.comment_stats?.first_comment_delay_hours)
                .filter(v => v != null);
            
            if (!delays.length) { 
                return { 
                    status: "neutral", 
                    badge: "Нет данных", 
                    hint: "Нет комментариев для расчёта скорости ревью" 
                };
            }
            
            const avg = delays.reduce((a, b) => a + b, 0) / delays.length;
            const avgHours = Math.round(avg);
            const avgText = avgHours < 24 ? `${avgHours} ч` : `${(avgHours / 24).toFixed(1)} дн`;
            
            return { 
                status: "neutral", 
                badge: `<span class="stat-highlight">${avgText}</span>`,
                hint: `Среднее время до первого комментария: ${formatHours(avg)}` 
            };
        },
    },
    {
        key: "desc",
        icon: "📝",
        title: "Описание MR",
        compute(r, username) {
            const mrs = r.merge_requests ?? [];
            
            if (!mrs.length) { 
                return { 
                    status: "neutral", 
                    badge: "—", 
                    hint: "Нет MR для анализа" 
                };
            }
            
            const withDesc = mrs.filter(m => {
                const d = m.quality_score?.details;
                return d && (d.description_length ?? 0) > 20;
            }).length;
            
            const withoutDesc = mrs.length - withDesc;
            
            let parts = [];
            if (withDesc > 0) parts.push(`<span class="stat-highlight stat-good">${withDesc}</span> с описанием`);
            if (withoutDesc > 0) parts.push(`<span class="stat-highlight stat-bad">${withoutDesc}</span> без описания`);
            
            const badgeText = parts.length ? parts.join(', ') : `${withDesc}/${mrs.length}`;
            
            return { 
                status: "neutral", 
                badge: badgeText,
                hint: `${withDesc} MR с описанием, ${withoutDesc} без описания` 
            };
        },
    },
];

/* ═══════════════════════════════════════════
   RENDER FUNCTIONS
   ═══════════════════════════════════════════ */
function renderSignals(report, username) {
    const grid = document.getElementById("signalsGrid");
    const results = [];
    
    grid.innerHTML = SIGNALS_CONFIG.map(cfg => {
        const res = cfg.compute(report, username);
        results.push({ label: cfg.title, ...res });
        return `
        <div class="signal-card">
            <div class="signal-top">
                <span class="signal-title">${cfg.icon} ${cfg.title}</span>
                <span class="signal-badge" data-status="${res.status}">${res.badge}</span>
            </div>
            <p class="signal-hint">${res.hint}</p>
        </div>`;
    }).join('');
    
    return results;
}

function renderMRTable(mrs) {
    const tbody = document.getElementById("mrTableBody");
    
    if (!mrs || !mrs.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty-row">Нет Merge Requests за период</td></td>`;
        return;
    }
    
    tbody.innerHTML = mrs.map(mr => {
        const d = mr.quality_score?.details ?? {};
        const commitsCount = mr.commits_count ?? 0;
        const hasDesc = (d.description_length ?? 0) > 20;
        const descClass = hasDesc ? "yn-yes" : "yn-no";
        const descIcon = hasDesc ? "✅" : "✖️";
        const actualAuthor = mr.actual_author || mr.author || '';
        const mergedBy = mr.merged_by || '';
        const projectInfo = mr.project_name ? ` | 📁 ${escHtml(mr.project_name)}` : '';
        
        return `
        <tr>
            <td>
                <a href="${mr.web_url}" target="_blank" class="mr-link">!${mr.iid}</a>
                <span class="mr-title-sub">${escHtml(mr.title)}</span>
                <span class="mr-title-sub" style="font-size: 0.65rem; color: #888; display: block;">
                    ✍️ ${escHtml(actualAuthor)}
                    ${mergedBy ? ` | Смержил: ${escHtml(mergedBy)}` : ''}
                    ${projectInfo}
                </span>
            </td>
            <td>${stateBadge(mr.state)}</td>
            <td><span class="yn ${descClass}">${descIcon}</span></td>
            <td>${commitsCount}</td>
            <td>${mr.time_to_merge_hours != null ? formatHours(mr.time_to_merge_hours) : "—"}</td>
        </tr>`;
    }).join('');
}

function renderCommentTypes(mrs) {
    const grid = document.getElementById("commentTypes");
    
    const byType = {};
    for (const mr of (mrs || [])) {
        const types = mr.comment_stats?.by_type || {};
        for (const [type, count] of Object.entries(types)) {
            byType[type] = (byType[type] || 0) + count;
        }
    }
    
    const entries = Object.entries(byType).sort(([, a], [, b]) => b - a);
    
    if (!entries.length) {
        grid.innerHTML = '<span class="tag-empty">Нет комментариев</span>';
        return;
    }
    
    grid.innerHTML = entries.map(([type, count]) =>
        `<span class="tag">${type}<span class="tag-count">${count}</span></span>`
    ).join('');
}

function renderPrompt(report) {
    const card = document.getElementById("promptCard");
    const el = document.getElementById("conversationPrompt");
    const icon = document.getElementById("promptIcon");
    
    card.classList.remove("level-good", "level-warn", "level-bad");
    
    // Используем conversation_prompt из API
    if (report && report.conversation_prompt) {
        const text = report.conversation_prompt.toLowerCase();
        
        // Определяем стиль по содержанию
        if (text.includes("соответствует") && !text.includes("не соответствует")) {
            card.classList.add("level-good");
            icon.textContent = "🟢";
        } else if (text.includes("частичное") || text.includes("рекомендуется") || text.includes("улучшить")) {
            card.classList.add("level-warn");
            icon.textContent = "🟡";
        } else if (text.includes("несоблюдение") || text.includes("вмешательство") || text.includes("ни одного")) {
            card.classList.add("level-bad");
            icon.textContent = "🔴";
        } else {
            card.classList.add("level-good");
            icon.textContent = "🟢";
        }
        
        el.textContent = report.conversation_prompt;
    } else {
        // Fallback если нет данных
        card.classList.add("level-good");
        icon.textContent = "💬";
        el.textContent = "Нет данных для анализа";
    }
}

/* ═══════════════════════════════════════════
   ГРАФИК АКТИВНОСТИ
   ═══════════════════════════════════════════ */
function initChart() {
    const ctx = document.getElementById('commitsChart');
    if (!ctx) {
        console.error('Canvas element not found');
        return;
    }
    
    // Уничтожаем старый график если есть
    if (commitsChart) {
        commitsChart.destroy();
    }
    
    commitsChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: 'Коммиты',
                data: [],
                backgroundColor: 'rgba(99, 102, 241, 0.7)',
                borderColor: 'rgba(99, 102, 241, 1)',
                borderWidth: 1,
                borderRadius: 6,
                barPercentage: 0.7,
                categoryPercentage: 0.8
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    backgroundColor: '#1c2233',
                    titleColor: '#e2e6ef',
                    bodyColor: '#7c849b',
                    borderColor: '#252d3f',
                    borderWidth: 1
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(37, 45, 63, 0.5)'
                    },
                    ticks: {
                        color: '#7c849b',
                        stepSize: 1
                    },
                    title: {
                        display: true,
                        text: 'Количество коммитов',
                        color: '#7c849b'
                    }
                },
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        color: '#7c849b',
                        maxRotation: 45,
                        minRotation: 45
                    }
                }
            }
        }
    });
    
    console.log('Chart initialized:', commitsChart);
}

function updateChart(commitsByDate, range) {
    console.log('updateChart called with:', { commitsByDate, range });
    
    if (!commitsChart) {
        console.log('Chart not initialized, initializing now...');
        initChart();
    }
    
    if (!commitsChart) {
        console.error('Failed to initialize chart');
        return;
    }
    
    if (!commitsByDate || Object.keys(commitsByDate).length === 0) {
        console.log('No commits data available');
        commitsChart.data.labels = [];
        commitsChart.data.datasets[0].data = [];
        commitsChart.update();
        return;
    }
    
    // Преобразуем данные в массив
    let dates = Object.keys(commitsByDate).sort();
    let counts = dates.map(date => commitsByDate[date]);
    
    console.log('All dates:', dates);
    console.log('All counts:', counts);
    
    // Фильтруем по выбранному диапазону
    let daysToShow = 30;
    if (range === 'week') daysToShow = 7;
    else if (range === 'month') daysToShow = 30;
    else if (range === 'quarter') daysToShow = 90;
    
    // Берём последние N дней
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - daysToShow);
    
    let filteredDates = [];
    let filteredCounts = [];
    
    for (let i = 0; i < dates.length; i++) {
        const date = new Date(dates[i]);
        if (date >= cutoffDate) {
            filteredDates.push(dates[i]);
            filteredCounts.push(counts[i]);
        }
    }
    
    console.log('Filtered dates:', filteredDates);
    console.log('Filtered counts:', filteredCounts);
    
    // Форматируем даты для отображения
    const formattedLabels = filteredDates.map(date => {
        const d = new Date(date);
        if (range === 'week') {
            return d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric' });
        } else {
            return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
        }
    });
    
    commitsChart.data.labels = formattedLabels;
    commitsChart.data.datasets[0].data = filteredCounts;
    commitsChart.update();
    
    console.log('Chart updated with labels:', formattedLabels);
}

/* ═══════════════════════════════════════════
   ЗАГРУЗКА ПРОЕКТОВ
   ═══════════════════════════════════════════ */
async function loadProjects() {
    const sel = document.getElementById("projectSelect");
    if (!sel) return;
    
    try {
        const res = await fetch(`${API_BASE}/projects`);
        if (!res.ok) throw new Error(res.statusText);
        const { projects } = await res.json();
        
        sel.innerHTML = '<option value="">🌍 Все проекты</option>';
        projects.forEach(p => {
            const o = document.createElement("option");
            o.value = p.id;
            o.textContent = `${p.namespace}/${p.name}`;
            sel.appendChild(o);
        });
    } catch (e) {
        console.error("loadProjects:", e);
        sel.innerHTML = '<option value="">🌍 Все проекты</option>';
    }
}

/* ═══════════════════════════════════════════
   ЗАГРУЗКА РАЗРАБОТЧИКОВ (с фильтром проекта)
   ═══════════════════════════════════════════ */
async function loadDevelopers(projectId = null) {
    const sel = document.getElementById("developerSelect");
    const days = document.getElementById("periodSelect").value;
    
    let url = `${API_BASE}/team/list?days=${days}`;
    if (projectId) {
        url += `&project_id=${projectId}`;
    }
    
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(res.statusText);
        const { developers } = await res.json();
        
        sel.innerHTML = '<option value="">Выберите разработчика</option>';
        developers.forEach(name => {
            const o = document.createElement("option");
            o.value = name;
            o.textContent = name;
            sel.appendChild(o);
        });
    } catch (e) {
        sel.innerHTML = '<option>Ошибка загрузки</option>';
        console.error("loadDevelopers:", e);
    }
}

/* ═══════════════════════════════════════════
   ЗАГРУЗКА ОБЩЕГО ОБЗОРА (все разработчики)
   ═══════════════════════════════════════════ */
async function loadOverview(days, projectId = null) {
    const dashboard = document.getElementById("dashboard");
    const empty = document.getElementById("emptyState");
    const loading = document.getElementById("loadingOverlay");
    
    empty.classList.add("hidden");
    loading.classList.remove("hidden");
    
    let url = `${API_BASE}/overview?days=${days}`;
    if (projectId) {
        url += `&project_id=${projectId}`;
    }
    
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const data = await res.json();
        
        console.log("[DEBUG] Overview received:", data);
        
        // Обновляем заголовок
        const projectName = projectId ? 
            `Обзор проекта (ID: ${projectId})` : 
            "📊 Обзор всех проектов";
        document.getElementById("projectName").textContent = projectName;
        document.getElementById("periodLabel").textContent = `${days} дней`;
        document.getElementById("generatedAt").textContent = formatDate(data.generated_at);
        
        // Обновляем числа
        document.getElementById("totalCommits").textContent = data.totals?.commits || 0;
        document.getElementById("totalMRs").textContent = data.totals?.merge_requests || 0;
        document.getElementById("mergedMRs").textContent = data.totals?.merged_merge_requests || 0;
        document.getElementById("avgMergeTime").textContent = formatHours(data.totals?.avg_merge_time_hours);
        document.getElementById("totalComments").textContent = data.totals?.total_comments || 0;
        
        // Скрываем карточку с one-on-one темой
        const promptCard = document.getElementById("promptCard");
        promptCard.style.display = "none";
        
        // Скрываем график в режиме обзора
        const chartCard = document.querySelector(".chart-card");
        if (chartCard) {
            chartCard.style.display = "none";
        }
        
        // Показываем всех разработчиков
        const signalsGrid = document.getElementById("signalsGrid");
        const allDevelopers = data.all_contributors || [];
        
        if (allDevelopers.length) {
            signalsGrid.innerHTML = `
                <div class="signal-card" style="grid-column: span 4;">
                    <div class="signal-top">
                        <span class="signal-title">👥 Все разработчики</span>
                        <span class="signal-badge" data-status="good">${allDevelopers.length} человек</span>
                    </div>
                    <div class="contributors-list">
                        ${allDevelopers.map((c, i) => `
                            <div class="contributor-item">
                                <span class="contributor-rank">${i+1}.</span>
                                <span class="contributor-name">${escHtml(c.name)}</span>
                                <span class="contributor-commits">📦 ${c.commits} коммитов</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        } else {
            signalsGrid.innerHTML = '<div class="signal-card">Нет данных за период</div>';
        }
        
        // Показываем список MR
        const mrTableBody = document.getElementById("mrTableBody");
        const mrsList = data.merge_requests?.list || [];
        
        if (mrsList.length) {
            renderMRTable(mrsList);
        } else {
            mrTableBody.innerHTML = `<tr><td colspan="6" class="empty-row">Нет Merge Requests за период</td></tr>`;
        }
        
        // Показываем типы комментариев
        renderCommentTypes(mrsList);
        
        dashboard.classList.remove("hidden");
    } catch (e) {
        console.error("loadOverview:", e);
        dashboard.classList.add("hidden");
        empty.classList.remove("hidden");
        document.getElementById("emptyIcon").textContent = "⚠️";
        document.getElementById("emptyTitle").textContent = "Ошибка загрузки обзора";
        document.getElementById("emptyText").textContent = String(e);
    } finally {
        loading.classList.add("hidden");
    }
}

/* ═══════════════════════════════════════════
   ЗАГРУЗКА ОТЧЁТА ПО РАЗРАБОТЧИКУ
   ═══════════════════════════════════════════ */
async function loadDeveloperReport(username, days, projectId = null) {
    const dashboard = document.getElementById("dashboard");
    const empty = document.getElementById("emptyState");
    const loading = document.getElementById("loadingOverlay");
    
    empty.classList.add("hidden");
    loading.classList.remove("hidden");
    
    let url = `${API_BASE}/team/${encodeURIComponent(username)}/report?days=${days}`;
    if (projectId) {
        url += `&project_id=${projectId}`;
    }
    
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const report = await res.json();

        console.log("[DEBUG] Report received:", report);
        
        // Сохраняем данные отчёта
        lastReportData = report;

        // Header
        document.getElementById("projectName").textContent = report.project_name || "Project";
        document.getElementById("periodLabel").textContent = `${days} дней`;
        document.getElementById("generatedAt").textContent = formatDate(report.generated_at);

        // Данные
        const totalCommits = report.commits?.total ?? 0;
        const additions = report.commits?.total_additions ?? 0;
        const deletions = report.commits?.total_deletions ?? 0;
        
        const mrs = report.merge_requests ?? [];
        const totalMRs = mrs.length;
        const mergedMRs = mrs.filter(m => m.state === 'merged').length;
        
        const mergeTimes = mrs
            .filter(m => m.state === 'merged' && m.time_to_merge_hours != null)
            .map(m => m.time_to_merge_hours);
        const avgMergeTime = mergeTimes.length
            ? mergeTimes.reduce((a, b) => a + b, 0) / mergeTimes.length
            : null;
        
        const totalComments = report.comments?.total_comments ?? 0;

        // Обновляем числа
        document.getElementById("totalCommits").textContent = totalCommits;
        document.getElementById("totalMRs").textContent = totalMRs;
        document.getElementById("mergedMRs").textContent = mergedMRs;
        document.getElementById("avgMergeTime").textContent = formatHours(avgMergeTime);
        document.getElementById("totalComments").textContent = totalComments;

        // Показываем карточку
        const promptCard = document.getElementById("promptCard");
        promptCard.style.display = "flex";
        
        // Показываем график
        const chartCard = document.querySelector(".chart-card");
        if (chartCard) {
            chartCard.style.display = "block";
        }

        // Signals
        const signals = renderSignals(report, username);
        
        // Prompt - используем report с conversation_prompt от LLM
        renderPrompt(report);

        // MR Table
        renderMRTable(mrs);

        // Comment Types
        renderCommentTypes(mrs);

        // Обновляем график
        console.log('Checking for chart data...');
        if (report.commits?.activity_by_date) {
            console.log('activity_by_date found:', report.commits.activity_by_date);
            updateChart(report.commits.activity_by_date, currentChartRange);
        } else {
            console.log("Нет данных activity_by_date для графика");
        }

        dashboard.classList.remove("hidden");
    } catch (e) {
        console.error("loadDeveloperReport:", e);
        dashboard.classList.add("hidden");
        empty.classList.remove("hidden");
        document.getElementById("emptyIcon").textContent = "⚠️";
        document.getElementById("emptyTitle").textContent = "Ошибка загрузки";
        document.getElementById("emptyText").textContent = String(e);
    } finally {
        loading.classList.add("hidden");
    }
}

/* ═══════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════ */
document.addEventListener("DOMContentLoaded", async () => {
    console.log('DOM Content Loaded');
    
    // Инициализируем график
    initChart();
    
    // Загружаем проекты
    await loadProjects();
    
    // Загружаем разработчиков
    await loadDevelopers();
    
    // Обработчики кнопок графика
    const chartBtns = document.querySelectorAll('.chart-btn');
    console.log('Chart buttons found:', chartBtns.length);
    
    chartBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            console.log('Chart button clicked:', btn.dataset.range);
            
            // Убираем активный класс со всех кнопок
            chartBtns.forEach(b => b.classList.remove('active'));
            // Добавляем активный класс на нажатую кнопку
            btn.classList.add('active');
            
            const range = btn.dataset.range;
            currentChartRange = range;
            
            // Если есть сохранённые данные, обновляем график
            if (lastReportData && lastReportData.commits?.activity_by_date) {
                console.log('Updating chart with range:', range);
                updateChart(lastReportData.commits.activity_by_date, range);
            } else {
                console.log('No report data available for chart update');
            }
        });
    });
    
    // Смена режима просмотра
    const viewModeSelect = document.getElementById("viewModeSelect");
    if (viewModeSelect) {
        viewModeSelect.addEventListener("change", async e => {
            currentViewMode = e.target.value;
            
            const developerSelectWrap = document.getElementById("developerSelectWrap");
            if (currentViewMode === "overview") {
                if (developerSelectWrap) developerSelectWrap.classList.add("hidden");
                const days = document.getElementById("periodSelect").value;
                await loadOverview(days, currentProjectId);
            } else {
                if (developerSelectWrap) developerSelectWrap.classList.remove("hidden");
                document.getElementById("dashboard").classList.add("hidden");
                document.getElementById("emptyState").classList.remove("hidden");
                document.getElementById("emptyIcon").textContent = "👤";
                document.getElementById("emptyTitle").textContent = "Выберите разработчика";
                document.getElementById("emptyText").textContent = "Выберите проект и разработчика, чтобы увидеть аналитику";
            }
        });
    }
    
    // Смена проекта
    const projectSelect = document.getElementById("projectSelect");
    if (projectSelect) {
        projectSelect.addEventListener("change", async e => {
            currentProjectId = e.target.value || null;
            await loadDevelopers(currentProjectId);
            
            if (currentViewMode === "overview") {
                const days = document.getElementById("periodSelect").value;
                await loadOverview(days, currentProjectId);
            } else {
                const devSelect = document.getElementById("developerSelect");
                if (devSelect) devSelect.value = "";
                document.getElementById("dashboard").classList.add("hidden");
                document.getElementById("emptyState").classList.remove("hidden");
            }
        });
    }
    
    // Смена разработчика
    const developerSelect = document.getElementById("developerSelect");
    if (developerSelect) {
        developerSelect.addEventListener("change", e => {
            if (currentViewMode === "overview") return;
            
            const u = e.target.value;
            const d = document.getElementById("periodSelect").value;
            if (u) {
                // Сбрасываем период графика на месяц при смене разработчика
                currentChartRange = 'month';
                chartBtns.forEach(b => b.classList.remove('active'));
                const monthBtn = document.querySelector('.chart-btn[data-range="month"]');
                if (monthBtn) monthBtn.classList.add('active');
                
                loadDeveloperReport(u, d, currentProjectId);
            } else {
                document.getElementById("dashboard").classList.add("hidden");
                document.getElementById("emptyState").classList.remove("hidden");
            }
        });
    }
    
    // Смена периода
    const periodSelect = document.getElementById("periodSelect");
    if (periodSelect) {
        periodSelect.addEventListener("change", e => {
            const days = e.target.value;
            if (currentViewMode === "overview") {
                loadOverview(days, currentProjectId);
            } else {
                const u = document.getElementById("developerSelect").value;
                if (u) {
                    // Сбрасываем период графика
                    currentChartRange = 'month';
                    chartBtns.forEach(b => b.classList.remove('active'));
                    const monthBtn = document.querySelector('.chart-btn[data-range="month"]');
                    if (monthBtn) monthBtn.classList.add('active');
                    
                    loadDeveloperReport(u, days, currentProjectId);
                }
            }
        });
    }
});