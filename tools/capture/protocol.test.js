'use strict';

const test = require('node:test');
const assert = require('node:assert');
const API = require('./protocol.js');

// Copy of KEYBOARD_LAYOUT in key_mapper_gui.py, one array per row.
const KEYBOARD_LAYOUT_ROWS = [
  ['ESC', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=', 'BKSP', 'DEL'],
  ['TAB', 'Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P', '[', ']', '\\', 'PGUP'],
  ['CAPS', 'A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', ';', "'", 'ENTER', 'PGDN'],
  ['LSHIFT', 'Z', 'X', 'C', 'V', 'B', 'N', 'M', ',', '.', '/', 'RSHIFT', 'UP'],
  ['LCTRL', 'WIN', 'LALT', 'SPACE', 'RALT', 'FN', 'LEFT', 'DOWN', 'RIGHT'],
];

function layoutById(id) {
  const layout = API.LAYOUTS.find((l) => l.id === id);
  assert.ok(layout, `layout ${id} missing`);
  return layout;
}

function fakeDevice() {
  return {
    vendorId: 0x3151,
    productId: 0x5030,
    productName: 'X68PRO HE',
    collections: [
      {
        usagePage: 0x01,
        usage: 0x06,
        type: 1,
        inputReports: [
          { reportId: 5, items: [{ usagePage: 0x07, usages: [4], reportSize: 8, reportCount: 1 }] },
        ],
        outputReports: [],
        featureReports: [],
        children: [
          {
            usagePage: 0xff00,
            usage: 0x01,
            type: 1,
            inputReports: [],
            outputReports: [],
            featureReports: [{ reportId: 0, items: [] }],
            children: [],
          },
        ],
      },
    ],
  };
}

test('buildCommand enable sets flag and checksum 0xE3', () => {
  const cmd = API.buildCommand(true);
  assert.ok(cmd instanceof Uint8Array);
  assert.strictEqual(cmd.length, 64);
  assert.strictEqual(cmd[0], 0x1b);
  assert.strictEqual(cmd[1], 1);
  assert.strictEqual(cmd[7], 0xe3);
  for (let i = 8; i < 64; i++) assert.strictEqual(cmd[i], 0);
});

test('buildCommand disable clears flag and checksum 0xE4', () => {
  const cmd = API.buildCommand(false);
  assert.strictEqual(cmd.length, 64);
  assert.strictEqual(cmd[0], 0x1b);
  assert.strictEqual(cmd[1], 0);
  assert.strictEqual(cmd[7], 0xe4);
});

test('parseAnalogReport reads a valid report', () => {
  const data = new DataView(new Uint8Array([0x1b, 0x2c, 0x01, 7]).buffer);
  assert.deepStrictEqual(API.parseAnalogReport(data), { keyId: 7, value: 300 });
});

test('parseAnalogReport returns null on wrong prefix', () => {
  const data = new DataView(new Uint8Array([0x1c, 0x2c, 0x01, 7]).buffer);
  assert.strictEqual(API.parseAnalogReport(data), null);
});

test('parseAnalogReport returns null when shorter than 4 bytes', () => {
  const data = new DataView(new Uint8Array([0x1b, 0x2c, 0x01]).buffer);
  assert.strictEqual(API.parseAnalogReport(data), null);
});

test('toHex prints lowercase space-separated bytes', () => {
  assert.strictEqual(API.toHex(new Uint8Array([0x1b, 0x05, 0x01])), '1b 05 01');
});

test('describeDevice copies identity and nested collections', () => {
  const info = API.describeDevice(fakeDevice(), 3);
  assert.strictEqual(info.index, 3);
  assert.strictEqual(info.vid, '0x3151');
  assert.strictEqual(info.pid, '0x5030');
  assert.strictEqual(info.productName, 'X68PRO HE');
  assert.strictEqual(info.collections.length, 1);
  const top = info.collections[0];
  assert.strictEqual(top.usagePage, 0x01);
  assert.strictEqual(top.inputReports[0].reportId, 5);
  assert.deepStrictEqual(top.inputReports[0].items[0].usages, [4]);
  assert.strictEqual(top.children.length, 1);
  assert.strictEqual(top.children[0].usagePage, 0xff00);
  assert.strictEqual(top.children[0].featureReports[0].reportId, 0);
});

test('layout 65 matches KEYBOARD_LAYOUT flattened', () => {
  const expected = [].concat(...KEYBOARD_LAYOUT_ROWS);
  assert.deepStrictEqual(layoutById('65').keys, expected);
});

test('every layout has ids and no duplicate keys', () => {
  assert.deepStrictEqual(
    API.LAYOUTS.map((l) => l.id),
    ['65', '75', 'tkl', 'full']
  );
  for (const layout of API.LAYOUTS) {
    assert.strictEqual(
      new Set(layout.keys).size,
      layout.keys.length,
      `duplicate key in layout ${layout.id}`
    );
  }
});

test('larger layouts contain every 65 key', () => {
  const base = layoutById('65').keys;
  for (const id of ['75', 'tkl', 'full']) {
    const keys = new Set(layoutById(id).keys);
    for (const k of base) assert.ok(keys.has(k), `${k} missing from ${id}`);
  }
});

test('buildKeyConfig maps W to 14 and reports peak 340', () => {
  const state = API.newState();
  state.keyMapping.W = 14;
  state.peaks.W = 340;
  const cfg = API.buildKeyConfig(state);
  assert.strictEqual(cfg.key_mapping.W, 14);
  assert.deepStrictEqual(cfg.reverse_mapping, { 14: 'W' });
  assert.strictEqual(cfg.protocol.analog_max, 340);
  assert.strictEqual(cfg.protocol.report_id, 5);
  assert.strictEqual(cfg.device.name, null);
});

test('buildKeyConfig defaults analog_max to 350 without peaks', () => {
  const cfg = API.buildKeyConfig(API.newState());
  assert.strictEqual(cfg.protocol.analog_max, 350);
});

test('pushRaw keeps MAX_RAW_LOG entries and counts the dropped ones', () => {
  const state = API.newState();
  const entry = { t: 0, device: 0, reportId: 5, hex: '1b' };
  for (let i = 0; i < API.MAX_RAW_LOG; i++) API.pushRaw(state, entry);
  assert.strictEqual(state.rawLog.length, API.MAX_RAW_LOG);
  assert.strictEqual(state.rawDropped, 0);
  API.pushRaw(state, { t: 1, device: 0, reportId: 5, hex: '2b' });
  assert.strictEqual(state.rawLog.length, API.MAX_RAW_LOG);
  assert.strictEqual(state.rawLog[API.MAX_RAW_LOG - 1].hex, '1b');
  assert.strictEqual(state.rawDropped, 1);
});
