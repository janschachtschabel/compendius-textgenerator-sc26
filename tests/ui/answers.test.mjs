// Every view of the review page with answers as the endpoints really give them (D66; audit 2026-09-29, U4): whatever
// the answer holds shows, and no field the page reads in vain leaves "undefined" in the text.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { MODES, NAMES, OPTIONS, shown } from './saved_answers.mjs';
import { PROFILE_ABOUT, PROFILE_NAMES } from '../../app/ui/static/texts.mjs';

test('every profile of the server has a name, and words for what it does at every endpoint', () => {
  for (const { id } of OPTIONS.presets) {
    assert.ok(PROFILE_NAMES[id], `the name of ${id}`);
    for (const mode of MODES) assert.ok(PROFILE_ABOUT[mode]?.[id], `${id} at ${mode}`);
  }
});

test('both writing profiles are offered for groups and topics with an aspect (M52)', () => {
  // Review 2026-10-02: since D72 best-quality-generated writes about the topic as asked too - fit 4.7 for a group and
  // 4.2 for an aspect - but the page sent it to topics with an article of their own and called the other the only one
  const { compendium } = PROFILE_ABOUT;
  assert.match(compendium['best-quality-generated'], /Sammelthemen/);
  assert.doesNotMatch(compendium['best-quality-generated'], /für Themen mit eigenem Artikel/);
  assert.doesNotMatch(compendium['best-coverage-generated'], /nur dieses Profil/);
});

test('there is a saved answer of every endpoint', () => {
  const modes = new Set(NAMES.map((name) => MODES.find((mode) => name.startsWith(`${mode}_`))));

  assert.deepEqual([...modes].sort(), [...MODES].sort());
});

for (const name of NAMES) {
  test(`the answer ${name} shows with its metrics and how it came about, without a value the page could not read`, () => {
    const results = shown(name);

    const nodes = results.descendants();
    assert.doesNotMatch(results.textContent, /ließ sich nicht darstellen/);
    assert.ok(nodes.some((node) => node.classList.contains('metrics')), 'the metrics');
    assert.ok(nodes.some((node) => node.tagName === 'SECTION' && node.classList.contains('info')), 'how it came about');
    // The texts of the page; the JSON of the technical details may hold null
    const texts = nodes.filter((node) => node.tagName !== 'PRE').flatMap((node) => node.childNodes.filter((child) => child.data !== undefined).map((child) => child.data));
    assert.deepEqual(texts.filter((value) => /undefined|NaN|\[object Object\]|^null$/.test(value)), []);
  });
}
