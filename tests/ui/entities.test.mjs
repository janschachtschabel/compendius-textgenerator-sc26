// Entities marked where they stand in their text, however the text is written (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { segments } from '../../app/ui/static/view_entities.mjs';

const marked = (parts) => parts.filter((part) => part.entity).map((part) => part.text);

test('start and end count code points, as the service counts them, also after an emoji', () => {
  const parts = segments('📚 Arbeitsblatt zu Isaac Newton', [{ start: 18, end: 30, text: 'Isaac Newton' }]);

  assert.deepEqual(marked(parts), ['Isaac Newton']);
  assert.equal(parts.map((part) => part.text).join(''), '📚 Arbeitsblatt zu Isaac Newton');
});

test('entities come out in the order of the text, an overlapping one unmarked', () => {
  const parts = segments('Alexander von Humboldt reiste nach Quito.', [
    { start: 35, end: 40, text: 'Quito' },
    { start: 0, end: 22, text: 'Alexander von Humboldt' },
    { start: 14, end: 22, text: 'Humboldt' },
  ]);

  assert.deepEqual(marked(parts), ['Alexander von Humboldt', 'Quito']);
});

test('an entity beyond the end of the text is left out', () => {
  assert.deepEqual(marked(segments('kurz', [{ start: 2, end: 10, text: 'x' }])), []);
});
