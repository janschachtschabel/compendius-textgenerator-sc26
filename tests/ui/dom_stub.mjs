// A small stand-in for the browser's document, enough for the page's own builders (dom.mjs and what uses it) to run
// under node:test (D66). It knows elements, text nodes, fragments, attributes, listeners, classes, style properties,
// focus and the copy command - no layout, no markup parser: nothing here can turn text into elements either.

class FakeNode {
  constructor() {
    this.childNodes = [];
    this.parentNode = null;
  }

  append(...nodes) {
    for (const node of nodes) {
      const child = typeof node === 'string' ? new FakeText(node) : node;
      if (child instanceof FakeFragment) {
        this.append(...child.childNodes);
        child.childNodes = [];
      } else {
        child.parentNode?.removeChild(child);
        child.parentNode = this;
        this.childNodes.push(child);
      }
    }
  }

  replaceChildren(...nodes) {
    for (const child of this.childNodes) child.parentNode = null;
    this.childNodes = [];
    this.append(...nodes);
  }

  removeChild(child) {
    this.childNodes = this.childNodes.filter((node) => node !== child);
    child.parentNode = null;
  }

  remove() {
    this.parentNode?.removeChild(this);
  }

  get textContent() {
    return this.childNodes.map((node) => node.textContent).join('');
  }

  set textContent(value) {
    this.replaceChildren(new FakeText(String(value)));
  }
}

class FakeText extends FakeNode {
  constructor(data) {
    super();
    this.data = String(data);
  }

  get textContent() {
    return this.data;
  }
}

class FakeFragment extends FakeNode {}

class FakeElement extends FakeNode {
  constructor(tag, doc) {
    super();
    this.tagName = tag.toUpperCase();
    this.attributes = new Map();
    this.listeners = {};
    this.style = { properties: {}, setProperty: (name, value) => (this.style.properties[name] = value) };
    this.value = '';
    this.selected = false;
    this.ownerDocument = doc;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  hasAttribute(name) {
    return this.attributes.has(name);
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  get id() {
    return this.getAttribute('id') ?? '';
  }

  get classList() {
    const names = () => new Set((this.getAttribute('class') ?? '').split(/\s+/).filter(Boolean));
    const write = (set) => this.setAttribute('class', [...set].join(' '));
    return {
      contains: (name) => names().has(name),
      toggle: (name, on) => {
        const set = names();
        if (on ?? !set.has(name)) set.add(name);
        else set.delete(name);
        write(set);
      },
    };
  }

  get children() {
    return this.childNodes.filter((node) => node instanceof FakeElement);
  }

  addEventListener(type, listener) {
    (this.listeners[type] ??= []).push(listener);
  }

  focus() {
    this.ownerDocument.activeElement = this;
  }

  select() {
    this.selected = true;
  }

  /** Every element below this one, depth first. */
  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }
}

/** Put a fresh stand-in in place of document, Node and navigator; returns the document to look into. */
export function installDocument({ clipboard } = {}) {
  const doc = {
    commands: [],
    copyResult: true,
    createElement: (tag) => new FakeElement(tag, doc),
    createTextNode: (text) => new FakeText(text),
    createDocumentFragment: () => new FakeFragment(),
    execCommand(command) {
      const field = doc.activeElement;
      doc.commands.push({ command, text: field?.selected ? field.value : null });
      return doc.copyResult;
    },
  };
  doc.body = new FakeElement('body', doc);
  doc.activeElement = doc.body;
  globalThis.document = doc;
  globalThis.Node = FakeNode;
  Object.defineProperty(globalThis, 'navigator', { value: clipboard ? { clipboard } : {}, configurable: true, writable: true });
  return doc;
}
