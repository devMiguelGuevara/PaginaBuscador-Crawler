(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var form = $("scan-form"), errBox = $("form-error"), startBtn = $("start-btn");
  var source = null, currentId = null, jsCount = 0, errCount = 0;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function normalizeUrl(v) {
    v = (v || "").trim();
    if (!v) return "";
    if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(v)) v = "https://" + v;
    try {
      var u = new URL(v);
      if (!/^https?:$/.test(u.protocol) || (u.hostname.indexOf(".") === -1 && u.hostname !== "localhost")) return "";
      return u.href;
    } catch (e) { return ""; }
  }

  function payload() {
    var fd = new FormData(form), data = {};
    form.querySelectorAll("input,select").forEach(function (el) {
      if (!el.name) return;
      if (el.type === "checkbox") data[el.name] = el.checked;
      else if (el.type === "number") { if (el.value !== "") data[el.name] = Number(el.value); }
      else data[el.name] = fd.get(el.name);
    });
    return data;
  }

  function showError(msg) { errBox.textContent = msg; errBox.hidden = !msg; }

  function log(html, cls) {
    var box = $("log"), line = document.createElement("div");
    line.className = "line " + (cls || "");
    line.innerHTML = html;
    box.appendChild(line);
    while (box.children.length > 400) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  }

  function setProgress(done, queued, max) {
    $("c-done").textContent = done; $("c-queued").textContent = queued; $("c-max").textContent = max;
    var total = Math.max(1, Math.min(max || 1, done + queued));
    $("bar-fill").style.width = Math.min(100, Math.round(100 * done / total)) + "%";
  }

  function resetProgress(job) {
    jsCount = 0; errCount = 0;
    $("progress").hidden = false; $("log").innerHTML = ""; $("summary").hidden = true; $("summary").innerHTML = "";
    ["open-report", "open-json", "open-pdf"].forEach(function (id) { $(id).hidden = true; });
    $("cancel-btn").hidden = false;
    $("prog-title").textContent = "Escaneando " + job.url;
    $("prog-phase").textContent = "";
    $("c-js").textContent = "0"; $("c-err").textContent = "0";
    $("bar-fill").className = "";
    setProgress(0, 0, job.max_pages);
  }

  function showFiles(files) {
    if (files.html) { $("open-report").href = files.html; $("open-report").hidden = false; }
    if (files.json) { $("open-json").href = files.json; $("open-json").hidden = false; }
    if (files.pdf) { $("open-pdf").href = files.pdf; $("open-pdf").hidden = false; }
  }

  function follow(job) {
    if (source) source.close();
    currentId = job.id;
    resetProgress(job);
    source = new EventSource("/api/scans/" + job.id + "/events");
    source.addEventListener("phase", function (e) {
      var ev = JSON.parse(e.data);
      $("prog-phase").textContent = ev.message;
      log("› " + esc(ev.message), "phase");
    });
    source.addEventListener("page", function (e) {
      var ev = JSON.parse(e.data);
      if (ev.rendered) jsCount++;
      var bad = !ev.status || ev.status >= 400;
      if (bad) errCount++;
      $("c-js").textContent = jsCount; $("c-err").textContent = errCount;
      setProgress(ev.done || 0, ev.queued || 0, ev.max_pages || job.max_pages);
      log('<span class="st ' + (bad ? "bad" : ev.status >= 300 ? "mid" : "ok") + '">' + esc(ev.status || "ERR") +
          "</span> " + (ev.rendered ? '<span class="js">JS</span> ' : "") + esc(ev.url));
    });
    source.addEventListener("done", function (e) {
      var ev = JSON.parse(e.data);
      $("prog-title").textContent = "Análisis completado";
      $("prog-phase").textContent = ev.output_dir ? "Guardado en " + ev.output_dir : "";
      $("bar-fill").style.width = "100%"; $("bar-fill").className = "done";
      $("cancel-btn").hidden = true;
      showFiles(ev.files || {});
      if (ev.summary && ev.summary.length) {
        $("summary").innerHTML = ev.summary.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("");
        $("summary").hidden = false;
      }
      log("✔ Reporte generado", "phase");
      finish();
    });
    source.addEventListener("error", function (e) {
      if (e.data) {
        var ev = JSON.parse(e.data);
        $("prog-title").textContent = "El escaneo terminó con error";
        $("prog-phase").textContent = ev.message;
        $("bar-fill").className = "fail";
        $("cancel-btn").hidden = true;
        log("✖ " + esc(ev.message), "bad");
        finish();
      } else if (source && source.readyState === EventSource.CLOSED) {
        finish();
      }
    });
  }

  function finish() {
    if (source) { source.close(); source = null; }
    startBtn.disabled = false;
    loadHistory();
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var input = $("url"), url = normalizeUrl(input.value);
    if (!url) { showError("Introduce una URL válida, por ejemplo https://ejemplo.com"); return; }
    input.value = url; showError("");
    var data = payload(); data.start_url = url;
    startBtn.disabled = true;
    fetch("/api/scans", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (!res.ok) {
          var d = res.body.detail;
          showError(typeof d === "string" ? d : "Parámetros no válidos: " + JSON.stringify(d));
          startBtn.disabled = false; return;
        }
        follow(res.body); loadHistory();
      })
      .catch(function (err) { showError("No se pudo iniciar: " + err); startBtn.disabled = false; });
  });

  $("cancel-btn").addEventListener("click", function () {
    if (currentId) fetch("/api/scans/" + currentId + "/cancel", { method: "POST" });
  });

  var STATUS = { "completado": "ok", "error": "bad", "cancelado": "mid", "ejecutando": "run", "pendiente": "run" };
  function loadHistory() {
    fetch("/api/scans").then(function (r) { return r.json(); }).then(function (jobs) {
      var tb = $("history");
      if (!jobs.length) { tb.innerHTML = '<tr><td colspan="5" class="muted">Sin escaneos todavía.</td></tr>'; return; }
      tb.innerHTML = jobs.map(function (j) {
        var links = [];
        if (j.files.html) links.push('<a href="' + esc(j.files.html) + '" target="_blank">HTML</a>');
        if (j.files.json) links.push('<a href="' + esc(j.files.json) + '" target="_blank">JSON</a>');
        if (j.files.pdf) links.push('<a href="' + esc(j.files.pdf) + '" target="_blank">PDF</a>');
        if (!j.files.html && (j.status === "ejecutando" || j.status === "pendiente"))
          links.push('<a href="#" data-follow="' + esc(j.id) + '">Ver progreso</a>');
        return "<tr><td>" + esc(j.created_at.replace("T", " ")) + '</td><td class="u">' + esc(j.url) +
          '</td><td><span class="pill ' + (STATUS[j.status] || "") + '">' + esc(j.status) + "</span></td><td>" +
          esc(j.pages_done) + "</td><td>" + (links.join(" · ") || "—") + "</td></tr>";
      }).join("");
      tb.querySelectorAll("[data-follow]").forEach(function (a) {
        a.addEventListener("click", function (ev) {
          ev.preventDefault();
          var job = jobs.filter(function (x) { return x.id === a.getAttribute("data-follow"); })[0];
          if (job) follow(job);
        });
      });
    }).catch(function () {});
  }
  $("refresh").addEventListener("click", loadHistory);
  loadHistory();
})();
