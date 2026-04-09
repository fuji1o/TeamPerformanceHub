/* ═══════════════════════════════════════════
   Team Performance Hub — Frontend
   ═══════════════════════════════════════════ */
const API_BASE = "http://127.0.0.1:8000/api";

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
    return h < 24 ? `${Math.round(h)} ч` : `${(h / 24).toFixed(1)} дн`;
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
            const perWeek = total / (days / 7);
            
            if (perWeek >= 5) return { status: "good", badge: `${total} коммитов`, hint: "Регулярная активность" };
            if (perWeek >= 2) return { status: "warning", badge: `${total} коммитов`, hint: "Можно чаще" };
            return { status: "bad", badge: `${total} коммитов`, hint: "Мало коммитов — обсудите блоки" };
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
            
            if (total === 0) return { status: "bad", badge: "0 MR", hint: "Нет MR за период" };
            if (merged > 0) return { status: "good", badge: `${total} MR (${merged} смержено)`, hint: "Есть результат" };
            return { status: "warning", badge: `${total} MR`, hint: "Ни один не смержен" };
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
            
            if (!delays.length) return { status: "neutral", badge: "Нет ревью", hint: "Проверьте, назначены ли ревьюеры" };
            
            const avg = delays.reduce((a, b) => a + b, 0) / delays.length;
            
            if (avg <= 4) return { status: "good", badge: `≈${Math.round(avg)} ч`, hint: "Быстрая обратная связь" };
            if (avg <= 24) return { status: "warning", badge: `≈${Math.round(avg)} ч`, hint: "Ревью с задержкой" };
            return { status: "bad", badge: `≈${Math.round(avg)} ч`, hint: "Долгое ожидание ревью" };
        },
    },
    {
        key: "desc",
        icon: "📝",
        title: "Описание MR",
        compute(r, username) {
            const mrs = r.merge_requests ?? [];
            
            if (!mrs.length) return { status: "neutral", badge: "—", hint: "Нет MR" };
            
            const withDesc = mrs.filter(m => {
                const d = m.quality_score?.details;
                return d && (d.description_length ?? 0) > 20;
            }).length;
            
            const ratio = withDesc / mrs.length;
            
            if (ratio >= 0.8) return { status: "good", badge: `${withDesc}/${mrs.length}`, hint: "MR с описанием" };
            if (ratio >= 0.4) return { status: "warning", badge: `${withDesc}/${mrs.length}`, hint: "Часть MR без описания" };
            return { status: "bad", badge: `${withDesc}/${mrs.length}`, hint: "Описание помогает ревьюверу" };
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
        tbody.innerHTML = `<tr><td colspan="6" class="empty-row">Нет Merge Requests за период</td></tr>`;
        return;
    }
    
    tbody.innerHTML = mrs.map(mr => {
        const d = mr.quality_score?.details ?? {};
        const additions = d.additions ?? 0;
        const deletions = d.deletions ?? 0;
        const commitsCount = mr.commits_count ?? 0;
        const hasDesc = (d.description_length ?? 0) > 20;
        const descClass = hasDesc ? "yn-yes" : "yn-no";
        const descIcon = hasDesc ? "✅" : "✖️";
        const actualAuthor = mr.actual_author || mr.author || '';
        const mergedBy = mr.merged_by || '';
        
        return `
        <tr>
            <td>
                <a href="${mr.web_url}" target="_blank" class="mr-link">!${mr.iid}</a>
                <span class="mr-title-sub">${escHtml(mr.title)}</span>
                <span class="mr-title-sub" style="font-size: 0.65rem; color: #888; display: block;">
                    ✍️ ${escHtml(actualAuthor)}
                    ${mergedBy ? ` | Смержил: ${escHtml(mergedBy)}` : ''}
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

function renderPrompt(signals) {
    const card = document.getElementById("promptCard");
    const el = document.getElementById("conversationPrompt");
    const icon = document.getElementById("promptIcon");
    
    card.classList.remove("level-good", "level-warn", "level-bad");
    
    const bad = signals.filter(s => s.status === "bad");
    const warn = signals.filter(s => s.status === "warning");
    
    if (bad.length) {
        card.classList.add("level-bad");
        icon.textContent = "🔴";
        el.textContent = `Обратите внимание: ${bad.map(s => s.label.toLowerCase()).join(", ")}. Обсудите, есть ли блоки или нужна помощь.`;
    } else if (warn.length) {
        card.classList.add("level-warn");
        icon.textContent = "🟡";
        el.textContent = `Есть зоны роста: ${warn.map(s => s.label.toLowerCase()).join(", ")}. Спросите, что мешает улучшить.`;
    } else {
        card.classList.add("level-good");
        icon.textContent = "🟢";
        el.textContent = "Активность в норме. Спросите, чем можно поддержать текущий темп.";
    }
}

/* ═══════════════════════════════════════════
   DATA LOADING
   ═══════════════════════════════════════════ */
async function loadDevelopers() {
    const sel = document.getElementById("developerSelect");
    try {
        const res = await fetch(`${API_BASE}/team/list`);
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

async function loadDashboard(username, days) {
    const dashboard = document.getElementById("dashboard");
    const empty = document.getElementById("emptyState");
    const loading = document.getElementById("loadingOverlay");
    
    empty.classList.add("hidden");
    loading.classList.remove("hidden");
    
    try {
        const res = await fetch(`${API_BASE}/team/${encodeURIComponent(username)}/report?days=${days}`);
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const report = await res.json();

        console.log("[DEBUG] Report received:", report);

        // Header
        document.getElementById("projectName").textContent = report.project_name || "Project";
        document.getElementById("periodLabel").textContent = `${days} дней`;
        document.getElementById("generatedAt").textContent = formatDate(report.generated_at);

        // Данные уже отфильтрованы на бэкенде
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

        // Signals + Prompt
        const signals = renderSignals(report, username);
        renderPrompt(signals);

        // MR Table
        renderMRTable(mrs);

        // Comment Types
        renderCommentTypes(mrs);

        dashboard.classList.remove("hidden");
    } catch (e) {
        console.error("loadDashboard:", e);
        dashboard.classList.add("hidden");
        empty.classList.remove("hidden");
        document.querySelector(".empty-icon").textContent = "⚠️";
        document.querySelector(".empty-state h2").textContent = "Ошибка загрузки";
        document.querySelector(".empty-state p").textContent = String(e);
    } finally {
        loading.classList.add("hidden");
    }
}

/* ═══════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════ */
document.addEventListener("DOMContentLoaded", async () => {
    await loadDevelopers();
    
    document.getElementById("developerSelect").addEventListener("change", e => {
        const u = e.target.value;
        const d = document.getElementById("periodSelect").value;
        if (u) {
            loadDashboard(u, d);
        } else {
            document.getElementById("dashboard").classList.add("hidden");
            document.getElementById("emptyState").classList.remove("hidden");
        }
    });
    
    document.getElementById("periodSelect").addEventListener("change", e => {
        const u = document.getElementById("developerSelect").value;
        if (u) loadDashboard(u, e.target.value);
    });
});