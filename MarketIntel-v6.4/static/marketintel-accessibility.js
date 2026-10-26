(function () {
  'use strict';

  // Add semantics around the existing controls; their click callbacks stay intact.
  var started = false;
  var navSelector = '.nav-item[data-target], .mi-mobile button[data-target]';
  var generatedLabels = new WeakMap();
  var knownIconLabels = [
    ['.mi-open-mobile', 'Abrir menú de navegación'],
    ['.mi-drawer [data-close]', 'Cerrar menú de navegación'],
    ['[data-close-command]', 'Cerrar buscador']
  ];

  function navigation(item) {
    if (item.matches('.nav-item') && !item.matches('button, a[href], input, select, textarea')) {
      if (!item.hasAttribute('role')) item.setAttribute('role', 'button');
      if (!item.hasAttribute('tabindex')) item.setAttribute('tabindex', '0');
    }
    if (item.classList.contains('active')) {
      if (item.getAttribute('aria-current') !== 'page') item.setAttribute('aria-current', 'page');
    } else if (item.hasAttribute('aria-current')) {
      item.removeAttribute('aria-current');
    }
  }

  function fieldLabels(field) {
    var labels = Array.from(field.querySelectorAll('label')).filter(function (label) {
      return label.closest('.calc-field') === field;
    });
    var controls = Array.from(field.querySelectorAll('input:not([type="hidden"]), select, textarea')).filter(function (control) {
      return control.closest('.calc-field') === field;
    });
    // Multiple controls or labels need an explicit association from the component.
    if (labels.length !== 1 || controls.length !== 1) return;
    var label = labels[0], control = controls[0];
    if (label.hasAttribute('for') || label.contains(control) || !control.id) return;
    if (document.getElementById(control.id) === control) label.htmlFor = control.id;
  }

  function iconLabel(button) {
    if (button.hasAttribute('aria-labelledby')) return;
    var current = button.getAttribute('aria-label');
    // Respect labels supplied by the application, including ones changed later.
    if (current !== null && current !== generatedLabels.get(button)) return;
    var label = '';
    if (button.matches('.mi-icon, .mi-size-toggle, #theme-toggle-btn') || !button.textContent.trim()) {
      label = button.getAttribute('title') || '';
    }
    if (!label) {
      knownIconLabels.some(function (entry) {
        if (!button.matches(entry[0])) return false;
        label = entry[1];
        return true;
      });
    }
    if (!label) return;
    generatedLabels.set(button, label);
    if (current !== label) button.setAttribute('aria-label', label);
  }

  function visit(root, selector, enhance) {
    if (root.nodeType === 1 && root.matches(selector)) enhance(root);
    root.querySelectorAll(selector).forEach(enhance);
  }

  function enhance(root) {
    visit(root, navSelector, navigation);
    visit(root, '.calc-field', fieldLabels);
    visit(root, 'button', iconLabel);
  }

  function onKeydown(event) {
    if (event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key !== 'Enter' && event.key !== ' ' && event.key !== 'Spacebar') return;
    var target = event.target;
    if (!target || target.nodeType !== 1) return;
    // Native controls keep their own keyboard behavior, even inside a nav item.
    if (target.closest('input, textarea, select, button, a[href], [contenteditable]:not([contenteditable="false"])')) return;
    var item = target.closest('.nav-item[data-target]');
    if (!item || item.getAttribute('aria-disabled') === 'true') return;
    event.preventDefault();
    if (!event.repeat) item.click();
  }

  function start() {
    if (started || !document.body) return;
    started = true;
    enhance(document.body);
    document.addEventListener('keydown', onKeydown);

    // Process only inserted subtrees and affected controls. ARIA/for/tabindex
    // writes are deliberately excluded so enhancements cannot retrigger themselves.
    var observer = new MutationObserver(function (records) {
      var roots = new Set(), fields = new Set(), buttons = new Set(), navItems = new Set();
      records.forEach(function (record) {
        var target = record.target;
        if (record.type === 'attributes') {
          if (target.matches(navSelector)) navItems.add(target);
          if (record.attributeName === 'title' && target.matches('button')) buttons.add(target);
          return;
        }
        record.addedNodes.forEach(function (node) {
          if (node.nodeType === 1) roots.add(node);
        });
        var field = target.closest('.calc-field'), button = target.closest('button');
        if (field) fields.add(field);
        if (button) buttons.add(button);
      });
      roots.forEach(function (root) {
        if (!root.isConnected) return;
        for (var parent = root.parentElement; parent; parent = parent.parentElement) {
          if (roots.has(parent)) return;
        }
        enhance(root);
      });
      fields.forEach(function (field) { if (field.isConnected) fieldLabels(field); });
      buttons.forEach(function (button) { if (button.isConnected) iconLabel(button); });
      navItems.forEach(function (item) { if (item.isConnected) navigation(item); });
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'title'] });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
}());
