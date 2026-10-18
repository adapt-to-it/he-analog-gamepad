// HE Capture wizard. Classic script: protocol.js must load first and set window.HECapture.
(function () {
  'use strict';

  var HC = window.HECapture;
  var TOTAL_STEPS = 6;
  var FEATURE_TIMEOUT_MS = 2000;
  var LISTEN_MS = 5000;
  var ANALOG_WAIT_MS = 20000;
  var PRESS_HIGH = 60;
  var PRESS_LOW = 10;
  var ISSUE_URL = 'https://github.com/adapt-to-it/he-analog-gamepad/issues/new?title=';

  var screen = document.getElementById('screen');
  var progress = document.getElementById('progress');

  var state = null;         // CaptureState, created once protocol.js is loaded
  var hidDevices = [];      // HIDDevice objects, same order as state.devices
  var listened = new WeakSet();
  var timers = [];
  var token = 0;            // bumped on every screen change; stale async work checks it
  var analogOn = false;     // enable command sent and not yet turned off
  var sampleHook = null;    // receives parsed analog samples during steps 4-5
  var keyListener = null;   // capture-phase keydown while mapping
  var mapCtx = null;        // working data for step 5

  // ---------- DOM helpers ----------

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === false || v === null || v === undefined) return;
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k === 'value') node.value = v;
      else if (k === 'on') Object.keys(v).forEach(function (ev) { node.addEventListener(ev, v[ev]); });
      else node.setAttribute(k, v === true ? '' : v);
    });
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return node;
  }

  function btn(label, onClick, kind) {
    return el('button', { type: 'button', class: 'btn ' + (kind || 'primary'), text: label, on: { click: onClick } });
  }

  function para(text) {
    return el('p', { text: text });
  }

  function field(labelText, input) {
    return el('label', { class: 'field' }, [el('span', { text: labelText }), input]);
  }

  function messageBox() {
    return el('div', { class: 'message', role: 'status', hidden: true });
  }

  function setMessage(node, text, isError) {
    node.textContent = text;
    node.className = 'message' + (isError ? ' error' : '');
    node.hidden = !text;
  }

  function liveBar() {
    var fill = el('div', { class: 'fill' });
    var text = el('p', { class: 'live-text', text: 'Waiting for key data...' });
    return {
      node: el('div', { class: 'live' }, [el('div', { class: 'track' }, [fill]), text]),
      set: function (keyId, value) {
        // Raw travel is ~0-350 on the X68PRO HE; scale to 400 so other models fit too
        fill.style.width = Math.max(0, Math.min(100, value / 4)) + '%';
        text.textContent = 'Key ' + keyId + ': ' + Math.round(value);
      }
    };
  }

  // ---------- screen and timer management ----------

  function later(fn, ms) {
    var id = setTimeout(fn, ms);
    timers.push(id);
    return id;
  }

  function setKeyListener(on) {
    if (on && !keyListener) {
      keyListener = onMapKeydown;
      window.addEventListener('keydown', keyListener, true);
    } else if (!on && keyListener) {
      window.removeEventListener('keydown', keyListener, true);
      keyListener = null;
    }
  }

  function show(step, nodes) {
    token += 1;
    timers.forEach(function (id) { clearTimeout(id); });
    timers = [];
    setKeyListener(false);
    sampleHook = null;
    mapCtx = null;
    progress.hidden = !step;
    progress.textContent = step ? 'Step ' + step + ' of ' + TOTAL_STEPS : '';
    screen.replaceChildren.apply(screen, nodes);
  }

  // ---------- WebHID helpers ----------

  function withTimeout(promise, ms) {
    return new Promise(function (resolve, reject) {
      var id = setTimeout(function () {
        var err = new Error('No answer within ' + ms / 1000 + ' seconds');
        err.name = 'TimeoutError';
        reject(err);
      }, ms);
      promise.then(function (v) { clearTimeout(id); resolve(v); },
                   function (e) { clearTimeout(id); reject(e); });
    });
  }

  function explain(err) {
    var name = err && err.name;
    if (name === 'NotAllowedError') return 'Permission was not granted. Click Retry and pick your keyboard in the browser window.';
    if (name === 'NotFoundError') return 'No keyboard was picked. Click Retry and select your keyboard.';
    if (name === 'SecurityError') return 'The browser blocked access to the keyboard on this page. Try again in Chrome or Edge.';
    if (name === 'InvalidStateError' || name === 'NotReadableError') {
      return 'The keyboard is busy or was disconnected. Unplug it, plug it back in, then click Retry.';
    }
    return 'Something went wrong with the keyboard' + (err && err.message ? ': ' + err.message : '.') +
      ' Unplug it, plug it back in, then click Retry.';
  }

  function flatten(cols) {
    var out = [];
    (function walk(list) {
      list.forEach(function (c) {
        out.push(c);
        walk(c.children || []);
      });
    })(cols);
    return out;
  }

  function hasVendorFeature(device) {
    return flatten(device.collections).some(function (c) {
      return c.usagePage >= 0xFF00 && c.featureReports.length > 0;
    });
  }

  function attachInputListeners(devices) {
    devices.forEach(function (d) {
      if (listened.has(d)) return;
      listened.add(d);
      d.addEventListener('inputreport', onInputReport);
    });
  }

  function onInputReport(event) {
    var index = hidDevices.indexOf(event.target);
    var data = event.data;
    if (analogOn) state.analogTest.reportsSeen += 1;
    HC.pushRaw(state, { t: Date.now(), device: index, reportId: event.reportId, hex: HC.toHex(data) });
    if (sampleHook) {
      var sample = HC.parseAnalogReport(data);
      if (sample) sampleHook(sample);
    }
  }

  // Sends buildCommand(enable) to each device index; returns the indices that accepted it.
  async function sendToDevices(indices, enable) {
    var result = { ok: [], errors: [] };
    for (const i of indices) {
      try {
        await hidDevices[i].sendFeatureReport(0, HC.buildCommand(enable));
        result.ok.push(i);
      } catch (err) {
        result.errors.push('device ' + i + ': ' + (err && err.message ? err.message : String(err)));
      }
    }
    return result;
  }

  // Turns analog mode off on the devices that accepted it. Resolves to a list of error strings.
  function leaveAnalog() {
    if (!analogOn) return Promise.resolve([]);
    analogOn = false;
    return sendToDevices(state.analogTest.enabledOn, false).then(function (r) { return r.errors; });
  }

  // ---------- steps ----------

  // Step 1: about the keyboard.
  function stepAbout() {
    var modelInput = el('input', {
      type: 'text', id: 'model', maxlength: '80', autocomplete: 'off',
      placeholder: 'For example: HE65 Pro', value: state.userInfo.model || ''
    });
    var layoutSelect = el('select', { id: 'layout' }, HC.LAYOUTS.map(function (l) {
      return el('option', { value: l.id, text: l.label, selected: l.id === state.userInfo.layout });
    }));
    var notesInput = el('textarea', {
      id: 'notes', rows: '3', maxlength: '500',
      placeholder: 'Optional: anything unusual about this keyboard', value: state.userInfo.notes || ''
    });
    var msg = messageBox();

    function next() {
      var model = modelInput.value.trim();
      if (!model) {
        setMessage(msg, 'Please type the keyboard model.', true);
        return;
      }
      state.userInfo = { model: model, layout: layoutSelect.value, notes: notesInput.value.trim() };
      stepConnect();
    }

    show(1, [
      el('h2', { text: 'About this keyboard' }),
      para('Tell us which keyboard you are testing. The whole check takes about five minutes.'),
      field('Keyboard model', modelInput),
      field('Layout', layoutSelect),
      field('Notes (optional)', notesInput),
      msg,
      btn('Next', next)
    ]);
  }

  // Step 2: pick the keyboard in the browser dialog.
  function stepConnect() {
    var status = messageBox();
    var connectBtn = btn('Connect keyboard', connect);

    show(2, [
      el('h2', { text: 'Connect your keyboard' }),
      para('Click the button below. The browser will show a list of devices. Pick your keyboard and click Connect.'),
      para('If your keyboard does not appear in the list, unplug it, plug it back in, and click the button again.'),
      connectBtn,
      status
    ]);

    function fail(msg) {
      setMessage(status, msg, true);
      connectBtn.disabled = false;
      connectBtn.textContent = 'Retry';
    }

    async function connect() {
      var my = token;
      connectBtn.disabled = true;
      setMessage(status, 'Waiting for you to pick the keyboard...');
      try {
        var picked = await navigator.hid.requestDevice({ filters: [] });
        if (my !== token) return;
        if (picked.length === 0) return fail('No keyboard was picked. Click Retry and select your keyboard.');
        var chosen = picked[0];
        var all = await navigator.hid.getDevices();
        if (my !== token) return;
        var same = all.filter(function (d) {
          return d.vendorId === chosen.vendorId && d.productId === chosen.productId;
        });
        if (same.length === 0) {
          return fail('Your keyboard does not show up. Unplug it, plug it back in, then click Retry.');
        }
        for (const d of same) {
          if (!d.opened) await d.open();
          if (my !== token) return;
        }
        hidDevices = same;
        state.devices = same.map(function (d, i) { return HC.describeDevice(d, i); });
        attachInputListeners(same);
        showConnected();
      } catch (err) {
        if (my === token) fail(explain(err));
      }
    }
  }

  function showConnected() {
    var items = state.devices.map(function (d) {
      var features = flatten(d.collections).reduce(function (n, c) { return n + c.featureReports.length; }, 0);
      return el('li', null, [
        el('strong', { text: d.productName + ' (' + d.vid + ':' + d.pid + ')' }),
        el('span', { text: d.collections.length + ' HID collection(s), ' + features + ' feature report(s)' })
      ]);
    });
    show(2, [
      el('h2', { text: 'Keyboard connected' }),
      para('We found this:'),
      el('ul', { class: 'devices' }, items),
      btn('Continue', stepReadOnly)
    ]);
  }

  // Step 3: read-only checks, then listen for key presses.
  function stepReadOnly() {
    var status = messageBox();
    show(3, [
      el('h2', { text: 'Read-only check' }),
      para('We read a few status values from the keyboard. This does not change any setting.'),
      status
    ]);
    readFeatures(token, status);
  }

  async function readFeatures(my, status) {
    var jobs = [];
    state.devices.forEach(function (d, i) {
      flatten(d.collections).forEach(function (c) {
        c.featureReports.forEach(function (r) { jobs.push({ device: i, reportId: r.reportId }); });
      });
    });

    for (var n = 0; n < jobs.length; n++) {
      if (my !== token) return;
      var job = jobs[n];
      setMessage(status, 'Reading status ' + (n + 1) + ' of ' + jobs.length + '...');
      var read = { device: job.device, reportId: job.reportId };
      try {
        var data = await withTimeout(hidDevices[job.device].receiveFeatureReport(job.reportId), FEATURE_TIMEOUT_MS);
        read.hex = HC.toHex(data);
      } catch (err) {
        read.error = err && err.message ? err.message : String(err);
      }
      if (my !== token) return;
      state.featureReads.push(read);
    }

    if (my !== token) return;
    setMessage(status, 'Now press a few keys on the keyboard. Listening for 5 seconds...');
    later(stepAnalog, LISTEN_MS);
  }

  // Step 4: analog test. Only for HE keyboards, with explicit consent.
  function stepAnalog() {
    var known = state.devices.some(function (d) { return d.vendorId === HC.KNOWN_VENDOR_ID; });
    if (!known) {
      state.analogTest.attempted = false;
      show(4, [
        el('h2', { text: 'Analog test skipped' }),
        para('The analog test only works with HE keyboards. This tool does not send commands to other brands, so nothing was sent to your keyboard.'),
        btn('Continue to export', stepExport)
      ]);
      return;
    }

    var bar = liveBar();
    var status = messageBox();
    var consent = el('input', { type: 'checkbox' });
    var startBtn = btn('Start analog test', start);
    var toMapping = btn('Continue to mapping', stepMapping);
    var toExport = btn('Continue to export', stepExport);
    var finished = false;
    var waitId = null;

    toMapping.hidden = true;
    toExport.hidden = true;
    startBtn.disabled = true;
    consent.addEventListener('change', function () { startBtn.disabled = !consent.checked; });

    show(4, [
      el('h2', { text: 'Analog test' }),
      para('This sends one command that switches the keyboard into analog mode, so each key reports how far it is pressed. The command is switched off again when the test ends.'),
      el('label', { class: 'check' }, [consent, el('span', { text: 'I agree to run this test on my keyboard.' })]),
      startBtn,
      bar.node,
      status,
      toMapping,
      toExport
    ]);

    function onSample(sample) {
      bar.set(sample.keyId, sample.value);
      if (finished) return;
      finished = true;
      clearTimeout(waitId);
      state.analogTest.success = true;
      startBtn.disabled = true;
      setMessage(status, 'Analog data received. Continue to mapping.');
      toMapping.hidden = false;
    }

    function analogFailed(reason) {
      if (finished) return;
      finished = true;
      clearTimeout(waitId);
      state.analogTest.success = false;
      state.analogTest.error = state.analogTest.error ? state.analogTest.error + '; ' + reason : reason;
      startBtn.disabled = true;
      setMessage(status, reason + ' The standard analog mode did not respond. The advanced procedure is needed: see intercept_webhid.js in the repo.', true);
      toExport.hidden = false;
    }

    async function start() {
      var my = token;
      startBtn.disabled = true;
      setMessage(status, 'Turning on analog mode...');

      var eligible = [];
      state.devices.forEach(function (d, i) { if (hasVendorFeature(d)) eligible.push(i); });
      var result = await sendToDevices(eligible, true);

      if (my !== token) {
        if (result.ok.length) sendToDevices(result.ok, false);
        return;
      }

      state.analogTest.attempted = true;
      state.analogTest.enabledOn = result.ok;
      if (result.errors.length) state.analogTest.error = result.errors.join('; ');

      if (result.ok.length === 0) {
        if (result.errors.length) {
          setMessage(status, 'The keyboard did not accept the analog command: ' + result.errors.join('; ') + '. Click Retry.', true);
          startBtn.textContent = 'Retry';
          startBtn.disabled = false;
          return;
        }
        analogFailed('No vendor interface was found on this keyboard.');
        return;
      }

      analogOn = true;
      sampleHook = onSample;
      setMessage(status, 'Press W slowly all the way down, then release.');
      waitId = later(function () { analogFailed('No analog data arrived within 20 seconds.'); }, ANALOG_WAIT_MS);
    }
  }

  // Step 5: map one key at a time, in the order of the chosen layout.
  function stepMapping() {
    var layout = HC.LAYOUTS.find(function (l) { return l.id === state.userInfo.layout; }) || HC.LAYOUTS[0];
    var counter = el('p', { class: 'counter' });
    var prompt = el('p', { class: 'prompt' });
    var warn = messageBox();
    var bar = liveBar();
    var backBtn = btn('Back', undoKey, 'secondary');
    var skipBtn = btn('Skip', skipKey, 'secondary');
    var finishBtn = btn('Finish now', stepExport, 'secondary');

    show(5, [
      el('h2', { text: 'Press each key' }),
      para('Press the key shown below all the way down, then let go. Use Skip for keys you do not have.'),
      counter,
      prompt,
      warn,
      bar.node,
      el('div', { class: 'row' }, [backBtn, skipBtn, finishBtn])
    ]);

    mapCtx = {
      keys: layout.keys,
      history: [],
      armed: {},
      peakFor: {},
      ui: { counter: counter, prompt: prompt, warn: warn, bar: bar, backBtn: backBtn }
    };
    sampleHook = onMapSample;
    setKeyListener(true);
    refreshMapping();
  }

  function resetPress() {
    if (!mapCtx) return;
    mapCtx.armed = {};
    mapCtx.peakFor = {};
  }

  function refreshMapping() {
    var ctx = mapCtx;
    var done = ctx.history.length;
    if (done >= ctx.keys.length) {
      stepExport();
      return;
    }
    var ui = ctx.ui;
    ui.counter.textContent = done + ' / ' + ctx.keys.length;
    ui.prompt.textContent = ctx.keys[done];
    ui.backBtn.disabled = done === 0;
    setMessage(ui.warn, '');
  }

  function onMapSample(sample) {
    if (!mapCtx) return;
    var ctx = mapCtx;
    var k = sample.keyId;
    var v = sample.value;
    ctx.ui.bar.set(k, v);
    if (ctx.history.length >= ctx.keys.length) return;
    if (!(k in ctx.peakFor) || v > ctx.peakFor[k]) ctx.peakFor[k] = v;
    if (v > PRESS_HIGH) ctx.armed[k] = true;
    if (ctx.armed[k] && v < PRESS_LOW) assignKey(k);
  }

  function assignKey(keyId) {
    var ctx = mapCtx;
    var label = ctx.keys[ctx.history.length];
    var peak = ctx.peakFor[keyId];
    var owner = Object.keys(state.keyMapping).filter(function (l) {
      return state.keyMapping[l] === keyId;
    })[0];
    resetPress();
    if (owner) {
      setMessage(ctx.ui.warn, 'Key ' + keyId + ' is already used by ' + owner + '. Press again or Skip.', true);
      return;
    }
    state.keyMapping[label] = keyId;
    state.peaks[label] = peak;
    ctx.history.push({ label: label, kind: 'mapped' });
    refreshMapping();
  }

  function skipKey() {
    var ctx = mapCtx;
    if (!ctx || ctx.history.length >= ctx.keys.length) return;
    var label = ctx.keys[ctx.history.length];
    state.skipped.push(label);
    ctx.history.push({ label: label, kind: 'skipped' });
    resetPress();
    refreshMapping();
  }

  function undoKey() {
    var ctx = mapCtx;
    if (!ctx) return;
    var last = ctx.history.pop();
    if (!last) return;
    if (last.kind === 'mapped') {
      delete state.keyMapping[last.label];
      delete state.peaks[last.label];
    } else {
      var at = state.skipped.lastIndexOf(last.label);
      if (at >= 0) state.skipped.splice(at, 1);
    }
    delete state.browserCodes[last.label];
    resetPress();
    refreshMapping();
  }

  // Keys must not move focus or activate page controls while mapping.
  function onMapKeydown(event) {
    event.preventDefault();
    event.stopPropagation();
    if (!mapCtx || event.repeat || mapCtx.history.length >= mapCtx.keys.length) return;
    if (event.code) state.browserCodes[mapCtx.keys[mapCtx.history.length]] = event.code;
  }

  // Step 6: turn analog mode off, then export.
  function stepExport() {
    var offPromise = leaveAnalog();
    var status = messageBox();
    var summaryBox = el('textarea', { class: 'summary', rows: '8', readonly: true, hidden: true });

    function downloadJson() {
      var data = HC.buildExport(state, navigator.userAgent, new Date());
      var name = exportName();
      saveFile(name, JSON.stringify(data, null, 2));
      setMessage(status, 'Saved ' + name + '.');
    }

    function downloadKeyConfig() {
      saveFile('key_config.json', JSON.stringify(HC.buildKeyConfig(state), null, 2));
      setMessage(status, 'Saved key_config.json.');
    }

    async function copySummary() {
      var text = HC.buildIssueSummary(state);
      try {
        await navigator.clipboard.writeText(text);
        setMessage(status, 'Summary copied. Paste it into the GitHub issue.');
      } catch (err) {
        summaryBox.value = text;
        summaryBox.hidden = false;
        summaryBox.select();
        setMessage(status, 'The browser blocked copying. Select the text below and copy it by hand.', true);
      }
    }

    function openIssue() {
      var url = ISSUE_URL + encodeURIComponent('Capture: ' + state.userInfo.model);
      window.open(url, '_blank', 'noopener');
      setMessage(status, 'GitHub opened in a new tab. Paste the summary, attach the JSON.');
    }

    var buttons = [btn('Download JSON', downloadJson)];
    if (Object.keys(state.keyMapping).length > 0) {
      buttons.push(btn('Download key_config.json', downloadKeyConfig));
    }
    buttons.push(btn('Copy summary', copySummary, 'secondary'));
    buttons.push(btn('Open GitHub issue', openIssue, 'secondary'));

    show(6, [
      el('h2', { text: 'Export' }),
      para('Nothing is sent automatically. Save the files, then send them to us.'),
      para('Next: click Copy summary, then Open GitHub issue. On the GitHub page, paste the summary, attach the JSON.')
    ].concat(buttons, [status, summaryBox]));

    offPromise.then(function (errors) {
      if (errors.length) {
        setMessage(status, 'Could not switch analog mode off: ' + errors.join('; ') + '. Unplug and reconnect the keyboard.', true);
      }
    });
  }

  function exportName() {
    var d = new Date();
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    var stamp = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    var slug = state.userInfo.model.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'keyboard';
    return 'he-capture-' + slug + '-' + stamp + '.json';
  }

  function saveFile(name, text) {
    var url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    var link = el('a', { href: url, download: name });
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  // ---------- start ----------

  function init() {
    if (!navigator.hid) {
      show(0, [
        el('h2', { text: 'Use Chrome or Edge on a computer' }),
        para('This capture needs WebHID, which only Chrome and Edge support.')
      ]);
      return;
    }
    if (!HC) {
      show(0, [
        el('h2', { text: 'Files missing' }),
        el('div', { class: 'message error', role: 'alert', text: 'protocol.js did not load. Keep all files of tools/capture in the same folder and reload the page.' })
      ]);
      return;
    }
    state = HC.newState();
    window.addEventListener('pagehide', function () { leaveAnalog(); });
    stepAbout();
  }

  init();
})();
