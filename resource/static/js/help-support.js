// 未收录报错的本地整理与手册入口，不自动收集或提交用户数据。
(function(root) {
  'use strict';
  const MASK = '[已隐藏]';

  function redact(value) {
    let text = String(value ?? '').slice(0, 50000).replace(/\r\n?/g, '\n').replace(/\\\//g, '/');
    text = text.replace(/^(?:#HttpOnly_)?[^\t\n]+\t(?:TRUE|FALSE)\t[^\t\n]*\t(?:TRUE|FALSE)\t-?\d+\t[^\t\n]+\t[^\n]*$/gim, '[Cookie 行已隐藏]');
    text = text.replace(/(--(?:cookies(?:-from-browser)?|cookie|password|video-password|username|http-basic-user|http-basic-pass|ap-username|ap-password|client-certificate-password|webhook-url|proxy|add-headers?|http-header|extractor-args|token|api-key|client-secret)(?:\s*=\s*|\s+))(?:"(?:\\[^\r\n]|[^"\\\r\n])*(?:"|\\?(?=\n|$))|'(?:\\[^\r\n]|[^'\\\r\n])*(?:'|\\?(?=\n|$))|[^\s]+)/gi,
      (_, prefix) => prefix + MASK);
    text = text.replace(/^([^\n]*?\b(?:cookie|set-cookie|authorization|proxy-authorization)\s*:\s*)[^\n]*$/gim,
      (_, prefix) => prefix + MASK);
    text = text.replace(/(["']?\b(?:access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|authorization|proxy[_-]?authorization|cookie|set-cookie|password|passwd|pwd|token|secret|client[_-]?secret|video[_-]?password|session(?:[_-]?id)?|sid|sessid|fanboxsessid|phpsessid|jsessionid|sessdata|bili_jct|DedeUserID(?:__ckMd5)?|csrf(?:[_-]?token)?|xsrf(?:[_-]?token)?|signature|sig|credentials?|jwt)["']?\s*[:=]\s*)(?:\[已隐藏\]|"(?:\\[^\r\n]|[^"\\\r\n])*(?:"|\\?(?=\n|$))|'(?:\\[^\r\n]|[^'\\\r\n])*(?:'|\\?(?=\n|$))|(?:Bearer|Basic)\s+[^\s,;}\]]+|[^\s,;}\]]+)/gi,
      (_, prefix) => prefix + MASK);
    text = text.replace(/\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+/gi, (_, scheme) => scheme + ' ' + MASK);
    text = text.replace(/(?:https?|wss?|ftp):\/\/[^\s<>"']+/gi, raw => {
      try {
        const url = new URL(raw);
        url.username = '';
        url.password = '';
        url.search = '';
        url.hash = '';
        return url.href;
      } catch(e) { return '[链接已隐藏]'; }
    });
    text = text.replace(/\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*/g, MASK);
    return text;
  }

  function buildReport(fields, mode = 'organize') {
    const get = key => redact(fields[key]).trim() || '未提供';
    const lines = [
      mode === 'feedback' ? '# 问题反馈模板' : '# 报错信息摘要',
      '',
      '程序版本：' + get('version'),
      '平台：' + get('platform'),
      '报错来源：' + get('source'),
      '错误码或标识：' + get('code'),
      '原因：尚未确认',
    ];
    if(mode === 'feedback') lines.push('', '## 操作步骤', get('steps'), '', '## 预期结果', get('expected'), '', '## 实际结果', get('actual'));
    lines.push('', '## 错误原文', get('error'), '', '## 报错前后相关日志', get('logs'), '',
      '说明：请结合完整手册与前后日志核对，具体原因尚未确认。已按常见规则尝试遮盖敏感信息，提交前仍需人工检查；没有自动上传或提交。');
    return lines.join('\n');
  }

  function init({request, getVersion = () => '', getPlatform = () => ''}) {
    const doc = root.document, host = doc.querySelector('#help-errors .help-missing-error');
    if(!host || host.dataset.supportReady === '1') return;
    host.dataset.supportReady = '1';
    const byId = id => doc.getElementById(id);
    const manualPanel = byId('helpManualPanel'), manualButton = byId('helpOpenManual');
    const manualStatus = byId('helpManualStatus'), manualText = byId('helpManualText');
    let manualLoaded = false, manualLoading = false, mode = 'organize';
    const closeManual = () => { manualPanel.hidden = true; manualButton.setAttribute('aria-expanded', 'false'); };
    manualText.hidden = true;
    byId('helpCloseManual').onclick = closeManual;
    manualButton.onclick = async () => {
      if(!manualPanel.hidden) { closeManual(); return; }
      manualPanel.hidden = false;
      manualButton.setAttribute('aria-expanded', 'true');
      if(manualLoaded || manualLoading) return;
      manualLoading = true;
      manualStatus.classList.remove('is-error');
      manualStatus.textContent = '正在加载完整手册…';
      try {
        const data = await request('/api/help/error-manual');
        if(typeof data.text !== 'string' || !data.text.trim()) throw new Error('手册内容暂不可用，请查看程序目录中的 docs/错误码.txt');
        manualText.textContent = data.text;
        manualText.hidden = false;
        manualStatus.textContent = '来源：docs/错误码.txt。可使用 Ctrl+F 查找报错文本。';
        manualLoaded = true;
      } catch(error) {
        manualStatus.textContent = '加载失败：' + redact(error.message || String(error)) + '。收起后再次打开可重试。';
        manualStatus.classList.add('is-error');
      } finally { manualLoading = false; }
    };

    const panel = byId('helpSupportPanel'), output = byId('helpReportOutput');
    const outputPanel = byId('helpReportOutputPanel'), copy = byId('helpCopyReport');
    const status = byId('helpReportStatus');
    const fields = {version:'helpReportVersion', platform:'helpReportPlatform', source:'helpReportSource',
      code:'helpReportCode', error:'helpReportError', logs:'helpReportLogs', steps:'helpReportSteps',
      expected:'helpReportExpected', actual:'helpReportActual'};
    for(const id of Object.values(fields)) byId(id).setAttribute('autocomplete', 'off');
    output.setAttribute('autocomplete', 'off');
    const clearOutput = () => { output.value = ''; outputPanel.hidden = true; copy.disabled = true; status.textContent = ''; };
    const openPanel = nextMode => {
      if(mode !== nextMode) clearOutput();
      mode = nextMode;
      panel.hidden = false;
      byId('helpFeedbackFields').hidden = mode !== 'feedback';
      byId('helpSupportTitle').textContent = mode === 'feedback' ? '生成反馈模板' : '整理报错信息';
      byId('helpSupportHint').textContent = mode === 'feedback'
        ? '核对版本与平台，补充操作步骤、预期和实际结果，检查预览后再自行复制提交。'
        : '核对版本与平台，填写或粘贴具体错误及前后日志，生成可检查的报错摘要。';
      byId('helpGenerateReport').textContent = mode === 'feedback' ? '生成反馈模板' : '生成报错摘要';
      if(!byId(fields.version).value.trim()) byId(fields.version).value = String(getVersion() || '');
      if(!byId(fields.platform).value.trim()) byId(fields.platform).value = String(getPlatform() || '');
    };
    byId('helpOpenOrganizer').onclick = () => openPanel('organize');
    byId('helpOpenFeedback').onclick = () => openPanel('feedback');
    byId('helpCloseSupport').onclick = () => { panel.hidden = true; };
    for(const id of Object.values(fields)) byId(id).addEventListener('input', () => {
      if(output.value) clearOutput();
    });
    byId('helpGenerateReport').onclick = () => {
      const values = Object.fromEntries(Object.entries(fields).map(([key, id]) => [key, byId(id).value.trim()]));
      if(![values.error, values.code, values.logs, ...(mode === 'feedback' ? [values.steps, values.actual] : [])].some(Boolean)) {
        status.textContent = '请至少填写错误码、错误原文或相关日志；反馈模板也可填写操作步骤与实际结果。';
        return;
      }
      output.value = buildReport(values, mode);
      output.scrollTop = 0;
      output.scrollLeft = 0;
      outputPanel.hidden = false;
      copy.disabled = false;
      status.textContent = '结果已生成。请检查预览并移除剩余隐私信息，再复制。';
    };
    output.addEventListener('input', () => { copy.disabled = !output.value.trim(); });
    copy.onclick = async () => {
      const text = redact(output.value).trim();
      if(!text) return;
      output.value = text;
      try {
        if(!root.navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
        await root.navigator.clipboard.writeText(text);
        status.textContent = '已复制整理结果。请在提交前再次检查隐私内容，本页没有自动提交反馈。';
      } catch(e) {
        output.focus();
        output.select();
        status.textContent = '浏览器不允许自动复制，已选中结果，请按 Ctrl+C 手动复制。';
      }
    };
  }

  root.HelpSupport = Object.freeze({init, redact, buildReport});
})(window);
