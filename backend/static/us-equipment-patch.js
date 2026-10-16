(function () {
  "use strict";
  if (window.__pprUsPatch) return;
  window.__pprUsPatch = true;

  function typeBadgeClass(t) {
    if (t === "us" || t === "cod") return "bg-blue-50 text-blue-800 border border-blue-100";
    if (t === "camera_integration" || t === "ovn") return "bg-violet-50 text-violet-800 border border-violet-100";
    if (["core_router","core_switch","access_switch","edge_router","wifi_controller","server","ups","network"].includes(t))
      return "bg-slate-100 text-slate-700 border border-slate-200";
    if (t === "voles" || t === "sip") return "bg-cyan-50 text-cyan-800 border border-cyan-100";
    return "bg-slate-100 text-slate-600 border border-slate-200";
  }
  function statusBadge(status) {
    var s = status || "active";
    var map = {
      active: "bg-emerald-50 text-emerald-800 border border-emerald-100",
      relocated: "bg-amber-50 text-amber-800 border border-amber-100",
      decommissioned: "bg-slate-100 text-slate-500 border border-slate-200",
      inactive: "bg-slate-100 text-slate-500 border border-slate-200"
    };
    return '<span class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ' + (map[s] || map.active) + '">' + s + "</span>";
  }
  window.typeBadgeClass = typeBadgeClass;
  window.statusBadge = statusBadge;

  function installModalPatch() {
    if (typeof window.openObjectModal !== "function") return false;
    if (window.openObjectModal.__usPatched) return true;
    var orig = window.openObjectModal;
    window.openObjectModal = async function (objectId) {
      await orig.apply(this, arguments);
      var form = document.getElementById("object-form");
      if (!form) return;
      var typeSelect = form.querySelector('select[name="object_type"]');
      if (!typeSelect) return;

      if (document.getElementById("obj-us-equipment")) {
        sync();
        return;
      }

      var camerasGrid = null;
      form.querySelectorAll("label").forEach(function (lab) {
        if ((lab.textContent || "").indexOf("Кол-во камер") >= 0) {
          camerasGrid = lab.closest(".grid") || (lab.parentElement && lab.parentElement.parentElement);
        }
      });

      var usBlock = document.createElement("div");
      usBlock.id = "obj-us-equipment";
      usBlock.className = "hidden rounded-xl border border-blue-100 bg-blue-50/40 p-3 space-y-3";
      usBlock.innerHTML =
        '<div class="text-xs font-semibold uppercase tracking-wide text-blue-800">Оборудование узла связи</div>' +
        '<div class="grid grid-cols-3 gap-3">' +
        '<div><label class="block text-slate-600 mb-1 text-xs">Коммутаторов</label>' +
        '<input name="switches_count" type="number" min="0" value="0" class="w-full border rounded-lg px-3 py-2"></div>' +
        '<div><label class="block text-slate-600 mb-1 text-xs">Роутеров</label>' +
        '<input name="routers_count" type="number" min="0" value="0" class="w-full border rounded-lg px-3 py-2"></div>' +
        '<div><label class="block text-slate-600 mb-1 text-xs">Дочерних объектов</label>' +
        '<input name="children_count" type="number" min="0" value="0" class="w-full border rounded-lg px-3 py-2"></div>' +
        "</div>";

      if (camerasGrid && camerasGrid.parentNode) {
        camerasGrid.parentNode.insertBefore(usBlock, camerasGrid.nextSibling);
      } else {
        var btnRow = form.querySelector(".flex.justify-between");
        if (btnRow) form.insertBefore(usBlock, btnRow);
        else form.appendChild(usBlock);
      }

      if (objectId) {
        try {
          var obj = await api("/api/objects/" + objectId);
          var s = form.querySelector('[name="switches_count"]');
          var r = form.querySelector('[name="routers_count"]');
          var c = form.querySelector('[name="children_count"]');
          if (s) s.value = obj.switches_count || 0;
          if (r) r.value = obj.routers_count || 0;
          if (c) c.value = obj.children_count || 0;
        } catch (e) {}
      }

      function sync() {
        var isUs = typeSelect.value === "us";
        usBlock.classList.toggle("hidden", !isUs);
        if (camerasGrid) camerasGrid.classList.toggle("opacity-60", isUs);
      }
      typeSelect.addEventListener("change", sync);
      sync();

      form.onsubmit = async function (e) {
        e.preventDefault();
        var fd = new FormData(form);
        var body = {
          code: (fd.get("code") || "").trim(),
          name: fd.get("name") || null,
          address: fd.get("address") || null,
          object_type: fd.get("object_type"),
          cameras_count: parseInt(fd.get("cameras_count") || "0", 10) || 0,
          switches_count: parseInt(fd.get("switches_count") || "0", 10) || 0,
          routers_count: parseInt(fd.get("routers_count") || "0", 10) || 0,
          children_count: parseInt(fd.get("children_count") || "0", 10) || 0,
          status: fd.get("status") || "active",
          responsible_default: fd.get("responsible_default") || null,
          notes: fd.get("notes") || null
        };
        try {
          if (objectId) {
            await api("/api/objects/" + objectId, { method: "PATCH", body: JSON.stringify(body) });
          } else {
            await api("/api/objects", { method: "POST", body: JSON.stringify(body) });
          }
          closeModal();
          loadPage("objects");
        } catch (err) {
          if (window.NotificationController) NotificationController.error(err.message);
          else alert(err.message);
        }
      };
    };
    window.openObjectModal.__usPatched = true;
    return true;
  }

  function enhanceObjectsTable() {
    var table = document.querySelector("#content table");
    if (!table) return;
    table.querySelectorAll("tbody tr").forEach(function (tr) {
      var cells = tr.querySelectorAll("td");
      if (cells.length < 6) return;
      var typeCell = cells[2];
      var typeText = (typeCell.textContent || "").trim();
      if (typeText.indexOf("УС") >= 0 && !typeCell.querySelector(".rounded-full")) {
        typeCell.innerHTML = '<span class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ' +
          typeBadgeClass("us") + '">' + typeText + "</span>";
      }
      var statusCell = cells[5];
      var st = (statusCell.textContent || "").trim();
      if (st && !statusCell.querySelector(".rounded-full")) {
        statusCell.innerHTML = statusBadge(st);
      }
    });
  }

  var tries = 0;
  var timer = setInterval(function () {
    tries++;
    installModalPatch();
    enhanceObjectsTable();
    if (tries > 40) clearInterval(timer);
  }, 500);

  var obs = new MutationObserver(function () {
    installModalPatch();
    enhanceObjectsTable();
  });
  setTimeout(function () {
    var c = document.getElementById("content");
    if (c) obs.observe(c, { childList: true, subtree: true });
  }, 1000);

  console.info("[ppr] US equipment UI patch installed");
})();
