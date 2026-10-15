'use strict';
const slider = document.getElementById('exposure');
const value = document.getElementById('value');
const status = document.getElementById('status');
const save = document.getElementById('save');
const reset = document.getElementById('reset');
const command = 'sh /data/adb/modules/questlhsync_gxr/settings.sh ';
let sequence = 0;
function busy(on) { slider.disabled = save.disabled = reset.disabled = on; }
function display() { value.textContent = Number(slider.value).toFixed(1) + ' ms'; }
function exec(args) {
  return new Promise((resolve, reject) => {
    const callback = 'gxrSettings' + sequence++;
    const timer = setTimeout(() => {
      delete window[callback];
      reject(new Error('No response. Reopen this page to check the saved setting.'));
    }, 30000);
    window[callback] = (code, stdout, stderr) => {
      clearTimeout(timer);
      delete window[callback];
      if (Number(code) === 0) resolve(stdout.trim());
      else reject(new Error(stderr.trim() || stdout.trim() || 'Settings command failed.'));
    };
    try { window.ksu.exec(command + args, '{}', callback); }
    catch (error) { clearTimeout(timer); delete window[callback]; reject(error); }
  });
}
slider.addEventListener('input', display);
reset.addEventListener('click', () => { slider.value = '5'; display(); status.textContent = 'Default selected. Save & apply to use it.'; });
save.addEventListener('click', async () => {
  const ns = Math.round(Number(slider.value) * 10) * 100000;
  if (!Number.isInteger(ns) || ns < 1000000 || ns > 5000000) return;
  busy(true);
  let saved = false;
  try {
    status.textContent = 'Saving…';
    await exec('set ' + ns);
    saved = true;
    status.textContent = 'Saved. Restarting camera service…';
    await exec('apply');
    status.textContent = 'Saved. Service restart requested; tracking will reconnect shortly.';
  } catch (error) { status.textContent = (saved ? 'Setting saved. ' : '') + error.message; }
  finally { busy(false); }
});
(async () => {
  if (!window.ksu || typeof window.ksu.exec !== 'function') {
    status.textContent = 'Open this page from the module’s WebUI button in KernelSU Manager.';
    return;
  }
  try {
    const ns = Number(await exec('get'));
    if (!Number.isInteger(ns) || ns < 1000000 || ns > 5000000 || ns % 100000) throw new Error('Invalid saved cutoff.');
    slider.value = String(ns / 1000000); display(); busy(false);
    status.textContent = 'Settings loaded.';
  } catch (error) { status.textContent = error.message; }
})();
