'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class FakeClassList {
  constructor(owner) {
    this.owner = owner;
    this.values = new Set();
  }

  add(...values) {
    values.forEach((value) => this.values.add(value));
  }

  remove(...values) {
    values.forEach((value) => this.values.delete(value));
  }

  contains(value) {
    return this.values.has(value);
  }
}

class FakeElement {
  constructor() {
    this.dataset = {};
    this.attributes = new Map();
    this.classList = new FakeClassList(this);
    this.parentNode = null;
    this.textContent = '';
  }

  set className(value) {
    this.classList.values = new Set(String(value).split(/\s+/).filter(Boolean));
  }

  get className() {
    return [...this.classList.values].join(' ');
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  hasAttribute(name) {
    return this.attributes.has(name);
  }
}

class FakeButton extends FakeElement {
  constructor() {
    super();
    this.disabled = false;
    this.innerHTML = 'Salvar';
    this.form = null;
  }

  dispatchEvent() {}
}

class FakeForm extends FakeElement {
  constructor(button) {
    super();
    this.id = 'async-form';
    this.children = [button];
    this.listeners = [];
    button.form = this;
    button.parentNode = this;
  }

  addEventListener(type, callback) {
    if (type === 'submit') this.listeners.push(callback);
  }

  querySelector(selector) {
    if (selector === '.form-status-message') {
      return this.children.find((child) => child.classList.contains('form-status-message')) || null;
    }
    if (selector.includes('button')) return this.children.find((child) => child instanceof FakeButton) || null;
    return null;
  }

  insertBefore(child, reference) {
    const index = this.children.indexOf(reference);
    child.parentNode = this;
    this.children.splice(index < 0 ? this.children.length : index, 0, child);
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
  }

  submitEvent() {
    const event = {
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
    };
    this.listeners.forEach((listener) => listener(event));
    return event;
  }
}

const button = new FakeButton();
const form = new FakeForm(button);
const documentListeners = new Map();

// Simula uma validação da página registrada antes do feedback global.
form.addEventListener('submit', (event) => {
  event.preventDefault();
  sandbox.window.FormFeedback.showStatus(form, 'Revise os dados.', 'warning');
});

const fakeDocument = {
  addEventListener(type, callback) {
    const callbacks = documentListeners.get(type) || [];
    callbacks.push(callback);
    documentListeners.set(type, callbacks);
  },
  createElement() {
    return new FakeElement();
  },
  querySelector() {
    return null;
  },
  querySelectorAll(selector) {
    return selector === 'form[data-sync]' ? [form] : [];
  },
};

const sandbox = {
  console,
  Response,
  CustomEvent: class CustomEvent {},
  HTMLButtonElement: FakeButton,
  HTMLFormElement: FakeForm,
  document: fakeDocument,
  setTimeout,
  clearTimeout,
};
sandbox.window = sandbox;
sandbox.window.CSS = { escape: (value) => value };

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'form_feedback.js'), 'utf8');
vm.runInNewContext(source, sandbox, { filename: 'form_feedback.js' });
(documentListeners.get('DOMContentLoaded') || []).forEach((listener) => listener());

const prevented = form.submitEvent();
assert.equal(prevented.defaultPrevented, true);
assert.equal(button.disabled, false, 'a validação bloqueada não pode travar o botão');
assert.equal(form.querySelector('.form-status-message').textContent, 'Revise os dados.');
assert.equal(form.querySelector('.form-status-message').classList.contains('d-none'), false);

sandbox.window.FormFeedback.showStatus(form, 'Revise os dados.', 'danger');
const status = form.querySelector('.form-status-message');
assert.ok(status, 'formulários sem área própria devem receber uma automaticamente');
assert.equal(status.textContent, 'Revise os dados.');
assert.equal(status.classList.contains('d-none'), false);
assert.equal(status.classList.contains('alert-danger'), true);
