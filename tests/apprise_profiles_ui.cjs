const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

for (const language of ['de', 'en']) {
  test(`Apprise provider selection and compatibility guidance (${language})`, () => {
    const labels = JSON.parse(fs.readFileSync(`ui/i18n/${language}.json`, 'utf8'));
    const translate = (key, params = {}) => {
      const text = key.split('.').reduce((value, part) => value?.[part], labels) || key;
      return text.replace(/\{(\w+)\}/g, (_, name) => params[name] ?? '');
    };
    const context = vm.createContext({
      window: {BBUI: {api: {_fetch401Wrapped: true}, components: {i18n: {t: translate}}}, addEventListener() {}},
      document: {addEventListener() {}},
      escHtml: value => String(value), escAttr: value => String(value),
      notificationEventOptions: () => [], settingsCard: (_title, _icon, body) => body,
      locationIcon: () => '',
    });
    vm.runInContext(fs.readFileSync('ui/js/api/client.js', 'utf8'), context);
    vm.runInContext(fs.readFileSync('ui/js/pages/settings.js', 'utf8'), context);
    const state = context.window.BBUI.settingsState;
    // The optional input lets the same check use real adapter metadata during
    // upgrade validation. The committed inventory always checks every schema.
    const inventory = JSON.parse(fs.readFileSync(process.argv[2] || 'plugin/apprise-providers.json', 'utf8'));
    state.appriseProviders = inventory.providers;
    state.appriseProvidersLoaded = true;
    for (const provider of inventory.providers) {
      state.appriseProviderFilter = provider.service_name;
      const choices = context._renderAppriseProviderResults('');
      for (const schema of provider.schemas) {
        assert.ok(choices.includes(`data-apprise-provider="${schema}"`), schema);
        const form = context._renderAppriseUrlConfig(schema, {}, true);
        assert.ok(form.includes('apprise-profile-url'), schema);
        if (provider.tokens?.length && context._appriseTemplateTokenKeys(context._appriseSelectedTemplate(schema, {})).length) {
          assert.ok(form.includes('apprise-url-builder'), schema);
        }
      }
    }
    assert.ok(context._renderAppriseUrlConfig('custom-provider', {}, true).includes('apprise-profile-url'));

    const profile = {id: 'old-alerts', name: 'Old alerts', provider: 'apprise', url_set: true,
      warning_code: 'apprise_notificationapi_retired', selected_events: ['backup_success']};
    state.appriseProfiles = [profile];
    state.appriseSelectedProfileId = profile.id;
    const warning = translate('api.messages.apprise_notificationapi_retired');
    assert.ok(context.renderSettingsAppriseProfiles().includes(warning));
    state.appriseDraftProfile = context._appriseDraftFromProfile(profile);
    assert.ok(context.renderSettingsAppriseProfiles().includes(warning));
    state.appriseDraftProfile = null;
    state.appriseProfiles = [{...profile, provider: 'ntfy', warning_code: ''}];
    assert.ok(!context.renderSettingsAppriseProfiles().includes(warning));
  });
}
