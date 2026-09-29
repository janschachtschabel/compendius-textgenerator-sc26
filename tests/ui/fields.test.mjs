// The controls of the forms under the stand-in document, with the options of a real server (D66).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { installDocument } from './dom_stub.mjs';
import { OPTIONS } from './saved_answers.mjs';
import { buildForm } from '../../app/ui/static/fields.mjs';
import { buildRequests, defaults, problems } from '../../app/ui/static/forms.mjs';

function compendiumForm() {
  installDocument();
  const form = buildForm('compendium', OPTIONS, { onSubmit() {}, onExample() {} });
  form.write({ ...defaults('compendium', OPTIONS), topic: 'Optik' });
  const field = (name) => form.element.descendants().find((node) => node.getAttribute('name') === name);
  return { form, field };
}

test('a number the field cannot read keeps the form from being sent, instead of leaving the value to the server', () => {
  const { form, field } = compendiumForm();
  // What a browser holds for "viele" in a number field (HTML, the value sanitization of type=number)
  Object.assign(field('max_articles'), { value: '', validity: { badInput: true } });

  const found = problems('compendium', form.read(), OPTIONS);

  assert.match(found.max_articles ?? '', /^Bitte eine ganze Zahl von 1 bis \d+ eingeben\.$/);
});

test('an empty number field still leaves the value to the server, and a number goes as one', () => {
  const { form, field } = compendiumForm();
  field('target_length').value = '8000';

  const values = form.read();

  assert.deepEqual(problems('compendium', values, OPTIONS), {});
  const [run] = buildRequests('compendium', values, OPTIONS);
  assert.equal(run.request.body.target_length, 8000);
  assert.ok(!('max_articles' in run.request.body));
});
