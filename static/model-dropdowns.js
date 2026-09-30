(() => {
  const MODELS = {
    openai: [
      { value: 'gpt-6-astra', label: 'GPT-6 Astra — Most capable' },
      { value: 'gpt-5.6-sol', label: 'GPT-5.6 Sol — High quality' },
      { value: 'gpt-5.6-terra', label: 'GPT-5.6 Terra — Balanced' },
      { value: 'gpt-5.6-luna', label: 'GPT-5.6 Luna — Fast' },
    ],
    anthropic: [
      { value: 'claude-fable-5', label: 'Claude Fable 5 — Most capable' },
      { value: 'claude-opus-5', label: 'Claude Opus 5 — Advanced' },
      { value: 'claude-sonnet-5', label: 'Claude Sonnet 5 — Balanced' },
      { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5 — Fast' },
    ],
    codex_local: [
      { value: 'default', label: 'Portable default — GPT-5.6 Terra' },
      { value: 'gpt-6-astra', label: 'GPT-6 Astra' },
      { value: 'gpt-5.6-sol', label: 'GPT-5.6 Sol' },
      { value: 'gpt-5.6-terra', label: 'GPT-5.6 Terra' },
      { value: 'gpt-5.6-luna', label: 'GPT-5.6 Luna' },
    ],
    claude_local: [
      { value: 'default', label: 'Claude Code account default' },
      { value: 'sonnet', label: 'Claude Sonnet' },
      { value: 'opus', label: 'Claude Opus' },
    ],
  };

  const PROVIDER_LABELS = {
    codex_local: 'Codex / ChatGPT Subscription',
    claude_local: 'Claude Code / Claude Subscription',
    openai: 'OpenAI API',
    anthropic: 'Anthropic API',
  };

  const PAIRS = [
    ['sResearchProvider', 'sResearchModel'],
    ['sWriterProvider', 'sWriterModel'],
    ['sReviewerProvider', 'sReviewerModel'],
  ];

  function ensureProviderOptions(select) {
    if (!select) return;
    const expected = Object.entries(PROVIDER_LABELS);
    const current = select.value;
    const same = select.options.length === expected.length &&
      expected.every(([value, label], index) =>
        select.options[index]?.value === value &&
        select.options[index]?.textContent === label
      );
    if (!same) {
      select.innerHTML = '';
      for (const [value, label] of expected) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
      }
    }
    if (current && PROVIDER_LABELS[current]) select.value = current;
  }

  function ensureModelSelect(element) {
    if (!element) return null;
    if (element.tagName === 'SELECT') return element;
    const select = document.createElement('select');
    select.id = element.id;
    select.className = element.className;
    select.disabled = element.disabled;
    select.dataset.initialModel = element.value || '';
    element.replaceWith(select);
    return select;
  }

  function modelBelongsToProvider(model, provider) {
    return (MODELS[provider] || []).some(item => item.value === model);
  }

  function renderModels(providerId, modelId, preferredModel = null) {
    const providerSelect = document.getElementById(providerId);
    const modelSelect = ensureModelSelect(document.getElementById(modelId));
    if (!providerSelect || !modelSelect) return;

    const provider = providerSelect.value || 'codex_local';
    const models = MODELS[provider] || [];
    const requested = preferredModel ?? modelSelect.value ?? modelSelect.dataset.initialModel ?? '';
    const current = String(requested || '').trim();

    modelSelect.innerHTML = '';
    for (const model of models) {
      const option = document.createElement('option');
      option.value = model.value;
      option.textContent = model.label;
      modelSelect.appendChild(option);
    }

    if (current && !modelBelongsToProvider(current, provider)) {
      const custom = document.createElement('option');
      custom.value = current;
      custom.textContent = `Saved/custom — ${current}`;
      modelSelect.appendChild(custom);
    }

    const next = current && [...modelSelect.options].some(option => option.value === current)
      ? current
      : (models[0]?.value || '');
    if (next) modelSelect.value = next;

    modelSelect.dataset.visibleProvider = provider;
    modelSelect.dataset.initialModel = '';
  }

  function wirePair(providerId, modelId) {
    const providerSelect = document.getElementById(providerId);
    const modelElement = document.getElementById(modelId);
    if (!providerSelect || !modelElement) return false;

    ensureProviderOptions(providerSelect);
    const modelSelect = ensureModelSelect(modelElement);

    if (!providerSelect.dataset.modelDropdownWired) {
      providerSelect.dataset.modelDropdownWired = '1';
      providerSelect.addEventListener('change', () => renderModels(providerId, modelId));
    }

    if (modelSelect.dataset.visibleProvider !== providerSelect.value || !modelSelect.options.length) {
      renderModels(providerId, modelId);
    }
    return true;
  }

  function upgradeAll() {
    for (const [providerId, modelId] of PAIRS) wirePair(providerId, modelId);
  }

  window.YTNewsModels = {
    apply(providerId, modelId, provider, model) {
      const providerSelect = document.getElementById(providerId);
      if (!providerSelect) return;
      ensureProviderOptions(providerSelect);
      providerSelect.value = PROVIDER_LABELS[provider] ? provider : 'codex_local';
      renderModels(providerId, modelId, model || 'default');
    },
    refresh: upgradeAll,
    models: MODELS,
  };

  upgradeAll();
})();
