// Pure logic for the HE capture wizard. Classic script, no ES modules.
// Browser: sets window.HECapture. Node (tests): module.exports.
// Types live in protocol.d.ts.

(function () {
  'use strict';

  var KNOWN_VENDOR_ID = 0x3151;
  var MAX_RAW_LOG = 2000;
  var PREFIX = 0x1b;
  var REPORT_ID = 5;
  var DEFAULT_ANALOG_MAX = 350;

  var F_KEYS = [];
  for (var i = 1; i <= 12; i++) F_KEYS.push('F' + i);

  // Physical rows, left to right. Flattened they give the press order.
  var ROWS_65 = [
    ['ESC', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=', 'BKSP', 'DEL'],
    ['TAB', 'Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P', '[', ']', '\\', 'PGUP'],
    ['CAPS', 'A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', ';', "'", 'ENTER', 'PGDN'],
    ['LSHIFT', 'Z', 'X', 'C', 'V', 'B', 'N', 'M', ',', '.', '/', 'RSHIFT', 'UP'],
    ['LCTRL', 'WIN', 'LALT', 'SPACE', 'RALT', 'FN', 'LEFT', 'DOWN', 'RIGHT']
  ];

  // 75%: F1-F12 after ESC, HOME and END after DEL.
  var ROWS_75 = [
    ['ESC'].concat(F_KEYS, ROWS_65[0].slice(1), ['HOME', 'END']),
    ROWS_65[1],
    ROWS_65[2],
    ROWS_65[3],
    ROWS_65[4]
  ];

  // TKL (ANSI 87): F-row with PRTSC SCRLK PAUSE, INS HOME PGUP / DEL END PGDN, RCTRL MENU.
  var ROWS_TKL = [
    ['ESC'].concat(F_KEYS, ['PRTSC', 'SCRLK', 'PAUSE']),
    ['GRAVE', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=', 'BKSP', 'INS', 'HOME', 'PGUP'],
    ['TAB', 'Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P', '[', ']', '\\', 'DEL', 'END', 'PGDN'],
    ['CAPS', 'A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', ';', "'", 'ENTER'],
    ['LSHIFT', 'Z', 'X', 'C', 'V', 'B', 'N', 'M', ',', '.', '/', 'RSHIFT', 'UP'],
    ['LCTRL', 'WIN', 'LALT', 'SPACE', 'RALT', 'FN', 'RCTRL', 'MENU', 'LEFT', 'DOWN', 'RIGHT']
  ];

  // Full (ANSI 104): TKL plus the numpad block on the right.
  var NUMPAD = [
    ['NUMLK', 'NUM/', 'NUM*', 'NUM-'],
    ['NUM7', 'NUM8', 'NUM9', 'NUM+'],
    ['NUM4', 'NUM5', 'NUM6'],
    ['NUM1', 'NUM2', 'NUM3', 'NUMENTER'],
    ['NUM0', 'NUM.']
  ];
  var ROWS_FULL = ROWS_TKL.map(function (row, idx) {
    return idx === 0 ? row : row.concat(NUMPAD[idx - 1]);
  });

  function flat(rows) {
    return [].concat.apply([], rows);
  }

  function hexId(n) {
    return '0x' + n.toString(16).toUpperCase().padStart(4, '0');
  }

  function layout(id, name, rows) {
    var keys = flat(rows);
    return { id: id, label: name + ' (' + keys.length + ' keys)', keys: keys };
  }

  var LAYOUTS = [
    layout('65', '65%', ROWS_65),
    layout('75', '75%', ROWS_75),
    layout('tkl', 'TKL', ROWS_TKL),
    layout('full', 'Full', ROWS_FULL)
  ];

  function buildCommand(enable) {
    var cmd = new Uint8Array(64);
    var flag = enable ? 1 : 0;
    cmd[0] = PREFIX;
    cmd[1] = flag;
    cmd[7] = 0xe4 - flag;
    return cmd;
  }

  function describeReports(list) {
    return (list || []).map(function (r) {
      return {
        reportId: r.reportId,
        items: (r.items || []).map(function (it) {
          return {
            usagePage: it.usagePage,
            usages: Array.from(it.usages || []),
            reportSize: it.reportSize,
            reportCount: it.reportCount
          };
        })
      };
    });
  }

  function describeCollection(c) {
    return {
      usagePage: c.usagePage,
      usage: c.usage,
      type: c.type,
      inputReports: describeReports(c.inputReports),
      outputReports: describeReports(c.outputReports),
      featureReports: describeReports(c.featureReports),
      children: (c.children || []).map(describeCollection)
    };
  }

  function describeDevice(device, index) {
    return {
      index: index,
      vendorId: device.vendorId,
      productId: device.productId,
      productName: device.productName,
      vid: hexId(device.vendorId),
      pid: hexId(device.productId),
      collections: (device.collections || []).map(describeCollection)
    };
  }

  function toHex(data) {
    var bytes = ArrayBuffer.isView(data)
      ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength)
      : new Uint8Array(data);
    return Array.from(bytes, function (b) {
      return b.toString(16).padStart(2, '0');
    }).join(' ');
  }

  function parseAnalogReport(data) {
    if (!data || data.byteLength < 4 || data.getUint8(0) !== PREFIX) return null;
    return {
      keyId: data.getUint8(3),
      value: data.getUint8(1) + data.getUint8(2) * 256
    };
  }

  function pushRaw(state, entry) {
    if (state.rawLog.length >= MAX_RAW_LOG) {
      state.rawDropped += 1;
      return;
    }
    state.rawLog.push(entry);
  }

  function newState() {
    return {
      userInfo: { model: '', layout: '', notes: '' },
      devices: [],
      featureReads: [],
      analogTest: { attempted: false, success: false, enabledOn: [], reportsSeen: 0 },
      rawLog: [],
      keyMapping: {},
      peaks: {},
      skipped: [],
      browserCodes: {},
      rawDropped: 0
    };
  }

  function localTimestamp(d) {
    var p = function (n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' +
      p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }

  function buildKeyConfig(state) {
    var dev = state.devices[0];
    var peakValues = Object.values(state.peaks);
    var reverse = {};
    Object.keys(state.keyMapping).forEach(function (label) {
      reverse[String(state.keyMapping[label])] = label;
    });
    return {
      device: dev
        ? { name: dev.productName, vid: dev.vid, pid: dev.pid, vid_int: dev.vendorId, pid_int: dev.productId }
        : { name: null, vid: null, pid: null, vid_int: null, pid_int: null },
      protocol: {
        enable_cmd: Array.from(buildCommand(true)),
        disable_cmd: Array.from(buildCommand(false)),
        report_id: REPORT_ID,
        prefix: PREFIX,
        analog_byte_lo: 2,
        analog_byte_hi: 3,
        key_id_byte: 4,
        analog_max: peakValues.length ? Math.max.apply(null, peakValues) : DEFAULT_ANALOG_MAX,
        note: 'pywinusb byte indices (byte[0]=report_id)'
      },
      key_mapping: Object.assign({}, state.keyMapping),
      reverse_mapping: reverse,
      unmapped_keys: state.skipped.slice(),
      timestamp: localTimestamp(new Date())
    };
  }

  function buildExport(state, userAgent, now) {
    return Object.assign({
      tool: 'he-capture',
      version: 1,
      created_at: now.toISOString(),
      user_agent: userAgent
    }, state, { key_config: buildKeyConfig(state) });
  }

  // Escapes user text for markdown (tables included) and flattens line breaks.
  function md(s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/[\\`*_\[\]<>|]/g, '\\$&')
      .replace(/\s*\r?\n\s*/g, ' ');
  }

  function flattenCollections(list, out) {
    out = out || [];
    list.forEach(function (c) {
      out.push(c);
      flattenCollections(c.children || [], out);
    });
    return out;
  }

  function reportIds(list) {
    return (list || []).map(function (r) { return r.reportId; }).join(', ') || '-';
  }

  function hexUsage(n) {
    return '0x' + n.toString(16).toUpperCase().padStart(4, '0');
  }

  function buildIssueSummary(state) {
    var u = state.userInfo;
    var lines = [];
    lines.push('## HE Analog Gamepad capture report', '');
    lines.push('- Model: ' + (md(u.model) || 'n/a'));
    lines.push('- Layout: ' + (md(u.layout) || 'n/a'));
    if (u.notes) lines.push('- Notes: ' + md(u.notes));

    lines.push('', '### Devices', '');
    if (state.devices.length === 0) lines.push('No devices recorded.');
    state.devices.forEach(function (d) {
      lines.push('- #' + d.index + ': ' + md(d.productName) + ' (VID ' + d.vid + ', PID ' + d.pid + ')');
    });

    lines.push('', '### HID collections', '');
    var rows = [];
    state.devices.forEach(function (d) {
      flattenCollections(d.collections).forEach(function (c) {
        rows.push('| #' + d.index + ' ' + md(d.productName) + ' | ' + hexUsage(c.usagePage) + ' | ' +
          hexUsage(c.usage) + ' | ' + reportIds(c.inputReports) + ' | ' + reportIds(c.featureReports) + ' |');
      });
    });
    if (rows.length === 0) {
      lines.push('No collections recorded.');
    } else {
      lines.push('| Device | Usage page | Usage | Input report IDs | Feature report IDs |');
      lines.push('| --- | --- | --- | --- | --- |');
      rows.forEach(function (r) { lines.push(r); });
    }

    var t = state.analogTest;
    var verdict = !t.attempted ? 'not attempted' : (t.success ? 'success' : 'failed');
    lines.push('', '### Analog test', '');
    lines.push('- Result: ' + verdict);
    lines.push('- Enabled on devices: ' + (t.enabledOn.join(', ') || 'none'));
    lines.push('- Reports seen: ' + t.reportsSeen);
    if (t.error) lines.push('- Error: ' + md(t.error));

    var mapped = Object.keys(state.keyMapping);
    var peakValues = Object.values(state.peaks);
    lines.push('', '### Key mapping', '');
    lines.push('- Mapped (' + mapped.length + '): ' + (mapped.map(md).join(', ') || 'none'));
    lines.push('- Skipped (' + state.skipped.length + '): ' + (state.skipped.map(md).join(', ') || 'none'));
    lines.push('- Peak max: ' + (peakValues.length ? Math.max.apply(null, peakValues) : 'n/a'));

    lines.push('', 'Please attach the downloaded JSON file to this issue.');
    return lines.join('\n');
  }

  var API = {
    KNOWN_VENDOR_ID: KNOWN_VENDOR_ID,
    MAX_RAW_LOG: MAX_RAW_LOG,
    LAYOUTS: LAYOUTS,
    buildCommand: buildCommand,
    describeDevice: describeDevice,
    toHex: toHex,
    parseAnalogReport: parseAnalogReport,
    pushRaw: pushRaw,
    newState: newState,
    buildKeyConfig: buildKeyConfig,
    buildExport: buildExport,
    buildIssueSummary: buildIssueSummary
  };

  if (typeof module !== 'undefined') module.exports = API;
  else window.HECapture = API;
})();
