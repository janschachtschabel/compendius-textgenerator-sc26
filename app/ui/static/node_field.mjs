// The field of a collection or a material (D77; Jan, 2026-10-02: "vielleicht reicht ein feld für die nodeid der
// sammlung"): its id or a link to it, the node as the service reads it (GET /api/v2/nodes/{id}, through ctx.lookup),
// and under it what the node does in the request, in the lines of node_use.mjs. What reading showed is the form's
// node_kind: forms.mjs sends a collection as collection_id and offers its materials as a source.

import { h } from './dom.mjs';
import { fromAnotherRepository, wholeNodeId } from './forms.mjs';
import { nodeLine, nodeUses } from './node_use.mjs';

const MISSING = 'Keine für den Dienst sichtbare Sammlung und kein Material mit dieser ID im Repository.';

/** `wrapper` is the plain id field fields.mjs built for `spec`; this adds the reading, its line and the uses. */
export function nodeField(spec, ctx, wrapper) {
  const control = ctx.controls.get(spec.name).focus;
  const status = h('p', { class: 'help node-status', id: `${control.id}-knoten`, role: 'status', hidden: true });
  const uses = h('ul', { class: 'node-uses' });
  // The node as text (D114): fills the text field with what reading gave (text_input) and empties the id, so the
  // request reads no repository and gets the same compendium
  const take = h('button', { type: 'button', class: 'secondary node-take', hidden: true }, 'Als Text übernehmen');
  take.addEventListener('click', () => {
    const target = ctx.controls.get('node_text');
    if (!target || !state.node?.text_input) return;
    target.write(JSON.stringify(state.node.text_input, null, 2));
    ctx.controls.get(spec.name).write('');
    ctx.refresh();
  });
  control.setAttribute('aria-describedby', [control.getAttribute('aria-describedby'), status.id].filter(Boolean).join(' '));
  wrapper.append(status, take, uses);
  // What reading showed, for which id and repository; an example names the kind of its id before reading answers
  const state = { key: '', id: '', node: null, error: '', reading: null, written: { id: '', kind: '' } };
  const kind = () => {
    const id = wholeNodeId(control.value);
    if (state.node && state.id === id) return state.node.kind;
    return state.written.id === id ? state.written.kind : '';
  };
  ctx.controls.set('node_kind', {
    name: 'node_kind',
    read: kind,
    write: (value) => (state.written = { id: wholeNodeId(control.value), kind: value || '' }),
    error: h('p', { hidden: true }),
    focus: control,
  });
  ctx.refreshers.push((values) => {
    read(values);
    show(values);
  });

  function read(values) {
    const id = wholeNodeId(values[spec.name]);
    const repository = String(values.repository ?? '').trim();
    const key = id ? `${id} ${repository}` : '';
    if (key === state.key) return;
    state.reading?.abort();
    Object.assign(state, { key, id, node: null, error: '', reading: null });
    if (!id || !ctx.lookup) return;
    const reading = new AbortController();
    state.reading = reading;
    ctx.lookup(id, repository, reading.signal).then(
      ({ data }) => settle(key, data, ''),
      (error) => {
        if (error?.name === 'AbortError') return;
        // What the server said where it said something: "the repository does not answer" hid refused credentials
        const said = typeof error?.detail === 'string' ? error.detail : String(error?.message ?? error);
        settle(key, null, error?.status === 404 ? MISSING : said);
      },
    );
  }

  function settle(key, node, error) {
    if (key !== state.key) return; // the field holds another id by now
    Object.assign(state, { node, error, reading: null });
    ctx.refresh();
  }

  function show(values) {
    const id = wholeNodeId(values[spec.name]);
    status.textContent = !id ? '' : state.node ? nodeLine(state.node) : state.error || (ctx.lookup ? 'Wird gelesen …' : '');
    status.hidden = !status.textContent;
    take.hidden = !(id && state.node?.text_input && ctx.controls.has('node_text'));
    const lines = nodeUses(ctx.mode, values, state.node, { foreign: fromAnotherRepository(values, ctx.options) });
    uses.replaceChildren(...lines.map((line) => h('li', {}, line)));
  }

  return wrapper;
}
