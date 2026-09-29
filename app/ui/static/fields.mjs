// The controls of a form of forms.mjs (D66): a label for every field, its help and its error tied to it, the
// options as small check boxes, the methods of the steps behind "Erweitert". A step left open shows what the chosen
// profile does there; while two profiles are compared the steps are theirs alone.

import { h } from './dom.mjs';
import { bounds, FORMS } from './forms.mjs';
import { formatNumber } from './stats.mjs';
import { ENTITY_METHODS, label, LINK_CHECKS, PARTS, PROFILE_ABOUT, PROFILE_NAMES, QA_METHODS, STEPS } from './texts.mjs';

let ids = 0;
const uid = (name) => `feld-${(ids += 1)}-${name}`;

/** A form for one mode: its element, and functions to read and set its values and to show what keeps it back. */
export function buildForm(mode, options, { onSubmit, onExample }) {
  const ctx = { mode, options, controls: new Map(), refreshers: [], datalist: null };
  const basic = [];
  const small = [];
  const advanced = [];
  for (const field of FORMS[mode].fields) {
    const node = TYPES[field.type](field, ctx);
    (field.advanced ? advanced : field.option ? small : basic).push(node);
  }
  const submit = h('button', { type: 'submit', class: 'primary' }, FORMS[mode].submit);
  let hadFocus = false;
  const element = h(
    'form',
    {
      class: 'query',
      novalidate: true,
      on: {
        submit: (event) => {
          event.preventDefault(); // the page sends the request itself; the form has nowhere to go
          onSubmit();
        },
      },
    },
    examples(mode, options, onExample),
    basic,
    small.length ? h('fieldset', { class: 'options' }, h('legend', {}, 'Optionen'), small) : null,
    advanced.length ? h('details', { class: 'advanced' }, h('summary', {}, 'Erweitert'), advanced) : null,
    h('div', { class: 'submit-row' }, submit),
    ctx.datalist,
  );
  const read = () => Object.fromEntries([...ctx.controls].map(([name, control]) => [name, control.read()]));
  const refresh = () => {
    const values = read();
    for (const refresher of ctx.refreshers) refresher(values);
  };
  ctx.refresh = refresh;
  return {
    element,
    read,
    write(values) {
      for (const [name, value] of Object.entries(values)) ctx.controls.get(name)?.write(value);
      refresh();
    },
    show(problems) {
      let first = null;
      for (const control of ctx.controls.values()) {
        const message = problems[control.name];
        control.error.hidden = !message;
        control.error.textContent = message ?? '';
        if (message) control.focus.setAttribute('aria-invalid', 'true');
        else control.focus.removeAttribute('aria-invalid');
        first ??= message ? control.focus : null;
      }
      if (first) {
        const folded = first.closest('details');
        if (folded) folded.open = true; // a field under "Erweitert" takes the focus only when it shows
        first.focus();
      }
      return Boolean(first);
    },
    busy(on) {
      if (on) hadFocus = document.activeElement === submit;
      submit.disabled = on;
      element.setAttribute('aria-busy', String(on));
      // A disabled button drops the focus to the page; a keyboard user gets it back where it was
      if (!on && hadFocus && document.activeElement === document.body) submit.focus();
    },
  };
}

function examples(mode, options, onExample) {
  const list = options.examples?.[mode] ?? [];
  if (!list.length) return null;
  const id = uid('beispiel');
  const select = h(
    'select',
    {
      id,
      on: {
        // It keeps the choice: reset to the prompt, every arrow key on the closed list loaded the first example again
        change: () => {
          const example = select.value === '' ? null : list[Number(select.value)];
          if (example) onExample(example);
        },
      },
    },
    h('option', { value: '' }, 'Beispiel wählen …'),
    list.map((example, index) => h('option', { value: String(index) }, example.label)),
  );
  const help = h('p', { class: 'help', id: `${id}-hilfe` }, 'Füllt die Felder; erzeugt wird erst mit dem Knopf unten.');
  select.setAttribute('aria-describedby', help.id);
  return h('div', { class: 'field examples' }, h('label', { for: id }, 'Beispiel laden'), select, help);
}

// A control with its label, help and error slot; `access` reads and writes its value
function field(spec, ctx, control, access, wrapperClass = 'field') {
  const help = spec.help ? h('p', { class: 'help', id: `${control.id}-hilfe` }, spec.help) : null;
  const error = h('p', { class: 'field-error', id: `${control.id}-fehler`, hidden: true });
  control.setAttribute('aria-describedby', [help?.id, error.id].filter(Boolean).join(' '));
  ctx.controls.set(spec.name, { name: spec.name, ...access, error, focus: control });
  const optional = spec.optional ? h('span', { class: 'optional' }, ' (optional)') : null;
  return h('div', { class: wrapperClass }, h('label', { for: control.id }, spec.label, optional), control, help, error);
}

function input(spec, ctx, attributes = {}, read = (control) => control.value) {
  const control = h('input', { id: uid(spec.name), name: spec.name, type: 'text', placeholder: spec.placeholder, autocomplete: 'off', ...attributes });
  return field(spec, ctx, control, { read: () => read(control), write: (value) => (control.value = value ?? '') });
}

// A number field holds '' for text it cannot read and says so in validity.badInput; read as empty, it sent nothing and
// the server took its default. It reads as no number instead, which the checks of forms.mjs refuse in plain words
const numberOf = (control) => (control.validity?.badInput ? Number.NaN : control.value);

const TYPES = {
  text: (spec, ctx) => input(spec, ctx),
  id: (spec, ctx) => input(spec, ctx, { spellcheck: 'false', placeholder: 'ID oder Link' }),
  subject(spec, ctx) {
    ctx.datalist ??= h('datalist', { id: uid('faecher') }, (ctx.options.subjects ?? []).map((subject) => h('option', { value: subject })));
    return input(spec, ctx, { list: ctx.datalist.id, placeholder: 'z. B. Physik' });
  },
  textarea(spec, ctx) {
    const control = h('textarea', { id: uid(spec.name), name: spec.name, rows: 6, placeholder: spec.placeholder });
    return field(spec, ctx, control, { read: () => control.value, write: (value) => (control.value = value ?? '') });
  },
  number(spec, ctx) {
    const { default: preset, min, max } = bounds(ctx.mode, spec.name, ctx.options);
    const placeholder = preset === null || preset === undefined ? 'Vorgabe des Servers' : `Vorgabe: ${formatNumber(preset)}`;
    return input(spec, ctx, { type: 'number', inputmode: 'numeric', step: 1, min, max, placeholder }, numberOf);
  },
  check(spec, ctx) {
    const control = h('input', { id: uid(spec.name), name: spec.name, type: 'checkbox' });
    const error = h('p', { class: 'field-error', hidden: true });
    ctx.controls.set(spec.name, { name: spec.name, read: () => control.checked, write: (value) => (control.checked = Boolean(value)), error, focus: control });
    return h('div', { class: 'check' }, control, h('label', { for: control.id }, spec.label), error);
  },
  select(spec, ctx) {
    const control = h('select', { id: uid(spec.name), name: spec.name });
    const first = spec.profile ? h('option', { value: '' }) : null;
    const choices = typeof spec.choices === 'function' ? spec.choices(ctx.options) : spec.choices;
    control.append(...[first, ...Object.entries(choices).map(([value, text]) => h('option', { value }, text))].filter(Boolean));
    if (spec.profile) {
      ctx.refreshers.push((values) => {
        first.textContent = `wie im Profil: ${profileDefault(spec.name, values.preset, ctx.options)}`;
        control.disabled = Boolean(values.compare);
      });
    }
    return field(spec, ctx, control, { read: () => control.value, write: (value) => (control.value = value ?? '') });
  },
  template(spec, ctx) {
    // The count of blocks once: the built-in templates name it already ("SC26 (13 Bausteine)")
    const named = (template) => (template.name.includes(`${template.slots} Bausteine`) ? template.name : `${template.name} (${template.slots} Bausteine)`);
    const choices = Object.fromEntries((ctx.options.templates ?? []).map((template) => [template.id, named(template)]));
    const control = h('select', { id: uid(spec.name), name: spec.name }, h('option', { value: '' }, 'Vorgabe des Servers'), Object.entries(choices).map(([value, text]) => h('option', { value }, text)));
    return field(spec, ctx, control, { read: () => control.value, write: (value) => (control.value = value ?? '') });
  },
  parts(spec, ctx) {
    const boxes = (ctx.options.parts ?? []).map((part) => [part, h('input', { id: uid(part), type: 'checkbox', value: part })]);
    const error = h('p', { class: 'field-error', id: uid('teile-fehler'), hidden: true });
    const group = h('fieldset', { class: 'parts', 'aria-describedby': error.id }, h('legend', {}, spec.label), boxes.map(([part, box]) => h('div', { class: 'check' }, box, h('label', { for: box.id }, label(PARTS, part)))), error);
    ctx.controls.set(spec.name, {
      name: spec.name,
      read: () => boxes.filter(([, box]) => box.checked).map(([part]) => part),
      write: (value) => boxes.forEach(([part, box]) => (box.checked = (value ?? []).includes(part))),
      error,
      focus: boxes[0][1],
    });
    return group;
  },
  preset: presetField,
  steps: stepsField,
  methods: methodsField,
};

function presetField(spec, ctx) {
  const { options, mode } = ctx;
  const choose = (name) => {
    const control = h(
      'select',
      { id: uid(name), name, on: { change: () => ctx.refresh() } },
      options.presets.map(({ id }) => {
        const unavailable = !options.llm_configured && id !== 'llm-free';
        return h('option', { value: id, disabled: unavailable }, `${label(PROFILE_NAMES, id)}${unavailable ? ' – braucht KI' : ''}`);
      }),
    );
    const about = h('p', { class: 'help about', id: `${control.id}-hilfe` });
    const error = h('p', { class: 'field-error', id: `${control.id}-fehler`, hidden: true });
    control.setAttribute('aria-describedby', `${about.id} ${error.id}`);
    const write = (value) => {
      if (value) control.value = value;
    };
    ctx.controls.set(name, { name, read: () => control.value, write, error, focus: control });
    ctx.refreshers.push((values) => (about.textContent = PROFILE_ABOUT[mode]?.[values[name]] ?? ''));
    return { control, about, error };
  };
  const first = choose('preset');
  const second = choose('preset_b');
  // Without an LLM only llm-free answers, and a profile has nothing to be compared with
  const compareId = uid('vergleich');
  const withoutLlm = options.llm_configured ? null : h('p', { class: 'help', id: `${compareId}-hilfe` }, 'Zum Vergleich braucht der Server eine KI.');
  const compare = h('input', { id: compareId, type: 'checkbox', disabled: !options.llm_configured, 'aria-describedby': withoutLlm?.id, on: { change: () => ctx.refresh() } });
  ctx.controls.set('compare', { name: 'compare', read: () => compare.checked, write: (value) => (compare.checked = Boolean(value)), error: h('p', { hidden: true }), focus: compare });
  const secondBox = h('div', { class: 'field second-profile' }, h('label', { for: second.control.id }, 'Zweites Profil'), second.control, second.about, second.error);
  ctx.refreshers.push((values) => (secondBox.hidden = !values.compare));
  return h(
    'div',
    { class: 'profile' },
    h('div', { class: 'field' }, h('label', { for: first.control.id }, spec.label), first.control, first.about, first.error),
    h('div', { class: 'check' }, compare, h('label', { for: compare.id }, 'Mit einem zweiten Profil vergleichen')),
    withoutLlm,
    secondBox,
  );
}

function stepsField(spec, ctx) {
  const note = h('p', { class: 'help', id: uid('methoden-hilfe') }, 'Offen gelassen gilt die Methode des Profils.');
  const rows = spec.steps.map((step) => {
    const first = h('option', { value: '' });
    const control = h('select', { id: uid(step), name: step }, first, (ctx.options.switches?.[step] ?? []).map((value) => h('option', { value }, label(STEPS[step].values, value))));
    ctx.controls.set(step, { name: step, read: () => control.value, write: (value) => (control.value = value ?? ''), error: h('p', { hidden: true }), focus: control });
    ctx.refreshers.push((values) => {
      first.textContent = `wie im Profil: ${profileDefault(step, values.preset, ctx.options)}`;
      control.disabled = Boolean(values.compare);
    });
    return h('div', { class: 'field' }, h('label', { for: control.id }, STEPS[step].name), control);
  });
  ctx.refreshers.push((values) => (note.textContent = values.compare ? 'Im Vergleich gelten die Methoden der beiden Profile.' : 'Offen gelassen gilt die Methode des Profils.'));
  return h('fieldset', { class: 'steps', 'aria-describedby': note.id }, h('legend', {}, spec.label), note, rows);
}

function methodsField(spec, ctx) {
  const boxes = (ctx.options.entities?.methods ?? []).map((method) => [method, h('input', { id: uid(method), type: 'checkbox', value: method })]);
  const note = h('p', { class: 'help', id: uid('wege-hilfe') });
  ctx.controls.set(spec.name, {
    name: spec.name,
    read: () => boxes.filter(([, box]) => box.checked).map(([method]) => method),
    write: (value) => boxes.forEach(([method, box]) => (box.checked = (value ?? []).includes(method))),
    error: h('p', { hidden: true }),
    focus: boxes[0]?.[1],
  });
  ctx.refreshers.push((values) => {
    note.textContent = `Keiner gewählt: wie im Profil (${profileDefault('methods', values.preset, ctx.options)}).`;
    boxes.forEach(([, box]) => (box.disabled = Boolean(values.compare)));
  });
  return h('fieldset', { class: 'methods', 'aria-describedby': note.id }, h('legend', {}, spec.label), boxes.map(([method, box]) => h('div', { class: 'check' }, box, h('label', { for: box.id }, label(ENTITY_METHODS, method)))), note);
}

// What a profile does in a step the reader left open, in the words of texts.mjs
function profileDefault(name, preset, options) {
  if (name === 'methods') return (options.entities?.profiles?.[preset] ?? []).map((method) => label(ENTITY_METHODS, method)).join(', ');
  if (name === 'method') return label(QA_METHODS, options.qa?.profiles?.[preset]);
  if (name === 'link_check') return label(LINK_CHECKS, options.entities?.link_check_default);
  const value = options.presets.find((profile) => profile.id === preset)?.switches?.[name];
  return label(STEPS[name]?.values, value);
}
