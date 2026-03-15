(function() {
    "use strict";

    // Egy port / reverse proxy: ha az oldal pl. https://nas.local/pdfai/ alatt van, alapútvonal /pdfai
    var API_BASE = window.APP_BASE;
    if (API_BASE === undefined) {
        var p = window.location.pathname.replace(/\/$/, "");
        API_BASE = (p === "" || p === "/") ? "" : p;
    }

    function get(url) {
        return fetch(API_BASE + url, { method: "GET", headers: { "Accept": "application/json" } });
    }

    function postJson(url) {
        return fetch(API_BASE + url, { method: "POST", headers: { "Accept": "application/json" } });
    }

    function postForm(url, formData) {
        return fetch(API_BASE + url, { method: "POST", body: formData }); // no Content-Type, browser sets multipart
    }

    function hideAll() {
        document.getElementById("error-section").style.display = "none";
        document.getElementById("results-section").style.display = "none";
    }

    function showError(msg) {
        hideAll();
        document.getElementById("error-text").textContent = msg;
        document.getElementById("error-section").style.display = "block";
    }

    function showResult(data) {
        hideAll();
        if (data.error) {
            showError(data.error);
            return;
        }
        var badge = document.getElementById("doc-label-badge");
        if (data.doc_label) {
            if (data.doc_url) {
                badge.innerHTML = "Dokumentum: <a href=\"" + escapeHtml(API_BASE + data.doc_url) + "\" target=\"_blank\" rel=\"noopener\" class=\"doc-link\">" + escapeHtml(data.doc_label) + "</a>";
            } else {
                badge.textContent = "Dokumentum: " + data.doc_label;
            }
        } else {
            badge.textContent = "";
        }
        var meta = document.getElementById("meta-area");
        meta.innerHTML = "";
        if (data.student_name) {
            var d = document.createElement("div");
            d.innerHTML = "<strong>Hallgató neve:</strong> " + escapeHtml(data.student_name);
            meta.appendChild(d);
        }
        if (data.institution) {
            var d = document.createElement("div");
            d.innerHTML = "<strong>Intézmény:</strong> " + escapeHtml(data.institution);
            meta.appendChild(d);
        }
        if (data.model_used) {
            var d = document.createElement("div");
            d.className = "model-used";
            d.innerHTML = "<strong>Modell:</strong> " + escapeHtml(getModelLabel(data.model_used));
            meta.appendChild(d);
        }
        if (data.usage_total_tokens != null || data.usage_prompt_tokens != null || data.usage_completion_tokens != null) {
            var d = document.createElement("div");
            d.className = "usage-tokens";
            var parts = [];
            if (data.usage_total_tokens != null) parts.push("Összesen: " + data.usage_total_tokens + " token");
            if (data.usage_prompt_tokens != null || data.usage_completion_tokens != null) {
                var p = data.usage_prompt_tokens != null ? data.usage_prompt_tokens : "?";
                var c = data.usage_completion_tokens != null ? data.usage_completion_tokens : "?";
                parts.push("(prompt: " + p + ", válasz: " + c + ")");
            }
            d.innerHTML = "<strong>Felhasznált tokenek:</strong> " + parts.join(" ");
            meta.appendChild(d);
        }
        if (data.rate_limit_remaining_tokens != null || data.rate_limit_remaining_requests != null) {
            var d = document.createElement("div");
            d.className = "rate-limit";
            var parts = [];
            if (data.rate_limit_remaining_tokens != null) {
                var s = "Maradék: " + data.rate_limit_remaining_tokens + " token/perc";
                if (data.rate_limit_limit_tokens != null) s += " (limit: " + data.rate_limit_limit_tokens + ")";
                parts.push(s);
            }
            if (data.rate_limit_remaining_requests != null) {
                var s = data.rate_limit_remaining_requests + " kérés maradt";
                if (data.rate_limit_limit_requests != null) s += " (limit: " + data.rate_limit_limit_requests + ")";
                parts.push(s);
            }
            d.innerHTML = "<strong>Maradék lehetőség:</strong> " + parts.join("; ");
            meta.appendChild(d);
        }
        var tbody = document.getElementById("results-tbody");
        tbody.innerHTML = "";
        (data.result || []).forEach(function(row) {
            var tr = document.createElement("tr");
            tr.innerHTML = "<td>" + escapeHtml(row.course_name || "") + "</td><td>" + escapeHtml(row.course_code || "") + "</td><td>" + escapeHtml(row.term || "") + "</td><td>" + (row.credits != null ? escapeHtml(String(row.credits)) : "") + "</td><td>" + escapeHtml(row.grade || "") + "</td>";
            tbody.appendChild(tr);
        });
        if (data.raw_json) {
            document.getElementById("raw-json-code").textContent = data.raw_json;
            document.getElementById("json-section").style.display = "block";
        } else {
            document.getElementById("json-section").style.display = "none";
        }
        document.getElementById("results-section").style.display = "block";
        lastResult = data;
        loadHistoryForCompare();
    }

    var lastResult = null;
    var compareHistoryEntries = [];

    function loadHistoryForCompare() {
        var sel = document.getElementById("compare-select");
        var wrap = document.getElementById("compare-result");
        if (wrap) wrap.style.display = "none";
        if (!sel) return;
        get("/api/history")
            .then(function(r) { return r.ok ? r.json() : Promise.reject(); })
            .then(function(d) {
                compareHistoryEntries = d.entries || [];
                sel.innerHTML = "<option value=\"\">— Korábbi futtatás kiválasztása —</option>";
                compareHistoryEntries.forEach(function(e, i) {
                    var opt = document.createElement("option");
                    opt.value = i;
                    var label = (e.doc_label || "?") + " — " + (e.started_at ? e.started_at.replace("T", " ").slice(0, 19) : "");
                    opt.textContent = label;
                    sel.appendChild(opt);
                });
            })
            .catch(function() { compareHistoryEntries = []; });
    }

    function buildCompareTable(currentRows, prevRows, docLabel, startedAt) {
        var maxLen = Math.max(currentRows.length, prevRows.length);
        var html = "<p class=\"compare-meta\">Kiválasztott: " + escapeHtml(docLabel || "?") + " <span class=\"compare-date\">" + escapeHtml(startedAt ? startedAt.replace("T", " ").slice(0, 19) : "") + "</span></p>";
        html += "<div class=\"table-wrap\"><table class=\"compare-table\"><thead><tr><th>Tárgy neve</th><th>Kód</th><th>Félév</th><th>Kredit</th><th>Osztályzat (most)</th><th>Osztályzat (korábbi)</th><th>Eltérés</th></tr></thead><tbody>";
        for (var i = 0; i < maxLen; i++) {
            var cur = currentRows[i] || {};
            var prev = prevRows[i] || {};
            var cGrade = cur.grade != null ? String(cur.grade) : "";
            var pGrade = prev.grade != null ? String(prev.grade) : "";
            var diff = cGrade !== pGrade;
            html += "<tr" + (diff ? " class=\"row-diff\"" : "") + ">";
            html += "<td>" + escapeHtml((cur.course_name || prev.course_name || "")) + "</td>";
            html += "<td>" + escapeHtml((cur.course_code || prev.course_code || "")) + "</td>";
            html += "<td>" + escapeHtml((cur.term || prev.term || "")) + "</td>";
            html += "<td>" + (cur.credits != null ? escapeHtml(String(cur.credits)) : (prev.credits != null ? escapeHtml(String(prev.credits)) : "")) + "</td>";
            html += "<td" + (diff ? " class=\"cell-diff\"" : "") + ">" + escapeHtml(cGrade) + "</td>";
            html += "<td" + (diff ? " class=\"cell-diff\"" : "") + ">" + escapeHtml(pGrade) + "</td>";
            html += "<td>" + (diff ? "●" : "—") + "</td></tr>";
        }
        html += "</tbody></table></div>";
        return html;
    }

    function initCompare() {
        var btn = document.getElementById("compare-btn");
        var sel = document.getElementById("compare-select");
        var resultDiv = document.getElementById("compare-result");
        if (!btn || !sel || !resultDiv) return;
        btn.addEventListener("click", function() {
            var idx = parseInt(sel.value, 10);
            if (isNaN(idx) || idx < 0 || !compareHistoryEntries[idx]) {
                resultDiv.style.display = "none";
                return;
            }
            if (!lastResult || !lastResult.result) {
                resultDiv.innerHTML = "<p class=\"compare-meta\">Nincs aktuális eredmény az összehasonlításhoz.</p>";
                resultDiv.style.display = "block";
                return;
            }
            var prev = compareHistoryEntries[idx];
            resultDiv.innerHTML = buildCompareTable(lastResult.result, prev.result, prev.doc_label, prev.started_at);
            resultDiv.style.display = "block";
        });
    }

    function escapeHtml(s) {
        var div = document.createElement("div");
        div.textContent = s;
        return div.innerHTML;
    }

    function getModelLabel(id) {
        var list = document.querySelectorAll("#models-list [data-model-id]");
        for (var i = 0; i < list.length; i++) {
            if (list[i].getAttribute("data-model-id") === id) return list[i].textContent.trim();
        }
        return id;
    }

    function getSelectedModelId() {
        var sel = document.querySelector("#models-list input[name=model]:checked");
        return sel ? sel.value : null;
    }

    function initVersion() {
        get("/api/health")
            .then(function(r) { return r.ok ? r.json() : Promise.reject(); })
            .then(function(data) {
                var el = document.getElementById("app-version");
                if (el && data.version) el.textContent = "v" + data.version;
            })
            .catch(function() {});
    }

    function initModels() {
        get("/api/models")
            .then(function(r) { return r.ok ? r.json() : Promise.reject(); })
            .then(function(data) {
                var list = document.getElementById("models-list");
                if (!list) return;
                list.innerHTML = "";
                var defaultId = data.default_model || "";
                (data.models || []).forEach(function(m) {
                    var label = document.createElement("label");
                    label.className = "model-option";
                    var radio = document.createElement("input");
                    radio.type = "radio";
                    radio.name = "model";
                    radio.value = m.id;
                    radio.setAttribute("data-model-id", m.id);
                    if (m.id === defaultId) radio.checked = true;
                    label.appendChild(radio);
                    label.appendChild(document.createTextNode(" " + (m.label || m.id)));
                    if (m.limit_label) {
                        var limitSpan = document.createElement("span");
                        limitSpan.className = "model-limit";
                        limitSpan.textContent = " — " + m.limit_label;
                        label.appendChild(limitSpan);
                    }
                    list.appendChild(label);
                });
            })
            .catch(function() {
                var list = document.getElementById("models-list");
                if (list) list.innerHTML = "<p class=\"no-models\">Nem sikerült betölteni a modelleket.</p>";
            });
    }

    function initDefaultButton() {
        get("/api/default-pdf-info")
            .then(function(r) { return r.json(); })
            .then(function(info) {
                var area = document.getElementById("default-button-area");
                if (info.default_pdf_name) {
                    var row = document.createElement("div");
                    row.className = "default-button-row";
                    var btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "btn-default";
                    btn.textContent = "Alapértelmezett elemzése: " + info.default_pdf_name;
                    btn.addEventListener("click", runDefault);
                    row.appendChild(btn);
                    var docLink = document.createElement("a");
                    docLink.href = API_BASE + "/api/default-pdf";
                    docLink.target = "_blank";
                    docLink.rel = "noopener";
                    docLink.className = "default-doc-link";
                    docLink.textContent = "Megnyitás";
                    row.appendChild(docLink);
                    area.appendChild(row);
                } else {
                    var p = document.createElement("p");
                    p.className = "no-default";
                    p.innerHTML = "Nincs alapértelmezett PDF. Tegyél egy .pdf fájlt a <code>pdf/</code> mappába, majd frissítsd az oldalt.";
                    area.appendChild(p);
                }
            })
            .catch(function() {
                document.getElementById("default-button-area").innerHTML = "<p class=\"no-default\">Nem sikerült betölteni az alapértelmezett PDF adatot.</p>";
            });
    }

    function runDefault() {
        var btn = document.querySelector("#default-button-area .btn-default");
        var loading = document.getElementById("default-loading");
        if (btn) btn.disabled = true;
        loading.style.display = "flex";
        var controller = new AbortController();
        var timeoutId = setTimeout(function() { controller.abort(); }, 600000);
        var url = API_BASE + "/api/process-default";
        var modelId = getSelectedModelId();
        if (modelId) url += "?model=" + encodeURIComponent(modelId);
        fetch(url, { method: "POST", signal: controller.signal, headers: { "Accept": "application/json" } })
            .then(function(r) {
                return r.text().then(function(text) {
                    if (!r.ok) {
                        try {
                            var detail = text ? JSON.parse(text).detail : "";
                            if (detail) text = typeof detail === "string" ? detail : JSON.stringify(detail);
                        } catch (e) {}
                        throw new Error("HTTP " + r.status + (text ? ": " + text.slice(0, 300) : ""));
                    }
                    try {
                        return JSON.parse(text);
                    } catch (e) {
                        throw new Error("A szerver válasza nem érvényes JSON. " + (text ? text.slice(0, 150) : ""));
                    }
                });
            })
            .then(function(data) {
                clearTimeout(timeoutId);
                loading.style.display = "none";
                if (btn) btn.disabled = false;
                showResult(data);
            })
            .catch(function(err) {
                clearTimeout(timeoutId);
                loading.style.display = "none";
                if (btn) btn.disabled = false;
                showError("Hiba vagy időtúllépés: " + (err.message || err));
            });
    }

    var fileInput = document.getElementById("file");
    var fileHint = document.getElementById("file-hint");
    if (fileInput && fileHint) {
        fileInput.addEventListener("change", function() {
            fileHint.textContent = fileInput.files.length ? fileInput.files[0].name : "";
        });
    }

    document.getElementById("upload-form").addEventListener("submit", function(e) {
        e.preventDefault();
        if (!fileInput.files.length) return;
        var fd = new FormData();
        fd.append("file", fileInput.files[0]);
        var label = document.getElementById("label").value;
        if (label) fd.append("label", label);
        var modelId = getSelectedModelId();
        if (modelId) fd.append("model", modelId);
        var btn = this.querySelector('button[type="submit"]');
        var uploadLoading = document.getElementById("upload-loading");
        btn.disabled = true;
        if (uploadLoading) uploadLoading.style.display = "flex";
        postForm("/api/upload", fd)
            .then(function(r) {
                return r.text().then(function(text) {
                    if (!r.ok) {
                        try {
                            var detail = text ? JSON.parse(text).detail : "";
                            if (detail) text = typeof detail === "string" ? detail : JSON.stringify(detail);
                        } catch (e) {}
                        throw new Error("HTTP " + r.status + (text ? ": " + text.slice(0, 300) : ""));
                    }
                    try {
                        return JSON.parse(text);
                    } catch (e) {
                        throw new Error("A szerver válasza nem érvényes JSON. " + (text ? text.slice(0, 150) : ""));
                    }
                });
            })
            .then(function(data) {
                btn.disabled = false;
                if (uploadLoading) uploadLoading.style.display = "none";
                showResult(data);
            })
            .catch(function(err) {
                btn.disabled = false;
                if (uploadLoading) uploadLoading.style.display = "none";
                showError(err.message || "Feltöltési hiba.");
            });
    });

    function initLogPanel() {
        var toggle = document.getElementById("log-toggle");
        var content = document.getElementById("log-content");
        var refreshBtn = document.getElementById("log-refresh");
        if (!toggle || !content) return;

        function renderLog(lines) {
            content.innerHTML = "";
            if (!lines || !lines.length) {
                content.textContent = "Nincs még log.";
                return;
            }
            var pre = document.createElement("pre");
            pre.className = "log-lines";
            pre.textContent = lines.join("\n");
            content.appendChild(pre);
        }

        function fetchLog() {
            get("/api/logs")
                .then(function(r) { return r.ok ? r.json() : Promise.reject(); })
                .then(function(data) {
                    renderLog(data.lines || []);
                })
                .catch(function() { renderLog([]); });
        }

        toggle.addEventListener("click", function() {
            var open = content.hidden === false;
            content.hidden = open;
            toggle.setAttribute("aria-expanded", !open);
            if (!open) fetchLog();
        });
        refreshBtn.addEventListener("click", function() {
            if (!content.hidden) fetchLog();
        });
    }

    initVersion();
    initModels();
    initDefaultButton();
    initLogPanel();
    initCompare();
})();
