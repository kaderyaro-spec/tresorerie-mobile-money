/* Moteur hors-ligne — file d'attente locale + synchronisation automatique.
 *
 * Principe : quand une saisie ne peut pas atteindre le serveur (pas de réseau,
 * serveur endormi, coupure), elle est stockée dans localStorage puis renvoyée
 * automatiquement dès que possible. Le serveur déduplique via client_uid.
 */
(function () {
  var KEY = "opQueue";

  function readQueue() {
    try { return JSON.parse(localStorage.getItem(KEY) || "[]"); }
    catch (e) { return []; }
  }
  function writeQueue(q) {
    localStorage.setItem(KEY, JSON.stringify(q));
    updateBanner();
  }

  function updateBanner() {
    var b = document.getElementById("offline-banner");
    if (!b) return;
    var n = readQueue().length;
    if (n > 0) {
      b.textContent = "⏳ " + n + " opération(s) en attente de synchronisation";
      b.hidden = false;
    } else {
      b.hidden = true;
    }
  }

  function newUid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "uid-" + Date.now() + "-" + Math.random().toString(36).slice(2);
  }

  function nowStr() {
    var d = new Date(), p = function (x) { return String(x).padStart(2, "0"); };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
           " " + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }

  /* Ajoute une opération à la file locale (appelé quand le réseau échoue). */
  function enqueue(op) {
    var q = readQueue();
    q.push(op);
    writeQueue(q);
  }

  var syncing = false;
  function sync() {
    if (syncing) return;
    var q = readQueue();
    if (q.length === 0) { updateBanner(); return; }
    syncing = true;
    fetch("/api/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
      body: JSON.stringify({ ops: q })
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (res) {
        if (!res.ok) return;
        var done = {};
        (res.accepted || []).forEach(function (u) { done[u] = 1; });
        // Les opérations rejetées (données invalides) sont retirées aussi :
        // les garder bloquerait la file pour toujours.
        (res.rejected || []).forEach(function (r) { done[r.uid] = 1; });
        var rest = readQueue().filter(function (op) { return !done[op.uid]; });
        writeQueue(rest);
        if ((res.accepted || []).length > 0 &&
            location.pathname.indexOf("/dashboard") === 0) {
          location.reload();   // rafraîchit les soldes après synchronisation
        }
      })
      .catch(function () { /* toujours hors-ligne : on réessaiera */ })
      .finally(function () { syncing = false; updateBanner(); });
  }

  /* Soumission « réseau d'abord, file locale en secours » d'un formulaire
     de saisie (transaction / réappro). */
  function submitOperation(form, redirectTo) {
    var fd = new FormData(form);
    var uid = newUid();
    fd.set("client_uid", uid);

    var op = {
      uid: uid,
      type: fd.get("type"),
      wallet_id: fd.get("wallet_id") || null,
      amount: fd.get("amount"),
      commission: fd.get("commission") || 0,
      created_at: nowStr()
    };

    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, 6000);

    fetch(form.action || location.pathname, {
      method: "POST",
      body: fd,
      headers: { "X-Requested-With": "fetch" },
      signal: ctrl.signal
    })
      .then(function (r) {
        clearTimeout(timer);
        if (r.status === 400) {
          return r.json().then(function (j) {
            alert(j.error || "Saisie invalide.");
            throw "invalid";
          });
        }
        if (!r.ok) throw "server";
        return r.json();
      })
      .then(function (j) {
        location.href = redirectTo + "?undo=" + (j.undo || "");
      })
      .catch(function (e) {
        clearTimeout(timer);
        if (e === "invalid") return;       // erreur de saisie : on reste sur place
        enqueue(op);                        // réseau KO : on garde l'opération
        location.href = redirectTo + "?offline=1";
      });
  }

  // Exposé pour les pages de saisie
  window.AppOffline = { submitOperation: submitOperation, sync: sync };

  /* -----------------------------------------------------------------------
   * Mise en forme automatique des saisies (présentation uniforme partout) :
   *  - montants  → séparateur de milliers « 5 000 »   (champs .js-money)
   *  - téléphone → groupes de 2 « 07 10 10 10 10 »     (champs .js-phone)
   * Le serveur ne garde que les chiffres : les espaces n'ont aucun impact.
   * --------------------------------------------------------------------- */
  function groupMoney(value) {
    var d = String(value).replace(/\D/g, "");
    if (!d) return "";
    return d.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }
  function groupPhone(value) {
    var d = String(value).replace(/\D/g, "").slice(0, 10);
    return d.replace(/(\d{2})(?=\d)/g, "$1 ");
  }
  function attachFormatter(el, formatter) {
    el.addEventListener("input", function () {
      el.value = formatter(el.value);
      try { el.setSelectionRange(el.value.length, el.value.length); } catch (e) {}
    });
    if (el.value) el.value = formatter(el.value);   // mise en forme initiale
  }
  function initFormatters() {
    document.querySelectorAll(".js-money").forEach(function (el) {
      attachFormatter(el, groupMoney);
    });
    document.querySelectorAll(".js-phone").forEach(function (el) {
      attachFormatter(el, groupPhone);
    });
  }

  // Synchronisation : au chargement, au retour du réseau, et toutes les 30 s
  window.addEventListener("online", sync);
  document.addEventListener("DOMContentLoaded", function () {
    updateBanner();
    initFormatters();
    sync();
    setInterval(sync, 30000);
  });
})();
