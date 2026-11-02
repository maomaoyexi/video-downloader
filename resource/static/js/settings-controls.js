/** 设置页的选项测宽与原生下拉箭头；配置读取、保存仍由 app.js 负责。 */
function initSettingsControls() {
  const page = document.getElementById('page-settings');
  if(!page || page._settingsControlsReady) return;
  const context = document.createElement('canvas').getContext('2d');
  if(!context) return;
  page._settingsControlsReady = true;
  let frame = 0;
  const updateWidths = () => {
    frame = 0;
    const groups = new Map();
    for(const select of page.querySelectorAll('select')) {
      let wrapper = select.parentElement;
      if(!wrapper.matches('.sel')) {
        wrapper = document.createElement('span');
        wrapper.className = 'sel';
        select.replaceWith(wrapper);
        wrapper.appendChild(select);
      }
      if(!wrapper.querySelector(':scope > .cv')) {
        wrapper.insertAdjacentHTML('beforeend',
          '<svg class="ico s14 cv" aria-hidden="true" focusable="false"><use href="#i-chevron"></use></svg>');
      }
      const arrow = wrapper.querySelector(':scope > .cv');
      arrow.setAttribute('aria-hidden','true');
      arrow.setAttribute('focusable','false');
      // 嵌套平台列表、FANBOX 各小组与常规分区分别计算，避免整页共用最长值。
      const host = select.closest('#livePlatformModes,#liveCommentPlatforms') ||
        select.closest('.lc-group,.output-settings-group,.fb-settings-list') ||
        select.closest('#fanboxSettingsFields') || select.closest('.settings-section-body');
      if(!host) continue;
      if(!groups.has(host)) groups.set(host,new Set());
      groups.get(host).add(wrapper);
    }
    for(const [host,wrappers] of groups) {
      const width = Math.max(...[...wrappers].map(wrapper => {
        const select = wrapper.querySelector('select');
        const style = getComputedStyle(select);
        context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
        const spacing = parseFloat(style.letterSpacing) || 0;
        const text = [...select.options].reduce((longest,option) => Math.max(longest,
          context.measureText(option.label).width + Math.max(0,[...option.label].length-1)*spacing),0);
        const padding = ['paddingLeft','paddingRight','borderLeftWidth','borderRightWidth']
          .reduce((total,key) => total+(parseFloat(style[key])||0),0);
        return Math.ceil(text+padding+4);
      }));
      const value = `${width}px`;
      if(host.style.getPropertyValue('--settings-select-width') !== value) host.style.setProperty('--settings-select-width',value);
      if(host.style.getPropertyValue('--lc-select-width') !== value) host.style.setProperty('--lc-select-width',value);
    }
  };
  const schedule = () => { if(!frame) frame = requestAnimationFrame(updateWidths); };
  // 只监听选项和动态平台行；不监听自身 style，避免测宽反复触发。
  new MutationObserver(schedule).observe(page,{
    childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['label']
  });
  window.addEventListener('resize',schedule);
  if(document.fonts) document.fonts.ready.then(schedule);
  schedule();
}
