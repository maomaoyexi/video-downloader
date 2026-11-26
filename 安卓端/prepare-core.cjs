'use strict';
const fs = require('node:fs/promises');
const { createHash } = require('node:crypto');
const path = require('node:path');
const { version, sha256: expected, releaseAssetId } = require('./core-lock.json');

const target = path.join(__dirname, '.build', 'override-res', 'raw', 'ytdlp');
const digest = buffer => createHash('sha256').update(buffer).digest('hex');

async function prepare() {
    try {
        if (digest(await fs.readFile(target)) === expected) return;
        throw Error('已有 yt-dlp 与锁定 SHA-256 不符，请先移走旧文件。');
    } catch (error) {
        if (error.code !== 'ENOENT') throw error;
    }
    const downloads = [
        [`https://github.com/yt-dlp/yt-dlp/releases/download/${version}/yt-dlp`, {}],
        [`https://api.github.com/repos/yt-dlp/yt-dlp/releases/assets/${releaseAssetId}`, { Accept: 'application/octet-stream' }],
    ];
    for (const [url, headers] of downloads) {
        try {
            const response = await fetch(url, { headers, signal: AbortSignal.timeout(30000) });
            if (!response.ok) throw Error('HTTP ' + response.status);
            const bytes = Buffer.from(await response.arrayBuffer());
            if (digest(bytes) !== expected) throw Error('yt-dlp 的 SHA-256 不匹配');
            await fs.mkdir(path.dirname(target), { recursive:true });
            await fs.writeFile(target, bytes, { flag:'wx' });
            console.log(`已核验 yt-dlp ${version}`);
            return;
        } catch (error) {
            console.error(error.message);
        }
    }
    throw Error('两个官方下载入口均未提供经校验的 yt-dlp 文件。');
}
prepare().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
});
