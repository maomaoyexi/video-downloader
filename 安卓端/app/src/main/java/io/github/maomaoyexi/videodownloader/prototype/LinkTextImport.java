package io.github.maomaoyexi.videodownloader.prototype;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;

final class LinkTextImport {
    private static final int MAX_BYTES = 128 * 1024;

    private LinkTextImport() {}

    static final class InvalidText extends IOException {
        InvalidText(String message) {
            super(message);
        }
    }

    static String read(InputStream input) throws IOException {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        for (int count; (count = input.read(chunk)) != -1; ) {
            if (buffer.size() + count > MAX_BYTES) throw new InvalidText("TXT 文件最多支持 128 KiB。");
            buffer.write(chunk, 0, count);
        }
        byte[] bytes = buffer.toByteArray();
        Charset encoding = StandardCharsets.UTF_8;
        if (bytes.length >= 2) {
            int bom = (bytes[0] & 0xff) << 8 | (bytes[1] & 0xff);
            if (bom == 0xfffe || bom == 0xfeff) encoding = StandardCharsets.UTF_16;
        }
        String text;
        try {
            text = encoding.newDecoder().decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException error) {
            throw new InvalidText("请使用 UTF-8 或带 BOM 的 UTF-16 文本。");
        }
        if (text.startsWith("\ufeff")) text = text.substring(1);
        boolean hasLinks = false;
        for (String raw : text.split("\\r\\n|[\\r\\n]")) {
            if (raw.chars().anyMatch(c -> Character.isISOControl(c) && c != '\t')) {
                throw new InvalidText("文件包含无效的文本字符。");
            }
            String line = raw.trim();
            if (!line.isEmpty() && !line.startsWith("#")) hasLinks = true;
        }
        if (!hasLinks) throw new InvalidText("TXT 文件中没有链接。");
        return text;
    }
}
