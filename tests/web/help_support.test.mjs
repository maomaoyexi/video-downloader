// 合成凭据仅用于本地脱敏验证，不读取真实账号、配置或日志。
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context={window:{},URL};
vm.runInNewContext(fs.readFileSync('resource/static/js/help-support.js','utf8'),context);
const {redact,buildReport}=context.window.HelpSupport;
const cases=[
  {name:'Cookie headers',input:'[debug] Cookie: sid=DEMO_A; auth=DEMO_B\nSet-Cookie: session=DEMO_C; Path=/',secrets:['DEMO_A','DEMO_B','DEMO_C']},
  {name:'Authorization headers',input:'Authorization: Bearer DEMO_TOKEN\nProxy-Authorization: Basic ZGVtbzpwYXNz',secrets:['DEMO_TOKEN','ZGVtbzpwYXNz']},
  {name:'JSON credential values',input:'{"access_token":"DEMO_A","refresh-token":"DEMO_B","password":"demo with spaces"}',secrets:['DEMO_A','DEMO_B','demo with spaces']},
  {name:'quoted CLI values',input:'--password "demo with spaces" --video-password=DEMO_B --add-header \'Cookie: sid=DEMO_C\' --proxy https://u:DEMO_P@example.invalid',secrets:['demo with spaces','DEMO_B','DEMO_C','DEMO_P']},
  {name:'Netscape Cookie row',input:'#HttpOnly_.fanbox.cc\tTRUE\t/\tTRUE\t1999999999\tFANBOXSESSID\tDEMO_COOKIE',secrets:['DEMO_COOKIE','FANBOXSESSID']},
  {name:'URL credentials query and fragment',input:'HTTP 403 https://user:DEMO_P@example.invalid/video.m3u8?sig=DEMO_S#DEMO_F',secrets:['user:','DEMO_P','DEMO_S','DEMO_F'],expected:'https://example.invalid/video.m3u8'},
  {name:'IPv6 URL',input:'https://user:DEMO_P@[::1]:19876/path?token=DEMO_S#DEMO_F',secrets:['user:','DEMO_P','DEMO_S','DEMO_F'],expected:'https://[::1]:19876/path'},
  {name:'bare JWT',input:'eyJhbGciOiJub25lIn0.eyJzdWIiOiJkZW1vIn0.DEMO_SIGNATURE',secrets:['eyJhbGci','DEMO_SIGNATURE']},
  {name:'invalid URL',input:'https://[bad?token=DEMO_A#DEMO_F',secrets:['DEMO_A','DEMO_F'],expected:'[链接已隐藏]'},
  {name:'JSON escaped URL',input:'{"url":"https:\\/\\/example.invalid\\/video?signature=DEMO_A"}',secrets:['DEMO_A'],expected:'https://example.invalid/video'},
  {name:'unwrapped session values',input:'FANBOXSESSID=DEMO_A csrf_token="DEMO_B" signature: DEMO_C',secrets:['DEMO_A','DEMO_B','DEMO_C']},
  {name:'additional supported CLI secrets',input:'--http-basic-user DEMO_USER --http-basic-pass DEMO_PASS --ap-password DEMO_AP --client-certificate-password DEMO_CERT',secrets:['DEMO_USER','DEMO_PASS','DEMO_AP','DEMO_CERT']},
  {name:'unterminated quoted credential',input:'password="DEMO_A DEMO_B',secrets:['DEMO_A','DEMO_B']},
  {name:'unterminated quoted CLI credential',input:"--password 'DEMO_A DEMO_B",secrets:['DEMO_A','DEMO_B']},
  {name:'Bilibili cookie fields',input:'SESSDATA=DEMO_COOKIE bili_jct=DEMO_CSRF',secrets:['DEMO_COOKIE','DEMO_CSRF']},
];
for(const item of cases)test('redact '+item.name,()=>{
  const output=redact(item.input);
  for(const secret of item.secrets)assert.ok(!output.includes(secret),item.name+' must hide '+secret);
  if(item.expected)assert.ok(output.includes(item.expected));
  assert.equal(redact(output),output,'再次整理或复制不能破坏已整理结果');
});
test('ordinary error codes and messages remain readable',()=>{
  const original='ERROR HTTP 403; invalid_payload; lease_expired; exit code 1';
  assert.equal(redact(original),original);
});
test('report preserves source and code without inventing a diagnosis',()=>{
  const report=buildReport({version:'2.7.0',platform:'Fanbox',source:'HTTP',code:'403',error:'access_denied',logs:'Cookie: sid=DEMO_A'});
  assert.ok(report.includes('报错来源：HTTP'));
  assert.ok(report.includes('错误码或标识：403'));
  assert.ok(report.includes('原因：尚未确认'));
  assert.ok(!report.includes('该报错暂未收录'),'未做自动匹配时不能断言该错误一定未收录');
  assert.ok(report.includes('access_denied'));
  assert.ok(!report.includes('DEMO_A'));
  assert.ok(!report.includes('## 操作步骤'));
});
test('feedback template covers reproduction and redacts every field',()=>{
  const fields={version:'token=DEMO_V',platform:'Fanbox',source:'FFmpeg',code:'4294967294',
    steps:'打开任务后点击开始',expected:'生成视频',actual:'任务失败',error:'<img src=x onerror="demo"> HTTP 403',
    logs:'https://example.invalid/file?token=DEMO_T'};
  const original={...fields},report=buildReport(fields,'feedback');
  for(const title of ['## 操作步骤','## 预期结果','## 实际结果','## 错误原文','## 报错前后相关日志'])assert.ok(report.includes(title));
  assert.ok(report.includes('<img src=x onerror="demo"> HTTP 403'),'整理器返回纯文本供界面安全显示');
  assert.ok(!report.includes('DEMO_V')&&!report.includes('DEMO_T'));
  assert.deepEqual(fields,original,'不能修改用户输入对象');
});
test('missing fields stay explicitly unspecified',()=>{
  const report=buildReport({},'feedback');
  assert.ok(report.includes('错误码或标识：未提供'));
  assert.ok(report.includes('原因：尚未确认'));
});
test('truncated credentials are hidden through the last available character',()=>{
  const prefix='x'.repeat(49975)+'\npassword="DEMO_A DEMO_B trailing';
  const output=redact(prefix);
  assert.ok(!output.includes('DEMO_A')&&!output.includes('DEMO_B'));
});
