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
        document.getElementById("doc-label-badge").textContent = data.doc_label ? "Dokumentum: " + data.doc_label : "";
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
    }

    function escapeHtml(s) {
        var div = document.createElement("div");
        div.textContent = s;
        return div.innerHTML;
    }

    function initDefaultButton() {
        get("/api/default-pdf-info")
            .then(function(r) { return r.json(); })
            .then(function(info) {
                var area = document.getElementById("default-button-area");
                if (info.default_pdf_name) {
                    var btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "btn-default";
                    btn.textContent = "Alapértelmezett elemzése: " + info.default_pdf_name;
                    btn.addEventListener("click", runDefault);
                    area.appendChild(btn);
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
        fetch(API_BASE + "/api/process-default", { method: "POST", signal: controller.signal, headers: { "Accept": "application/json" } })
            .then(function(r) { return r.json(); })
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

    document.getElementById("upload-form").addEventListener("submit", function(e) {
        e.preventDefault();
        var fileInput = document.getElementById("file");
        if (!fileInput.files.length) return;
        var fd = new FormData();
        fd.append("file", fileInput.files[0]);
        var label = document.getElementById("label").value;
        if (label) fd.append("label", label);
        var btn = this.querySelector('button[type="submit"]');
        btn.disabled = true;
        postForm(API_BASE + "/api/upload", fd)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                btn.disabled = false;
                showResult(data);
            })
            .catch(function(err) {
                btn.disabled = false;
                showError(err.message || "Feltöltési hiba.");
            });
    });

    initDefaultButton();
})();
